"""Explicit scanner-to-paper handoff. No broker, order or notification calls.

Queue decisions are durable. Position effects use the existing atomic/idempotent
paper service. A crash between a fill and decision update is recovered by its
deterministic entry event, before inspecting a newer observation.
"""
import json
from datetime import datetime, timedelta

from brokers import assess_live_candle_batch
from instrument_identity import check_echo
from paper_portfolio import FORWARD_FILL_POLICY, PaperPortfolio, PaperPortfolioError, _encode, _hash
from strategies import TradeSignal, format_ist_timestamp, parse_ist_timestamp, signal_state_identity, validate_candles


class ForwardPaperCoordinator:
    def __init__(self, portfolio):
        if not isinstance(portfolio, PaperPortfolio) or portfolio.config.fill_policy != FORWARD_FILL_POLICY:
            raise PaperPortfolioError("EXPLICIT_FORWARD_CLOSE_ACCOUNT_REQUIRED")
        self.paper, self.store, self.config = portfolio, portfolio.store, portfolio.config

    def _transition(self, candidate_id, status, reason, position_id=None):
        with self.store.paper_transaction() as conn:
            row = conn.execute("SELECT payload_json FROM paper_candidate_decisions WHERE account_id=? AND candidate_id=?",
                               (self.config.account_id, candidate_id)).fetchone()
            data = json.loads(row[0])
            effect = conn.execute("SELECT position_id FROM paper_events WHERE account_id=? AND event_key=? AND kind='ENTRY'",
                                  (self.config.account_id, candidate_id)).fetchone()
            if effect:
                status, reason, position_id = "FILLED", "PAPER_RISK_APPROVED", effect[0]
            elif data["status"] in ("FILLED", "REJECTED"):
                return data
            event = dict(status=status, reason_code=reason, observed_at_ist=format_ist_timestamp(self.paper._now()))
            if (status, reason) != (data["status"], data["reason_code"]):
                data["history"] = (data["history"] + [event])[-32:]
            data.update(status=status, reason_code=reason, position_id=position_id)
            conn.execute("UPDATE paper_candidate_decisions SET payload_json=? WHERE account_id=? AND candidate_id=?",
                         (_encode(data), self.config.account_id, candidate_id))
        return data

    def _queue(self, summary):
        if summary.get("scan_status") not in ("COMPLETED", "COMPLETED_EMPTY") or summary.get("persistence_status") != "OK":
            raise PaperPortfolioError("SUCCESSFUL_PERSISTED_SCAN_REQUIRED")
        if summary.get("data_mode") != self.config.source_data_mode:
            raise PaperPortfolioError("SCAN_SOURCE_SCOPE_MISMATCH")
        with self.store.paper_transaction() as conn:
            run = conn.execute("SELECT status,data_mode FROM scan_runs WHERE run_id=?", (summary.get("run_id"),)).fetchone()
            if not run or run["status"] != summary["scan_status"] or run["data_mode"] != self.config.source_data_mode:
                raise PaperPortfolioError("PERSISTED_SCAN_LINK_REQUIRED")
            for supplied in summary.get("signals", []):
                if not isinstance(supplied, dict) or len(_encode(supplied).encode()) > 65536:
                    raise PaperPortfolioError("BOUNDED_CANDIDATE_REQUIRED")
                data = json.loads(_encode(supplied))
                reason = "WAITING_FOR_NEXT_COMPLETED_OBSERVATION"
                status = "QUEUED"
                try:
                    self.paper._candidate(data)
                    signal_key = signal_state_identity(data)[0]
                    source = conn.execute("SELECT * FROM signals WHERE dedup_key=?", (signal_key,)).fetchone()
                    if source is None:
                        raise PaperPortfolioError("PERSISTED_CANDIDATE_LINK_REQUIRED")
                    for key, value in data.items():
                        column = {"timestamp": "candle_timestamp", "instrument_identity": "instrument_identity_json",
                                  "score_breakdown": "score_breakdown_json"}.get(key, key)
                        actual = source[column]
                        if column.endswith("_json"):
                            actual = json.loads(actual)
                        if actual != value:
                            raise PaperPortfolioError("PERSISTED_CANDIDATE_CONFLICT")
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    signal_key = _hash(data)
                    status = "REJECTED"
                    reason = exc.reason_code if isinstance(exc, PaperPortfolioError) else "INVALID_SCANNER_CANDIDATE"
                candidate_id = _hash([self.config.account_id, signal_key])
                previous = conn.execute("SELECT payload_json FROM paper_candidate_decisions WHERE account_id=? AND signal_key=?",
                                        (self.config.account_id, signal_key)).fetchone()
                if previous:
                    if json.loads(previous[0])["candidate"] != data:
                        raise PaperPortfolioError("SCANNER_CANDIDATE_IDEMPOTENCY_CONFLICT")
                    continue
                decision = dict(candidate_id=candidate_id, account_id=self.config.account_id,
                    config_hash=self.config.config_hash, run_id=self.config.run_id,
                    source_scan_run_id=summary["run_id"], signal_key=signal_key,
                    candidate_hash=_hash(data), candidate=data, execution_mode="SIMULATED",
                    status=status, reason_code=reason, position_id=None,
                    history=[dict(status=status, reason_code=reason, observed_at_ist=format_ist_timestamp(self.paper._now()))])
                conn.execute("INSERT INTO paper_candidate_decisions VALUES (?,?,?,?,?)",
                             (candidate_id, self.config.account_id, signal_key, summary["run_id"], _encode(decision)))

    def _observations(self, symbol, rows):
        if not isinstance(rows, list) or not rows:
            raise PaperPortfolioError("OBSERVATIONS_UNAVAILABLE")
        for row in rows:
            identity = row.get("instrument_identity") if isinstance(row, dict) else None
            if (not identity or identity.get("provider") != self.config.provider or identity.get("symbol") != symbol
                    or row.get("data_mode") != self.config.source_data_mode
                    or row.get("is_simulated") is not (self.config.source_data_mode == "SIMULATED")):
                raise PaperPortfolioError("OBSERVATION_IDENTITY_OR_MODE_MISMATCH")
            if identity != rows[0]["instrument_identity"]:
                raise PaperPortfolioError("OBSERVATION_IDENTITY_OR_MODE_MISMATCH")
            check_echo({key: value for key, value in row.items() if key not in ("data_mode", "is_simulated")}, identity)
        now = self.paper._now()
        if self.config.source_data_mode == "LIVE":
            normalized, report = assess_live_candle_batch(rows, 5, now, self.config.configured_holidays,
                self.config.session_start_ist, self.config.session_end_ist, self.config.max_mark_age_seconds, 0,
                provider=self.config.provider, symbol=symbol, context="SCANNER",
                normalized_ist=all(row.get("timestamp_timezone") == "Asia/Kolkata" for row in rows))
            if not report["live_signal_allowed"]:
                raise PaperPortfolioError("INVALID_OR_STALE_OBSERVATION_BATCH")
        else:
            for row in rows:
                stamp = row.get("timestamp")
                if row.get("timestamp_timezone") != "Asia/Kolkata":
                    value = datetime.fromisoformat(stamp) if isinstance(stamp, str) else stamp
                    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                        raise PaperPortfolioError("EXPLICIT_SOURCE_TIME_REQUIRED")
            normalized = validate_candles(rows, interval_min=5, now=now, deduplicate=False)
            for previous, current in zip(normalized, normalized[1:]):
                left, right = parse_ist_timestamp(previous["timestamp"]), parse_ist_timestamp(current["timestamp"])
                if left.date() == right.date() and right != left + timedelta(minutes=5):
                    raise PaperPortfolioError("OBSERVATION_GAP")
            for row in normalized:
                row["timestamp_timezone"] = "Asia/Kolkata"
        completed = [row for row in normalized if row["is_complete"]]
        if not completed:
            raise PaperPortfolioError("NO_COMPLETED_OBSERVATION")
        return completed

    def consume_scan(self, summary, observations):
        self._queue(summary)
        actions = []
        batches, failures = {}, {}
        for symbol, rows in observations.items():
            try:
                batches[symbol] = self._observations(symbol, rows)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                failures[symbol] = exc.reason_code if isinstance(exc, PaperPortfolioError) else "INVALID_OBSERVATION_BATCH"
        # Mark/exit prior positions at the observed close before considering new
        # close-priced entries; intrabar outcomes cannot fund an earlier open.
        for position in self.paper.open_positions():
            rows = batches.get(position["symbol"])
            if not rows:
                actions.append(dict(position_id=position["position_id"], status="DEFERRED", reason_code="MARK_UNAVAILABLE"))
                continue
            bar = rows[-1]
            if parse_ist_timestamp(bar["timestamp"]) <= parse_ist_timestamp(position["mark_timestamp_ist"]):
                continue
            try:
                result = self.paper.process_bar(position["position_id"], bar,
                    event_key="mark:" + _hash([position["position_id"], bar["timestamp"]]))
                actions.append(result)
            except PaperPortfolioError as exc:
                actions.append(dict(position_id=position["position_id"], status="DEFERRED", reason_code=exc.reason_code))
        with self.store.paper_transaction(write=False) as conn:
            rows = conn.execute("SELECT payload_json FROM paper_candidate_decisions WHERE account_id=? ORDER BY candidate_id",
                                (self.config.account_id,))
            pending = []
            for row in rows:
                decision = json.loads(row["payload_json"])
                if decision["status"] == "QUEUED":
                    pending.append(decision)
        pending.sort(key=lambda d: (d["candidate"].get("timestamp", ""), d["candidate"].get("strategy_id", ""), d["candidate_id"]))
        for decision in pending:
            candidate_id, data = decision["candidate_id"], decision["candidate"]
            with self.store.paper_transaction(write=False) as conn:
                effect = conn.execute("SELECT position_id FROM paper_events WHERE account_id=? AND event_key=? AND kind='ENTRY'",
                                      (self.config.account_id, candidate_id)).fetchone()
            if effect:
                actions.append(self._transition(candidate_id, "FILLED", "RECOVERED_IDEMPOTENT_ENTRY", effect[0]))
                continue
            if decision["candidate_hash"] != _hash(data) or decision["config_hash"] != self.config.config_hash:
                actions.append(self._transition(candidate_id, "REJECTED", "CANDIDATE_DECISION_INTEGRITY_FAILURE"))
                continue
            bars = batches.get(data["symbol"], [])
            if not bars:
                actions.append(self._transition(candidate_id, "QUEUED", failures.get(data["symbol"], "OBSERVATIONS_UNAVAILABLE")))
                continue
            expected = parse_ist_timestamp(data["timestamp"]) + timedelta(minutes=5)
            bar = next((b for b in bars if parse_ist_timestamp(b["timestamp"]) == expected), None)
            if bar is None:
                reason = "WAITING_FOR_NEXT_COMPLETED_OBSERVATION" if parse_ist_timestamp(bars[-1]["timestamp"]) < expected else "REQUIRED_OBSERVATION_MISSING"
                actions.append(self._transition(candidate_id, "QUEUED", reason))
                continue
            try:
                result = self.paper.enter(data, bar, event_key=candidate_id, candidate_decision_id=candidate_id)
                actions.append(self._transition(candidate_id, "FILLED", "PAPER_RISK_APPROVED", result["position_id"]))
            except PaperPortfolioError as exc:
                actions.append(self._transition(candidate_id, "REJECTED", exc.reason_code))
        return dict(status="COMPLETED", execution_mode="SIMULATED", actions=actions,
                    account_id=self.config.account_id, report=self.store.get_paper_portfolio_report(self.config.account_id, self.paper._now()))

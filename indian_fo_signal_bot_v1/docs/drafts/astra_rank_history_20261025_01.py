"""Authenticated local cash priority history; no execution or empirical authority.

Only the scanner result transaction creates records. Reads authenticate retained
inputs, explanations and signals, and never acquire data or refresh a snapshot.
One predecessor is checked without recursively walking the entire history.
"""
import copy
from datetime import datetime
import json

from candle_lineage import (code_fingerprint, digest, encoded, load,
                            load_scan_evaluations, runtime_profile)
from opportunity_ranking import build_snapshot, current_view, verify_snapshot
from strategies import (IST, TradeSignal, filter_completed_candles,
                        parse_ist_timestamp, signal_risk_reward)


SCHEMA = "tradepulse.cash-rank-history.v1"
DESCRIPTOR = "tradepulse.cash-rank-descriptor.v1"
SEGMENT = "NSE_EQUITY_INTRADAY"
MAX_CANDIDATES = 512
_SHALLOW_PREDECESSOR = object()


def _require(condition, reason):
    if not condition:
        from storage import PersistenceValidationError
        raise PersistenceValidationError(reason)


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS cash_rank_snapshots (
        run_id TEXT PRIMARY KEY REFERENCES cash_candle_scans(run_id),
        work_id TEXT NOT NULL UNIQUE, scope_digest TEXT NOT NULL,
        reference TEXT NOT NULL, payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS cash_rank_scope_order
        ON cash_rank_snapshots(scope_digest,reference,work_id,run_id)""")


def _clock(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    _require(isinstance(value, datetime) and value.tzinfo is not None
             and value.utcoffset() is not None, "RANKING_AWARE_CLOCK_REQUIRED")
    return value.astimezone(IST)


def _scope(profile, mode):
    return dict(provider=profile["provider"], data_mode=mode, segment=SEGMENT,
                profile_digest=digest(profile))


def _reference(snapshot):
    # This is the scanner's retained exchange-local reference, not an API clock.
    return parse_ist_timestamp(snapshot["reference"]).isoformat()


def _row(conn, run_id):
    return conn.execute("SELECT * FROM cash_rank_snapshots WHERE run_id=?", (run_id,)).fetchone()


def _latest(conn, scope_digest):
    return conn.execute("""SELECT * FROM cash_rank_snapshots WHERE scope_digest=?
        ORDER BY reference DESC,work_id DESC,run_id DESC LIMIT 1""", (scope_digest,)).fetchone()


def _preceding(conn, row):
    return conn.execute("""SELECT * FROM cash_rank_snapshots WHERE scope_digest=?
        AND (reference,work_id,run_id) < (?,?,?)
        ORDER BY reference DESC,work_id DESC,run_id DESC LIMIT 1""",
        (row["scope_digest"], row["reference"], row["work_id"], row["run_id"])).fetchone()


def _decode(row):
    body = json.loads(row["payload_json"])
    _require(isinstance(body, dict) and body.get("schema_version") == SCHEMA
             and digest(body) == row["payload_sha256"], "RANK_HISTORY_CHECKSUM_FAILURE")
    _require(body["run_id"] == row["run_id"] and body["work_id"] == row["work_id"]
             and digest(body["scope"]) == row["scope_digest"]
             and body["reference"] == row["reference"], "RANK_HISTORY_ROW_SCOPE_FAILURE")
    verify_snapshot(body["ranking"])
    return body


def _descriptor(row, body=None):
    body = _decode(row) if body is None else body
    ranking = body["ranking"]
    return dict(schema_version=DESCRIPTOR, run_id=row["run_id"], work_id=row["work_id"],
        scope_digest=row["scope_digest"], reference=row["reference"],
        payload_sha256=row["payload_sha256"], rank_version=ranking["rank_version"],
        previous_rank_version=ranking["previous_rank_version"], actionable=False)


def _source(conn, work, result, read_cache=None):
    """Bind ranking inputs to the actual durable scanner contracts, not hashes alone."""
    from storage import compute_signal_dedup_key
    snapshot, run_id = work["snapshot"], work["run_id"]
    profile = snapshot["profile"]
    _require(result.get("run_id") == run_id and result.get("actionable") is False
             and result.get("data_mode") == "LIVE"
             and digest(profile) == snapshot["profile_digest"], "RANK_SOURCE_SCOPE_FAILURE")
    evaluation = load_scan_evaluations(conn, run_id, read_cache=read_cache)
    _require(isinstance(evaluation, dict) and evaluation.get("data_mode") == result["data_mode"]
             and all(evaluation.get(key) == result.get(key)
                     for key in ("strategy_evaluations", "candidate_evaluations")),
             "RANK_EVALUATION_RESULT_FAILURE")
    candidates = evaluation["candidate_evaluations"]
    _require(len(candidates) <= MAX_CANDIDATES, "RANK_CANDIDATE_BOUND_EXCEEDED")
    batches = snapshot["batches"]
    _require(isinstance(batches, list) and bool(batches), "RANK_DURABLE_CASH_INPUT_REQUIRED")
    by_symbol = {batch["content"]["identity"]["symbol"]: batch for batch in batches}
    _require(len(by_symbol) == len(batches), "RANK_AMBIGUOUS_CASH_IDENTITY")
    signals = {compute_signal_dedup_key(signal, result["broker"]): signal for signal in result["signals"]}
    _require(len(signals) == len(result["signals"]), "RANK_DUPLICATE_SIGNAL_IDENTITY")
    qualified_cash_ids = set()
    references = {}
    for candidate in candidates:
        reference = candidate.get("source_reference") or {}
        identity = reference.get("instrument_identity") or {}
        batch = by_symbol.get(candidate.get("symbol"))
        signal = signals.get(candidate.get("candidate_id"))
        # F&O has a different contract and is explicitly excluded by the pure
        # cash policy. It cannot be disguised as an authenticated cash batch.
        cash = batch is not None or identity.get("instrument_type") == "EQ" or (
            signal is not None and signal.get("segment") == SEGMENT)
        if not cash:
            continue
        _require(batch is not None, "RANK_CASH_SOURCE_BATCH_MISSING")
        if batch["batch_id"] not in references:
            bars = filter_completed_candles(batch["content"]["candles"], interval_min=5,
                                           now=parse_ist_timestamp(snapshot["reference"]))
            references[batch["batch_id"]] = dict(run_id=run_id, provider=profile["provider"],
                batch_ids=[batch["batch_id"]], instrument_identity=batch["content"]["identity"],
                candle_timestamps=[bar["timestamp"] for bar in bars], candle_digest=digest(bars),
                source_authenticity="NOT_ESTABLISHED", data_mode=result["data_mode"])
        expected_reference = references[batch["batch_id"]]
        _require(reference == expected_reference and candidate.get("data_mode") == result["data_mode"]
                 and candidate.get("actionable") is False, "RANK_CANDIDATE_SOURCE_FAILURE")
        trace = (candidate.get("explanation") or {}).get("rule_evaluation")
        _require(isinstance(trace, dict) and trace in evaluation["strategy_evaluations"]
                 and trace.get("source_reference") == expected_reference
                 and trace.get("symbol") == candidate["symbol"]
                 and trace.get("strategy_id") == candidate["strategy_id"]
                 and trace.get("data_mode") == result["data_mode"], "RANK_CANDIDATE_TRACE_FAILURE")
        qualified = candidate.get("status") == "QUALIFIED"
        _require((candidate.get("ranking") or {}).get("qualified") is qualified,
                 "RANK_QUALIFICATION_CONFLICT")
        if not qualified:
            _require(signal is None, "RANK_REJECTED_PERSISTED_SIGNAL_CONFLICT")
            continue
        _require(signal is not None and trace.get("status") == "DETECTED"
                 and signal["segment"] == SEGMENT
                 and signal["instrument_identity"] == expected_reference["instrument_identity"]
                 and signal["timestamp"] == expected_reference["candle_timestamps"][-1]
                 and all(signal[key] == candidate[key] for key in ("symbol", "strategy_id", "data_mode"))
                 and signal["provider"] == profile["provider"], "RANK_QUALIFIED_SIGNAL_LINK_FAILURE")
        explanation = candidate["explanation"]
        for explanation_key, signal_key in (("setup_quality", "quality_score"), ("rationale", "rationale"),
                ("entry_condition", "rationale"), ("entry_price", "entry_price"), ("stop_loss", "stop_loss"),
                ("invalidation_level", "invalidation_level"), ("target_1", "target_1"),
                ("target_2", "target_2"), ("score_breakdown", "score_breakdown")):
            _require(explanation.get(explanation_key) == signal[signal_key], "RANK_SIGNAL_COMPONENT_FAILURE")
        numeric = signal_risk_reward(TradeSignal(**signal))
        _require(numeric["allowed"] is True and candidate["risk_reward"] == numeric,
                 "RANK_ACTUAL_REWARD_RISK_FAILURE")
        qualified_cash_ids.add(candidate["candidate_id"])
    _require(qualified_cash_ids == {key for key, signal in signals.items() if signal["segment"] == SEGMENT},
             "RANK_QUALIFIED_CASH_COVERAGE_FAILURE")
    source = dict(snapshot_digest=digest(snapshot), evaluation_digest=digest(evaluation),
        result_digest=digest({key: value for key, value in result.items() if key != "opportunity_ranking"}),
        code_digest=snapshot["code_digest"], profile_digest=snapshot["profile_digest"],
        batch_ids=[batch["batch_id"] for batch in batches], source_authenticity="NOT_ESTABLISHED")
    return evaluation, source, _scope(profile, result["data_mode"])


def _base_priority(ranking):
    """Fields independent of older ancestry, all recomputable from this source."""
    ignored = {"previous_rank", "rank_change_reason", "component_changes"}
    return dict(policy=ranking["policy"], scope=ranking["scope"], run_id=ranking["run_id"],
        as_of=ranking["as_of"], valid_until=ranking["valid_until"], rank_version=ranking["rank_version"],
        evaluation_digest=ranking["evaluation_digest"], exclusions=ranking["exclusions"],
        rows=[{key: value for key, value in row.items() if key not in ignored} for row in ranking["rows"]],
        actionable=ranking["actionable"], evidence_scope=ranking["evidence_scope"])


def _predecessor(store, conn, row, read_cache):
    if row is None:
        return None
    prior = _decode(row)
    # The predecessor's retained source and base priority are authenticated once.
    # Its own historical delta is not traversed: only its base priority is an
    # input to the current snapshot's fully reconstructed change explanation.
    marker = (_SHALLOW_PREDECESSOR, row["run_id"])
    before = read_cache.get(marker)
    read_cache[marker] = True
    try:
        previous_work = load(store, row["run_id"], connection=conn, read_cache=read_cache)
        _require(previous_work["status"] == "COMMITTED", "RANK_PREDECESSOR_NOT_COMMITTED")
    finally:
        if before is None:
            read_cache.pop(marker, None)
        else:
            read_cache[marker] = before
    return prior


def _validate(store, conn, work, result, read_cache):
    row = _row(conn, work["run_id"])
    descriptor = result.get("opportunity_ranking")
    if descriptor is None and row is None and result.get("ranking_required") is not True:
        return None  # Legacy committed scans predate this additive contract.
    _require(row is not None and isinstance(descriptor, dict), "RANK_REQUIRED_DESCRIPTOR_MISSING")
    body = _decode(row)
    _require(descriptor == _descriptor(row, body), "RANK_DESCRIPTOR_BINDING_FAILURE")
    evaluation, source, scope = _source(conn, work, result, read_cache)
    _require(body["work_id"] == work["snapshot"]["work_id"] and body["scope"] == scope
             and body["reference"] == _reference(work["snapshot"])
             and body["source"] == source and result.get("ranking_required") is True,
             "RANK_SOURCE_BINDING_FAILURE")
    if read_cache.get((_SHALLOW_PREDECESSOR, work["run_id"])):
        rebuilt = build_snapshot(evaluation, provider=scope["provider"], as_of=body["reference"])
        _require(_base_priority(body["ranking"]) == _base_priority(rebuilt), "RANK_PREDECESSOR_PRIORITY_FAILURE")
        return body
    prior_row = _preceding(conn, row)
    prior = _predecessor(store, conn, prior_row, read_cache)
    _require(body["previous_snapshot"] == (_descriptor(prior_row, prior) if prior else None),
             "RANK_PREDECESSOR_LINK_FAILURE")
    rebuilt = build_snapshot(evaluation, provider=scope["provider"], as_of=body["reference"],
                             previous=prior["ranking"] if prior else None)
    _require(body["ranking"] == rebuilt, "RANK_RECONSTRUCTION_FAILURE")
    return body


def validate_descriptor(store, conn, work, result, read_cache=None):
    from storage import PersistenceValidationError
    try:
        return _validate(store, conn, work, result, {} if read_cache is None else read_cache)
    except PersistenceValidationError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, RecursionError) as exc:
        raise PersistenceValidationError("RANK_HISTORY_INTEGRITY_FAILURE") from exc


def record(store, conn, work, summary):
    """Append in the caller's existing scanner transaction; never open a writer."""
    from storage import PersistenceValidationError
    try:
        if summary.get("ranking_required") is not True:
            _require(summary.get("opportunity_ranking") is None and _row(conn, work["run_id"]) is None,
                     "RANK_LEGACY_DESCRIPTOR_CONFLICT")
            return None
        _require(getattr(store._scan_local, "connection", None) is conn,
                 "RANK_SCANNER_RESULT_TRANSACTION_REQUIRED")
        _require(work["snapshot"]["code_digest"] == code_fingerprint(), "RANK_RECORD_CODE_CHANGED")
        _require(work["status"] == "PENDING" and work["run_id"] == summary["run_id"]
                 and summary.get("opportunity_ranking") is None
                 and _row(conn, work["run_id"]) is None, "RANK_APPEND_ONLY_TRANSACTION_REQUIRED")
        cache = {}
        evaluation, source, scope = _source(conn, work, summary, cache)
        scope_digest = digest(scope)
        reference = _reference(work["snapshot"])
        prior_row = _latest(conn, scope_digest)
        if prior_row is not None:
            _require((reference, work["snapshot"]["work_id"], work["run_id"]) >
                     (prior_row["reference"], prior_row["work_id"], prior_row["run_id"]),
                     "RANK_OUT_OF_ORDER_SOURCE")
        prior = _predecessor(store, conn, prior_row, cache)
        ranking = build_snapshot(evaluation, provider=scope["provider"], as_of=reference,
                                 previous=prior["ranking"] if prior else None)
        body = dict(schema_version=SCHEMA, run_id=work["run_id"], work_id=work["snapshot"]["work_id"],
            scope=scope, reference=reference, source=source, ranking=ranking,
            previous_snapshot=_descriptor(prior_row, prior) if prior else None)
        payload = encoded(body)
        conn.execute("INSERT INTO cash_rank_snapshots VALUES (?,?,?,?,?,?)",
            (work["run_id"], body["work_id"], scope_digest, reference, payload, digest(body)))
        summary["opportunity_ranking"] = _descriptor(_row(conn, work["run_id"]), body)
        return copy.deepcopy(summary["opportunity_ranking"])
    except PersistenceValidationError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, RecursionError) as exc:
        raise PersistenceValidationError("RANK_RECORD_INTEGRITY_FAILURE") from exc


def read_current(store, config, now, run_id=None, limit=20, offset=0):
    """Bounded, read-only view. A stale/corrupt latest row never selects an older one."""
    from storage import PersistenceValidationError
    try:
        clock = _clock(now)
        _require(type(limit) is int and 1 <= limit <= 100 and type(offset) is int
                 and 0 <= offset <= MAX_CANDIDATES, "RANK_PAGE_INVALID")
        _require(run_id is None or isinstance(run_id, str) and 0 < len(run_id) <= 160,
                 "RANK_RUN_ID_INVALID")
        profile = runtime_profile(config)
        requested_scope = _scope(profile, "SIMULATED" if profile["provider"] == "paper_sim" else "LIVE")
        empty = dict(status="RANKING_UNAVAILABLE_NO_DURABLE_SCAN", actionable=False,
            scope=requested_scope, as_of=clock.isoformat(), current_rows=[], historical_rows=[],
            pagination=dict(offset=offset, limit=limit, total=0), snapshot=None)
        with store.lineage_read() as conn:
            selected_run = run_id
            if selected_run is None:
                # Select from committed scanner work first. Deleting the newest
                # rank row must not reveal an older row as current priority.
                latest_work = conn.execute("""SELECT run_id FROM cash_candle_scans
                    WHERE status='COMMITTED' AND json_extract(snapshot_json,'$.profile_digest')=?
                    AND json_extract(result_json,'$.data_mode')=?
                    ORDER BY json_extract(snapshot_json,'$.reference') DESC,work_id DESC,run_id DESC LIMIT 1""",
                    (requested_scope["profile_digest"], requested_scope["data_mode"])).fetchone()
                selected_run = latest_work[0] if latest_work else None
            row = _row(conn, selected_run) if selected_run is not None else None
            if row is None:
                if selected_run is not None:
                    # A legacy result may lack ranks; a required or orphaned
                    # descriptor fails through the ordinary lineage validator.
                    absent_work = load(store, selected_run, connection=conn, read_cache={})
                    validate_descriptor(store, conn, absent_work, absent_work["result"], read_cache={})
                return empty
            cache = {}
            work = load(store, row["run_id"], connection=conn, read_cache=cache)
            _require(work["status"] == "COMMITTED", "RANK_SOURCE_NOT_COMMITTED")
            # Explicit validation also supports callers before lineage's hook is
            # installed, and never assumes a self-hashed snapshot is authentic.
            body = validate_descriptor(store, conn, work, work["result"], read_cache=cache)
            _require(body is not None, "RANK_REQUIRED_DESCRIPTOR_MISSING")
            ranking = body["ranking"]
            view = current_view(ranking, clock)
            status = view["status"]
            if body["scope"] != requested_scope:
                status = "ARCHIVED_DIFFERENT_RUNTIME_SCOPE"
            elif body["source"]["code_digest"] != code_fingerprint():
                status = "ARCHIVED_DIFFERENT_CODE"
            elif (work["result"].get("candle_freshness") or {}).get("live_signal_allowed") is not True:
                status = "ARCHIVED_NON_CURRENT_SCAN"
            rows = ranking["rows"][offset:offset + limit]
            metadata = {key: copy.deepcopy(ranking[key]) for key in (
                "policy", "rank_version", "previous_rank_version", "valid_until", "evidence_scope")}
            metadata.update(run_id=body["run_id"], work_id=body["work_id"], reference=body["reference"],
                scope=copy.deepcopy(body["scope"]), previous_snapshot=copy.deepcopy(body["previous_snapshot"]),
                source_authenticity="NOT_ESTABLISHED",
                source_data_watermarks=sorted({entry["source_data_watermark"] for entry in ranking["rows"]})[:100],
                source_data_watermark_count=len({entry["source_data_watermark"] for entry in ranking["rows"]}),
                exclusions=copy.deepcopy(ranking["exclusions"][:100]), exclusion_count=len(ranking["exclusions"]),
                removals=copy.deepcopy(ranking["removals"][:100]), removal_count=len(ranking["removals"]),
                metadata_preview_limit=100,
                exclusions_truncated=len(ranking["exclusions"]) > 100,
                removals_truncated=len(ranking["removals"]) > 100,
                source_data_watermarks_truncated=len({entry["source_data_watermark"] for entry in ranking["rows"]}) > 100)
            return dict(status=status, actionable=False, scope=copy.deepcopy(body["scope"]),
                as_of=clock.isoformat(), current_rows=copy.deepcopy(rows) if status == "CURRENT_CANDIDATE_PRIORITY" else [],
                historical_rows=copy.deepcopy(rows), pagination=dict(offset=offset, limit=limit, total=len(ranking["rows"])),
                snapshot=metadata)
    except PersistenceValidationError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, RecursionError) as exc:
        raise PersistenceValidationError("RANK_READ_INTEGRITY_FAILURE") from exc

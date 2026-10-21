"""Durable locally validated cash inputs; hashes never confer source authority.

No transport, credentials, historical-source qualification or live acceptance.
The existing scanner and SQLite writers remain the execution implementation.
"""
import copy
import hashlib
import json
import math
import sqlite3
import sys
from pathlib import Path

from instrument_identity import bind_candles, spot_identity
from strategies import parse_ist_timestamp

VERSION = "cash-lineage-v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_BARS = 25000
POLICY_KEYS = ("configured_holidays", "session_start_ist", "session_end_ist",
               "live_candle_max_delay_seconds", "live_candle_future_skew_seconds")
PARAMETER_KEYS = POLICY_KEYS + ("account_capital_inr", "max_risk_per_trade_pct",
    "max_daily_loss_inr", "max_concurrent_positions", "daily_profit_target_inr")
IDENTITY_KEYS = ("provider", "symbol", "identifier", "exchange", "segment", "instrument_type",
                 "is_index", "source", "source_revision", "historical_validity", "response_binding", "master_record")
BAR_KEYS = ("timestamp", "open", "high", "low", "close", "volume", "is_complete", "is_simulated",
            "data_mode", "timestamp_timezone", "interval_min", "instrument_identity", "provider",
            "component_count", "expected_components", "traded_quantity")


def encoded(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise ValueError("LINEAGE_SIZE_LIMIT")
    return data


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def runtime_profile(config):
    """Only execution inputs; never credential fields, paths or account identifiers."""
    def instrument(meta):
        return {k: meta[k] for k in ("symbol", "angel_token", "dhan_id", "dhan_security_id", "upstox_key",
                                    "lot_size", "strike_step", "name", "sector") if k in meta}
    return dict(version=VERSION, provider=config.active_broker.strip().lower(),
        runtime=dict(python=list(sys.version_info[:3]), sqlite=sqlite3.sqlite_version),
        parameters={key: copy.deepcopy(getattr(config, key)) for key in PARAMETER_KEYS},
        equities=[instrument(m) for m in config.equity_watchlist],
        indices={k: instrument(dict(v, symbol=k)) for k, v in config.fo_indices.items()})


def code_fingerprint():
    files = sorted(p for p in Path(__file__).parent.glob("*.py") if not p.name.startswith("test_"))
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def _policy(profile):
    p = profile["parameters"]
    return dict(configured_holidays=p["configured_holidays"], session_start_ist=p["session_start_ist"],
        session_end_ist=p["session_end_ist"], max_delay_seconds=p["live_candle_max_delay_seconds"],
        future_skew_seconds=p["live_candle_future_skew_seconds"])


def completed_cash_batch(rows, meta, profile, reference):
    """Re-run production gates before creating an accepted completed-only record."""
    from brokers import assess_live_candle_batch
    if not isinstance(rows, list) or not rows or len(rows) > MAX_BARS:
        raise ValueError("LINEAGE_INVALID_BATCH")
    provider = profile["provider"]
    supplied = rows[0].get("instrument_identity") if isinstance(rows[0], dict) else None
    if not isinstance(supplied, dict) or supplied.get("instrument_type") != "EQ":
        raise ValueError("LINEAGE_CASH_IDENTITY_REQUIRED")
    master = {meta["symbol"]: supplied["master_record"]} if supplied.get("master_record") else None
    identity = spot_identity(meta, provider, master=master)
    if any(not isinstance(r, dict) or r.get("data_mode") != "LIVE" or r.get("is_simulated") is not False
           or r.get("timestamp_timezone") != "Asia/Kolkata" or r.get("interval_min") != 5
           or type(r.get("is_complete")) is not bool or not isinstance(r.get("instrument_identity"), dict)
           or any(r["instrument_identity"].get(k) != supplied.get(k) for k in IDENTITY_KEYS) for r in rows):
        raise ValueError("LINEAGE_MIXED_OR_MISSING_PROVENANCE")
    for key in ("source", "source_revision", "historical_validity"):
        if supplied.get(key) != identity.get(key):
            raise ValueError("LINEAGE_SOURCE_MISMATCH")
    bound = bind_candles(rows, identity)
    for row in bound:
        if row.get("provider", provider) != provider:
            raise ValueError("LINEAGE_PROVIDER_MISMATCH")
        if "traded_quantity" in row:
            q = row["traded_quantity"]
            if isinstance(q, bool) or not isinstance(q, (int, float)) or not math.isfinite(q) or q < 0:
                raise ValueError("LINEAGE_INVALID_QUANTITY")
    normalized, validation = assess_live_candle_batch(bound, 5, reference,
        provider=provider, symbol=meta["symbol"], context="SCANNER", normalized_ist=True, **_policy(profile))
    if not validation["live_signal_allowed"]:
        raise ValueError("LINEAGE_REJECTED_" + validation["reason_code"])
    bars = [{k: r[k] for k in BAR_KEYS if k in r} for r in normalized if r["is_complete"]]
    if not bars:
        raise ValueError("LINEAGE_COMPLETED_INPUT_REQUIRED")
    identity = bars[0]["instrument_identity"]
    content = dict(version=VERSION, provider=provider, identity=identity, interval_min=5, candles=bars)
    return dict(batch_id=digest(content), content=content, validation=validation,
        retrieved_at=reference, retrieval_clock="LOCAL_OBSERVATION_AFTER_ACQUISITION",
        source_observation_at=None, source_authenticity="NOT_ESTABLISHED",
        rejected_tail_count=len(normalized)-len(bars))


def make_snapshot(config, equities, indices, chains, zones, reference):
    profile = runtime_profile(config)
    reference = parse_ist_timestamp(reference).isoformat()
    batches = [completed_cash_batch(equities[m["symbol"]], m, profile, reference)
               for m in config.equity_watchlist]
    if not batches or len({b["batch_id"] for b in batches}) != len(batches):
        raise ValueError("LINEAGE_UNIQUE_CASH_UNIVERSE_REQUIRED")
    # These are normalized market inputs, not accepted cash records or publisher proof.
    auxiliary = dict(index_candles=indices, option_chains=chains)
    snapshot = dict(version=VERSION, profile=profile, profile_digest=digest(profile),
        code_digest=code_fingerprint(), reference=reference,
        batches=batches, auxiliary=copy.deepcopy(auxiliary),
        zones={key: sorted(value) for key, value in zones.items()})
    # Original zone state/time are frozen for resumption, not additional work identities.
    snapshot["work_id"] = work_identity(snapshot)
    encoded(snapshot)
    return snapshot


def work_identity(snapshot):
    return digest(dict(version=VERSION, profile=snapshot["profile_digest"], code=snapshot["code_digest"],
        batches=[b["batch_id"] if isinstance(b, dict) else b for b in snapshot["batches"]],
        auxiliary=snapshot["auxiliary"]))


def create_schema(conn):
    for sql in (
        """CREATE TABLE IF NOT EXISTS cash_candle_facts (
            candle_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, content_digest TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS cash_candle_batches (
            batch_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL, candle_count INTEGER NOT NULL,
            metadata_digest TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS cash_candle_batch_members (
            batch_id TEXT NOT NULL REFERENCES cash_candle_batches(batch_id), ordinal INTEGER NOT NULL,
            candle_key TEXT NOT NULL REFERENCES cash_candle_facts(candle_key),
            PRIMARY KEY(batch_id, ordinal), UNIQUE(batch_id, candle_key))""",
        """CREATE TABLE IF NOT EXISTS cash_candle_scans (
            run_id TEXT PRIMARY KEY, work_id TEXT NOT NULL UNIQUE, snapshot_json TEXT NOT NULL,
            snapshot_digest TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('PENDING','COMMITTED')),
            result_json TEXT, result_digest TEXT)""",
        """CREATE TABLE IF NOT EXISTS cash_candle_scan_inputs (
            run_id TEXT NOT NULL REFERENCES cash_candle_scans(run_id),
            batch_id TEXT NOT NULL REFERENCES cash_candle_batches(batch_id), PRIMARY KEY(run_id,batch_id))""",
        """CREATE TABLE IF NOT EXISTS cash_candle_signal_inputs (
            run_id TEXT NOT NULL REFERENCES cash_candle_scans(run_id), dedup_key TEXT NOT NULL,
            batch_id TEXT NOT NULL REFERENCES cash_candle_batches(batch_id), PRIMARY KEY(run_id,dedup_key,batch_id))""",
    ):
        conn.execute(sql)


def _candle_key(content, bar):
    i = content["identity"]
    return digest([content["provider"], i["identifier"], i["exchange"], i["segment"],
                   content["interval_min"], bar["timestamp"]])


def prepare(store, run_id, snapshot):
    from storage import PersistenceValidationError
    if not isinstance(run_id, str) or not run_id or len(run_id) > 160:
        raise PersistenceValidationError("LINEAGE_INVALID_RUN_ID")
    profile = snapshot["profile"]
    expected = [completed_cash_batch(b["content"]["candles"], m, profile, snapshot["reference"])
                for b, m in zip(snapshot["batches"], profile["equities"])]
    if (len(expected) != len(profile["equities"]) or not expected
            or [b["batch_id"] for b in expected] != [b["batch_id"] for b in snapshot["batches"]]
            or digest(profile) != snapshot["profile_digest"] or work_identity(snapshot) != snapshot["work_id"]):
        raise PersistenceValidationError("LINEAGE_CONTENT_OR_PROFILE_CONFLICT")
    body = copy.deepcopy(snapshot)
    body["batches"] = [b["batch_id"] for b in snapshot["batches"]]
    store._lineage_checkpoint("before_input_transaction")
    with store.paper_transaction() as conn:
        previous = conn.execute("SELECT run_id FROM cash_candle_scans WHERE work_id=?", (body["work_id"],)).fetchone()
        if previous:
            return load(store, previous[0], connection=conn)
        for batch in snapshot["batches"]:
            content = batch["content"]
            old = conn.execute("SELECT batch_id FROM cash_candle_batches WHERE batch_id=?", (batch["batch_id"],)).fetchone()
            if old:
                # An immutable prior batch will be fully rechecked by load below.
                continue
            metadata = {k: v for k, v in batch.items() if k != "content"}
            metadata["content_header"] = {k: v for k, v in content.items() if k != "candles"}
            conn.execute("INSERT INTO cash_candle_batches VALUES (?,?,?,?)",
                         (batch["batch_id"], encoded(metadata), len(content["candles"]), digest(metadata)))
            for ordinal, bar in enumerate(content["candles"]):
                key, bar_payload = _candle_key(content, bar), encoded(bar)
                old_bar = conn.execute("SELECT payload_json FROM cash_candle_facts WHERE candle_key=?", (key,)).fetchone()
                if old_bar and old_bar[0] != bar_payload:
                    raise PersistenceValidationError("LINEAGE_CANDLE_CORRECTION_CONFLICT")
                conn.execute("INSERT OR IGNORE INTO cash_candle_facts VALUES (?,?,?)", (key, bar_payload, digest(bar)))
                conn.execute("INSERT INTO cash_candle_batch_members VALUES (?,?,?)", (batch["batch_id"], ordinal, key))
                store._lineage_checkpoint("after_candle_write")
        # A different pending input must finish before a later scan can freeze
        # its consumed-zone state. Same-work retries above remain idempotent.
        for pending in conn.execute("SELECT snapshot_json FROM cash_candle_scans WHERE status='PENDING'"):
            if json.loads(pending[0])["profile"]["provider"] == profile["provider"]:
                raise PersistenceValidationError("LINEAGE_PRIOR_SCAN_REQUIRES_RECOVERY")
        body["zones"] = {segment: sorted(r[0] for r in conn.execute(
            """SELECT zone_key FROM scoped_mitigated_order_blocks WHERE provider=? AND data_mode='LIVE'
               AND state_context='SCANNER' AND segment=? AND interval_min=5""", (profile["provider"], segment)))
            for segment in ("NSE_EQUITY_INTRADAY", "NSE_FO_INDEX")}
        payload = encoded(body)
        store._lineage_checkpoint("between_batches_and_scan")
        conn.execute("INSERT INTO cash_candle_scans VALUES (?,?,?,?, 'PENDING',NULL,NULL)",
                     (run_id, body["work_id"], payload, digest(body)))
        for batch_id in body["batches"]:
            conn.execute("INSERT INTO cash_candle_scan_inputs VALUES (?,?)", (run_id, batch_id))
        store._lineage_checkpoint("before_input_commit")
        result = load(store, run_id, connection=conn)
    store._lineage_checkpoint("after_input_commit")
    return result


def load(store, run_id, connection=None):
    from storage import PersistenceValidationError
    if connection is None:
        with store.lineage_read() as conn:
            return load(store, run_id, connection=conn)
    conn = connection
    row = conn.execute("SELECT * FROM cash_candle_scans WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise PersistenceValidationError("LINEAGE_SCAN_NOT_FOUND")
    snapshot = json.loads(row["snapshot_json"])
    if digest(snapshot) != row["snapshot_digest"] or snapshot["work_id"] != row["work_id"]:
        raise PersistenceValidationError("LINEAGE_SNAPSHOT_INTEGRITY_FAILURE")
    links = {r[0] for r in conn.execute("SELECT batch_id FROM cash_candle_scan_inputs WHERE run_id=?", (run_id,))}
    if links != set(snapshot["batches"]):
        raise PersistenceValidationError("LINEAGE_INPUT_LINK_INTEGRITY_FAILURE")
    batches = []
    for batch_id in snapshot["batches"]:
        meta = conn.execute("SELECT metadata_json,candle_count,metadata_digest FROM cash_candle_batches WHERE batch_id=?", (batch_id,)).fetchone()
        if meta is None:
            raise PersistenceValidationError("LINEAGE_BATCH_MISSING")
        metadata = json.loads(meta[0])
        if digest(metadata) != meta[2]:
            raise PersistenceValidationError("LINEAGE_METADATA_INTEGRITY_FAILURE")
        rows = conn.execute("""SELECT m.ordinal,f.* FROM cash_candle_batch_members m
            JOIN cash_candle_facts f ON f.candle_key=m.candle_key WHERE m.batch_id=? ORDER BY m.ordinal""", (batch_id,)).fetchall()
        bars = []
        content = metadata.pop("content_header")
        for ordinal, entry in enumerate(rows):
            bar = json.loads(entry["payload_json"])
            if (entry["ordinal"] != ordinal or digest(bar) != entry["content_digest"]
                    or _candle_key(content, bar) != entry["candle_key"] or bar.get("is_complete") is not True):
                raise PersistenceValidationError("LINEAGE_CANDLE_INTEGRITY_FAILURE")
            bars.append(bar)
        content["candles"] = bars
        if len(bars) != meta[1] or not bars or digest(content) != batch_id or metadata["batch_id"] != batch_id:
            raise PersistenceValidationError("LINEAGE_BATCH_INTEGRITY_FAILURE")
        batches.append(dict(metadata, content=content))
    snapshot["batches"] = batches
    if work_identity(snapshot) != row["work_id"]:
        raise PersistenceValidationError("LINEAGE_WORK_ID_CONFLICT")
    result = json.loads(row["result_json"]) if row["result_json"] else None
    if (row["status"] == "COMMITTED") != (result is not None):
        raise PersistenceValidationError("LINEAGE_COMMIT_INTEGRITY_FAILURE")
    if result is not None and digest(result) != row["result_digest"]:
        raise PersistenceValidationError("LINEAGE_RESULT_INTEGRITY_FAILURE")
    if result is not None:
        _check_committed_outcome(conn, run_id, snapshot, result)
    return dict(run_id=run_id, status=row["status"], snapshot=snapshot, result=result)


def _check_committed_outcome(conn, run_id, snapshot, result):
    from storage import PersistenceValidationError, compute_signal_dedup_key
    scan = conn.execute("SELECT * FROM scan_runs WHERE run_id=?", (run_id,)).fetchone()
    if (not scan or result["run_id"] != run_id
            or any(scan[column] != result[field] for column, field in (
                ("status", "scan_status"), ("total_signals", "total_signals"),
                ("persisted_signals", "persisted_signals"), ("duplicate_signals", "duplicate_signals")))):
        raise PersistenceValidationError("LINEAGE_SCAN_OUTCOME_INTEGRITY_FAILURE")
    by_symbol = {b["content"]["identity"]["symbol"]: b["batch_id"] for b in snapshot["batches"]}
    expected = set()
    for sig in result["signals"]:
        key = compute_signal_dedup_key(sig, result["broker"])
        persisted = conn.execute("SELECT * FROM signals WHERE dedup_key=?", (key,)).fetchone()
        if (not persisted or persisted["symbol"] != sig["symbol"]
                or persisted["segment"] != sig["segment"]
                or json.loads(persisted["instrument_identity_json"]) != sig["instrument_identity"]
                or any(persisted[k] != round(float(sig[k]), 2) for k in
                       ("entry_price", "stop_loss", "target_1", "target_2"))):
            raise PersistenceValidationError("LINEAGE_SIGNAL_INTEGRITY_FAILURE")
        if sig["segment"] == "NSE_EQUITY_INTRADAY":
            if sig["symbol"] not in by_symbol:
                raise PersistenceValidationError("LINEAGE_SIGNAL_INPUT_MISSING")
            expected.add((key, by_symbol[sig["symbol"]]))
    actual = {tuple(r) for r in conn.execute(
        "SELECT dedup_key,batch_id FROM cash_candle_signal_inputs WHERE run_id=?", (run_id,))}
    if expected != actual:
        raise PersistenceValidationError("LINEAGE_SIGNAL_LINK_INTEGRITY_FAILURE")


def finish(store, run_id, summary):
    from storage import PersistenceError, compute_signal_dedup_key
    if getattr(store._scan_local, "connection", None) is None:
        raise PersistenceError("LINEAGE_RESULT_TRANSACTION_REQUIRED")
    work = store.load_cash_scan(run_id)
    if work["status"] != "PENDING" or summary["persistence_status"] != "OK":
        raise PersistenceError("LINEAGE_SCAN_NOT_COMMITTABLE")
    conn = store._get_connection()
    by_symbol = {b["content"]["identity"]["symbol"]: b["batch_id"] for b in work["snapshot"]["batches"]}
    for sig in summary["signals"]:
        if sig["segment"] != "NSE_EQUITY_INTRADAY":
            continue
        key = compute_signal_dedup_key(sig, summary["broker"])
        row = conn.execute("SELECT dedup_key FROM signals WHERE dedup_key=?", (key,)).fetchone()
        if not row or sig["symbol"] not in by_symbol:
            raise PersistenceError("LINEAGE_PERSISTED_SIGNAL_LINK_REQUIRED")
        conn.execute("INSERT INTO cash_candle_signal_inputs VALUES (?,?,?)", (run_id, key, by_symbol[sig["symbol"]]))
    scan = conn.execute("SELECT status FROM scan_runs WHERE run_id=?", (run_id,)).fetchone()
    if not scan or scan[0] != summary["scan_status"]:
        raise PersistenceError("LINEAGE_PERSISTED_SCAN_OUTCOME_REQUIRED")
    body = encoded(summary)
    conn.execute("UPDATE cash_candle_scans SET status='COMMITTED',result_json=?,result_digest=? WHERE run_id=?",
                 (body, digest(summary), run_id))
    store._lineage_checkpoint("before_result_commit")


def replay_summary(work):
    """No new scan or signal claimed; original committed result stays immutable."""
    result = copy.deepcopy(work["result"])
    result.update(idempotent_replay=True, original_total_signals=result["total_signals"],
        original_result=copy.deepcopy(work["result"]), total_signals=0, signals=[],
        persisted_signals=0, duplicate_signals=0, telegram_dispatches=[],
        recovery_scope="RETAINED_INPUT_NOT_CURRENT_MARKET_ACCEPTANCE")
    result["candle_freshness"] = dict(status="RETAINED_INPUT", live_signal_allowed=False)
    return result

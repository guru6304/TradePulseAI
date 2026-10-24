"""Transactional local notification previews; real delivery is not authorized.

Only DRY_RUN_ONLY intents are supported. Rendering and acknowledgement are local
SQLite operations; no destination, credential, HTTP sender or scheduler exists
here. A future real transport needs its own authorization and uncertain-ack policy.
"""
from datetime import datetime, timedelta
import json

from candle_lineage import digest, encoded, load
from storage import PersistenceError, PersistenceValidationError, compute_signal_dedup_key
from strategies import IST, parse_ist_timestamp

STATES = ("PENDING", "RETRY", "ACKNOWLEDGED", "DEAD")
MAX_ATTEMPTS = 3
MAX_PAYLOAD_BYTES = 256 * 1024
CONTEXT_POLICY = "QUALIFIED_CONTEXT_FOR_STORED_CANDIDATE_V1"


def create_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS notification_outbox (
        intent_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES cash_candle_scans(run_id),
        payload_json TEXT NOT NULL, content_digest TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('PENDING','RETRY','ACKNOWLEDGED','DEAD')),
        attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL,
        receipt_json TEXT, receipt_digest TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS notification_attempts (
        attempt_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL REFERENCES notification_outbox(intent_id),
        attempt_number INTEGER NOT NULL, status TEXT NOT NULL, reason_code TEXT NOT NULL,
        observed_at TEXT NOT NULL, UNIQUE(intent_id,attempt_number))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_pending ON notification_outbox(status,next_attempt_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS context_alert_decisions (
        decision_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES scan_context_snapshots(snapshot_id),
        candidate_id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES scan_runs(run_id),
        payload_json TEXT NOT NULL, payload_digest TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_context_alert_run ON context_alert_decisions(run_id,snapshot_id)")


def enqueue(store, run_id, signal, dispatcher, broker, batch_ids, reference):
    if getattr(store._scan_local, "connection", None) is None:
        raise PersistenceError("NOTIFICATION_SCAN_TRANSACTION_REQUIRED")
    key = compute_signal_dedup_key(signal, broker)
    intent_id = digest(["notification-preview-v1", key])
    html = dispatcher.format_signal_html(signal, broker)
    if not isinstance(html, str) or len(html)>16000:
        raise PersistenceValidationError("NOTIFICATION_PREVIEW_SIZE_LIMIT")
    body = dict(version=1, mode="DRY_RUN_ONLY", intent_id=intent_id, run_id=run_id,
        signal_key=key, batch_ids=batch_ids, source_reference=str(reference),
        message_html="<b>DRY-RUN PREVIEW: stored candidate; no delivery or live acceptance.</b>\n"+html)
    conn = store._get_connection()
    old = conn.execute("SELECT content_digest FROM notification_outbox WHERE intent_id=?", (intent_id,)).fetchone()
    if old and old[0]!=digest(body):
        raise PersistenceValidationError("NOTIFICATION_INTENT_CONFLICT")
    conn.execute("INSERT OR IGNORE INTO notification_outbox VALUES (?,?,?,?, 'PENDING',0,?,NULL,NULL)",
        (intent_id, run_id, encoded(body), digest(body), parse_ist_timestamp(reference).isoformat()))
    return intent_id


def _checked(row):
    if row is None:
        raise PersistenceValidationError("NOTIFICATION_INTENT_NOT_FOUND")
    try:
        if (not isinstance(row["payload_json"], str) or len(row["payload_json"]) > MAX_PAYLOAD_BYTES
                or len(row["payload_json"].encode("utf-8")) > MAX_PAYLOAD_BYTES):
            raise ValueError("oversized intent")
        body = json.loads(row["payload_json"])
        if (not isinstance(body, dict) or type(body.get("version")) is not int or body["version"] not in (1, 2)
                or not isinstance(body.get("message_html"), str) or len(body["message_html"]) > 17000
                or digest(body)!=row["content_digest"] or body["mode"]!="DRY_RUN_ONLY"
            or body["intent_id"]!=row["intent_id"] or body["run_id"]!=row["run_id"]
            or row["status"] not in STATES or type(row["attempts"]) is not int
            or not 0<=row["attempts"]<=MAX_ATTEMPTS
            or row["status"]=="PENDING" and row["attempts"]!=0
            or row["status"]=="RETRY" and row["attempts"] not in (1,2)
            or row["status"]=="DEAD" and row["attempts"]!=MAX_ATTEMPTS
                or row["status"]=="ACKNOWLEDGED" and row["attempts"]==0):
            raise ValueError("invalid intent")
        parse_ist_timestamp(row["next_attempt_at"])
        receipt_json = row["receipt_json"]
        if receipt_json is not None and (not isinstance(receipt_json, str)
                or len(receipt_json) > MAX_PAYLOAD_BYTES
                or len(receipt_json.encode("utf-8")) > MAX_PAYLOAD_BYTES):
            raise PersistenceValidationError("NOTIFICATION_RECEIPT_INTEGRITY_FAILURE")
        receipt = json.loads(receipt_json) if receipt_json is not None else None
        if ((row["status"]=="ACKNOWLEDGED") != (receipt is not None)
                or receipt is not None and (digest(receipt)!=row["receipt_digest"] or receipt != _receipt(body))
                or receipt is None and row["receipt_digest"] is not None):
            raise PersistenceValidationError("NOTIFICATION_RECEIPT_INTEGRITY_FAILURE")
    except PersistenceValidationError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise PersistenceValidationError("NOTIFICATION_INTENT_INTEGRITY_FAILURE") from exc
    return body, receipt


def descriptors(store, intent_ids):
    """Bind newly enqueued original previews into the immutable scan result."""
    if not isinstance(intent_ids, list) or len(set(intent_ids)) != len(intent_ids):
        raise PersistenceValidationError("NOTIFICATION_DESCRIPTOR_SCOPE_INVALID")
    conn = store._get_connection()
    try:
        result = []
        for intent_id in intent_ids:
            row = conn.execute("SELECT * FROM notification_outbox WHERE intent_id=?", (intent_id,)).fetchone()
            body, _ = _checked(row)
            if body["version"] != 1:
                raise PersistenceValidationError("NOTIFICATION_ORIGINAL_DESCRIPTOR_REQUIRED")
            result.append(dict(intent_id=intent_id, content_digest=row["content_digest"]))
        return result
    finally:
        store._close_if_file(conn)


def _validate_original(store, row, body, conn, work=None, read_cache=None):
    work = work or load(store, row["run_id"], connection=conn, read_cache=read_cache)
    if work["status"] != "COMMITTED":
        raise PersistenceValidationError("NOTIFICATION_COMMITTED_SCAN_REQUIRED")
    result = work["result"]
    key = body.get("signal_key")
    signal = next((value for value in result["signals"]
                   if compute_signal_dedup_key(value, result["broker"]) == key), None)
    expected_batches = [batch["batch_id"] for batch in work["snapshot"]["batches"]]
    if (signal is None or body["intent_id"] != digest(["notification-preview-v1", key])
            or body.get("batch_ids") != expected_batches
            or parse_ist_timestamp(body.get("source_reference")) != parse_ist_timestamp(work["snapshot"]["reference"])):
        raise PersistenceValidationError("NOTIFICATION_SOURCE_BINDING_FAILURE")
    bound = result.get("notification_descriptors")
    if bound is not None:
        expected = dict(intent_id=row["intent_id"], content_digest=row["content_digest"])
        if not isinstance(bound, list) or sum(item == expected for item in bound) != 1:
            raise PersistenceValidationError("NOTIFICATION_CONTENT_BINDING_FAILURE")
        return "COMMITTED_CONTENT_BINDING"
    # Old snapshots are readable without inventing a retroactive content receipt.
    return "LEGACY_STRUCTURAL_BINDING_CONTENT_AUTHORITY_UNAVAILABLE"


def _context_semantic(candidate_id, context):
    return digest(dict(candidate_id=candidate_id, policy=CONTEXT_POLICY, kind="CONTEXT_UPDATE",
        status=context.get("status"), reason_codes=sorted(context.get("reason_codes", [])),
        records=sorted(([row.get("record_id"), row.get("content_id")]
                        for row in context.get("records", [])), key=encoded)))


def _context_components(store, run_id, snapshot_id, conn, read_cache=None):
    key = ("components", run_id, snapshot_id)
    if read_cache is not None and key in read_cache:
        return read_cache[key]
    snapshot = store.load_scan_context(run_id, connection=conn, snapshot_id=snapshot_id, read_cache=read_cache)
    evaluation = store.load_scan_evaluations(run_id, connection=conn, read_cache=read_cache)
    if (not isinstance(snapshot, dict) or snapshot.get("snapshot_id") != snapshot_id
            or snapshot.get("run_id") != run_id or evaluation is None
            or snapshot.get("phase4_digest") != digest(evaluation)
            or snapshot.get("actionable") is not False or snapshot.get("affects_ranking") is not False):
        raise PersistenceValidationError("CONTEXT_ALERT_SNAPSHOT_BINDING_FAILURE")
    result = snapshot, evaluation
    if read_cache is not None:
        read_cache[key] = result
    return result


def _context_qualification(candidate, context, snapshot):
    from context_data import IDENTITY_FIELDS
    if not candidate or candidate.get("status") != "QUALIFIED" or candidate.get("actionable") is not False:
        return "SUPPRESSED", "CANDIDATE_NOT_QUALIFIED"
    if (not context or context.get("status") != "QUALIFIED" or context.get("actionable") is not False
            or context.get("affects_ranking") is not False):
        return "SUPPRESSED", "CONTEXT_NOT_QUALIFIED"
    records = context.get("records", [])
    if not records:
        return "SUPPRESSED", "CONTEXT_RECORDS_MISSING"
    identity = candidate.get("source_reference", {}).get("instrument_identity", {})
    for record in records:
        verify = record.get("verification", {})
        actual = record.get("instrument_identity", {})
        if (verify.get("allowed") is not True or verify.get("status") != "QUALIFIED_UNDER_LOCAL_POLICY"
                or record.get("retracted") or record.get("conflict")
                or record.get("freshness", {}).get("status") != "FRESH"
                or not record.get("record_id") or not record.get("content_id")
                or not identity or any(actual.get(field) != identity.get(field) for field in IDENTITY_FIELDS)):
            return "SUPPRESSED", "CONTEXT_SOURCE_NOT_QUALIFIED"
    return "ELIGIBLE", "QUALIFIED_CONTEXT_FOR_STORED_CANDIDATE"


def _context_body(candidate, context, snapshot, decision_at):
    from telegram_bot import format_context_alert_html
    semantic = _context_semantic(candidate["candidate_id"], context)
    intent_id = digest(["notification-context-v2", candidate["candidate_id"], semantic, CONTEXT_POLICY])
    message = format_context_alert_html(candidate, context, snapshot, decision_at)
    if len(message) > 16000:
        raise PersistenceValidationError("NOTIFICATION_PREVIEW_SIZE_LIMIT")
    return dict(version=2, mode="DRY_RUN_ONLY", kind="CONTEXT_UPDATE", policy=CONTEXT_POLICY,
        intent_id=intent_id, run_id=snapshot["run_id"], signal_key=candidate["candidate_id"],
        candidate_id=candidate["candidate_id"], snapshot_id=snapshot["snapshot_id"],
        snapshot_digest=digest(snapshot), phase4_digest=snapshot["phase4_digest"],
        semantic_context_digest=semantic, source_reference=snapshot["as_of"],
        context_record_refs=[dict(record_id=row["record_id"], content_id=row["content_id"])
                             for row in context["records"]],
        batch_ids=candidate.get("source_reference", {}).get("batch_ids", []),
        reason_codes=context.get("reason_codes", []), evaluation_mode=snapshot.get("evaluation_mode", "DECISION_TIME"),
        decision_at=decision_at, context_as_of=snapshot["as_of"], message_html=message)


def validate_context_intent(store, row, *, connection=None, read_cache=None):
    """Pure validation without loading cash work or dispatching a notification."""
    body, _ = _checked(row)
    if body["version"] != 2:
        return None
    conn = connection or store._get_connection()
    try:
        snapshot, evaluation = _context_components(store, row["run_id"], body.get("snapshot_id"), conn, read_cache)
        candidate = next((item for item in evaluation["candidate_evaluations"]
                          if item["candidate_id"] == body.get("candidate_id")), None)
        context = next((item for item in snapshot["candidate_contexts"]
                        if item.get("candidate_id") == body.get("candidate_id")), None)
        status, _ = _context_qualification(candidate, context, snapshot)
        cash = conn.execute("SELECT status FROM cash_candle_scans WHERE run_id=?", (row["run_id"],)).fetchone()
        decision_at = parse_ist_timestamp(snapshot["decision_at"]).isoformat()
        if (not cash or cash[0] != "COMMITTED" or status != "ELIGIBLE"
                or body != _context_body(candidate, context, snapshot, decision_at)):
            raise PersistenceValidationError("CONTEXT_ALERT_CONTENT_BINDING_FAILURE")
        return body
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, PersistenceValidationError):
            raise
        raise PersistenceValidationError("CONTEXT_ALERT_CONTENT_BINDING_FAILURE") from exc
    finally:
        if connection is None:
            store._close_if_file(conn)


def _decision_body(conn, snapshot, candidate, context, candidate_id, reference):
    status, reason = _context_qualification(candidate, context, snapshot)
    committed = conn.execute("SELECT status FROM cash_candle_scans WHERE run_id=?", (snapshot["run_id"],)).fetchone()
    if not committed or committed[0] != "COMMITTED":
        status, reason = "UNAVAILABLE", "CONTEXT_ALERT_REQUIRES_COMMITTED_CASH_SCAN"
    observed_at = parse_ist_timestamp(reference).isoformat()
    if parse_ist_timestamp(snapshot["as_of"]) > parse_ist_timestamp(observed_at):
        status, reason = "UNAVAILABLE", "CONTEXT_EVALUATION_IN_FUTURE"
    decision_id = digest(["context-alert-decision-v1", snapshot["snapshot_id"], candidate_id, CONTEXT_POLICY])
    semantic = _context_semantic(candidate_id, context) if context else None
    decision = dict(schema_version="tradepulse.context-alert-decision.v1", decision_id=decision_id,
        snapshot_id=snapshot["snapshot_id"], run_id=snapshot["run_id"], candidate_id=candidate_id,
        status=status, reason_code=reason, policy=CONTEXT_POLICY, semantic_context_digest=semantic,
        observed_at=observed_at, actionable=False, execution_mode="LOCAL_PREVIEW_ONLY", real_delivery_enabled=False)
    if status == "ELIGIBLE":
        decision["intent_id"] = digest(["notification-context-v2", candidate_id, semantic, CONTEXT_POLICY])
    return decision


def _checked_decision(store, row, conn, read_cache=None):
    try:
        if (not isinstance(row["payload_json"], str) or len(row["payload_json"]) > MAX_PAYLOAD_BYTES
                or len(row["payload_json"].encode("utf-8")) > MAX_PAYLOAD_BYTES):
            raise ValueError("oversized decision")
        body = json.loads(row["payload_json"])
        snapshot, evaluation = _context_components(store, row["run_id"], row["snapshot_id"], conn, read_cache)
        candidate = next((item for item in evaluation["candidate_evaluations"]
                          if item["candidate_id"] == row["candidate_id"]), None)
        context = next((item for item in snapshot["candidate_contexts"]
                        if item.get("candidate_id") == row["candidate_id"]), None)
        expected = _decision_body(conn, snapshot, candidate, context, row["candidate_id"], body["observed_at"])
        if (digest(body) != row["payload_digest"] or body != expected
                or body["decision_id"] != row["decision_id"]):
            raise ValueError("decision source binding mismatch")
        if body["status"] == "ELIGIBLE":
            intent = conn.execute("SELECT * FROM notification_outbox WHERE intent_id=?", (body["intent_id"],)).fetchone()
            checked = validate_context_intent(store, intent, connection=conn, read_cache=read_cache)
            if checked["semantic_context_digest"] != body["semantic_context_digest"]:
                raise ValueError("decision intent mismatch")
        return body
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise PersistenceValidationError("CONTEXT_ALERT_DECISION_INTEGRITY_FAILURE") from exc


def enqueue_context(store, run_id, candidate_id, context_snapshot, reference):
    """Persist a context alert decision; eligible output remains a local preview."""
    with store.paper_transaction(write=True) as conn:
        snapshot_id = context_snapshot.get("snapshot_id") if isinstance(context_snapshot, dict) else None
        snapshot, evaluation = _context_components(store, run_id, snapshot_id, conn)
        if digest(snapshot) != digest(context_snapshot):
            raise PersistenceValidationError("CONTEXT_ALERT_SNAPSHOT_BINDING_FAILURE")
        candidate = next((item for item in evaluation["candidate_evaluations"]
                          if item["candidate_id"] == candidate_id), None)
        context = next((item for item in snapshot["candidate_contexts"] if item.get("candidate_id") == candidate_id), None)
        decision = _decision_body(conn, snapshot, candidate, context, candidate_id, reference)
        decision_id, semantic = decision["decision_id"], decision["semantic_context_digest"]
        old = conn.execute("SELECT * FROM context_alert_decisions WHERE decision_id=?", (decision_id,)).fetchone()
        if old:
            return _checked_decision(store, old, conn)
        if decision["status"] == "ELIGIBLE":
            body = _context_body(candidate, context, snapshot, parse_ist_timestamp(snapshot["decision_at"]).isoformat())
            existing = conn.execute("SELECT * FROM notification_outbox WHERE intent_id=?", (body["intent_id"],)).fetchone()
            if existing:
                original = validate_context_intent(store, existing, connection=conn)
                if original["semantic_context_digest"] != semantic:
                    raise PersistenceValidationError("CONTEXT_ALERT_INTENT_CONFLICT")
            else:
                conn.execute("INSERT INTO notification_outbox VALUES (?,?,?,?, 'PENDING',0,?,NULL,NULL)",
                    (body["intent_id"], run_id, encoded(body), digest(body), parse_ist_timestamp(reference).isoformat()))
        conn.execute("INSERT INTO context_alert_decisions VALUES (?,?,?,?,?,?)", (
            decision_id, snapshot_id, candidate_id, run_id, encoded(decision), digest(decision)))
        return decision


def list_context_decisions(store, run_id=None, connection=None, read_cache=None):
    if connection is None:
        with store.lineage_read() as conn:
            return list_context_decisions(store, run_id, conn, {})
    conn = connection or store._get_connection()
    try:
        rows = conn.execute("SELECT * FROM context_alert_decisions WHERE (? IS NULL OR run_id=?) ORDER BY rowid DESC LIMIT 200",
                            (run_id, run_id)).fetchall()
        result = []
        # Reuse validated inputs only within this one read operation. Each
        # decision is still recomputed; no cached verdict survives a request.
        if read_cache is None:
            read_cache = {}
        for row in rows:
            result.append(_checked_decision(store, row, conn, read_cache))
        return result
    finally:
        if connection is None:
            store._close_if_file(conn)


def _check_attempts(conn, row):
    attempts = conn.execute("SELECT * FROM notification_attempts WHERE intent_id=? ORDER BY attempt_number",
                            (row["intent_id"],)).fetchall()
    if (len(attempts)!=row["attempts"] or any(r["attempt_number"]!=n or r["attempt_id"]!=digest([row["intent_id"], n])
            for n,r in enumerate(attempts,1)) or attempts and attempts[-1]["status"]!=row["status"]):
        raise PersistenceValidationError("NOTIFICATION_ATTEMPT_INTEGRITY_FAILURE")
    previous = None
    for index, attempt in enumerate(attempts):
        expected = "RETRY" if index < len(attempts)-1 else row["status"]
        reason = ("LOCAL_PREVIEW_RECORDED_NO_DELIVERY" if expected == "ACKNOWLEDGED" else "LOCAL_PREVIEW_RENDER_FAILED")
        try:
            observed = parse_ist_timestamp(attempt["observed_at"])
            if (attempt["status"] != expected or attempt["reason_code"] != reason
                    or previous is not None and observed < previous):
                raise ValueError("invalid attempt sequence")
            previous = observed
        except (ValueError, TypeError) as exc:
            raise PersistenceValidationError("NOTIFICATION_ATTEMPT_INTEGRITY_FAILURE") from exc


def _receipt(body):
    return dict(ok=True, dry_run=True, status="ACKNOWLEDGED", intent_id=body["intent_id"],
        run_id=body["run_id"], message_html=body["message_html"], current_live_acceptance=False,
        execution_mode="LOCAL_PREVIEW_ONLY")


def render_preview(body):
    """Pure local rendering of retained content, with no destination or sender."""
    return _receipt(body)


def preview(store, intent_id, now=None):
    reference = parse_ist_timestamp(now or datetime.now(IST))
    with store.paper_transaction() as conn:
        row = conn.execute("SELECT * FROM notification_outbox WHERE intent_id=?", (intent_id,)).fetchone()
        body, receipt = _checked(row)
        _check_attempts(conn, row)
        if body["version"] == 2:
            validate_context_intent(store, row, connection=conn)
            binding = "IMMUTABLE_CONTEXT_SNAPSHOT_AND_PHASE4_BINDING"
        else:
            binding = _validate_original(store, row, body, conn)
        if receipt:
            return dict(receipt, binding_status=binding)
        if row["status"]=="DEAD":
            return dict(ok=False, dry_run=True, status="DEAD", intent_id=intent_id, reason="PREVIEW_REQUIRES_INSPECTION")
        if reference < parse_ist_timestamp(row["next_attempt_at"]):
            return dict(ok=False, dry_run=True, status="DEFERRED", intent_id=intent_id)
        attempt = row["attempts"]+1
        try:
            receipt = render_preview(body)
            if receipt != _receipt(body):
                raise ValueError("INVALID_LOCAL_PREVIEW")
            status, reason = "ACKNOWLEDGED", "LOCAL_PREVIEW_RECORDED_NO_DELIVERY"
        except Exception:
            receipt = None
            status, reason = ("DEAD" if attempt>=MAX_ATTEMPTS else "RETRY"), "LOCAL_PREVIEW_RENDER_FAILED"
        due = reference+timedelta(seconds=5*2**(attempt-1))
        conn.execute("UPDATE notification_outbox SET status=?,attempts=?,next_attempt_at=?,receipt_json=?,receipt_digest=? WHERE intent_id=?",
            (status, attempt, due.isoformat(), encoded(receipt) if receipt else None,
             digest(receipt) if receipt else None, intent_id))
        conn.execute("INSERT INTO notification_attempts VALUES (?,?,?,?,?,?)", (
            digest([intent_id, attempt]), intent_id, attempt, status, reason, reference.isoformat()))
        store._notification_checkpoint("before_notification_commit")
    store._notification_checkpoint("after_notification_commit")
    return dict(receipt, binding_status=binding) if receipt else dict(
        ok=False, dry_run=True, status=status, intent_id=intent_id, reason=reason, binding_status=binding)


def list_items(store, limit=100, status=None, read_cache=None):
    if type(limit) is not int or not 1<=limit<=200 or status is not None and status not in STATES:
        raise PersistenceValidationError("INVALID_NOTIFICATION_QUERY")
    with store.paper_transaction(write=False) as conn:
        # No validated verdict survives this one locked SQLite read snapshot.
        read_cache = {}
        rows = conn.execute("SELECT * FROM notification_outbox WHERE (? IS NULL OR status=?) ORDER BY intent_id LIMIT ?",
                            (status, status, limit)).fetchall()
        counts = {r[0]: r[1] for r in conn.execute("SELECT status,COUNT(*) FROM notification_outbox GROUP BY status")}
        items = []
        work_cache = {}
        for row in rows:
            body, _ = _checked(row)
            _check_attempts(conn, row)
            if body["version"] == 2:
                validate_context_intent(store, row, connection=conn, read_cache=read_cache)
                binding = "IMMUTABLE_CONTEXT_SNAPSHOT_AND_PHASE4_BINDING"
            else:
                if row["run_id"] not in work_cache:
                    work_cache[row["run_id"]] = load(store, row["run_id"], connection=conn, read_cache=read_cache)
                binding = _validate_original(store, row, body, conn, work_cache[row["run_id"]], read_cache)
            items.append(dict(intent_id=row["intent_id"], run_id=row["run_id"], status=row["status"],
                attempts=row["attempts"], next_attempt_at=row["next_attempt_at"], mode=body["mode"],
                binding_status=binding, kind=body.get("kind", "CANDIDATE_PREVIEW"),
                candidate_id=body.get("candidate_id", body.get("signal_key")),
                context_snapshot_id=body.get("snapshot_id"), context_record_refs=body.get("context_record_refs", []),
                reason_codes=body.get("reason_codes", []),
                delivery_state="DRY_RUN_RECORDED" if row["status"] == "ACKNOWLEDGED" else row["status"],
                current_recommendation=False))
        decisions = list_context_decisions(store, connection=conn, read_cache=read_cache)
    return dict(status="OK", execution_mode="LOCAL_PREVIEW_ONLY", real_delivery_enabled=False,
                counts=counts, items=items, limit=limit, context_alert_decisions=decisions)

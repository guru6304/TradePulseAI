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
    body = json.loads(row["payload_json"])
    if (digest(body)!=row["content_digest"] or body["mode"]!="DRY_RUN_ONLY"
            or body["intent_id"]!=row["intent_id"] or body["run_id"]!=row["run_id"]
            or row["status"] not in STATES or type(row["attempts"]) is not int
            or not 0<=row["attempts"]<=MAX_ATTEMPTS
            or row["status"]=="PENDING" and row["attempts"]!=0
            or row["status"]=="RETRY" and row["attempts"] not in (1,2)
            or row["status"]=="DEAD" and row["attempts"]!=MAX_ATTEMPTS
            or row["status"]=="ACKNOWLEDGED" and row["attempts"]==0):
        raise PersistenceValidationError("NOTIFICATION_INTENT_INTEGRITY_FAILURE")
    receipt = json.loads(row["receipt_json"]) if row["receipt_json"] else None
    if ((row["status"]=="ACKNOWLEDGED") != (receipt is not None)
            or receipt is not None and digest(receipt)!=row["receipt_digest"]):
        raise PersistenceValidationError("NOTIFICATION_RECEIPT_INTEGRITY_FAILURE")
    return body, receipt


def _check_attempts(conn, row):
    attempts = conn.execute("SELECT * FROM notification_attempts WHERE intent_id=? ORDER BY attempt_number",
                            (row["intent_id"],)).fetchall()
    if (len(attempts)!=row["attempts"] or any(r["attempt_number"]!=n or r["attempt_id"]!=digest([row["intent_id"], n])
            for n,r in enumerate(attempts,1)) or attempts and attempts[-1]["status"]!=row["status"]):
        raise PersistenceValidationError("NOTIFICATION_ATTEMPT_INTEGRITY_FAILURE")


def render_preview(body):
    """Pure local rendering of retained content, with no destination or sender."""
    return dict(ok=True, dry_run=True, status="ACKNOWLEDGED", intent_id=body["intent_id"],
        run_id=body["run_id"], message_html=body["message_html"], current_live_acceptance=False,
        execution_mode="LOCAL_PREVIEW_ONLY")


def preview(store, intent_id, now=None):
    reference = parse_ist_timestamp(now or datetime.now(IST))
    with store.paper_transaction() as conn:
        row = conn.execute("SELECT * FROM notification_outbox WHERE intent_id=?", (intent_id,)).fetchone()
        body, receipt = _checked(row)
        _check_attempts(conn, row)
        work = load(store, row["run_id"], connection=conn)
        if work["status"]!="COMMITTED":
            raise PersistenceValidationError("NOTIFICATION_COMMITTED_SCAN_REQUIRED")
        if receipt:
            return receipt
        if row["status"]=="DEAD":
            return dict(ok=False, dry_run=True, status="DEAD", intent_id=intent_id, reason="PREVIEW_REQUIRES_INSPECTION")
        if reference < parse_ist_timestamp(row["next_attempt_at"]):
            return dict(ok=False, dry_run=True, status="DEFERRED", intent_id=intent_id)
        attempt = row["attempts"]+1
        try:
            receipt = render_preview(body)
            if receipt.get("status")!="ACKNOWLEDGED" or receipt.get("dry_run") is not True or receipt.get("ok") is not True:
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
    return receipt or dict(ok=False, dry_run=True, status=status, intent_id=intent_id, reason=reason)


def list_items(store, limit=100, status=None):
    if type(limit) is not int or not 1<=limit<=200 or status is not None and status not in STATES:
        raise PersistenceValidationError("INVALID_NOTIFICATION_QUERY")
    with store.paper_transaction(write=False) as conn:
        rows = conn.execute("SELECT * FROM notification_outbox WHERE (? IS NULL OR status=?) ORDER BY intent_id LIMIT ?",
                            (status, status, limit)).fetchall()
        counts = {r[0]: r[1] for r in conn.execute("SELECT status,COUNT(*) FROM notification_outbox GROUP BY status")}
        items = []
        for row in rows:
            body, _ = _checked(row)
            _check_attempts(conn, row)
            items.append(dict(intent_id=row["intent_id"], run_id=row["run_id"], status=row["status"],
                attempts=row["attempts"], next_attempt_at=row["next_attempt_at"], mode=body["mode"]))
    return dict(status="OK", execution_mode="LOCAL_PREVIEW_ONLY", real_delivery_enabled=False,
                counts=counts, items=items, limit=limit)

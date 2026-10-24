"""Offline context imports and immutable enrichment of existing scan results.

No fetcher, account client, message transport or scheduler exists here. Source
qualification uses separately supplied runtime policy, never request flags.
"""
import copy
import json
from datetime import datetime

from candle_lineage import digest, encoded
from strategies import IST

MAX_INGESTIONS = 200
MAX_RECORDS = 2000
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOTS_PER_RUN = 200


def create_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS context_ingestions (
        ingestion_id TEXT PRIMARY KEY, provider TEXT NOT NULL, collected_at TEXT NOT NULL,
        observed_at TEXT NOT NULL, capture_id TEXT NOT NULL UNIQUE,
        original_bytes BLOB NOT NULL, identities_json TEXT NOT NULL,
        payload_json TEXT NOT NULL, payload_digest TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS scan_context_snapshots (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id TEXT NOT NULL UNIQUE,
        run_id TEXT NOT NULL REFERENCES scan_runs(run_id), as_of TEXT NOT NULL,
        payload_json TEXT NOT NULL, payload_digest TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_context_scan ON scan_context_snapshots(run_id,sequence DESC)")
    conn.execute("""CREATE TABLE IF NOT EXISTS scan_context_sources (
        snapshot_id TEXT NOT NULL REFERENCES scan_context_snapshots(snapshot_id),
        capture_id TEXT NOT NULL REFERENCES context_ingestions(capture_id),
        PRIMARY KEY(snapshot_id,capture_id))""")


def _invalid(code):
    from storage import PersistenceValidationError
    raise PersistenceValidationError(code)


def _stored_json(value):
    # SQLite affinity permits privileged writers to put BLOBs in TEXT columns.
    # Reject invalid type and size before decoding or allocating derived objects.
    if (not isinstance(value, str) or len(value) > MAX_SNAPSHOT_BYTES
            or len(value.encode('utf-8')) > MAX_SNAPSHOT_BYTES):
        _invalid('CONTEXT_STORED_PAYLOAD_TYPE_OR_SIZE_INVALID')
    return json.loads(value)


def _aware(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and len(value) <= 64:
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            _invalid('CONTEXT_AWARE_TIMESTAMP_REQUIRED')
    else:
        _invalid('CONTEXT_AWARE_TIMESTAMP_REQUIRED')
    if result.tzinfo is None or result.utcoffset() is None:
        _invalid('CONTEXT_AWARE_TIMESTAMP_REQUIRED')
    return result.astimezone(IST)


def ingest(store, raw_bytes, *, provider, collected_at, trusted_identities, source_policy=None, observed_at=None):
    from context_data import parse_context_bytes
    identities = copy.deepcopy(list(trusted_identities))
    payload = parse_context_bytes(raw_bytes, provider=provider, collected_at=collected_at,
        trusted_identities=identities, source_policy=source_policy)
    observation = _aware(observed_at if observed_at is not None else datetime.now(IST)).isoformat()
    if _aware(payload['collected_at']) > _aware(observation):
        _invalid('CONTEXT_COLLECTION_AFTER_LOCAL_CAPTURE')
    capture_id = digest(['context-capture-v1', payload['ingestion_id'], observation])
    body, checksum = encoded(payload), digest(payload)
    identities_body = encoded(identities)
    if any(len(value.encode('utf-8')) > MAX_SNAPSHOT_BYTES for value in (body, identities_body)):
        _invalid('CONTEXT_STORED_PAYLOAD_TYPE_OR_SIZE_INVALID')
    with store.paper_transaction() as conn:
        old = conn.execute('SELECT * FROM context_ingestions WHERE ingestion_id=?', (payload['ingestion_id'],)).fetchone()
        if old:
            loaded = _load_ingestion(store, old, source_policy=source_policy)
            if loaded != payload:
                _invalid('CONTEXT_INGESTION_CONFLICT')
            return payload
        existing = conn.execute('SELECT * FROM context_ingestions').fetchall()
        if len(existing) >= MAX_INGESTIONS:
            _invalid('CONTEXT_INGESTION_QUERY_LIMIT')
        if sum(len(_load_ingestion(store, row, source_policy=source_policy)['records'])
               for row in existing) + len(payload['records']) > MAX_RECORDS:
            _invalid('CONTEXT_RECORD_QUERY_LIMIT')
        conn.execute('INSERT INTO context_ingestions VALUES (?,?,?,?,?,?,?,?,?)', (
            payload['ingestion_id'], provider, payload['collected_at'], observation, capture_id, raw_bytes,
            identities_body, body, checksum))
        store._context_checkpoint('before_context_import_commit')
    return payload


def _load_ingestion(store, row, source_policy=None):
    from context_data import MAX_BYTES, validate_ingestion
    try:
        raw = row['original_bytes']
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
            _invalid('CONTEXT_INGESTION_ORIGINAL_BYTES_INVALID')
        payload, identities = _stored_json(row['payload_json']), _stored_json(row['identities_json'])
        if (digest(payload) != row['payload_digest'] or payload['ingestion_id'] != row['ingestion_id']
                or payload['provider'] != row['provider'] or payload['collected_at'] != row['collected_at']
                or _aware(row['observed_at']).isoformat() != row['observed_at']
                or _aware(payload['collected_at']) > _aware(row['observed_at'])
                or row['capture_id'] != digest(['context-capture-v1', payload['ingestion_id'], row['observed_at']])):
            _invalid('CONTEXT_INGESTION_INTEGRITY_FAILURE')
        validate_ingestion(payload, raw, trusted_identities=identities,
            source_policy=source_policy if source_policy is not None else getattr(store, 'context_source_policy', None))
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        from storage import PersistenceValidationError
        raise PersistenceValidationError('CONTEXT_INGESTION_INTEGRITY_FAILURE') from exc
    return payload


def list_ingestions(store, limit=100, offset=0):
    if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
        _invalid('CONTEXT_INVALID_PAGE')
    with store.lineage_read() as conn:
        count = conn.execute('SELECT COUNT(*) FROM context_ingestions').fetchone()[0]
        rows = conn.execute('SELECT * FROM context_ingestions ORDER BY ingestion_id LIMIT ? OFFSET ?', (limit, offset)).fetchall()
        return dict(status='OK', source_mode='OFFLINE_IMPORT_ONLY', network_acquisition='NOT_CONFIGURED',
            items=[_load_ingestion(store, row) for row in rows], total_count=count, limit=limit, offset=offset)


def _phase4(store, conn, run_id, read_cache=None):
    key = ('phase4', run_id)
    if read_cache is not None and key in read_cache:
        return read_cache[key]
    evaluation = store.load_scan_evaluations(run_id, connection=conn, read_cache=read_cache)
    if evaluation is None:
        _invalid('CONTEXT_PHASE4_EVALUATION_NOT_RETAINED')
    row = conn.execute('SELECT started_at_ist FROM scan_runs WHERE run_id=?', (run_id,)).fetchone()
    if row is None:
        _invalid('CONTEXT_SCAN_NOT_FOUND')
    # Legacy scan timestamps are explicitly known-IST application timestamps.
    from strategies import parse_ist_timestamp
    decision = parse_ist_timestamp(row['started_at_ist'])
    durable = conn.execute('SELECT status,snapshot_json,snapshot_digest,result_json,result_digest '
                           'FROM cash_candle_scans WHERE run_id=?', (run_id,)).fetchone()
    if durable:
        # Do not invoke the full cash loader here: it validates context outbox
        # intents, which in turn load this context snapshot. Evaluation loading
        # above already checks exact durable strategy/candidate/result binding.
        if durable['status'] != 'COMMITTED' or not durable['result_json']:
            _invalid('CONTEXT_PHASE4_RESULT_NOT_COMMITTED')
        snapshot = json.loads(durable['snapshot_json'])
        result = json.loads(durable['result_json'])
        if (digest(snapshot) != durable['snapshot_digest'] or digest(result) != durable['result_digest']
                or result.get('run_id') != run_id):
            _invalid('CONTEXT_PHASE4_INPUT_INTEGRITY_FAILURE')
        decision = parse_ist_timestamp(snapshot['reference'])
    result = evaluation, decision
    if read_cache is not None:
        read_cache[key] = result
    return result


def _material(store, conn, ingestion_ids=None):
    if ingestion_ids is None:
        rows = conn.execute('SELECT * FROM context_ingestions ORDER BY ingestion_id LIMIT ?', (MAX_INGESTIONS + 1,)).fetchall()
        if len(rows) > MAX_INGESTIONS:
            _invalid('CONTEXT_INGESTION_QUERY_LIMIT')
    else:
        if (not isinstance(ingestion_ids, list) or len(ingestion_ids) > MAX_INGESTIONS
                or len(set(ingestion_ids)) != len(ingestion_ids) or ingestion_ids != sorted(ingestion_ids)):
            _invalid('CONTEXT_INGESTION_REFERENCE_INVALID')
        rows = []
        for key in ingestion_ids:
            row = conn.execute('SELECT * FROM context_ingestions WHERE ingestion_id=?', (key,)).fetchone()
            if row is None:
                _invalid('CONTEXT_INGESTION_REFERENCE_MISSING')
            rows.append(row)
    records, ids, captures = [], [], []
    for row in rows:
        payload = _load_ingestion(store, row)
        ids.append(payload['ingestion_id'])
        captures.append(row['capture_id'])
        records.extend(dict(record, local_ingestion_observed_at=row['observed_at']) for record in payload['records'])
    if len(records) > MAX_RECORDS:
        _invalid('CONTEXT_RECORD_QUERY_LIMIT')
    return records, ids, sorted(captures)


def _snapshot(evaluation, decision, records, ingestion_ids, capture_ids, as_of, evaluation_mode):
    from context_data import context_for_candidate
    reference = _aware(as_of)
    if evaluation_mode not in ('DECISION_TIME', 'CURRENT_INFORMATION'):
        _invalid('CONTEXT_INVALID_EVALUATION_MODE')
    if evaluation_mode == 'DECISION_TIME' and reference > decision:
        _invalid('CONTEXT_DECISION_CUTOFF_EXCEEDED')
    if evaluation_mode == 'CURRENT_INFORMATION' and reference < decision:
        _invalid('CONTEXT_CURRENT_CUTOFF_PRECEDES_DECISION')
    # A backdated caller collection claim cannot put a later local import into a
    # historical decision. The independently observed intake time is also a gate.
    available = [record for record in records if _aware(record['local_ingestion_observed_at']) <= reference]
    candidates = [context_for_candidate(available, candidate, as_of=reference.isoformat(), max_age_seconds=86400)
                  for candidate in evaluation['candidate_evaluations']]
    from context_data import IDENTITY_FIELDS
    for context, candidate in zip(candidates, evaluation['candidate_evaluations']):
        identity = (candidate.get('source_reference') or {}).get('instrument_identity', {})
        if context['status'] == 'MISSING' and identity and any(
                _aware(record['local_ingestion_observed_at']) > reference and
                all(record['instrument_identity'].get(field) == identity.get(field) for field in IDENTITY_FIELDS)
                for record in records):
            context.update(status='UNAVAILABLE', reason_codes=['CONTEXT_LOCAL_CAPTURE_AFTER_AS_OF'])
    states = {candidate['status'] for candidate in candidates}
    status = ('UNAVAILABLE' if not candidates else 'QUALIFIED' if states == {'QUALIFIED'} else
              'WARNING_ONLY' if states - {'MISSING', 'UNAVAILABLE'} else
              'UNAVAILABLE' if 'UNAVAILABLE' in states else 'MISSING')
    result = dict(schema_version='tradepulse.scan-context.v1', run_id=evaluation['run_id'],
        as_of=reference.isoformat(), decision_at=decision.isoformat(), evaluation_mode=evaluation_mode,
        status=status, phase4_digest=digest(evaluation), ingestion_ids=ingestion_ids, capture_ids=capture_ids,
        candidate_contexts=candidates, actionable=False, affects_ranking=False,
        source_mode='OFFLINE_IMPORT_ONLY', operational_source_acceptance=False,
        reason_codes=['NO_CANDIDATES_TO_ENRICH'] if not candidates else
            sorted({reason for context in candidates for reason in context['reason_codes']}),
        max_age_seconds=86400)
    result['snapshot_id'] = digest(['scan-context-v1', result])
    if len(encoded(result).encode('utf-8')) > MAX_SNAPSHOT_BYTES:
        _invalid('CONTEXT_SNAPSHOT_SIZE_LIMIT')
    return result


def enrich(store, run_id, *, as_of=None, evaluation_mode='DECISION_TIME'):
    if not isinstance(run_id, str) or not run_id or len(run_id) > 160:
        _invalid('CONTEXT_INVALID_RUN_ID')
    with store.paper_transaction() as conn:
        evaluation, decision = _phase4(store, conn, run_id)
        records, ids, captures = _material(store, conn)
        payload = _snapshot(evaluation, decision, records, ids, captures,
            as_of if as_of is not None else decision, evaluation_mode)
        old = conn.execute('SELECT * FROM scan_context_snapshots WHERE snapshot_id=?', (payload['snapshot_id'],)).fetchone()
        if old:
            if _load_snapshot(store, conn, old) != payload:
                _invalid('CONTEXT_SNAPSHOT_CONFLICT')
            return payload
        if conn.execute('SELECT COUNT(*) FROM scan_context_snapshots WHERE run_id=?', (run_id,)).fetchone()[0] >= MAX_SNAPSHOTS_PER_RUN:
            _invalid('CONTEXT_SNAPSHOT_QUERY_LIMIT')
        conn.execute('INSERT INTO scan_context_snapshots(snapshot_id,run_id,as_of,payload_json,payload_digest) VALUES (?,?,?,?,?)',
            (payload['snapshot_id'], run_id, payload['as_of'], encoded(payload), digest(payload)))
        conn.executemany('INSERT INTO scan_context_sources VALUES (?,?)',
                         [(payload['snapshot_id'], capture) for capture in captures])
        store._context_checkpoint('before_context_snapshot_commit')
    return payload


def _load_snapshot(store, conn, row, read_cache=None):
    key = ('context', row['run_id'], row['snapshot_id'])
    if read_cache is not None and key in read_cache:
        return read_cache[key]
    try:
        payload = _stored_json(row['payload_json'])
        if (digest(payload) != row['payload_digest'] or payload['snapshot_id'] != row['snapshot_id']
                or payload['run_id'] != row['run_id'] or payload['as_of'] != row['as_of']):
            _invalid('CONTEXT_SNAPSHOT_INTEGRITY_FAILURE')
        evaluation, decision = _phase4(store, conn, payload['run_id'], read_cache)
        records, ids, captures = _material(store, conn, payload['ingestion_ids'])
        actual_captures = sorted(row[0] for row in conn.execute(
            'SELECT capture_id FROM scan_context_sources WHERE snapshot_id=?', (payload['snapshot_id'],)))
        if captures != payload['capture_ids'] or captures != actual_captures:
            _invalid('CONTEXT_CAPTURE_REFERENCE_CONFLICT')
        expected = _snapshot(evaluation, decision, records, ids, captures, payload['as_of'], payload['evaluation_mode'])
        if expected != payload:
            _invalid('CONTEXT_SNAPSHOT_SOURCE_OR_PHASE4_CONFLICT')
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        from storage import PersistenceValidationError
        raise PersistenceValidationError('CONTEXT_SNAPSHOT_INTEGRITY_FAILURE') from exc
    if read_cache is not None:
        read_cache[key] = payload
    return payload


def load_snapshot(store, run_id, connection=None, snapshot_id=None, read_cache=None):
    if connection is None:
        with store.lineage_read() as conn:
            # A fresh cache lives only inside this locked SQLite read snapshot.
            return load_snapshot(store, run_id, conn, snapshot_id, {})
    key = ('context', run_id, snapshot_id)
    if read_cache is not None and key in read_cache:
        return read_cache[key]
    if snapshot_id is None:
        row = connection.execute('SELECT * FROM scan_context_snapshots WHERE run_id=? ORDER BY sequence DESC LIMIT 1', (run_id,)).fetchone()
    else:
        row = connection.execute('SELECT * FROM scan_context_snapshots WHERE run_id=? AND snapshot_id=?', (run_id, snapshot_id)).fetchone()
    result = _load_snapshot(store, connection, row, read_cache) if row else None
    if read_cache is not None:
        read_cache[key] = result
    return result


def candidate_context(snapshot, candidate_id):
    if snapshot:
        return next((copy.deepcopy(row) for row in snapshot['candidate_contexts'] if row['candidate_id'] == candidate_id),
                    dict(schema_version='tradepulse.candidate-context.v1', candidate_id=candidate_id,
                         status='UNAVAILABLE', reason_codes=['CONTEXT_CANDIDATE_NOT_RETAINED'], records=[],
                         actionable=False, affects_ranking=False))
    return dict(schema_version='tradepulse.candidate-context.v1', candidate_id=candidate_id,
        status='MISSING', reason_codes=['CONTEXT_NOT_EVALUATED'], records=[], actionable=False, affects_ranking=False)

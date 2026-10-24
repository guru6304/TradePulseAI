"""Real loopback context routes, with memory data and external networking blocked."""
from contextlib import ExitStack
from datetime import datetime, timedelta
from email.message import Message
import http.client
import json
import sqlite3
import threading
import unittest
from unittest.mock import Mock, patch

import test_bot
import context_data
import context_workflow
import test_phase45_integration as context_integration_fixtures
import notification_outbox
import test_phase4_recommendations as market_fixtures
from candle_lineage import digest
from context_data import SOURCE_SCHEMA
from scanner_engine import MarketScanScheduler
from server import DashboardRequestHandler, create_http_server
from storage import PersistenceValidationError
from strategies import IST
from verify_offline import offline_network


class TestContextHTTP(unittest.TestCase):
    def setUp(self):
        guard = ExitStack()
        offline_network(guard)
        self.addCleanup(guard.close)
        self.fixture = market_fixtures.TestPhase4IndependentRecommendations()
        self.fixture.clock_value = datetime(2026, 10, 23, 14, 15, 5, tzinfo=IST)
        self.addCleanup(self.fixture.doCleanups)
        self.engine, feed = self.fixture.engine()
        self.identity = feed.rows[0]['instrument_identity']
        handler = type('OfflineContextHTTP', (DashboardRequestHandler,), dict(engine=self.engine,
            scheduler=MarketScanScheduler(self.engine), paper_portfolio=None,
            evidence_scope='OFFLINE_CONTEXT_HTTP_FIXTURE', log_message=lambda *args: None))
        self.server = create_http_server('127.0.0.1', 0, handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()
        self.assertFalse(self.thread.is_alive())

    def body(self):
        return dict(provider='offline_notices', collected_at=self.engine._now_ist().isoformat(), payload=dict(
            schema_version=SOURCE_SCHEMA, records=[dict(source_id='offline_issuer', source_name='Authored HTTP fixture',
                source_url='https://issuer.example/notice/1', original_ref='https://issuer.example/notice/1',
                source_record_ref='notice-1', instrument_identity=self.identity,
                published_at=(self.engine._now_ist()-timedelta(minutes=5)).isoformat(),
                event_at=(self.engine._now_ist()-timedelta(minutes=4)).isoformat(),
                title='Authored fixture, not a real company event', summary='<script>untrusted fixture</script>')]))

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=10)
        try:
            payload = json.dumps(body).encode() if isinstance(body, dict) else body
            connection.request(method, path, body=payload, headers=headers or {'Content-Type':'application/json'})
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            connection.close()

    def test_real_import_scan_enrich_and_read_routes_agree_without_sends(self):
        with patch.object(self.engine.telegram, 'send_signal') as send:
            code, imported = self.request('POST', '/api/context-import', self.body())
            self.assertEqual(code, 200)
            self.assertEqual(imported['ingestion']['status'], 'WARNING_ONLY')
            code, scanned = self.request('POST', '/api/scan')
            self.assertEqual(code, 200)
            self.assertEqual(scanned['total_signals'], 1)
            code, result = self.request('POST', '/api/context-enrich', {'run_id':scanned['run_id']})
            self.assertEqual(code, 200)
            self.assertEqual(result['context'], scanned['context'])
            self.assertEqual(result['alert_decisions'][0]['status'], 'SUPPRESSED')
            code, retained = self.request('GET', '/api/v1/context?run_id='+scanned['run_id'])
            self.assertEqual(code, 200)
            self.assertEqual(retained['context'], result['context'])
            self.assertEqual(self.request('GET','/api/context-alerts?run_id='+scanned['run_id'])[0], 200)
            self.assertEqual(self.request('GET','/api/context')[1]['total_count'], 1)
            self.assertEqual(self.request('GET','/api/signals')[1]['items'][0]['context']['status'], 'WARNING_ONLY')
            self.assertFalse(self.request('GET','/api/signals')[1]['items'][0]['actionable'])
            send.assert_not_called()

    def test_foreign_origin_cannot_import_or_enrich_and_reads_are_inert(self):
        for route in ('/api/context-import','/api/context-enrich'):
            with self.subTest(route=route):
                code,_ = self.request('POST', route, b'', {'Origin':'https://untrusted.invalid', 'Content-Length':'128'})
                self.assertEqual(code, 403)
        self.assertEqual(self.engine.store.list_context_ingestions()['total_count'], 0)
        self.assertEqual(self.request('GET','/api/context-import')[0], 404)
        self.assertEqual(self.request('POST','/api/context')[0], 405)

    def test_duplicate_json_nonfinite_and_invalid_structures_are_rejected(self):
        for raw in (b'{"provider":"a","provider":"b"}', b'{"a":NaN}', b'{"a":1e999}',
                    b'[]', b'{', b'\xff'):
            for route in ('/api/context-import','/api/context-enrich'):
                with self.subTest(raw=raw,route=route):
                    self.assertEqual(self.request('POST',route,raw)[0], 400)
        self.assertEqual(self.engine.store.list_context_ingestions()['total_count'], 0)

    def test_no_request_can_supply_trust_mapping_or_intake_time(self):
        for key,value in (('source_policy',{'approved':True}), ('context_policy',{}),
                          ('trusted_identities',[self.identity]), ('observed_at','2020-01-01T00:00:00+00:00')):
            body=self.body()
            body[key]=value
            self.assertEqual(self.request('POST','/api/context-import',body)[0], 400)
        self.assertEqual(self.engine.store.list_context_ingestions()['total_count'], 0)

    def test_oversize_transfer_encoding_and_missing_length_are_rejected(self):
        # Reject the declared oversize before reading it. Streaming a huge body
        # after this immediate refusal can produce a Windows TCP reset instead.
        self.assertEqual(self.request('POST','/api/context-import',b'',
            {'Content-Length':str(512*1024+1)})[0], 400)
        self.assertEqual(self.request('POST','/api/context-enrich',b'',{'Transfer-Encoding':'chunked'})[0], 400)
        self.assertEqual(self.request('POST','/api/context-import')[0], 400)

    def test_duplicate_content_length_is_rejected_before_body_read(self):
        connection=http.client.HTTPConnection(*self.server.server_address,timeout=10)
        try:
            connection.putrequest('POST','/api/context-import')
            connection.putheader('Content-Length','2')
            connection.putheader('Content-Length','2')
            connection.endheaders()
            response=connection.getresponse()
            self.assertEqual(response.status,400)
            response.read()
        finally:
            connection.close()

    def test_timeout_in_both_new_body_readers_returns_bounded_unavailable(self):
        handler=DashboardRequestHandler.__new__(DashboardRequestHandler)
        handler.engine=self.engine
        handler.headers=Message()
        handler.headers['Content-Length']='2'
        handler.rfile=Mock()
        handler.rfile.read.side_effect=TimeoutError('offline controlled read timeout')
        handler.connection=Mock()
        for fn in (handler._handle_context_import,handler._handle_context_enrich):
            with self.subTest(fn=fn.__name__):
                code,body=fn()
                self.assertEqual(code,400)
                self.assertEqual(body['status'],'UNAVAILABLE')

    def test_corrupt_context_cannot_be_served_by_real_history_routes(self):
        self.assertEqual(self.request('POST','/api/context-import',self.body())[0],200)
        code,summary=self.request('POST','/api/scan')
        self.assertEqual(code,200)
        with self.engine.store.paper_transaction() as conn:
            row=conn.execute('SELECT * FROM scan_context_snapshots').fetchone()
            payload=json.loads(row['payload_json'])
            payload['phase4_digest']='rehashed false phase4 identity'
            conn.execute('UPDATE scan_context_snapshots SET payload_json=?,payload_digest=?',
                (json.dumps(payload),digest(payload)))
        for route in ('/api/context?run_id='+summary['run_id'],'/api/signals','/api/scans'):
            with self.subTest(route=route):
                code,body=self.request('GET',route)
                self.assertEqual(code,503)
                self.assertNotIn('items',body)


class TestActualContextSQLiteFailures(unittest.TestCase):
    def setUp(self):
        import test_phase45_integration as fixtures
        self.case=fixtures.TestPhase45IndependentIntegration()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.engine,_,self.raw=self.case.engine()

    def test_actual_sqlite_snapshot_failure_keeps_phase4_and_marks_context_unavailable(self):
        with self.engine.store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER authored_context_failure BEFORE INSERT ON scan_context_snapshots "
                         "BEGIN SELECT RAISE(ABORT,'authored SQLite failure'); END")
        result=self.engine.run_single_scan()
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['total_signals'],1)
        self.assertEqual(result['context']['status'],'UNAVAILABLE')
        self.assertEqual(self.engine.store.load_cash_scan(result['run_id'])['status'],'COMMITTED')
        self.assertEqual(self.engine.store.query_signals()['total_count'],1)

    def test_actual_sqlite_import_failure_returns503_and_rolls_back_source(self):
        with self.engine.store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER authored_import_failure BEFORE INSERT ON context_ingestions "
                         "BEGIN SELECT RAISE(ABORT,'authored SQLite failure'); END")
        code,payload=self.case.handler(self.engine)._handle_context_import(dict(provider='offline_notices',
            collected_at='2026-10-23T08:40:00+00:00',payload=self.raw.decode()))
        self.assertEqual(code,503)
        self.assertEqual(payload['status'],'UNAVAILABLE')
        self.assertEqual(self.engine.store.list_context_ingestions()['total_count'],0)


class TestStoredContextPayloadGuards(unittest.TestCase):
    """Real SQLite corruption must fail before unbounded decoding or coercion."""

    def setUp(self):
        self.case = context_integration_fixtures.TestPhase45IndependentIntegration()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.engine, _, self.raw = self.case.engine()
        self.case.import_source(self.engine, self.raw)
        self.summary = self.engine.run_single_scan()
        self.run_id = self.summary["run_id"]
        self.assertEqual(self.summary["context"]["status"], "QUALIFIED")
        self.assertEqual(self.summary["context_alert_decisions"][0]["status"], "ELIGIBLE")

    def assert_rejected_before_decode(self, raw, read):
        real_decoder = json.loads
        with patch("context_workflow.json.loads", wraps=real_decoder) as decoder:
            with self.assertRaises(PersistenceValidationError):
                read()
        self.assertFalse(any(call.args and call.args[0] == raw for call in decoder.call_args_list),
                         "Invalid stored raw payload reached the JSON decoder before rejection")

    def test_nontext_original_outbox_payload_is_graceful_persistence_failure(self):
        intent = self.summary["notification_intents"][0]
        with self.engine.store.paper_transaction() as conn:
            conn.execute("UPDATE notification_outbox SET payload_json=? WHERE intent_id=?",
                         (sqlite3.Binary(b'{"corrupt_stored_type":true}'), intent))
            actual_type = conn.execute("SELECT typeof(payload_json) FROM notification_outbox WHERE intent_id=?",
                                       (intent,)).fetchone()[0]
        self.assertEqual(actual_type, "blob")
        with self.assertRaises(PersistenceValidationError):
            self.engine.store.preview_notification(intent, now=self.engine._now_ist())

    def test_nontext_context_decision_returns503_from_supported_alert_api(self):
        decision = self.summary["context_alert_decisions"][0]["decision_id"]
        with self.engine.store.paper_transaction() as conn:
            conn.execute("UPDATE context_alert_decisions SET payload_json=? WHERE decision_id=?",
                         (sqlite3.Binary(b'{"corrupt_stored_type":true}'), decision))
            actual_type = conn.execute("SELECT typeof(payload_json) FROM context_alert_decisions WHERE decision_id=?",
                                       (decision,)).fetchone()[0]
        self.assertEqual(actual_type, "blob")
        code, body = self.case.handler(self.engine)._handle_context({"run_id": [self.run_id]}, alerts=True)
        self.assertEqual(code, 503)
        self.assertEqual(body["status"], "UNAVAILABLE")
        self.assertNotIn("alert_decisions", body)

    def test_oversized_or_nontext_stored_snapshot_is_rejected_before_decoding(self):
        oversized = '{"padding":"' + "x" * (context_workflow.MAX_SNAPSHOT_BYTES + 1) + '"}'
        for raw in (oversized, b'{"corrupt_stored_snapshot_type":true}'):
            with self.subTest(kind="oversize" if isinstance(raw, str) else "blob"):
                with self.engine.store.paper_transaction() as conn:
                    conn.execute("UPDATE scan_context_snapshots SET payload_json=? WHERE run_id=?", (raw, self.run_id))
                self.assert_rejected_before_decode(raw, lambda: self.engine.store.load_scan_context(self.run_id))

    def test_oversized_or_nontext_stored_source_json_is_rejected_before_decoding(self):
        oversized = '{"padding":"' + "x" * (context_workflow.MAX_SNAPSHOT_BYTES + 1) + '"}'
        with self.engine.store.lineage_read() as conn:
            original = dict(conn.execute("SELECT payload_json,identities_json FROM context_ingestions").fetchone())
        for field in ("payload_json", "identities_json"):
            for raw in (oversized, b'{"corrupt_stored_source_type":true}'):
                with self.subTest(field=field, kind="oversize" if isinstance(raw, str) else "blob"):
                    with self.engine.store.paper_transaction() as conn:
                        conn.execute("UPDATE context_ingestions SET payload_json=?,identities_json=?",
                                     (original["payload_json"], original["identities_json"]))
                        conn.execute("UPDATE context_ingestions SET " + field + "=?", (raw,))
                    self.assert_rejected_before_decode(raw, self.engine.store.list_context_ingestions)

    def test_integer_or_oversized_original_bytes_rejected_before_source_validator(self):
        real_validator = context_data.validate_ingestion
        for raw in (16, b"x" * (context_data.MAX_BYTES + 1)):
            with self.subTest(kind="integer" if isinstance(raw, int) else "oversize"):
                with self.engine.store.paper_transaction() as conn:
                    conn.execute("UPDATE context_ingestions SET original_bytes=?", (raw,))
                    actual_type = conn.execute("SELECT typeof(original_bytes) FROM context_ingestions").fetchone()[0]
                self.assertEqual(actual_type, "integer" if isinstance(raw, int) else "blob")
                with patch("context_data.validate_ingestion", wraps=real_validator) as validator:
                    with self.assertRaises(PersistenceValidationError):
                        self.engine.store.list_context_ingestions()
                validator.assert_not_called()

    def test_corrupt_receipt_type_or_size_is_rejected_before_decoding(self):
        intent = self.summary['notification_intents'][0]
        for raw in ('{"padding":"'+'x'*(notification_outbox.MAX_PAYLOAD_BYTES+1)+'"}',
                    b'{"corrupt_receipt_type":true}'):
            with self.subTest(kind='oversize' if isinstance(raw, str) else 'blob'):
                with self.engine.store.paper_transaction() as conn:
                    conn.execute('UPDATE notification_outbox SET receipt_json=? WHERE intent_id=?', (raw, intent))
                real_decoder = json.loads
                with patch('notification_outbox.json.loads', wraps=real_decoder) as decoder:
                    with self.assertRaises(PersistenceValidationError):
                        self.engine.store.preview_notification(intent, now=self.engine._now_ist())
                self.assertFalse(any(call.args and call.args[0] == raw for call in decoder.call_args_list))

    def test_corrupt_existing_import_inventory_returns_storage_failure(self):
        with self.engine.store.paper_transaction() as conn:
            conn.execute('UPDATE context_ingestions SET payload_json=?', ('{"records":null}',))
        document = json.loads(self.raw)
        document['records'][0]['source_record_ref'] = 'different-new-import'
        code, body = self.case.handler(self.engine)._handle_context_import(dict(provider='offline_notices',
            collected_at=self.engine._now_ist().isoformat(), payload=json.dumps(document)))
        self.assertEqual(code, 503)
        self.assertEqual(body['status'], 'UNAVAILABLE')
        with self.engine.store.lineage_read() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM context_ingestions').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)

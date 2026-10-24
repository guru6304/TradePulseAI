"""Follow-up stored receipt/inventory failure regressions; memory SQLite only."""
import json
import sqlite3
from unittest.mock import patch

import notification_outbox
from storage import PersistenceValidationError
import docs.evidence.phase45_corrupt_payload_regressions_20261024_01 as fixtures


class TestStoredReceiptAndImportGuards(fixtures.TestStoredContextPayloadGuards):
    def test_corrupt_receipt_type_or_size_is_rejected_before_decoding(self):
        intent = self.summary['notification_intents'][0]
        for raw in ('{"padding":"'+'x'*(notification_outbox.MAX_PAYLOAD_BYTES+1)+'"}',
                    b'{"corrupt_receipt_type":true}'):
            with self.subTest(kind='oversize' if isinstance(raw,str) else 'blob'):
                with self.engine.store.paper_transaction() as conn:
                    conn.execute('UPDATE notification_outbox SET receipt_json=? WHERE intent_id=?',(raw,intent))
                real_decoder=json.loads
                with patch('notification_outbox.json.loads',wraps=real_decoder) as decoder:
                    with self.assertRaises(PersistenceValidationError):
                        self.engine.store.preview_notification(intent,now=self.engine._now_ist())
                self.assertFalse(any(call.args and call.args[0]==raw for call in decoder.call_args_list))

    def test_corrupt_existing_import_inventory_returns_storage_failure(self):
        with self.engine.store.paper_transaction() as conn:
            conn.execute('UPDATE context_ingestions SET payload_json=?',('{"records":null}',))
        document=json.loads(self.raw)
        document['records'][0]['source_record_ref']='different-new-import'
        code,body=self.case.handler(self.engine)._handle_context_import(dict(provider='offline_notices',
            collected_at=self.engine._now_ist().isoformat(),payload=json.dumps(document)))
        self.assertEqual(code,503)
        self.assertEqual(body['status'],'UNAVAILABLE')
        with self.engine.store.lineage_read() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM context_ingestions').fetchone()[0],1)

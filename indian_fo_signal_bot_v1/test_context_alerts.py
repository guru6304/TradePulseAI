"""Independent context-alert integrity and local-preview QA; memory only."""
import copy
import hashlib
import json
import unittest
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_bot
from storage import PersistenceValidationError


def canonical_checksum(value):
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return body, hashlib.sha256(body.encode("utf-8")).hexdigest()


class TestContextAlerts(unittest.TestCase):
    def setUp(self):
        from test_phase4_recommendations import TestPhase4IndependentRecommendations
        self.fixture = TestPhase4IndependentRecommendations()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine, _ = self.fixture.engine()

    def pending(self):
        def interrupt(boundary):
            if boundary == "after_result_commit":
                raise RuntimeError("OFFLINE stop before preview")
        with patch.object(self.engine.store, "_lineage_checkpoint", side_effect=interrupt), self.assertRaises(RuntimeError):
            self.engine.run_single_scan()
        return self.engine.store.list_notification_outbox()["items"][0]["intent_id"]

    def test_rehashed_ack_cannot_forge_identity_real_delivery_or_live_acceptance(self):
        summary = self.engine.run_single_scan()
        intent = summary["notification_intents"][0]
        with self.engine.store.paper_transaction(write=True) as conn:
            row = conn.execute("SELECT receipt_json FROM notification_outbox WHERE intent_id=?", (intent,)).fetchone()
            receipt = json.loads(row[0])
            receipt.update(intent_id="WRONG_INTENT", run_id="WRONG_RUN", dry_run=False,
                           execution_mode="REAL_DELIVERY", current_live_acceptance=True)
            body, checksum = canonical_checksum(receipt)
            conn.execute("UPDATE notification_outbox SET receipt_json=?,receipt_digest=? WHERE intent_id=?",
                         (body, checksum, intent))
        with self.assertRaises(PersistenceValidationError):
            self.engine.store.preview_notification(intent, now=self.fixture.clock_value)

    def test_rehashed_pending_payload_cannot_change_signal_batch_or_message(self):
        intent = self.pending()
        with self.engine.store.paper_transaction(write=True) as conn:
            row = conn.execute("SELECT payload_json FROM notification_outbox WHERE intent_id=?", (intent,)).fetchone()
            payload = json.loads(row[0])
            payload.update(signal_key="WRONG_SIGNAL", batch_ids=["WRONG_BATCH"], message_html="UNBOUND_CONTEXT_MARKER")
            body, checksum = canonical_checksum(payload)
            conn.execute("UPDATE notification_outbox SET payload_json=?,content_digest=? WHERE intent_id=?",
                         (body, checksum, intent))
        with self.assertRaises(PersistenceValidationError):
            self.engine.store.preview_notification(intent, now=self.fixture.clock_value)


class TestContextAlertLifecycle(unittest.TestCase):
    def setUp(self):
        import test_phase45_integration as integration
        self.case = integration.TestPhase45IndependentIntegration()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.engine, _, raw = self.case.engine()
        self.original = self.engine.run_single_scan()
        self.case.import_source(self.engine, raw)
        self.snapshot = self.engine.store.enrich_scan_context(self.original['run_id'])
        self.candidate = self.original['candidate_evaluations'][0]
        self.decision = self.engine.store.enqueue_context_alert(self.original['run_id'],
            self.candidate['candidate_id'], self.snapshot, self.engine._now_ist())
        self.intent = self.decision['intent_id']

    def row(self):
        with self.engine.store.paper_transaction(write=False) as conn:
            return dict(conn.execute('SELECT * FROM notification_outbox WHERE intent_id=?', (self.intent,)).fetchone())

    def test_pending_preview_and_ack_replay_are_local_and_exact_once(self):
        import notification_outbox
        self.assertEqual(self.row()['status'], 'PENDING')
        actual = notification_outbox.render_preview
        with patch('notification_outbox.render_preview', wraps=actual) as render:
            first = self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())
            repeated = self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())
        self.assertEqual(first, repeated)
        self.assertEqual(render.call_count, 1)
        self.assertEqual(first['status'], 'ACKNOWLEDGED')
        self.assertTrue(first['dry_run'])
        self.assertFalse(first['current_live_acceptance'])
        self.assertEqual(first['execution_mode'], 'LOCAL_PREVIEW_ONLY')
        self.assertIn('no current recommendation', first['message_html'])
        self.assertEqual(self.row()['attempts'], 1)

    def test_failures_back_off_and_stop_at_dead_without_fourth_attempt(self):
        with patch('notification_outbox.render_preview', side_effect=RuntimeError('authored local failure')) as render:
            first = self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())
            self.assertEqual(first['status'], 'RETRY')
            self.assertEqual(self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())['status'], 'DEFERRED')
            self.case.market.clock_value += timedelta(seconds=5)
            self.assertEqual(self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())['status'], 'RETRY')
            self.case.market.clock_value += timedelta(seconds=10)
            self.assertEqual(self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())['status'], 'DEAD')
            self.case.market.clock_value += timedelta(days=1)
            self.assertEqual(self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())['status'], 'DEAD')
        self.assertEqual(render.call_count, 3)
        self.assertEqual(self.row()['attempts'], 3)

    def test_ack_loss_after_commit_recovers_without_a_second_render(self):
        def lose(boundary):
            if boundary == 'after_notification_commit':
                raise RuntimeError('authored acknowledgement loss')
        with patch.object(self.engine.store, '_notification_checkpoint', side_effect=lose), self.assertRaises(RuntimeError):
            self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())
        self.assertEqual(self.row()['status'], 'ACKNOWLEDGED')
        with patch('notification_outbox.render_preview') as render:
            receipt = self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())
        render.assert_not_called()
        self.assertEqual(receipt['status'], 'ACKNOWLEDGED')
        self.assertEqual(self.row()['attempts'], 1)

    def test_precommit_failure_rolls_back_attempt_and_remains_pending(self):
        def lose(boundary):
            if boundary == 'before_notification_commit':
                raise RuntimeError('authored commit failure')
        with patch.object(self.engine.store, '_notification_checkpoint', side_effect=lose), self.assertRaises(RuntimeError):
            self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())
        self.assertEqual((self.row()['status'], self.row()['attempts']), ('PENDING', 0))
        self.assertEqual(self.engine.store.preview_notification(self.intent, now=self.engine._now_ist())['status'], 'ACKNOWLEDGED')

    def test_rehashed_v2_message_and_context_refs_cannot_replace_bound_facts(self):
        row = self.row()
        payload = json.loads(row['payload_json'])
        payload.update(message_html='unbound authored message', context_record_refs=[], phase4_digest='forged')
        body, checksum = canonical_checksum(payload)
        with self.engine.store.paper_transaction() as conn:
            conn.execute('UPDATE notification_outbox SET payload_json=?,content_digest=? WHERE intent_id=?',
                (body, checksum, self.intent))
        for read in (lambda: self.engine.store.preview_notification(self.intent, now=self.engine._now_ist()),
                     self.engine.store.list_notification_outbox,
                     lambda: self.engine.store.load_cash_scan(self.original['run_id'])):
            with self.subTest(read=read), self.assertRaises(PersistenceValidationError):
                read()

    def test_rehashed_suppression_or_policy_reason_is_recomputed_from_sources(self):
        with self.engine.store.paper_transaction() as conn:
            row = conn.execute('SELECT * FROM context_alert_decisions WHERE decision_id=?',
                (self.decision['decision_id'],)).fetchone()
            payload = json.loads(row['payload_json'])
            payload.update(status='SUPPRESSED', reason_code='forged reason', semantic_context_digest='forged')
            body, checksum = canonical_checksum(payload)
            conn.execute('UPDATE context_alert_decisions SET payload_json=?,payload_digest=? WHERE decision_id=?',
                (body, checksum, self.decision['decision_id']))
        with self.assertRaises(PersistenceValidationError):
            self.engine.store.list_context_alert_decisions(self.original['run_id'])

    def test_concurrent_enqueue_and_reads_keep_one_semantic_intent(self):
        def enqueue(_):
            return self.engine.store.enqueue_context_alert(self.original['run_id'], self.candidate['candidate_id'],
                self.snapshot, self.engine._now_ist())
        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions = list(pool.map(enqueue, range(4)))
        self.assertTrue(all(item == self.decision for item in decisions))
        self.assertEqual(len(self.case.v2_rows(self.engine)), 1)
        self.assertEqual(self.row()['attempts'], 0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pages = list(pool.map(lambda _:self.engine.store.list_context_alert_decisions(self.original['run_id']), range(4)))
        self.assertTrue(all(page == pages[0] for page in pages))

    def test_signal_formatter_uses_numeric_gross_rr_and_labels_nominal_string(self):
        from strategies import TradeSignal
        signal = TradeSignal(**self.original['signals'][0])
        signal.risk_reward = '1:9999'
        message = self.engine.telegram.format_signal_html(signal, self.original['broker'])
        risk = signal.entry_price-signal.stop_loss
        self.assertIn('Gross T1 '+format((signal.target_1-signal.entry_price)/risk,'.2f'), message)
        self.assertIn('Nominal strategy label: 1:9999', message)
        self.assertIn('net target RR unavailable', message)

    def test_sqlite_restart_restores_pending_and_ack_without_duplicate_render(self):
        from storage import SQLitePersistenceStore
        restored = SQLitePersistenceStore(':memory:')
        again = SQLitePersistenceStore(':memory:')
        self.addCleanup(restored.close)
        self.addCleanup(again.close)
        with self.engine.store.lineage_read() as source:
            source.backup(restored._get_connection())
        with self.assertRaises(PersistenceValidationError):
            restored.preview_notification(self.intent, now=self.engine._now_ist())
        restored.context_source_policy = self.engine.context_policy
        self.assertEqual(restored.preview_notification(self.intent, now=self.engine._now_ist())['status'], 'ACKNOWLEDGED')
        with restored.lineage_read() as source:
            source.backup(again._get_connection())
        again.context_source_policy = self.engine.context_policy
        with patch('notification_outbox.render_preview') as render:
            result = again.preview_notification(self.intent, now=self.engine._now_ist())
        render.assert_not_called()
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['status'], 'ACKNOWLEDGED')
        self.assertEqual(self.row()['status'], 'PENDING')


if __name__ == "__main__":
    unittest.main()

"""Durable local dry-run previews; no real destination, sender or live delivery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import unittest
from unittest.mock import patch

import test_bot
from storage import PersistenceValidationError


class TestNotificationOutbox(unittest.TestCase):
    def setUp(self):
        from test_phase4_e2e import TestPhase4OfflineEndToEnd
        self.fixture = TestPhase4OfflineEndToEnd()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture._engine("upstox", database="outbox.sqlite")

    def pending(self):
        def interrupt(boundary):
            if boundary=="after_result_commit":
                raise RuntimeError("OFFLINE lost acknowledgement")
        with patch.object(self.engine.store, "_lineage_checkpoint", side_effect=interrupt), self.assertRaises(RuntimeError):
            self.engine.run_single_scan()
        return self.engine.store.list_notification_outbox()["items"][0]["intent_id"]

    def preview(self, intent_id):
        return self.engine.store.preview_notification(intent_id, now=self.fixture.now)

    def test_intent_rolls_back_with_result_and_never_survives_failed_scan(self):
        def interrupt(boundary):
            if boundary=="before_result_commit":
                raise RuntimeError("OFFLINE result write interruption")
        with patch.object(self.engine.store, "_lineage_checkpoint", side_effect=interrupt), self.assertRaises(RuntimeError):
            self.engine.run_single_scan()
        self.assertEqual(self.engine.store.list_notification_outbox()["items"], [])
        self.assertEqual(self.engine.store.query_signals()["total_count"], 0)

    def test_commit_before_ack_restart_and_concurrent_preview_have_one_receipt(self):
        intent_id = self.pending()
        self.engine.close()
        self.engine = self.fixture._engine("upstox", database="outbox.sqlite")
        with patch.object(self.engine.telegram, "send_signal", side_effect=AssertionError("No sender")), \
                ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: self.preview(intent_id), range(8)))
        self.assertTrue(all(r["dry_run"] and r["status"]=="ACKNOWLEDGED" for r in receipts))
        self.assertTrue(all(r==receipts[0] for r in receipts))
        self.assertNotIn("chat_id", receipts[0])
        self.assertIn("stored candidate", receipts[0]["message_html"])
        with self.engine.store.paper_transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notification_attempts").fetchone()[0], 1)

    def test_render_failure_has_bounded_backoff_and_recovery(self):
        intent_id = self.pending()
        with patch("notification_outbox.render_preview", side_effect=ValueError("OFFLINE formatter unavailable")):
            first = self.preview(intent_id)
        self.assertEqual(first["status"], "RETRY")
        self.assertEqual(self.preview(intent_id)["status"], "DEFERRED")
        self.fixture.now += timedelta(seconds=5)
        self.assertEqual(self.preview(intent_id)["status"], "ACKNOWLEDGED")
        self.assertEqual(self.engine.store.list_notification_outbox()["items"][0]["attempts"], 2)

    def test_repeated_render_failure_stops_without_false_ack(self):
        intent_id = self.pending()
        with patch("notification_outbox.render_preview", side_effect=ValueError("OFFLINE formatter unavailable")):
            for seconds in (0, 5, 10):
                self.fixture.now += timedelta(seconds=seconds)
                result = self.preview(intent_id)
        self.assertEqual(result["status"], "DEAD")
        self.assertFalse(result["ok"])
        self.assertEqual(self.preview(intent_id)["status"], "DEAD")

    def test_ack_write_failure_rolls_back_and_postcommit_ack_loss_is_idempotent(self):
        intent_id = self.pending()
        def interrupt(boundary):
            if boundary=="before_notification_commit":
                raise RuntimeError("OFFLINE ack write failure")
        with patch.object(self.engine.store, "_notification_checkpoint", side_effect=interrupt), self.assertRaises(RuntimeError):
            self.preview(intent_id)
        self.assertEqual(self.engine.store.list_notification_outbox()["items"][0]["attempts"], 0)
        with patch.object(self.engine.store, "_notification_checkpoint", side_effect=lambda b: (_ for _ in ()).throw(
                RuntimeError("OFFLINE lost receipt")) if b=="after_notification_commit" else None), self.assertRaises(RuntimeError):
            self.preview(intent_id)
        self.assertEqual(self.preview(intent_id)["status"], "ACKNOWLEDGED")
        self.assertEqual(self.engine.store.list_notification_outbox()["items"][0]["attempts"], 1)

    def test_tampered_intent_and_signal_cannot_generate_a_preview(self):
        intent_id = self.pending()
        with self.engine.store.paper_transaction() as conn:
            conn.execute("UPDATE signals SET position_qty=position_qty+1")
        with self.assertRaises(PersistenceValidationError):
            self.preview(intent_id)
        with self.engine.store.paper_transaction() as conn:
            conn.execute("UPDATE signals SET position_qty=position_qty-1")
            conn.execute("UPDATE notification_outbox SET content_digest='tampered'")
        with self.assertRaises(PersistenceValidationError):
            self.preview(intent_id)

    def test_corrupt_retry_counter_is_rejected_before_retry_work(self):
        intent_id = self.pending()
        with self.engine.store.paper_transaction() as conn:
            conn.execute("UPDATE notification_outbox SET attempts=1000000")
        with self.assertRaises(PersistenceValidationError):
            self.preview(intent_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)

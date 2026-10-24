"""Privileged stored-payload corruption regressions; real isolated SQLite only.

Authored fixtures exercise software failure boundaries, not source authority.
Decoder spies require bounded rejection before parsing the offending stored raw
value; other legitimate source/evaluation decoding remains enabled.
"""
import json
import sqlite3
import unittest
from unittest.mock import patch

import context_data
import context_workflow
import test_phase45_integration as fixtures
from storage import PersistenceValidationError


class TestStoredContextPayloadGuards(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.TestPhase45IndependentIntegration()
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
        self.assertFalse(
            any(call.args and call.args[0] == raw for call in decoder.call_args_list),
            "Invalid stored raw payload reached the JSON decoder before rejection",
        )

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
        nontext = b'{"corrupt_stored_snapshot_type":true}'
        for raw in (oversized, nontext):
            with self.subTest(kind="oversize" if isinstance(raw, str) else "blob"):
                with self.engine.store.paper_transaction() as conn:
                    conn.execute("UPDATE scan_context_snapshots SET payload_json=? WHERE run_id=?",
                                 (raw, self.run_id))
                self.assert_rejected_before_decode(raw, lambda: self.engine.store.load_scan_context(self.run_id))

    def test_oversized_or_nontext_stored_source_json_is_rejected_before_decoding(self):
        oversized = '{"padding":"' + "x" * (context_workflow.MAX_SNAPSHOT_BYTES + 1) + '"}'
        nontext = b'{"corrupt_stored_source_type":true}'
        with self.engine.store.lineage_read() as conn:
            original = dict(conn.execute("SELECT payload_json,identities_json FROM context_ingestions").fetchone())
        for field in ("payload_json", "identities_json"):
            for raw in (oversized, nontext):
                with self.subTest(field=field, kind="oversize" if isinstance(raw, str) else "blob"):
                    with self.engine.store.paper_transaction() as conn:
                        conn.execute("UPDATE context_ingestions SET payload_json=?,identities_json=?",
                                     (original["payload_json"], original["identities_json"]))
                        # Field comes exclusively from this fixed two-value test tuple.
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

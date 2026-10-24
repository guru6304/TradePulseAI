"""Independent cross-phase QA: authored sources, real signatures, memory only.

Local fixture policy is not genuine publisher authority or rights evidence.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest
from unittest.mock import patch

import test_bot
import test_context_data as source_fixtures
import test_phase4_recommendations as market_fixtures
from candle_lineage import digest, encoded
from context_data import ContextSourcePolicy
from scanner_engine import IntradayBotEngine
from server import DashboardRequestHandler
from storage import PersistenceError, PersistenceValidationError
from strategies import IST, evaluate_order_block_fvg


class TestPhase45IndependentIntegration(unittest.TestCase):
    def setUp(self):
        self.market = market_fixtures.TestPhase4IndependentRecommendations()
        self.market.setUp()
        self.market.clock_value = datetime(2026, 10, 23, 14, 15, 5, tzinfo=IST)
        self.addCleanup(self.market.doCleanups)
        self.source = source_fixtures.TestContextData()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)

    def engine(self, *, qualified=True, documents=None, policy_scope="RELIANCE", extra_identities=()):
        original, feed = self.market.engine()
        identity = copy.deepcopy(feed.rows[0]["instrument_identity"])
        self.source.identity = identity
        self.source.row["instrument_identity"] = identity
        raw = self.source.raw()
        raws = documents if documents is not None else [raw]
        policies = [self.source.policy(document, capture_time="2026-10-23T08:35:00+00:00",
                                      instrument_scope=policy_scope) for document in raws]
        policy = ContextSourcePolicy(trust_config=policies[0]._trust, approvals=policies[0]._approvals,
            manifests_by_sha256={key: value for item in policies for key, value in item._manifests.items()}) if qualified else None
        engine = IntradayBotEngine(original.config, clock=lambda: self.market.clock_value,
            broker_scanner=original.broker, store=original.store,
            context_policy=policy, context_identities=[identity, *extra_identities])
        self.addCleanup(engine.close)
        return engine, feed, raw

    def import_source(self, engine, raw, *, collected="2026-10-23T08:40:00+00:00"):
        return engine.import_context(raw, provider="offline_notices", collected_at=collected)

    def handler(self, engine):
        handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
        handler.engine, handler.paper_portfolio = engine, None
        handler.evidence_scope = "OFFLINE_CROSS_PHASE_FIXTURE_NOT_SOURCE_ACCEPTANCE"
        return handler

    def v2_rows(self, engine):
        with engine.store.paper_transaction(write=False) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM notification_outbox ORDER BY intent_id")
                    if json.loads(row["payload_json"])["version"] == 2]

    def test_actual_candidate_import_context_api_and_preview_preserve_phase4_result(self):
        engine, _, raw = self.engine()
        ingestion = self.import_source(engine, raw)
        self.assertEqual(ingestion["status"], "QUALIFIED")
        summary = engine.run_single_scan()
        self.assertEqual(summary["total_signals"], 1)
        context = summary["context"]
        self.assertEqual(context["status"], "QUALIFIED")
        self.assertFalse(context["actionable"])
        self.assertFalse(context["affects_ranking"])
        original = engine.store.load_cash_scan(summary["run_id"])["result"]
        evaluation = engine.store.load_scan_evaluations(summary["run_id"])
        self.assertNotIn("context", original)
        for field in ("signals", "candidate_evaluations", "strategy_evaluations"):
            self.assertEqual(original[field], summary[field])
        self.assertEqual(context["phase4_digest"], digest(evaluation))
        candidate = summary["candidate_evaluations"][0]
        enriched = context["candidate_contexts"][0]
        self.assertEqual(enriched["candidate_id"], candidate["candidate_id"])
        self.assertEqual(enriched["records"][0]["instrument_identity"], candidate["source_reference"]["instrument_identity"])
        decision = summary["context_alert_decisions"][0]
        self.assertEqual(decision["status"], "ELIGIBLE")
        self.assertEqual(decision["preview"]["status"], "ACKNOWLEDGED")
        self.assertFalse(decision["preview"]["current_live_acceptance"])
        self.assertEqual(len(self.v2_rows(engine)), 1)
        handler = self.handler(engine)
        code, response = handler._handle_context({"run_id": [summary["run_id"]]})
        self.assertEqual(code, 200)
        self.assertEqual(response["context"], context)
        code, response = handler._handle_signals({})
        self.assertEqual(code, 200)
        projected = response["items"][0]["context"]
        for key, value in enriched.items():
            self.assertEqual(projected[key], value)
        for key in ("snapshot_id", "as_of", "decision_at", "evaluation_mode"):
            self.assertEqual(projected[key], context[key])
        code, response = handler._handle_scans({})
        self.assertEqual(code, 200)
        self.assertEqual(response["items"][0]["context"], context)

    def test_default_unverified_context_cannot_change_rank_or_make_alert_eligible(self):
        engine, _, raw = self.engine(qualified=False)
        ingestion = self.import_source(engine, raw)
        self.assertEqual(ingestion["status"], "WARNING_ONLY")
        summary = engine.run_single_scan()
        candidate = summary["candidate_evaluations"][0]
        self.assertEqual(candidate["status"], "QUALIFIED")
        self.assertEqual(candidate["ranking"]["rank"], 1)
        self.assertEqual(summary["context"]["status"], "WARNING_ONLY")
        self.assertEqual(summary["context_alert_decisions"][0]["status"], "SUPPRESSED")
        self.assertEqual(self.v2_rows(engine), [])
        original = engine.store.load_cash_scan(summary["run_id"])["result"]
        self.assertEqual(original["candidate_evaluations"], summary["candidate_evaluations"])

    def test_qualified_other_company_context_never_attaches_to_candidate(self):
        other_identity = self.source.other
        wrong_company = dict(self.source.row, instrument_identity=other_identity)
        raw = self.source.raw([wrong_company])
        engine, _, _ = self.engine(documents=[raw], policy_scope="SBIN", extra_identities=[other_identity])
        ingestion = self.import_source(engine, raw)
        self.assertEqual(ingestion["status"], "QUALIFIED")
        summary = engine.run_single_scan()
        self.assertEqual(summary["total_signals"], 1)
        self.assertEqual(summary["candidate_evaluations"][0]["symbol"], "RELIANCE")
        self.assertEqual(summary["context"]["candidate_contexts"][0]["records"], [])
        self.assertEqual(summary["context"]["status"], "MISSING")
        self.assertEqual(summary["context_alert_decisions"][0]["status"], "SUPPRESSED")
        self.assertEqual(self.v2_rows(engine), [])

    def test_late_backdated_import_is_excluded_from_decision_time_but_current_view_is_labelled(self):
        engine, _, raw = self.engine()
        first = engine.run_single_scan()
        original = copy.deepcopy(engine.store.load_scan_evaluations(first["run_id"]))
        self.market.clock_value += timedelta(minutes=10)
        self.import_source(engine, raw)
        decision = engine.enrich_context(first["run_id"])
        self.assertEqual(decision["context"]["candidate_contexts"][0]["records"], [])
        self.assertNotIn(self.source.row["title"], json.dumps(decision["context"]))
        current = engine.enrich_context(first["run_id"], as_of=self.market.clock_value,
                                        evaluation_mode="CURRENT_INFORMATION")
        self.assertEqual(current["context"]["status"], "QUALIFIED")
        self.assertEqual(current["context"]["evaluation_mode"], "CURRENT_INFORMATION")
        self.assertEqual(engine.store.load_scan_evaluations(first["run_id"]), original)

    def test_rejected_detected_candidate_stays_rejected_with_qualified_context(self):
        engine, _, raw = self.engine()
        self.import_source(engine, raw)
        def corrupt_target(*args, **kwargs):
            signal = evaluate_order_block_fvg(*args, **kwargs)
            self.assertIsNotNone(signal)
            signal.target_1 = signal.entry_price - 1
            return signal
        with patch("scanner_engine.evaluate_order_block_fvg", side_effect=corrupt_target):
            summary = engine.run_single_scan()
        self.assertEqual(summary["total_signals"], 0)
        self.assertEqual(summary["candidate_evaluations"][0]["status"], "REJECTED")
        self.assertEqual(summary["context"]["candidate_contexts"][0]["status"], "QUALIFIED")
        decision = summary["context_alert_decisions"][0]
        self.assertEqual(decision["status"], "SUPPRESSED")
        self.assertEqual(decision["reason_code"], "CANDIDATE_NOT_QUALIFIED")
        self.assertNotIn("intent_id", decision)
        self.assertEqual(self.v2_rows(engine), [])

    def test_retry_uses_actual_clock_while_decision_context_cutoff_stays_fixed(self):
        import notification_outbox
        engine, _, raw = self.engine()
        self.import_source(engine, raw)
        original_renderer = notification_outbox.render_preview
        def fail_context_only(body):
            if body["version"] == 2:
                raise RuntimeError("Offline local-render failure")
            return original_renderer(body)
        with patch("notification_outbox.render_preview", side_effect=fail_context_only):
            summary = engine.run_single_scan()
        decision = summary["context_alert_decisions"][0]
        self.assertEqual(decision["preview"]["status"], "RETRY")
        fixed_cutoff = summary["context"]["as_of"]
        immediate = engine.enrich_context(summary["run_id"])
        self.assertEqual(immediate["alert_decisions"][0]["preview"]["status"], "DEFERRED")
        self.market.clock_value += timedelta(seconds=6)
        retried = engine.enrich_context(summary["run_id"])
        self.assertEqual(retried["context"]["as_of"], fixed_cutoff)
        self.assertEqual(retried["alert_decisions"][0]["preview"]["status"], "ACKNOWLEDGED")
        self.assertEqual(len(self.v2_rows(engine)), 1)
        self.assertEqual(self.v2_rows(engine)[0]["attempts"], 2)

    def test_same_context_deduplicates_and_new_source_record_creates_one_new_intent(self):
        first_raw = self.source.raw()
        changed = dict(self.source.row, source_record_ref="notice-124", title="Second authored fixture notice",
                       source_url="https://issuer.example/notice/124", original_ref="https://issuer.example/notice/124")
        second_raw = self.source.raw([changed])
        engine, _, _ = self.engine(documents=[first_raw, second_raw])
        self.import_source(engine, first_raw)
        summary = engine.run_single_scan()
        first_intent = summary["context_alert_decisions"][0]["intent_id"]
        self.market.clock_value += timedelta(seconds=10)
        same = engine.enrich_context(summary["run_id"], as_of=self.market.clock_value, evaluation_mode="CURRENT_INFORMATION")
        self.assertEqual(same["alert_decisions"][0]["intent_id"], first_intent)
        self.assertEqual(len(self.v2_rows(engine)), 1)
        self.import_source(engine, second_raw)
        changed_result = engine.enrich_context(summary["run_id"], as_of=self.market.clock_value, evaluation_mode="CURRENT_INFORMATION")
        self.assertEqual(changed_result["context"]["status"], "QUALIFIED")
        self.assertNotEqual(changed_result["alert_decisions"][0]["intent_id"], first_intent)
        self.assertEqual(len(self.v2_rows(engine)), 2)
        repeated = engine.enrich_context(summary["run_id"], as_of=self.market.clock_value, evaluation_mode="CURRENT_INFORMATION")
        self.assertEqual(repeated["alert_decisions"][0]["intent_id"], changed_result["alert_decisions"][0]["intent_id"])
        self.assertEqual(len(self.v2_rows(engine)), 2)

    def test_stale_context_is_warning_only_and_never_creates_new_alert(self):
        engine, _, raw = self.engine()
        self.import_source(engine, raw)
        summary = engine.run_single_scan()
        evaluation = copy.deepcopy(engine.store.load_scan_evaluations(summary["run_id"]))
        self.market.clock_value += timedelta(days=2)
        current = engine.enrich_context(summary["run_id"], evaluation_mode="CURRENT_INFORMATION")
        overlay = current["context"]["candidate_contexts"][0]
        self.assertEqual(overlay["status"], "WARNING_ONLY")
        self.assertIn("CONTEXT_STALE", overlay["reason_codes"])
        self.assertEqual(overlay["records"][0]["freshness"]["status"], "STALE")
        self.assertEqual(current["alert_decisions"][0]["status"], "SUPPRESSED")
        self.assertEqual(len(self.v2_rows(engine)), 1)
        self.assertEqual(engine.store.load_scan_evaluations(summary["run_id"]), evaluation)

    def test_conflicting_context_is_retained_as_warning_without_changing_candidate(self):
        raw = self.source.raw()
        conflict_raw = self.source.raw([dict(self.source.row, title="Conflicting authored fixture")])
        engine, _, _ = self.engine(documents=[raw, conflict_raw])
        self.import_source(engine, raw)
        summary = engine.run_single_scan()
        evaluation = copy.deepcopy(engine.store.load_scan_evaluations(summary["run_id"]))
        self.market.clock_value += timedelta(seconds=10)
        self.import_source(engine, conflict_raw)
        current = engine.enrich_context(summary["run_id"], evaluation_mode="CURRENT_INFORMATION")
        overlay = current["context"]["candidate_contexts"][0]
        self.assertEqual(overlay["status"], "WARNING_ONLY")
        self.assertIn("CONTEXT_CONFLICTING", overlay["reason_codes"])
        self.assertEqual(len(overlay["records"]), 2)
        self.assertEqual(current["alert_decisions"][0]["status"], "SUPPRESSED")
        self.assertEqual(len(self.v2_rows(engine)), 1)
        self.assertEqual(engine.store.load_scan_evaluations(summary["run_id"]), evaluation)

    def test_optional_context_commit_failure_cannot_erase_committed_phase4_candidate(self):
        engine, _, raw = self.engine()
        self.import_source(engine, raw)
        def fail_context_write(boundary):
            if boundary == "before_context_snapshot_commit":
                raise PersistenceError("OFFLINE context write failure")
        with patch.object(engine.store, "_context_checkpoint", side_effect=fail_context_write):
            summary = engine.run_single_scan()
        self.assertEqual(summary["scan_status"], "COMPLETED")
        self.assertEqual(summary["total_signals"], 1)
        self.assertEqual(summary["persisted_signals"], 1)
        self.assertEqual(summary["context"]["status"], "UNAVAILABLE")
        self.assertEqual(summary["context"]["reason_codes"], ["CONTEXT_REQUIRES_INSPECTION"])
        original = engine.store.load_cash_scan(summary["run_id"])["result"]
        self.assertEqual(original["candidate_evaluations"], summary["candidate_evaluations"])
        self.assertEqual(original["signals"], summary["signals"])
        self.assertIsNone(engine.store.load_scan_context(summary["run_id"]))
        self.assertEqual(self.v2_rows(engine), [])

    def test_future_collection_and_future_context_cutoff_cannot_be_accepted(self):
        engine, _, raw = self.engine()
        with self.assertRaises((PersistenceError, PersistenceValidationError, ValueError)):
            self.import_source(engine, raw, collected=(self.market.clock_value + timedelta(minutes=1)).isoformat())
        summary = engine.run_single_scan()
        with self.assertRaises((PersistenceError, PersistenceValidationError, ValueError)):
            engine.enrich_context(summary["run_id"], as_of=self.market.clock_value + timedelta(minutes=1),
                                  evaluation_mode="CURRENT_INFORMATION")

    def test_import_api_rejects_payload_trust_injection_and_malformed_source(self):
        engine, _, raw = self.engine(qualified=False)
        handler = self.handler(engine)
        base = dict(provider="offline_notices", collected_at="2026-10-23T08:40:00+00:00", payload=json.loads(raw))
        for field, value in (("source_policy", {"allowed": True}), ("trusted_identities", [self.source.identity]),
                             ("observed_at", "2026-10-01T00:00:00+00:00")):
            with self.subTest(field=field):
                code, response = handler._handle_context_import(dict(base, **{field: value}))
                self.assertEqual(code, 400)
                self.assertNotIn("records", response)
        for payload in ("not-json", {"schema_version": "unknown", "records": []}):
            code, response = handler._handle_context_import(dict(base, payload=payload))
            self.assertEqual(code, 400)
            self.assertNotIn("records", response)
        self.assertEqual(engine.store.list_context_ingestions()["total_count"], 0)

    def test_supported_import_and_enrich_post_handlers_use_same_retained_context(self):
        engine, _, raw = self.engine()
        handler = self.handler(engine)
        code, imported = handler._handle_context_import(dict(provider="offline_notices",
            collected_at="2026-10-23T08:40:00+00:00", payload=raw.decode()))
        self.assertEqual(code, 200)
        self.assertEqual(imported["ingestion"]["status"], "QUALIFIED")
        self.assertFalse(imported["operational_source_acceptance"])
        summary = engine.run_single_scan()
        code, enriched = handler._handle_context_enrich(dict(run_id=summary["run_id"]))
        self.assertEqual(code, 200)
        self.assertEqual(enriched["context"], summary["context"])
        self.assertEqual(enriched["alert_decisions"][0]["intent_id"], summary["context_alert_decisions"][0]["intent_id"])
        self.assertEqual(len(self.v2_rows(engine)), 1)

    def test_legacy_scan_history_reports_missing_context_without_fabricated_records(self):
        engine, _, _ = self.engine()
        engine.store.record_scan_run("legacy-fixture", "2026-10-23T14:15:05+05:30", None, 0,
                                    "COMPLETED_EMPTY", "angelone", "LIVE", False)
        handler = self.handler(engine)
        code, context = handler._handle_context({"run_id": ["legacy-fixture"]})
        self.assertEqual(code, 200)
        self.assertEqual(context["context"]["status"], "MISSING")
        self.assertFalse(context["context"]["actionable"])
        self.assertNotIn("candidate_contexts", context["context"])
        code, scans = handler._handle_scans({})
        self.assertEqual(code, 200)
        self.assertIsNone(scans["items"][0]["evaluation"])
        self.assertTrue(scans["items"][0]["context"] is None or scans["items"][0]["context"]["status"] in ("MISSING", "UNAVAILABLE"))

    def test_rehashed_snapshot_corruption_fails_context_and_existing_history_routes(self):
        engine, _, raw = self.engine()
        self.import_source(engine, raw)
        summary = engine.run_single_scan()
        snapshot_id = summary["context"]["snapshot_id"]
        with engine.store.paper_transaction(write=True) as conn:
            row = conn.execute("SELECT payload_json FROM scan_context_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            payload = json.loads(row[0])
            payload["candidate_contexts"][0]["records"][0]["title"] = "UNBOUND_SOURCE_MARKER"
            body = encoded(payload)
            conn.execute("UPDATE scan_context_snapshots SET payload_json=?,payload_digest=? WHERE snapshot_id=?",
                         (body, hashlib.sha256(body.encode()).hexdigest(), snapshot_id))
        handler = self.handler(engine)
        for method, query in ((handler._handle_context, {"run_id": [summary["run_id"]]}),
                              (handler._handle_signals, {}), (handler._handle_scans, {})):
            code, response = method(query)
            self.assertEqual(code, 503)
            self.assertNotIn("UNBOUND_SOURCE_MARKER", json.dumps(response))
            self.assertNotIn("items", response)


if __name__ == "__main__":
    unittest.main()

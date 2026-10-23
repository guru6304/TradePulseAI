"""Isolated TEST-ONLY signatures/rights documents; never provider acceptance."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_bot
from backtest_engine import BacktestConfig, DeterministicBacktestEngine
from config import BotConfig
from historical_study import (HistoricalEvidenceArchive, OperatorRightsPolicy, encode,
    qualify_artifact, run_frozen_study, sha, walk_forward_plan)
from storage import SQLitePersistenceStore
from strategies import IST


class TestHistoricalStudy(unittest.TestCase):
    def setUp(self):
        from test_publisher_trust import TestPublisherTrustMatrix
        self.fixture = TestPublisherTrustMatrix()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 16, 16, tzinfo=IST)
        self.engine = DeterministicBacktestEngine(BotConfig(active_broker="paper_sim",
            telegram_dry_run=True, enable_background_scheduler=False), self.store,
            clock=lambda: self.now, publisher_trust_config=self.fixture._build_trust_config())
        self.raw = self.fixture._sample_raw_bytes()
        self.manifest = json.dumps(self.fixture._build_manifest(self.raw, instrument_scope="RELIANCE"))
        self.document = b"TEST ONLY - simulated rights approval; grants no real rights"
        self.grant = dict(rights_reference="ANGEL_DEVELOPER_TERMS_REF_2026", provider="angelone",
            publisher_id="angelone", document_sha256=sha(self.document), artifact_sha256s=[sha(self.raw)],
            symbols=["RELIANCE"], allowed_uses=["HISTORICAL_RESEARCH"], revoked=False,
            effective_from="2026-10-01T00:00:00+00:00", effective_until="2026-10-31T23:59:59+00:00",
            approved_at="2026-10-01T00:00:00+00:00", review_due_at="2026-12-01T00:00:00+00:00",
            approved_by="TEST ONLY operator", approval_reference="TEST ONLY simulated review")
        self.rights = OperatorRightsPolicy([self.grant], {sha(self.document): self.document})

    def qualify(self, **changes):
        args = dict(trust_config=self.engine.publisher_trust_config, rights_policy=self.rights,
            provider="angelone", exchange="NSE", segment="NSE_EQUITY_INTRADAY", symbol="RELIANCE",
            artifact_type="instrument-master", schema_version="tradepulse.instrument-master.v1",
            coverage_start="2026-10-15T09:15:00+05:30", coverage_end="2026-10-15T15:30:00+05:30",
            verification_time=self.now.isoformat())
        args.update(changes)
        return qualify_artifact(self.raw, self.manifest, **args)

    def bars(self, mode="SIMULATED"):
        result = []
        for day in ("2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"):
            bars = test_bot.TestIndianFOSignalBotPhase3A._build_session_bars(day, data_mode=mode)
            for bar in bars:
                bar["timestamp"] = datetime.fromisoformat(bar["timestamp"]).replace(tzinfo=IST).isoformat()
            result.extend(bars)
        return result

    def test_genuine_signature_and_separate_documented_operator_rights_are_both_required(self):
        self.assertTrue(self.qualify()["allowed"])
        no_rights = self.qualify(rights_policy=None)
        self.assertFalse(no_rights["allowed"])
        self.assertIn("RIGHTS_DOCUMENT_AND_OPERATOR_APPROVAL_NOT_SUPPLIED", no_rights["missing_evidence"])
        self.assertFalse(self.qualify(trust_config=None)["allowed"])
        self.rights.grants[0]["revoked"] = True
        self.assertFalse(self.qualify()["allowed"])

    def test_rights_hash_symbol_use_expiry_and_document_are_bound_without_caller_flags(self):
        for key, value in (("symbols", ["TCS"]), ("artifact_sha256s", ["wrong"]),
                ("allowed_uses", ["DISPLAY"]), ("review_due_at", "2026-10-02T00:00:00+00:00"),
                ("document_sha256", "missing"), ("publisher_id", "other")):
            with self.subTest(field=key):
                self.rights.grants = [copy.deepcopy(self.grant)]
                self.rights.grants[0][key] = value
                self.assertFalse(self.qualify()["allowed"])

    def test_current_revoked_key_changed_bytes_signed_scope_and_synthetic_are_rejected(self):
        self.engine.publisher_trust_config._anchors[0]["revoked"] = True
        self.assertFalse(self.qualify()["allowed"])
        self.engine.publisher_trust_config._anchors[0]["revoked"] = False
        self.raw += b" "
        self.assertFalse(self.qualify()["allowed"])
        self.raw = self.fixture._sample_raw_bytes()
        self.assertFalse(self.qualify(schema_version="wrong")["allowed"])
        payload = json.loads(self.raw)
        payload["evidence_class"] = "SYNTHETIC_FIXTURE"
        self.raw = encode(payload)
        self.manifest = json.dumps(self.fixture._build_manifest(self.raw, instrument_scope="RELIANCE"))
        self.assertIn("SYNTHETIC_FIXTURE_IS_NOT_AUTHENTIC_DATA", self.qualify()["missing_evidence"])

    def test_original_source_manifest_rights_and_metadata_survive_reopen_and_tampering_fails(self):
        archive = HistoricalEvidenceArchive(self.store)
        artifacts = dict(source=self.raw, manifest=self.manifest.encode(), rights=self.document)
        identity = archive.retain(artifacts, dict(acquired_at=self.now.isoformat(), status="UNQUALIFIED"))
        self.assertEqual(identity, archive.retain(artifacts, dict(acquired_at=self.now.isoformat(), status="UNQUALIFIED")))
        self.assertEqual(HistoricalEvidenceArchive(self.store).load(identity)["artifacts"], artifacts)
        conn = self.store._get_connection()
        with conn:
            conn.execute("UPDATE historical_evidence_bytes SET original_bytes=? WHERE sha256=?", (b"changed", sha(self.raw)))
        with self.assertRaises(ValueError):
            archive.load(identity)

    def test_walk_forward_has_expanding_training_and_nonoverlapping_tests(self):
        sessions = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"]
        plan = walk_forward_plan(sessions, training_sessions=2, test_sessions=1)
        self.assertEqual(len(plan["folds"]), 2)
        self.assertEqual(plan["folds"][1]["train_sessions"], sessions[:3])
        for bad in (sessions[::-1], sessions + sessions[-1:]):
            with self.assertRaises(ValueError):
                walk_forward_plan(bad, training_sessions=2, test_sessions=1)
        with self.assertRaises(ValueError):
            walk_forward_plan(sessions, training_sessions=1, test_sessions=2, step_sessions=1)

    def test_original_bytes_are_durable_across_file_store_close_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix="task2_history_", dir=".") as folder:
            path = str(Path(folder) / "history.db")
            store = SQLitePersistenceStore(path)
            try:
                evidence_id = HistoricalEvidenceArchive(store).retain(
                    {"source": self.raw, "manifest": self.manifest.encode()}, dict(kind="TEST ONLY"))
            finally:
                store.close()
            reopened = SQLitePersistenceStore(path)
            try:
                saved = HistoricalEvidenceArchive(reopened).load(evidence_id)
                self.assertEqual(saved["artifacts"]["source"], self.raw)
                self.assertEqual(saved["artifacts"]["manifest"], self.manifest.encode())
            finally:
                reopened.close()

    def test_actual_cash_engine_walk_forward_is_frozen_repeatable_and_fixture_labelled(self):
        bars = self.bars()
        plan = walk_forward_plan(sorted({b["timestamp"][:10] for b in bars}), training_sessions=2, test_sessions=1)
        cfg = BacktestConfig(execution_scope="SIMULATED_TEST")
        args = dict(strategy_id="strat_1_order_block", symbol="RELIANCE", provider="paper_sim",
            backtest_config=cfg, plan=plan, candles=bars, instrument_token="2885")
        result = run_frozen_study(self.engine, **args)
        again = run_frozen_study(self.engine, **args)
        self.assertEqual(result["study_id"], again["study_id"])
        self.assertEqual(result["input_evidence_id"], again["input_evidence_id"])
        self.assertEqual([f["run"]["metrics"] for f in result["folds"]], [f["run"]["metrics"] for f in again["folds"]])
        self.assertEqual(result["real_historical_study_status"], "BLOCKED")
        self.assertFalse(result["empirical_performance_claim_allowed"])
        self.assertEqual(cfg.period_type, "FULL")
        for fold in result["folds"]:
            self.assertEqual(fold["run"]["period_type"], "OUT_OF_SAMPLE")
            for trade in fold["run"]["trades"]:
                self.assertIn(trade["entry_timestamp"][:10], fold["test_sessions"])
        retained = HistoricalEvidenceArchive(self.store).load(result["input_evidence_id"])
        self.assertIn("cash_dataset", retained["artifacts"])
        self.assertIn("frozen_plan", retained["artifacts"])
        bars[0]["volume"] += 1
        changed = run_frozen_study(self.engine, **args)
        self.assertNotEqual(result["study_id"], changed["study_id"])
        self.engine.bot_config.configured_holidays.append("2026-10-20")
        changed_policy = run_frozen_study(self.engine, **args)
        self.assertNotEqual(changed["study_id"], changed_policy["study_id"])

    def test_real_shaped_signed_cash_study_replays_and_rechecks_current_rights(self):
        # TEST-ONLY key and approval. This exercises admission machinery, not a
        # real provider publication, rights clearance or performance acceptance.
        bars = self.bars("LIVE")
        master = self.store.ingest_instrument_master_bytes(self.raw, "angelone", "test.json", "TEST ONLY")
        master_manifest = json.dumps(self.fixture._build_manifest(self.raw, instrument_scope="RELIANCE",
            publisher_publication_time="2026-10-01T00:00:00+00:00", capture_observation_time="2026-10-01T00:05:00+00:00"))
        self.engine.publisher_manifests = {master["archive_id"]: master_manifest}
        dataset = encode(dict(schema_version="tradepulse.cash-observations.v1", candles=bars))
        manifest = json.dumps(self.fixture._build_manifest(dataset, instrument_scope="RELIANCE",
            artifact_type="cash-observations", artifact_schema_version="tradepulse.cash-observations.v1"))
        self.rights.grants[0]["artifact_sha256s"].append(sha(dataset))
        plan = walk_forward_plan(sorted({b["timestamp"][:10] for b in bars}), training_sessions=2, test_sessions=1)
        args = dict(strategy_id="strat_1_order_block", symbol="RELIANCE", provider="angelone",
            backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH",
                historical_instrument_archive_id=master["archive_id"]), plan=plan, candles=bars,
            instrument_token="2885", data_mode="LIVE", rights_policy=self.rights,
            cash_source=dict(original_bytes=dataset, manifest_json=manifest))
        result = run_frozen_study(self.engine, **args)
        self.assertEqual(len(result["folds"]), 2)
        self.assertFalse(result["missing_evidence"])
        self.assertEqual(result["real_historical_study_status"], "QUALIFIED_REPRODUCIBLE_BOUNDED_STUDY")
        self.assertFalse(result["empirical_performance_claim_allowed"])
        self.rights.grants[0]["revoked"] = True
        with patch.object(self.engine, "run_backtest") as replay:
            denied = run_frozen_study(self.engine, **args)
            replay.assert_not_called()
        self.assertEqual(denied["real_historical_study_status"], "BLOCKED")

    def test_option_persistence_retains_exact_master_premiums_and_replay_envelope(self):
        from test_option_execution import TestOptionExecution
        fixture = TestOptionExecution()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        request = fixture.request()
        result = fixture.replay(persist_run=True)
        saved = HistoricalEvidenceArchive(fixture.store).load(result["input_evidence_id"])
        self.assertEqual(saved["artifacts"]["master_json"], request["master_json"].encode())
        self.assertEqual(saved["artifacts"]["dataset_json"], request["dataset_json"].encode())
        self.assertEqual(json.loads(saved["artifacts"]["request"]), request)
        self.assertEqual(saved["record"]["metadata"]["data_mode"], "SIMULATED")

    def test_actual_option_engine_walk_forward_keeps_test_entries_chronological(self):
        from test_option_execution import TestOptionExecution
        fixture = TestOptionExecution()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prior_bars = copy.deepcopy(fixture.data["underlying_candles"])
        prior_quotes = copy.deepcopy(fixture.data["premiums"])
        for row in prior_bars + prior_quotes:
            for field in ("timestamp", "available_at", "depth_observed_at"):
                if field in row:
                    row[field] = (datetime.fromisoformat(row[field]) - timedelta(days=1)).isoformat()
        fixture.data["underlying_candles"] = prior_bars + fixture.data["underlying_candles"]
        fixture.data["premiums"] = prior_quotes + fixture.data["premiums"]
        result = run_frozen_study(fixture.engine, strategy_id="strat_3_option_apex_oi", symbol="NIFTY",
            provider="upstox", backtest_config=fixture.config, option_request=fixture.request(),
            plan=walk_forward_plan(["2026-10-15", "2026-10-16"], training_sessions=1, test_sessions=1))
        self.assertEqual(result["real_historical_study_status"], "BLOCKED")
        self.assertEqual(len(result["folds"][0]["run"]["trades"]), 1)
        self.assertTrue(result["folds"][0]["run"]["trades"][0]["entry_timestamp"].startswith("2026-10-16"))

    def test_cash_quality_rejects_duplicates_out_of_order_forming_and_audits_missing(self):
        original = self.bars()
        plan = walk_forward_plan(sorted({b["timestamp"][:10] for b in original}), training_sessions=2, test_sessions=1)
        args = dict(strategy_id="strat_1_order_block", symbol="RELIANCE", provider="paper_sim",
            backtest_config=BacktestConfig(execution_scope="SIMULATED_TEST"), plan=plan, instrument_token="2885")
        for operation in (lambda b: b.insert(1, copy.deepcopy(b[0])), lambda b: b.reverse(),
                lambda b: b[0].update(is_complete=False)):
            bars = copy.deepcopy(original)
            operation(bars)
            with self.assertRaises(ValueError):
                run_frozen_study(self.engine, candles=bars, **args)
        missing = copy.deepcopy(original)
        del missing[10]
        result = run_frozen_study(self.engine, candles=missing, **args)
        self.assertEqual(result["quality_audit"]["missing_bars_count"], 1)
        self.assertEqual(result["real_historical_study_status"], "BLOCKED")

    def test_real_cash_study_without_authenticated_sources_is_blocked_before_evaluator(self):
        bars = self.bars("LIVE")
        plan = walk_forward_plan(sorted({b["timestamp"][:10] for b in bars}), training_sessions=2, test_sessions=1)
        with patch.object(self.engine, "run_backtest") as replay:
            result = run_frozen_study(self.engine, strategy_id="strat_1_order_block", symbol="RELIANCE",
                provider="angelone", backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH"),
                plan=plan, candles=bars, data_mode="LIVE", instrument_token="2885")
            replay.assert_not_called()
        self.assertEqual(result["real_historical_study_status"], "BLOCKED")
        self.assertIn("AUTHENTIC_INSTRUMENT-MASTER_AND_DETACHED_MANIFEST_NOT_SUPPLIED", result["missing_evidence"])

    def test_submitted_source_bytes_or_forged_overlapping_plan_cannot_change_study(self):
        bars = self.bars()
        plan = walk_forward_plan(sorted({b["timestamp"][:10] for b in bars}), training_sessions=2, test_sessions=1)
        args = dict(strategy_id="strat_1_order_block", symbol="RELIANCE", provider="angelone",
            backtest_config=BacktestConfig(execution_scope="SIMULATED_TEST"), plan=plan,
            candles=bars, instrument_token="2885")
        with self.assertRaises(ValueError):
            run_frozen_study(self.engine, **args, cash_source=dict(original_bytes=encode(dict(candles=[])), manifest_json="{}"))
        plan["folds"][1]["test_sessions"] = plan["folds"][0]["test_sessions"]
        with self.assertRaises(ValueError):
            run_frozen_study(self.engine, **args)


if __name__ == "__main__":
    unittest.main(verbosity=2)

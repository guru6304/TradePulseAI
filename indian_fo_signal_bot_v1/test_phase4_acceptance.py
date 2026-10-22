"""Real signatures under public TEST-ONLY keys, never publisher acceptance."""
import copy
import json
import unittest
from unittest.mock import patch

import test_bot
from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
from config import BotConfig
from instrument_archive import prepare_archive, resolve_archives
from instrument_identity import IdentityValidationError, digest
from source_qualification import assess_source_evidence


class TestPhase4TrustAcceptance(unittest.TestCase):
    def setUp(self):
        from test_publisher_trust import TestPublisherTrustMatrix
        self.f = TestPublisherTrustMatrix()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.raw = self.f._sample_raw_bytes()
        self.archive = prepare_archive(self.raw, "angelone", "test.json", "OFFLINE_TEST_KEYS")
        self.archive["original_bytes"] = self.raw
        self.trust = self.f._build_trust_config()

    def assessment(self, **overrides):
        self.archive["metadata"]["publisher_manifest_json"] = json.dumps(self.f._build_manifest(self.raw, **overrides))
        return assess_source_evidence(self.archive, self.raw, self.trust, self.f.now)

    def test_wrong_signed_exchange_or_segment_cannot_qualify_a_cash_archive(self):
        for changes in (dict(exchange="NFO"),dict(market_segment="NSE_FO_INDEX"),
                        dict(artifact_type="option-observations"),dict(artifact_schema_version="WRONG"),
                        dict(instrument_scope="TCS")):
            with self.subTest(changes=changes):
                self.assertFalse(self.assessment(**changes)["historical_eligibility"]["allowed"])

    def test_signed_dates_must_cover_record_dates_not_merely_be_well_ordered(self):
        self.assertFalse(self.assessment(effective_from="2026-10-15T00:00:00+00:00",
            effective_until="2026-10-16T23:59:59+00:00")["historical_eligibility"]["allowed"])

    def test_changed_normalized_records_and_digest_cannot_reuse_signed_original_bytes(self):
        self.archive["records"][0]["identifier"] = "CHANGED"
        self.archive["normalized_sha256"] = digest(self.archive["records"])
        self.assertFalse(self.assessment()["historical_eligibility"]["allowed"])

    def test_actual_archive_store_readiness_and_cash_replay_use_current_operator_trust(self):
        store = self.f.store
        saved = store.ingest_instrument_master_bytes(self.raw,"angelone","test.json","OFFLINE_TEST_KEYS")
        manifest = json.dumps(self.f._build_manifest(self.raw))
        cfg = BotConfig(active_broker="paper_sim",telegram_dry_run=True, enable_background_scheduler=False)
        engine = DeterministicBacktestEngine(cfg,store,clock=lambda:self.f.now,
            publisher_trust_config=self.trust,publisher_manifests={saved["archive_id"]:manifest})
        bars = test_bot.TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15")
        config = BacktestConfig(execution_scope="HISTORICAL_RESEARCH",historical_instrument_archive_id=saved["archive_id"])
        result = engine.run_backtest("strat_1_order_block","RELIANCE",candles=bars,
            provider="angelone", data_mode="LIVE",backtest_config=config)
        self.assertTrue(result)
        # No cached positive assessment can authorize a revoked key.
        self.trust._anchors[0]["revoked"] = True
        with patch.object(engine,"_invoke_strategy_evaluator") as evaluator:
            with self.assertRaises(BacktestEligibilityError):
                engine.run_backtest("strat_1_order_block","RELIANCE",candles=bars,
                    provider="angelone",data_mode="LIVE",backtest_config=config)
            evaluator.assert_not_called()
        self.trust._anchors[0]["revoked"]=False
        engine.publisher_manifests[saved["archive_id"]]=json.dumps(self.f._build_manifest(self.raw,
            publisher_publication_time="2026-10-16T00:00:00+00:00",capture_observation_time="2026-10-16T00:05:00+00:00"))
        with self.assertRaises(BacktestEligibilityError) as future:
            engine.run_backtest("strat_1_order_block","RELIANCE",candles=bars,
                provider="angelone",data_mode="LIVE",backtest_config=config)
        self.assertEqual(future.exception.details["reason_code"],"FUTURE_ARCHIVE_PUBLICATION")


if __name__ == "__main__":
    unittest.main(verbosity=2)

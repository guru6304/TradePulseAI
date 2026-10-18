"""Offline adversarial archive tests; no fixture is publisher/source evidence."""

import copy
import hashlib
import json
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot  # noqa: F401 -- reuse the established offline configuration bootstrap

_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
from config import BotConfig
from historical_data import evaluate_phase3a_backtest_readiness
from instrument_archive import SCHEMA, prepare_archive
from instrument_identity import IdentityValidationError
from source_qualification import POLICY_VERSION
from storage import SQLitePersistenceStore
from strategies import IST


class TestPhase5AHistoricalProvenance(unittest.TestCase):
    """Test real retained-byte/lookup/replay gates without a fabricated verifier."""

    TOKENS = {"angelone": "2885", "dhan": "2885", "upstox": "NSE_EQ|INE002A01018"}

    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        transport = patch("urllib.request.urlopen", side_effect=AssertionError("External transport forbidden"))
        transport.start()
        self.addCleanup(transport.stop)

    def _payload(self, provider="angelone", *, record=None, **claims):
        row = dict(provider=provider, symbol="RELIANCE", identifier=self.TOKENS[provider],
                   exchange="NSE", instrument_type="EQ", multiplier=1,
                   valid_from="2026-10-01", valid_to="2026-10-31")
        row.update(record or {})
        return dict(schema_version=SCHEMA, provider=provider, records=[row],
                    fixture_description="SYNTHETIC_UNAUTHENTICATED_SOURCE_DECLARATIONS", **claims)

    def _ingest(self, payload=None, provider="angelone", *, raw=None,
                source_reference="OFFLINE_SYNTHETIC_DECLARATIONS", **metadata):
        if raw is None:
            raw = json.dumps(self._payload(provider) if payload is None else payload).encode("utf-8")
        return self.store.ingest_instrument_master_bytes(
            raw, provider, "offline-provenance-fixture.json", source_reference, **metadata)

    def _args(self, provider="angelone", **changes):
        values = dict(provider=provider, symbol="RELIANCE", identifier=self.TOKENS[provider],
                      exchange="NSE", instrument_type="EQ", first_date="2026-10-15", last_date="2026-10-15")
        values.update(changes)
        return values

    def _blocked(self, reason="HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT", **changes):
        with self.assertRaises(IdentityValidationError) as caught:
            self.store.resolve_archived_instrument_identity(**self._args(**changes))
        self.assertEqual(caught.exception.rejection["reason_code"], reason)
        return caught.exception.rejection

    def test_forged_signature_and_trust_windows_never_create_a_supported_verifier(self):
        for provider in self.TOKENS:
            for start, end in (("2000-01-01", "2000-12-31"), ("2099-01-01", "2099-12-31")):
                with self.subTest(provider=provider, trust_start=start):
                    payload = self._payload(provider, verified=True, qualified=True,
                        source_evidence={"mechanism": "UNSUPPORTED_FIXTURE_SIGNATURE",
                            "publisher": provider, "signature_valid": True,
                            "trust_key": "UNTRUSTED_FIXTURE_KEY", "policy_version": POLICY_VERSION,
                            "not_before": start, "not_after": end, "revocation_status": "GOOD"},
                        effective_date_evidence={"verified": True, "valid_from": "1900-01-01",
                                                 "valid_to": "2099-12-31"})
                    archive = self._ingest(payload, provider)
                    report = self.store.qualify_instrument_master_archive(archive["archive_id"])
                    self.assertEqual(report["submitted_qualification_claims"], "PRESENT_UNVALIDATED")
                    self.assertEqual(report["publisher_authenticity"]["supported_verification_mechanisms"], [])
                    self.assertEqual(report["effective_dates"]["independently_supported_intervals"], [])
                    self.assertFalse(report["historical_eligibility"]["allowed"])
                    self._blocked(provider=provider, archive_id=archive["archive_id"])

    def test_same_bytes_with_new_capture_context_cannot_reuse_an_archive_assessment(self):
        raw = json.dumps(self._payload()).encode("utf-8")
        first = self._ingest(raw=raw, captured_at="2026-10-15T00:00:00+00:00")
        before = self.store.qualify_instrument_master_archive(first["archive_id"])
        second = self._ingest(raw=raw, captured_at="2026-10-16T00:00:00+00:00",
                              source_reference="SECOND_UNAUTHENTICATED_CAPTURE")
        self.assertNotEqual(first["archive_id"], second["archive_id"])
        self.assertEqual(first["metadata"]["original_sha256"], second["metadata"]["original_sha256"])
        self.assertEqual(first["normalized_sha256"], second["normalized_sha256"])
        for archive in (first, second):
            self._blocked(archive_id=archive["archive_id"])
        self.assertEqual(self.store.qualify_instrument_master_archive(first["archive_id"]), before)
        conn = self.store._get_connection()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM instrument_source_assessments").fetchone()[0], 2)

    def test_conflicting_publisher_url_and_future_capture_dates_remain_untrusted_claims(self):
        archive = self._ingest(source_reference="CALLER_ASSERTS_THIS_IS_AN_ANGEL_MASTER",
            source_url="https://upstox.com/developer/api-documentation/instruments/",
            captured_at="2099-01-01T00:00:00+00:00", publisher_published_at="2100-01-01T00:00:00+00:00")
        report = self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(report["source_attribution"]["status"], "USER_DECLARED")
        self.assertEqual(report["capture_time"]["status"], "USER_DECLARED")
        self.assertEqual(report["publication_time"]["status"], "USER_DECLARED")
        self.assertFalse(report["ingestion_time"]["is_capture_time_evidence"])
        self.assertEqual(report["publisher_authenticity"]["status"], "NOT_ESTABLISHED")
        self._blocked(archive_id=archive["archive_id"])

    def test_cross_instrument_substitution_cannot_borrow_another_records_token(self):
        payload = self._payload()
        payload["records"].append(dict(payload["records"][0], symbol="HDFCBANK", identifier="1333"))
        archive = self._ingest(payload)
        correct = self.store.inspect_archived_instrument_identity(**self._args(archive_id=archive["archive_id"]))
        self.assertFalse(correct["live_historical_eligible"])
        for changes in (dict(symbol="RELIANCE", identifier="1333"), dict(symbol="HDFCBANK", identifier="2885")):
            with self.subTest(**changes):
                self._blocked("AMBIGUOUS_ARCHIVE_COVERAGE", archive_id=archive["archive_id"], **changes)
        self._blocked(archive_id=archive["archive_id"])

    def test_disjoint_token_reuse_is_date_specific_and_cannot_cover_a_crossing_range(self):
        earlier = self._ingest(self._payload(record={"valid_to": "2026-10-14"}))
        later = self._ingest(self._payload(record={"symbol": "HDFCBANK", "valid_from": "2026-10-15"}))
        for symbol, day, archive in (("RELIANCE", "2026-10-14", earlier), ("HDFCBANK", "2026-10-15", later)):
            with self.subTest(symbol=symbol):
                inspected = self.store.inspect_archived_instrument_identity(**self._args(
                    symbol=symbol, first_date=day, last_date=day, archive_id=archive["archive_id"]))
                self.assertEqual(inspected["symbol"], symbol)
                self.assertFalse(inspected["live_historical_eligible"])
                self._blocked(symbol=symbol, first_date=day, last_date=day, archive_id=archive["archive_id"])
        self._blocked("HISTORICAL_ARCHIVE_COVERAGE_MISSING", archive_id=earlier["archive_id"])
        for pin in (None, earlier["archive_id"], later["archive_id"]):
            with self.subTest(crossing_pin=pin):
                self._blocked("AMBIGUOUS_ARCHIVE_COVERAGE", first_date="2026-10-14",
                              last_date="2026-10-15", archive_id=pin)

    def test_same_identifier_and_foreign_archive_pin_cannot_cross_provider_scope(self):
        archive = self._ingest()
        self._blocked("HISTORICAL_IDENTITY_UNVERIFIED", provider="dhan", archive_id=archive["archive_id"])
        other = self._ingest(provider="dhan")
        self.assertEqual(archive["records"][0]["identifier"], other["records"][0]["identifier"])
        self.assertNotEqual(archive["archive_id"], other["archive_id"])
        self._blocked("HISTORICAL_ARCHIVE_COVERAGE_MISSING", provider="dhan", archive_id=archive["archive_id"])
        self._blocked(provider="dhan", archive_id=other["archive_id"])

    def test_rewritten_bytes_and_normalized_digests_cannot_substitute_under_old_archive_id(self):
        archive = self._ingest()
        replacement_raw = json.dumps(self._payload(record={"symbol": "HDFCBANK", "identifier": "1333"})).encode()
        replacement = prepare_archive(replacement_raw, "angelone", archive["metadata"]["original_filename"],
            archive["metadata"]["source_reference"], ingested_at=archive["ingested_at"])
        self.assertNotEqual(replacement["archive_id"], archive["archive_id"])
        self.assertEqual(replacement["metadata"]["original_sha256"], hashlib.sha256(replacement_raw).hexdigest())
        replacement["archive_id"] = archive["archive_id"]
        conn = self.store._get_connection()
        with conn:
            conn.execute("UPDATE instrument_master_archives SET original_bytes=?,candidate_json=? WHERE archive_id=?",
                         (replacement_raw, json.dumps(replacement), archive["archive_id"]))
        with self.assertRaises(IdentityValidationError) as caught:
            self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(caught.exception.rejection["reason_code"], "ARCHIVE_INTEGRITY_FAILURE")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM instrument_source_assessments").fetchone()[0], 0)

    def test_current_policy_assessment_from_another_archive_cannot_be_substituted(self):
        first = self._ingest()
        foreign = self.store.qualify_instrument_master_archive(first["archive_id"])
        second = self._ingest(captured_at="2026-10-16T00:00:00+00:00")
        conn = self.store._get_connection()
        with conn:
            conn.execute("INSERT INTO instrument_source_assessments VALUES (?, ?, ?)",
                         (second["archive_id"], POLICY_VERSION, json.dumps(foreign, sort_keys=True, allow_nan=False)))
        with self.assertRaises(IdentityValidationError) as caught:
            self.store.qualify_instrument_master_archive(second["archive_id"])
        self.assertEqual(caught.exception.rejection["reason_code"], "SOURCE_ASSESSMENT_INTEGRITY_FAILURE")
        self.assertEqual(self.store.qualify_instrument_master_archive(first["archive_id"]), foreign)

    def test_expired_foreign_policy_verdict_is_retained_but_cannot_become_current_authority(self):
        archive = self._ingest()
        old = dict(policy_version="UNSUPPORTED_EXPIRED_FIXTURE_POLICY", archive_id=archive["archive_id"],
                   valid_until="2000-01-01T00:00:00+00:00", publisher_authenticity={"status": "VERIFIED"},
                   historical_eligibility={"allowed": True})
        serialized = json.dumps(old, sort_keys=True)
        conn = self.store._get_connection()
        with conn:
            conn.execute("INSERT INTO instrument_source_assessments VALUES (?, ?, ?)",
                         (archive["archive_id"], old["policy_version"], serialized))
        self._blocked(archive_id=archive["archive_id"])
        retained = dict(conn.execute("SELECT policy_version,assessment_json FROM instrument_source_assessments"))
        self.assertEqual(retained[old["policy_version"]], serialized)
        current = json.loads(retained[POLICY_VERSION])
        self.assertFalse(current["historical_eligibility"]["allowed"])
        self.assertEqual(current["publisher_authenticity"]["supported_verification_mechanisms"], [])

    def test_capture_and_publication_claims_cannot_fill_a_missing_effective_date(self):
        for record in ({"valid_from": None, "valid_to": None}, {"valid_to": "2026-10-14"}):
            with self.subTest(record=record):
                payload = self._payload(record=record, effective_date_evidence={"verified": True,
                    "valid_from": "2026-10-01", "valid_to": "2026-10-31"})
                archive = self._ingest(payload, captured_at="2026-10-16T00:00:00+00:00",
                                       publisher_published_at="2026-10-01T00:00:00+00:00")
                self._blocked("HISTORICAL_ARCHIVE_COVERAGE_MISSING", archive_id=archive["archive_id"])
                self.assertEqual(self.store.qualify_instrument_master_archive(archive["archive_id"])
                                 ["effective_dates"]["independently_supported_intervals"], [])

    def test_exact_original_bytes_and_transformations_remain_distinct_without_granting_authenticity(self):
        payload = self._payload()
        originals = (json.dumps(payload, sort_keys=True).encode("utf-8"),
                     b"\xef\xbb\xbf" + json.dumps(payload, indent=2).replace("\n", "\r\n").encode("utf-8"))
        archives = [self._ingest(raw=raw) for raw in originals]
        self.assertNotEqual(archives[0]["archive_id"], archives[1]["archive_id"])
        self.assertEqual(archives[0]["normalized_sha256"], archives[1]["normalized_sha256"])
        for archive, raw in zip(archives, originals):
            retained = self.store.get_instrument_master_archive(archive["archive_id"], include_original=True)
            self.assertEqual(retained["original_bytes"], raw)
            self.assertEqual(retained["metadata"]["original_sha256"], hashlib.sha256(raw).hexdigest())
            assessment = self.store.qualify_instrument_master_archive(archive["archive_id"])
            self.assertEqual(assessment["content_integrity"]["status"], "MATCHES_RECORDED_DIGESTS")
            self.assertFalse(assessment["historical_eligibility"]["allowed"])

    def test_valid_historical_inputs_and_inspectable_declarations_do_not_release_replay_or_strategy3(self):
        bars = _fixtures.TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15")
        for provider in self.TOKENS:
            with self.subTest(provider=provider):
                archive = self._ingest(provider=provider)
                cfg = BotConfig(active_broker=provider, database_url=":memory:", telegram_dry_run=True,
                                enable_background_scheduler=False)
                report = evaluate_phase3a_backtest_readiness(cfg, self.store, target_data_mode="LIVE",
                    provider=provider, symbol="RELIANCE", execution_scope="HISTORICAL_RESEARCH", now=self.now,
                    candles=copy.deepcopy(bars), instrument_token=self.TOKENS[provider])
                self.assertTrue(report["execution_gate"]["allowed"])
                self.assertFalse(report["phase3_ready_for_execution"])
                self.assertFalse(report["historical_source_qualification"]["live_historical_replay_allowed"])
                engine = DeterministicBacktestEngine(cfg, self.store, clock=lambda: self.now)
                with patch.object(engine, "_invoke_strategy_evaluator") as evaluator, \
                     patch.object(self.store, "save_backtest_run") as writer:
                    with self.assertRaises(BacktestEligibilityError) as caught:
                        engine.run_backtest("strat_1_order_block", "RELIANCE", candles=copy.deepcopy(bars),
                            provider=provider, instrument_token=self.TOKENS[provider], data_mode="LIVE",
                            backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH",
                                historical_instrument_archive_id=archive["archive_id"]))
                    self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
                    with self.assertRaises(BacktestEligibilityError) as strategy3:
                        engine.run_backtest("strat_3_option_apex_oi", "RELIANCE", candles=copy.deepcopy(bars),
                            provider=provider, data_mode="LIVE")
                    self.assertEqual(strategy3.exception.details["reason_code"], "HISTORICAL_OPTION_EXECUTION_NOT_IMPLEMENTED")
                    evaluator.assert_not_called()
                    writer.assert_not_called()
                self.assertEqual(self.store.check_health()["backtest_runs_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

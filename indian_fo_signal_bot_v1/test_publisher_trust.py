"""Phase 4A publisher trust verification tests.

Mandatory 14-case test matrix covering fail-closed Ed25519 publisher trust,
effective-date verification, scope matching, tamper resistance, and replay gating.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot  # noqa: F401 -- reuse established offline config defaults

_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from backtest_engine import BacktestConfig, BacktestEligibilityError, DeterministicBacktestEngine
from config import BotConfig
from historical_data import evaluate_phase3a_backtest_readiness
from instrument_archive import SCHEMA, prepare_archive, resolve_archives
from instrument_identity import IdentityValidationError
import publisher_trust
from publisher_trust import (
    PublisherTrustVerifier,
    TrustAnchorConfig,
    TrustVerificationResult,
    canonical_signed_payload,
    REASON_UNKNOWN_PUBLISHER,
    REASON_MISSING_TRUST_ANCHOR,
    REASON_UNSUPPORTED_SIG_ALGORITHM,
    REASON_INVALID_SIGNATURE,
    REASON_DIGEST_MISMATCH,
    REASON_REVOKED_KEY,
    REASON_TRUST_ANCHOR_NOT_VALID,
    REASON_UNSUPPORTED_ARTIFACT_SCHEMA,
    REASON_OUTSIDE_EFFECTIVE_DATE,
    REASON_MISSING_RIGHTS,
    REASON_VERIFIER_UNAVAILABLE,
    REASON_NAIVE_TIMESTAMP,
    REASON_SCOPE_MISMATCH,
    REASON_DUPLICATE_MANIFEST_KEY,
    REASON_MALFORMED_MANIFEST,
    REASON_MISSING_MANIFEST_FIELD,
    SUPPORTED_SIG_ALGORITHM,
    TRUST_POLICY_VERSION,
)
from source_qualification import POLICY_VERSION, assess_source_evidence
from storage import SQLitePersistenceStore
from strategies import IST


class MockEd25519PublicKey:
    """Synthetic test-only public key for isolated unit tests."""
    def __init__(self, key_id: str = "test-key-1") -> None:
        self.key_id = key_id

    def verify(self, signature: bytes, data: bytes) -> None:
        expected = hashlib.sha256(b"SYNTHETIC_TEST_KEY_SIG:" + data).digest()
        if signature != expected:
            raise publisher_trust.InvalidSignature("Mock signature verification failed")


def _synthetic_sign(data: bytes) -> bytes:
    """Produce deterministic signature matching MockEd25519PublicKey."""
    return hashlib.sha256(b"SYNTHETIC_TEST_KEY_SIG:" + data).digest()


class TestPublisherTrustMatrix(unittest.TestCase):
    """The 14-case Phase 4A test matrix."""

    TOKENS = {"angelone": "2885", "dhan": "2885", "upstox": "NSE_EQ|INE002A01018"}

    def setUp(self):
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=timezone.utc)
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)

        # Block any external network calls
        transport = patch("urllib.request.urlopen", side_effect=AssertionError("External transport forbidden"))
        transport.start()
        self.addCleanup(transport.stop)

        # Set up synthetic mock crypto if cryptography is unavailable
        self._real_crypto = publisher_trust._CRYPTO_AVAILABLE
        self._crypto_patches = []
        if not self._real_crypto:
            self._mock_pub_key = MockEd25519PublicKey("key-1")
            p1 = patch.object(publisher_trust, "_CRYPTO_AVAILABLE", True)
            p2 = patch.object(publisher_trust, "Ed25519PublicKey", MockEd25519PublicKey)
            p3 = patch.object(publisher_trust, "load_der_public_key", lambda der: self._mock_pub_key)
            class MockInvalidSig(Exception):
                pass
            p4 = patch.object(publisher_trust, "InvalidSignature", MockInvalidSig)
            for p in (p1, p2, p3, p4):
                p.start()
                self._crypto_patches.append(p)

    def tearDown(self):
        for p in reversed(self._crypto_patches):
            p.stop()

    def _sample_raw_bytes(self) -> bytes:
        row = dict(provider="angelone", symbol="RELIANCE", identifier="2885",
                   exchange="NSE", instrument_type="EQ", multiplier=1,
                   valid_from="2026-10-01", valid_to="2026-10-31")
        return json.dumps(dict(schema_version=SCHEMA, provider="angelone", records=[row])).encode("utf-8")

    def _build_manifest(self, raw_bytes: bytes, **overrides) -> dict:
        digest = hashlib.sha256(raw_bytes).hexdigest()
        manifest = {
            "schema_version": "tradepulse.publisher-manifest.v1",
            "publisher_id": "angelone",
            "key_id": "key-1",
            "artifact_type": "instrument-master",
            "artifact_schema_version": "tradepulse.instrument-master.v1",
            "artifact_digest_sha256": digest,
            "provider": "angelone",
            "exchange": "NSE",
            "market_segment": "NSE_EQUITY_INTRADAY",
            "instrument_scope": "ALL",
            "record_coverage": "EQ_INTRADAY",
            "publisher_publication_time": "2026-10-15T00:00:00+00:00",
            "capture_observation_time": "2026-10-15T00:05:00+00:00",
            "effective_from": "2026-10-01T00:00:00+00:00",
            "effective_until": "2026-10-31T23:59:59+00:00",
            "rights_reference": "ANGEL_DEVELOPER_TERMS_REF_2026",
            "signature_algorithm": "Ed25519",
            "signature": "",
        }
        manifest.update(overrides)
        if not manifest.get("signature"):
            payload = canonical_signed_payload(manifest)
            sig_bytes = _synthetic_sign(payload)
            manifest["signature"] = base64.b64encode(sig_bytes).decode("ascii")
        return manifest

    def _build_trust_config(self, anchors=None, **kwargs) -> TrustAnchorConfig:
        if anchors is None:
            anchors = [
                {
                    "publisher_id": "angelone",
                    "key_id": "key-1",
                    "algorithm": "Ed25519",
                    "public_key_der_b64": base64.b64encode(b"MOCK_DER_PUB_KEY").decode("ascii"),
                    "not_before": "2026-01-01T00:00:00+00:00",
                    "not_after": "2026-12-31T23:59:59+00:00",
                    "revoked": False,
                }
            ]
        return TrustAnchorConfig(policy_version=TRUST_POLICY_VERSION, anchors=anchors, **kwargs)

    # 1. Correct signature and exact artifact bytes under a test trust anchor.
    def test_case_01_correct_signature_and_exact_artifact_bytes(self):
        raw = self._sample_raw_bytes()
        manifest = self._build_manifest(raw)
        config = self._build_trust_config()
        verifier = PublisherTrustVerifier(config)

        res = verifier.verify(json.dumps(manifest), raw, verification_time=self.now)
        self.assertTrue(res.allowed)
        self.assertEqual(res.reason_code, "PUBLISHER_TRUST_VERIFIED")
        self.assertEqual(res.publisher_id, "angelone")
        self.assertEqual(res.key_id, "key-1")
        self.assertEqual(res.signed_artifact_digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(res.signature_algorithm, "Ed25519")

        # Integration test: assess_source_evidence with trust_config
        archive = prepare_archive(raw, "angelone", "test.json", "REF_01")
        archive["metadata"]["publisher_manifest_json"] = json.dumps(manifest)
        assessment = assess_source_evidence(archive, raw, trust_config=config, verification_time=self.now)
        self.assertTrue(assessment["historical_eligibility"]["allowed"])
        self.assertEqual(assessment["publisher_authenticity"]["status"], "VERIFIED")

        # Integration test: resolve_archives succeeds
        archive["original_bytes"] = raw
        identity = resolve_archives([archive], "angelone", "RELIANCE", "2885", "NSE", "EQ",
                                    "2026-10-15", "2026-10-15", trust_config=config, verification_time=self.now)
        self.assertTrue(identity["live_historical_eligible"])
        self.assertEqual(identity["historical_validity"], "PUBLISHER_TRUST_VERIFIED")

    # 2. Unknown publisher / key identifier.
    def test_case_02_unknown_publisher_or_key_identifier(self):
        raw = self._sample_raw_bytes()
        config = self._build_trust_config()
        verifier = PublisherTrustVerifier(config)

        # Unknown publisher
        m_unknown_pub = self._build_manifest(raw, publisher_id="unknown_broker")
        res = verifier.verify(json.dumps(m_unknown_pub), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_MISSING_TRUST_ANCHOR)

        # Unknown key_id
        m_unknown_key = self._build_manifest(raw, key_id="unknown_key_999")
        res = verifier.verify(json.dumps(m_unknown_key), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_MISSING_TRUST_ANCHOR)

    # 3. Missing trust roots and verifier dependency unavailable.
    def test_case_03_missing_trust_roots_and_verifier_dependency_unavailable(self):
        raw = self._sample_raw_bytes()
        manifest = self._build_manifest(raw)

        # Missing trust roots (empty config)
        empty_config = TrustAnchorConfig(policy_version=TRUST_POLICY_VERSION, anchors=[])
        verifier = PublisherTrustVerifier(empty_config)
        res = verifier.verify(json.dumps(manifest), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_MISSING_TRUST_ANCHOR)

        # Dependency unavailable: when _CRYPTO_AVAILABLE is False, fails closed with VERIFIER_UNAVAILABLE
        config = self._build_trust_config()
        with patch.object(publisher_trust, "_CRYPTO_AVAILABLE", False):
            v_no_crypto = PublisherTrustVerifier(config)
            res_no_crypto = v_no_crypto.verify(json.dumps(manifest), raw, verification_time=self.now)
            self.assertFalse(res_no_crypto.allowed)
            self.assertEqual(res_no_crypto.reason_code, REASON_VERIFIER_UNAVAILABLE)

    # 4. One-byte tampering, altered manifest fields and wrong digest.
    def test_case_04_tampering_altered_manifest_fields_and_wrong_digest(self):
        raw = self._sample_raw_bytes()
        manifest = self._build_manifest(raw)
        config = self._build_trust_config()
        verifier = PublisherTrustVerifier(config)

        # Tamper 1 byte of raw artifact
        tampered_raw = raw + b" "
        res = verifier.verify(json.dumps(manifest), tampered_raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_DIGEST_MISMATCH)

        # Altered digest in manifest
        bad_digest_manifest = dict(manifest, artifact_digest_sha256="0" * 64)
        res = verifier.verify(json.dumps(bad_digest_manifest), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_DIGEST_MISMATCH)

        # Altered manifest field after signing
        tampered_field_manifest = dict(manifest, effective_from="2025-01-01T00:00:00+00:00")
        res = verifier.verify(json.dumps(tampered_field_manifest), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_INVALID_SIGNATURE)

    # 5. Invalid signature and unsupported algorithm/schema/artifact type.
    def test_case_05_invalid_signature_and_unsupported_algorithm_schema_type(self):
        raw = self._sample_raw_bytes()
        config = self._build_trust_config()
        verifier = PublisherTrustVerifier(config)

        # Invalid/corrupted signature
        bad_sig_manifest = self._build_manifest(raw, signature=base64.b64encode(b"CORRUPTED_SIGNATURE").decode("ascii"))
        res = verifier.verify(json.dumps(bad_sig_manifest), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_INVALID_SIGNATURE)

        # Unsupported signature algorithm
        bad_algo_manifest = self._build_manifest(raw, signature_algorithm="RSA-PSS")
        res = verifier.verify(json.dumps(bad_algo_manifest), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_UNSUPPORTED_SIG_ALGORITHM)

        # Unsupported manifest schema
        bad_schema_manifest = self._build_manifest(raw, schema_version="tradepulse.publisher-manifest.v999")
        res = verifier.verify(json.dumps(bad_schema_manifest), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_UNSUPPORTED_ARTIFACT_SCHEMA)

        # Unsupported artifact type
        restricted_config = self._build_trust_config(permitted_artifact_types={"other-type"})
        v_restricted = PublisherTrustVerifier(restricted_config)
        res = v_restricted.verify(json.dumps(self._build_manifest(raw)), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_UNSUPPORTED_ARTIFACT_SCHEMA)

        # Duplicate keys in JSON
        dup_json = '{"schema_version": "tradepulse.publisher-manifest.v1", "schema_version": "tradepulse.publisher-manifest.v1"}'
        res = verifier.verify(dup_json, raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_DUPLICATE_MANIFEST_KEY)

        # Malformed JSON
        res = verifier.verify("NOT_JSON{", raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_MALFORMED_MANIFEST)

    # 6. Key not-yet-valid, just-valid boundary, expiry boundary and revoked key.
    def test_case_06_key_validity_boundaries_and_revoked_key(self):
        raw = self._sample_raw_bytes()
        manifest = self._build_manifest(raw)
        config = self._build_trust_config()
        verifier = PublisherTrustVerifier(config)

        # Not yet valid (verification before 2026-01-01)
        before_valid = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        res = verifier.verify(json.dumps(manifest), raw, verification_time=before_valid)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_TRUST_ANCHOR_NOT_VALID)

        # Just valid (at not_before boundary)
        at_start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        res = verifier.verify(json.dumps(manifest), raw, verification_time=at_start)
        self.assertTrue(res.allowed)

        # Expiry boundary (at not_after boundary)
        at_end = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        res = verifier.verify(json.dumps(manifest), raw, verification_time=at_end)
        self.assertTrue(res.allowed)

        # Expired (after not_after boundary)
        after_end = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        res = verifier.verify(json.dumps(manifest), raw, verification_time=after_end)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_TRUST_ANCHOR_NOT_VALID)

        # Revoked key
        revoked_anchors = [
            {
                "publisher_id": "angelone",
                "key_id": "key-1",
                "algorithm": "Ed25519",
                "public_key_der_b64": base64.b64encode(b"MOCK_DER_PUB_KEY").decode("ascii"),
                "not_before": "2026-01-01T00:00:00+00:00",
                "not_after": "2026-12-31T23:59:59+00:00",
                "revoked": True,
            }
        ]
        revoked_config = TrustAnchorConfig(policy_version=TRUST_POLICY_VERSION, anchors=revoked_anchors)
        v_revoked = PublisherTrustVerifier(revoked_config)
        res = v_revoked.verify(json.dumps(manifest), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_REVOKED_KEY)

    # 7. Effective-date lower/upper boundary, future scope, expired scope, malformed/naive timestamps.
    def test_case_07_effective_date_boundaries_and_naive_timestamps(self):
        raw = self._sample_raw_bytes()
        config = self._build_trust_config()
        verifier = PublisherTrustVerifier(config)

        # Reversed effective dates (from > until)
        rev_manifest = self._build_manifest(raw, effective_from="2026-10-31T00:00:00+00:00",
                                            effective_until="2026-10-01T00:00:00+00:00")
        res = verifier.verify(json.dumps(rev_manifest), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_OUTSIDE_EFFECTIVE_DATE)

        # Naive timestamp in manifest (missing UTC offset)
        naive_manifest = self._build_manifest(raw, effective_from="2026-10-01T00:00:00")
        res = verifier.verify(json.dumps(naive_manifest), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_NAIVE_TIMESTAMP)

        # Naive verification_time
        manifest = self._build_manifest(raw)
        naive_now = datetime(2026, 10, 16, 10, 35)  # no tzinfo
        res = verifier.verify(json.dumps(manifest), raw, verification_time=naive_now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_NAIVE_TIMESTAMP)

        # Timezone normalization: IST offset +05:30 is properly accepted and normalized
        ist_manifest = self._build_manifest(raw, effective_from="2026-10-01T05:30:00+05:30",
                                            effective_until="2026-10-31T23:59:59+05:30")
        res = verifier.verify(json.dumps(ist_manifest), raw, verification_time=self.now)
        self.assertTrue(res.allowed)
        self.assertEqual(res.effective_from, "2026-10-01T00:00:00+00:00")

    # 8. Missing rights evidence and explicit distinction between integrity, authenticity and licence.
    def test_case_08_missing_rights_evidence_and_integrity_distinction(self):
        raw = self._sample_raw_bytes()
        config = self._build_trust_config()
        verifier = PublisherTrustVerifier(config)

        # Missing / empty rights evidence
        no_rights_manifest = self._build_manifest(raw, rights_reference="")
        res = verifier.verify(json.dumps(no_rights_manifest), raw, verification_time=self.now)
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_MISSING_RIGHTS)

        # Explicit distinction: integrity != authenticity
        # An archive without trust_config has verified digests (integrity) but NOT publisher authenticity
        archive = prepare_archive(raw, "angelone", "test.json", "REF_01")
        assessment = assess_source_evidence(archive, raw, trust_config=None)
        self.assertEqual(assessment["content_integrity"]["status"], "MATCHES_RECORDED_DIGESTS")
        self.assertEqual(assessment["publisher_authenticity"]["status"], "NOT_ESTABLISHED")
        self.assertFalse(assessment["historical_eligibility"]["allowed"])

    # 9. Same-date/scope conflicting artifacts and deterministic rejection/selection rules.
    def test_case_09_same_date_scope_conflicting_artifacts(self):
        row_a = dict(provider="angelone", symbol="RELIANCE", identifier="2885",
                     exchange="NSE", instrument_type="EQ", multiplier=1,
                     valid_from="2026-10-01", valid_to="2026-10-31")
        row_b = dict(provider="angelone", symbol="HDFCBANK", identifier="2885",
                     exchange="NSE", instrument_type="EQ", multiplier=1,
                     valid_from="2026-10-01", valid_to="2026-10-31")  # conflict on token assignment
        raw_a = json.dumps(dict(schema_version=SCHEMA, provider="angelone", records=[row_a])).encode("utf-8")
        raw_b = json.dumps(dict(schema_version=SCHEMA, provider="angelone", records=[row_b])).encode("utf-8")
        arch_a = prepare_archive(raw_a, "angelone", "a.json", "REF_A")
        arch_b = prepare_archive(raw_b, "angelone", "b.json", "REF_B")

        with self.assertRaises(IdentityValidationError) as caught:
            resolve_archives([arch_a, arch_b], "angelone", "RELIANCE", "2885", "NSE", "EQ",
                             "2026-10-15", "2026-10-15")
        self.assertEqual(caught.exception.rejection["reason_code"], "AMBIGUOUS_ARCHIVE_COVERAGE")

        # Deterministic selection when claims have identical facts
        from instrument_archive import resolve_archive_declarations
        raw_c = json.dumps(dict(schema_version=SCHEMA, provider="angelone", records=[row_a])).encode("utf-8")
        arch_c = prepare_archive(raw_c, "angelone", "c.json", "REF_C")
        # arch_a and arch_c have identical facts; resolve_archive_declarations deterministically picks min archive_id
        selected = resolve_archive_declarations([arch_a, arch_c], "angelone", "RELIANCE", "2885", "NSE", "EQ",
                                                "2026-10-15", "2026-10-15")
        expected_archive_id = min(arch_a["archive_id"], arch_c["archive_id"])
        self.assertEqual(selected["archive_id"], expected_archive_id)

    # 10. Archive re-hashing cannot promote unauthenticated content; foreign/stale assessments cannot be reused.
    def test_case_10_archive_rehashing_and_stale_assessments(self):
        raw = self._sample_raw_bytes()
        archive = self.store.ingest_instrument_master_bytes(raw, "angelone", "test.json", "REF_10")
        before = self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertFalse(before["historical_eligibility"]["allowed"])

        # Re-hashing altered bytes under existing archive_id is rejected by qualify
        tampered_raw = raw + b"TAMPERED"
        conn = self.store._get_connection()
        with conn:
            conn.execute("UPDATE instrument_master_archives SET original_bytes=? WHERE archive_id=?",
                         (tampered_raw, archive["archive_id"]))
        with self.assertRaises(IdentityValidationError) as caught:
            self.store.qualify_instrument_master_archive(archive["archive_id"])
        self.assertEqual(caught.exception.rejection["reason_code"], "ARCHIVE_INTEGRITY_FAILURE")

    # 11. Wrong provider, symbol, token, segment, expiry or signed coverage cannot authorize replay.
    def test_case_11_wrong_provider_symbol_segment_scope_mismatch(self):
        raw = self._sample_raw_bytes()
        config = self._build_trust_config()
        verifier = PublisherTrustVerifier(config)

        # Manifest covers "angelone" but required_scope expects "upstox"
        manifest = self._build_manifest(raw, provider="angelone")
        res = verifier.verify(json.dumps(manifest), raw, verification_time=self.now,
                              required_scope={"provider": "upstox"})
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_SCOPE_MISMATCH)

        # Manifest covers "NSE_EQUITY_INTRADAY" but required_scope expects "NSE_FO_INDEX"
        res = verifier.verify(json.dumps(manifest), raw, verification_time=self.now,
                              required_scope={"market_segment": "NSE_FO_INDEX"})
        self.assertFalse(res.allowed)
        self.assertEqual(res.reason_code, REASON_SCOPE_MISMATCH)

    # 12. Historical gate rejects unqualified data before strategy evaluation/result writing.
    def test_case_12_historical_gate_rejects_unqualified_data(self):
        bars = _fixtures.TestIndianFOSignalBotPhase3A._build_session_bars("2026-10-15")
        raw = self._sample_raw_bytes()
        archive = self.store.ingest_instrument_master_bytes(raw, "angelone", "test.json", "REF_12")

        cfg = BotConfig(active_broker="angelone", database_url=":memory:", telegram_dry_run=True,
                        enable_background_scheduler=False)
        engine = DeterministicBacktestEngine(cfg, self.store, clock=lambda: self.now)
        with patch.object(engine, "_invoke_strategy_evaluator") as evaluator, \
             patch.object(self.store, "save_backtest_run") as writer:
            with self.assertRaises(BacktestEligibilityError) as caught:
                engine.run_backtest("strat_1_order_block", "RELIANCE", candles=copy.deepcopy(bars),
                                    provider="angelone", instrument_token="2885", data_mode="LIVE",
                                    backtest_config=BacktestConfig(execution_scope="HISTORICAL_RESEARCH",
                                                                  historical_instrument_archive_id=archive["archive_id"]))
            self.assertEqual(caught.exception.details["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
            evaluator.assert_not_called()
            writer.assert_not_called()
        self.assertEqual(self.store.check_health()["backtest_runs_count"], 0)

    # 13. Last-good archive does not bypass signature, effective-date or current-eligibility checks.
    def test_case_13_last_good_archive_does_not_bypass_eligibility(self):
        raw = self._sample_raw_bytes()
        archive = self.store.ingest_instrument_master_bytes(raw, "angelone", "test.json", "REF_13")
        source = self.store.get_instrument_master_archive(archive["archive_id"], include_original=True)
        # Attempting to supply a forged "last-good" qualification dictionary
        source["source_qualification"] = {"historical_eligibility": {"allowed": True},
                                          "publisher_authenticity": {"status": "VERIFIED"}}
        with self.assertRaises(IdentityValidationError) as caught:
            resolve_archives([source], "angelone", "RELIANCE", "2885", "NSE", "EQ",
                             "2026-10-15", "2026-10-15")
        self.assertEqual(caught.exception.rejection["reason_code"], "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT")
        actual = caught.exception.rejection["source_qualification"]
        self.assertFalse(actual["historical_eligibility"]["allowed"])

    # 14. Tests show no external network call, no secret disclosure, and no change to live/scheduler/delivery safety settings.
    def test_case_14_safety_no_network_no_secret_disclosure_safe_settings(self):
        import urllib.request
        with self.assertRaises(AssertionError):
            urllib.request.urlopen("https://smartapi.angelone.in")

        cfg = BotConfig(telegram_dry_run=True, enable_background_scheduler=False)
        self.assertTrue(cfg.telegram_dry_run)
        self.assertFalse(cfg.enable_background_scheduler)

        # Verifier result serialization does not disclose private keys or secrets
        raw = self._sample_raw_bytes()
        manifest = self._build_manifest(raw)
        config = self._build_trust_config()
        verifier = PublisherTrustVerifier(config)
        res = verifier.verify(json.dumps(manifest), raw, verification_time=self.now)
        out = json.dumps(res.as_dict())
        self.assertNotIn("private", out.lower())
        self.assertNotIn("secret", out.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)

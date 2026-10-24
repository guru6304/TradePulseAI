"""Authored context + synthetic keys exercise offline software, not source rights."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest
from unittest.mock import patch

import test_bot
from config import BotConfig
from candle_lineage import digest
from instrument_identity import spot_identity
from publisher_trust import TrustAnchorConfig, TRUST_POLICY_VERSION, _generate_test_manifest
from test_publisher_trust import test_key_pair
from context_data import (ContextSourcePolicy, ContextValidationError, SOURCE_SCHEMA,
    context_for_candidate, parse_context_bytes, safe_source_url, validate_ingestion)


class TestContextData(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
        cfg = BotConfig()
        self.identity = spot_identity(next(m for m in cfg.equity_watchlist if m["symbol"] == "RELIANCE"), "angelone")
        self.other = spot_identity(next(m for m in cfg.equity_watchlist if m["symbol"] == "SBIN"), "angelone")
        self.row = dict(source_id="offline_issuer", source_name="Offline authored fixture",
            source_url="https://issuer.example/notice/123", source_record_ref="notice-123",
            original_ref="https://issuer.example/notice/123", published_at="2026-10-23T08:00:00+00:00",
            event_at="2026-10-23T08:30:00+00:00", instrument_identity=self.identity,
            title="Authored fixture notice", summary="No real company fact or sentiment is asserted.")
        self.candidate = dict(candidate_id="candidate-1", status="REJECTED", actionable=False,
            reason_codes=["INSUFFICIENT_COMPLETED_CANDLES"], risk_reward={"allowed": False},
            source_reference=dict(instrument_identity=self.identity))
        guard = patch("socket.socket.connect", side_effect=AssertionError("Context is offline only"))
        guard.start()
        self.addCleanup(guard.stop)

    def raw(self, rows=None):
        return json.dumps(dict(schema_version=SOURCE_SCHEMA, records=rows if rows is not None else [self.row]),
                          sort_keys=True, separators=(",", ":")).encode()

    def parse(self, raw=None, **overrides):
        kwargs = dict(provider="offline_notices", collected_at=self.now.isoformat(),
                      trusted_identities=[self.identity])
        kwargs.update(overrides)
        return parse_context_bytes(self.raw() if raw is None else raw, **kwargs)

    def policy(self, raw, **changes):
        private, public = test_key_pair()
        from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
        private_seed = base64.b64encode(private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
        anchor = dict(publisher_id="offline_issuer", key_id="offline-test-key", algorithm="Ed25519",
            public_key_der_b64=base64.b64encode(public).decode(), not_before="2026-01-01T00:00:00+00:00",
            not_after="2027-01-01T00:00:00+00:00", revoked=False)
        anchor.update(changes.pop("anchor", {}))
        trust = TrustAnchorConfig(TRUST_POLICY_VERSION, [anchor],
            permitted_artifact_types={"context-records"}, permitted_providers={"offline_notices"})
        manifest_args = dict(artifact_bytes=raw, publisher_id="offline_issuer", key_id="offline-test-key",
            private_key_der_b64=private_seed, effective_from="2026-10-01T00:00:00+00:00",
            effective_until="2026-11-01T00:00:00+00:00", provider="offline_notices", instrument_scope="RELIANCE",
            artifact_type="context-records", artifact_schema_version=SOURCE_SCHEMA,
            capture_time="2026-10-23T09:00:00+00:00", pub_time="2026-10-23T08:00:00+00:00",
            rights_reference="OFFLINE_TEST_APPROVAL_NO_REAL_RIGHTS")
        manifest_args.update(changes)
        manifest = _generate_test_manifest(**manifest_args)
        return ContextSourcePolicy(trust_config=trust, approvals={"offline_issuer": dict(provider="offline_notices",
            source_name="Offline authored fixture", domains=["issuer.example"],
            authority_reference="OFFLINE_TEST_AUTHORITY_NO_REAL_PUBLISHER",
            rights_reference="OFFLINE_TEST_APPROVAL_NO_REAL_RIGHTS")},
            manifests_by_sha256={hashlib.sha256(raw).hexdigest(): manifest})

    def test_default_is_unverified_even_if_artifact_claims_qualification(self):
        self.row.update(verified=True, rights="approved", source_policy={"allowed": True},
                        verification={"allowed": True})
        result = self.parse()
        self.assertEqual(result["status"], "WARNING_ONLY")
        row = result["records"][0]
        self.assertFalse(row["verification"]["allowed"])
        self.assertEqual(row["verification"]["authority"], "NOT_ESTABLISHED")
        self.assertTrue(validate_ingestion(result, self.raw(), trusted_identities=[self.identity]))

    def test_real_signature_and_separate_local_policy_qualify_only_informationally(self):
        raw = self.raw()
        policy = self.policy(raw)
        ingestion = self.parse(raw, source_policy=policy)
        self.assertEqual(ingestion["status"], "QUALIFIED")
        row = ingestion["records"][0]
        self.assertEqual(row["verification"]["status"], "QUALIFIED_UNDER_LOCAL_POLICY")
        self.assertFalse(row["verification"]["independent_rights_established"])
        context = context_for_candidate(ingestion["records"], self.candidate, as_of=self.now.isoformat())
        self.assertEqual(context["status"], "QUALIFIED")
        self.assertFalse(context["actionable"])
        self.assertFalse(context["affects_ranking"])
        self.assertTrue(validate_ingestion(ingestion, raw, trusted_identities=[self.identity], source_policy=policy))

    def test_policy_signature_tamper_revocation_scope_and_rights_fail_closed(self):
        raw = self.raw()
        for changes in ({"anchor": {"revoked": True}}, {"instrument_scope": "SBIN"},
                        {"rights_reference": "DIFFERENT_RIGHTS"}, {"artifact_schema_version": "other"}):
            with self.subTest(changes=changes):
                row = self.parse(raw, source_policy=self.policy(raw, **changes))["records"][0]
                self.assertFalse(row["verification"]["allowed"])
        policy = self.policy(raw)
        self.row["title"] = "Changed bytes"
        self.assertFalse(self.parse(source_policy=policy)["records"][0]["verification"]["allowed"])

    def test_policy_cannot_be_supplied_as_payload_or_dictionary(self):
        with self.assertRaisesRegex(ContextValidationError, "INVALID_SOURCE_POLICY"):
            self.parse(source_policy={"allowed": True})

    def test_missing_local_source_approval_does_not_borrow_valid_signature(self):
        raw = self.raw()
        policy = self.policy(raw)
        policy._approvals.clear()
        self.assertFalse(self.parse(raw, source_policy=policy)["records"][0]["verification"]["allowed"])

    def test_signature_backend_unavailable_never_falls_back(self):
        raw = self.raw()
        policy = self.policy(raw)
        with patch("publisher_trust._CRYPTO_AVAILABLE", False):
            record = self.parse(raw, source_policy=policy)["records"][0]
        self.assertFalse(record["verification"]["allowed"])

    def test_signed_date_coverage_cannot_borrow_out_of_scope_source_times(self):
        raw = self.raw()
        policy = self.policy(raw, effective_from="2026-10-23T09:00:00+00:00")
        record = self.parse(raw, source_policy=policy)["records"][0]
        self.assertFalse(record["verification"]["allowed"])
        self.assertEqual(record["verification"]["reason_code"], "CONTEXT_SIGNED_TIME_COVERAGE_MISMATCH")

    def test_exact_canonical_mapping_and_cross_provider_or_company_reject_matching(self):
        wrong = copy.deepcopy(self.row)
        wrong["instrument_identity"] = self.other
        ingestion = self.parse(self.raw([wrong]))
        self.assertIn("CONTEXT_MAPPING_UNAVAILABLE", ingestion["reason_codes"])
        self.assertEqual(context_for_candidate(ingestion["records"], self.candidate,
            as_of=self.now.isoformat())["status"], "MISSING")
        cfg = BotConfig()
        upstox = spot_identity(next(m for m in cfg.equity_watchlist if m["symbol"] == "RELIANCE"), "upstox")
        wrong["instrument_identity"] = upstox
        self.assertEqual(context_for_candidate(self.parse(self.raw([wrong]))["records"], self.candidate,
            as_of=self.now.isoformat())["records"], [])

    def test_trusted_mapping_cannot_redefine_pinned_identifier(self):
        wrong = copy.deepcopy(self.identity)
        wrong["identifier"] = "99999"
        with self.assertRaises(ContextValidationError):
            self.parse(trusted_identities=[wrong])
        with self.assertRaisesRegex(ContextValidationError, "AMBIGUOUS_MAPPING"):
            self.parse(trusted_identities=[self.identity, self.identity])

    def test_logical_and_content_dedup_do_not_change_on_recollection(self):
        first = self.parse()
        later = self.parse(collected_at=(self.now + timedelta(minutes=1)).isoformat())
        self.assertNotEqual(first["ingestion_id"], later["ingestion_id"])
        for field in ("record_id", "content_id"):
            self.assertEqual(first["records"][0][field], later["records"][0][field])
        duplicate = self.parse(self.raw([self.row, self.row]))
        self.assertEqual(len(duplicate["records"]), 1)
        records = first["records"] + later["records"]
        a = context_for_candidate(records, self.candidate, as_of=later["collected_at"])
        b = context_for_candidate(list(reversed(records)), self.candidate, as_of=later["collected_at"])
        self.assertEqual(a, b)
        self.assertEqual(len(a["records"]), 1)

    def test_conflicting_facts_same_logical_source_remain_warning(self):
        changed = dict(self.row, title="Conflicting authored notice")
        ingestion = self.parse(self.raw([self.row, changed]))
        self.assertEqual(len(ingestion["records"]), 2)
        self.assertIn("CONTEXT_CONFLICTING", ingestion["reason_codes"])
        self.assertTrue(validate_ingestion(ingestion, self.raw([self.row, changed]), trusted_identities=[self.identity]))
        context = context_for_candidate(ingestion["records"], self.candidate, as_of=self.now.isoformat())
        self.assertEqual(context["status"], "WARNING_ONLY")
        self.assertIn("CONTEXT_CONFLICTING", context["reason_codes"])

    def test_cross_import_conflict_is_independent_of_input_order(self):
        first = self.parse()["records"]
        self.row["summary"] = "Different source fact, no invented correction policy."
        second = self.parse()["records"]
        a = context_for_candidate(first + second, self.candidate, as_of=self.now.isoformat())
        b = context_for_candidate(second + first, self.candidate, as_of=self.now.isoformat())
        self.assertEqual(a, b)
        self.assertIn("CONTEXT_CONFLICTING", a["reason_codes"])

    def test_retraction_and_correction_are_retained_without_rewriting_source(self):
        self.row.update(retracted=True, correction="Source withdrew this authored fixture.")
        ingestion = self.parse()
        self.assertIn("CONTEXT_RETRACTED", ingestion["reason_codes"])
        self.assertEqual(ingestion["records"][0]["correction"], self.row["correction"])

    def test_staleness_is_derived_at_requested_time(self):
        ingestion = self.parse()
        later = (self.now + timedelta(days=2)).isoformat()
        context = context_for_candidate(ingestion["records"], self.candidate, as_of=later)
        self.assertIn("CONTEXT_STALE", context["reason_codes"])
        self.assertEqual(context["records"][0]["freshness"]["status"], "STALE")

    def test_missing_timestamps_remain_missing_and_unavailable_for_qualification(self):
        self.row.pop("published_at")
        self.row.pop("event_at")
        record = self.parse()["records"][0]
        self.assertIsNone(record["published_at"])
        self.assertIsNone(record["event_at"])
        self.assertEqual(record["freshness"]["status"], "UNAVAILABLE")
        context = context_for_candidate([record], self.candidate, as_of=self.now.isoformat())
        self.assertIn("CONTEXT_PUBLISHED_AT_MISSING", context["reason_codes"])

    def test_no_lookahead_includes_collection_and_withholds_future_text_entirely(self):
        ingestion = self.parse()
        for cutoff in ("2026-10-23T07:59:00+00:00", "2026-10-23T08:15:00+00:00",
                       "2026-10-23T09:59:00+00:00"):
            context = context_for_candidate(ingestion["records"], self.candidate, as_of=cutoff)
            self.assertEqual(context["records"], [])
            self.assertEqual(context["status"], "UNAVAILABLE")
            self.assertNotIn(self.row["title"], json.dumps(context))

    def test_future_reversed_and_naive_timestamps_fail_without_inventing_values(self):
        for field in ("published_at", "event_at"):
            for value in ("2026-10-24T10:00:00+00:00", "2026-10-23T08:00:00", "bad"):
                row = dict(self.row, **{field: value})
                with self.subTest(field=field, value=value), self.assertRaises(ContextValidationError):
                    self.parse(self.raw([row]))
        with self.assertRaises(ContextValidationError):
            self.parse(collected_at="2026-10-23T10:00:00")

    def test_untrusted_interpretation_requires_rule_and_is_not_inferred_sentiment(self):
        self.assertIsNone(self.parse()["records"][0]["interpretation"])
        self.row["interpretation"] = dict(rule_id="source.claim.v1", text="Authored source interpretation")
        interpretation = self.parse()["records"][0]["interpretation"]
        self.assertEqual(interpretation["status"], "SOURCE_SUPPLIED_UNVALIDATED_INTERPRETATION")
        self.row["interpretation"].pop("rule_id")
        with self.assertRaises(ContextValidationError):
            self.parse()

    def test_candidate_and_original_records_are_never_mutated(self):
        records = self.parse()["records"]
        original = copy.deepcopy((records, self.candidate))
        context = context_for_candidate(records, self.candidate, as_of=self.now.isoformat())
        self.assertEqual((records, self.candidate), original)
        self.assertFalse(context["actionable"])
        self.assertFalse(context["affects_ranking"])
        self.assertEqual(self.candidate["status"], "REJECTED")

    def test_empty_records_and_missing_candidate_identity_are_explicit(self):
        self.assertEqual(self.parse(self.raw([]))["status"], "MISSING")
        missing = context_for_candidate([], self.candidate, as_of=self.now.isoformat())
        self.assertEqual(missing["reason_codes"], ["CONTEXT_MISSING"])
        context = context_for_candidate([], dict(candidate_id="old-candidate"), as_of=self.now.isoformat())
        self.assertEqual(context["status"], "UNAVAILABLE")

    def test_json_bounds_duplicate_keys_nonfinite_malformed_and_unsafe_links(self):
        for raw in (b'{"records":[],"records":[]}', b'{"records":[],"x":NaN}', b'[]', b'not-json',
                    b'\xff', b'{"records":[],"x":Infinity}', b'{"records":[],"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ContextValidationError):
                self.parse(raw)
        with patch("context_data.MAX_BYTES", 2), self.assertRaises(ContextValidationError):
            self.parse()
        with self.assertRaises(ContextValidationError):
            self.parse(self.raw([self.row] * 101))
        for url in ("javascript:alert(1)", "http://issuer.example", "https://user:pass@issuer.example", "https://localhost/a",
                    "https://127.0.0.1/a", "https://10.0.0.1", "https://[::1]/", "https://issuer.example:123/a",
                    "https://issuer.example\\@evil.example", "https://evil%2eexample/", "https://issuer.local"):
            with self.subTest(url=url), self.assertRaises(ContextValidationError):
                safe_source_url(url)

    def test_record_or_ingestion_rehash_cannot_replace_original_facts(self):
        ingestion = self.parse()
        ingestion["records"][0]["title"] = "Changed persisted fact"
        ingestion["records"][0]["content_id"] = digest("forged")
        with self.assertRaisesRegex(ContextValidationError, "INGESTION_INTEGRITY"):
            validate_ingestion(ingestion, self.raw(), trusted_identities=[self.identity])
        ingestion = self.parse()
        ingestion["records"][0]["verification"].update(allowed=True, status="QUALIFIED_UNDER_LOCAL_POLICY")
        with self.assertRaisesRegex(ContextValidationError, "INGESTION_INTEGRITY"):
            validate_ingestion(ingestion, self.raw(), trusted_identities=[self.identity])

    def test_content_integrity_is_checked_even_if_conflict_flag_is_true(self):
        row = self.parse()["records"][0]
        row.update(title="Substituted fact", conflict=True)
        with self.assertRaisesRegex(ContextValidationError, "RECORD_INTEGRITY"):
            context_for_candidate([row], self.candidate, as_of=self.now.isoformat())

    def test_ingestion_id_exact_contract_and_policy_fingerprint(self):
        raw = self.raw()
        a = self.parse(raw)
        self.assertEqual(a["ingestion_id"], digest(["context-ingestion-v1", a["provider"],
            a["collected_at"], hashlib.sha256(raw).hexdigest(), "NO_POLICY", a["mapping_id"]]))
        policy = self.policy(raw)
        b = self.parse(raw, source_policy=policy)
        self.assertNotEqual(a["ingestion_id"], b["ingestion_id"])
        self.assertEqual(b["policy_id"], policy.policy_id)

    def test_revalidation_binds_external_mapping_and_requires_original_policy(self):
        raw = self.raw()
        ingestion = self.parse(raw)
        with self.assertRaisesRegex(ContextValidationError, "INGESTION_INTEGRITY"):
            validate_ingestion(ingestion, raw, trusted_identities=[self.other])
        policy = self.policy(raw)
        qualified = self.parse(raw, source_policy=policy)
        with self.assertRaisesRegex(ContextValidationError, "INGESTION_INTEGRITY"):
            validate_ingestion(qualified, raw, trusted_identities=[self.identity])
        # A rehashed policy label cannot turn a default-policy receipt into trust.
        ingestion["policy_id"] = "a" * 64
        ingestion["ingestion_id"] = digest(["context-ingestion-v1", ingestion["provider"],
            ingestion["collected_at"], ingestion["original_sha256"], ingestion["policy_id"], ingestion["mapping_id"]])
        with self.assertRaisesRegex(ContextValidationError, "INGESTION_INTEGRITY"):
            validate_ingestion(ingestion, raw, trusted_identities=[self.identity])

    def test_new_artifact_proof_keeps_policy_identity_but_approval_changes_do_not(self):
        original_raw = self.raw()
        policy = self.policy(original_raw)
        original = self.parse(original_raw, source_policy=policy)
        self.row["source_record_ref"] = "new-notice-456"
        self.row["title"] = "Another independently signed offline fixture"
        new_raw = self.raw()
        later_policy = self.policy(new_raw)
        later_policy._manifests.update(policy._manifests)
        self.assertEqual(policy.policy_id, later_policy.policy_id)
        self.assertTrue(validate_ingestion(original, original_raw,
            trusted_identities=[self.identity], source_policy=later_policy))
        self.assertEqual(self.parse(new_raw, source_policy=later_policy)["status"], "QUALIFIED")
        later_policy._approvals["offline_issuer"]["authority_reference"] = "CHANGED_LOCAL_APPROVAL"
        self.assertNotEqual(policy.policy_id, later_policy.policy_id)
        with self.assertRaisesRegex(ContextValidationError, "INGESTION_INTEGRITY"):
            validate_ingestion(original, original_raw, trusted_identities=[self.identity], source_policy=later_policy)

    def test_matching_parameters_and_source_content_limits_are_bounded(self):
        for max_age in (True, 0, -1, 31 * 86400 + 1):
            with self.assertRaises(ContextValidationError):
                context_for_candidate([], self.candidate, as_of=self.now.isoformat(), max_age_seconds=max_age)
        self.row["summary"] = "x" * 8193
        with self.assertRaises(ContextValidationError):
            self.parse()


if __name__ == "__main__":
    unittest.main()

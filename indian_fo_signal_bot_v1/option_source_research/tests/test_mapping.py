"""Independent D2 synthetic join/authority boundaries; never provider captures."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import unittest
from unittest.mock import patch

from option_intelligence.context import DELTA_UNIT, GAMMA_UNIT, THETA_YEAR_UNIT, VEGA_POINT_UNIT
from option_intelligence.evidence import digest
from option_source_research.fixtures import DECISION, synthetic_fixture
from option_source_research.mapping import MappingResult, map_synthetic_fixture


FLAGS = ("source_qualified", "prospective_ready", "forward_entry_allowed", "actionable",
         "execution_allowed", "historical_replay_allowed", "activation_allowed")


def rehash(bundle):
    source = bundle["source"]
    source["source_sha256"] = digest({key: value for key, value in source.items() if key != "source_sha256"})
    return bundle


def mapping(bundle, target):
    return next(row for row in bundle["mapping"] if row["target_path"] == target)


def evidence(bundle, requirement):
    return next(row for row in bundle["evidence"] if row["requirement"] == requirement)


def optional_context(bundle):
    contract = bundle["source"]["master"]
    quote = bundle["source"]["quote"]
    return dict(contract_id=quote["contract_id"], provider=contract["provider"],
        source_revision=contract["source_revision"], source_id="AUTHORED_D2_OPTIONAL",
        observed_at=quote["observed_at"], received_at=quote["received_at"], available_at=DECISION,
        fields=dict(iv="20", delta=".5", gamma=".002", vega="9.5", theta="-1241", oi=0),
        units=dict(iv="PERCENT", delta=DELTA_UNIT, gamma=GAMMA_UNIT,
                   vega=VEGA_POINT_UNIT, theta=THETA_YEAR_UNIT, oi="CONTRACTS"),
        theta_calendar_basis=365)


class TestSyntheticOptionSourceMapping(unittest.TestCase):
    def mapped(self, bundle=None):
        return map_synthetic_fixture(bundle if bundle is not None else synthetic_fixture(), enabled=True)

    def assertBlocked(self, bundle, state, code=None):
        result = self.mapped(bundle)
        self.assertEqual(state, result.state, result.reason_codes)
        if code is not None:
            self.assertIn(code, result.reason_codes)
        for flag in FLAGS:
            self.assertIs(False, getattr(result, flag))
        return result

    def test_default_off_requires_literal_true(self):
        fixture = synthetic_fixture()
        self.assertEqual("DISABLED", map_synthetic_fixture(fixture).state)
        for enabled in (False, 1, "true", None):
            with self.subTest(enabled=enabled):
                self.assertEqual("DISABLED", map_synthetic_fixture(fixture, enabled=enabled).state)

    def test_authored_all_provider_vectors_check_structure_but_never_authority(self):
        for provider in ("upstox", "angelone", "dhan"):
            with self.subTest(provider=provider):
                result = self.mapped(synthetic_fixture(provider))
                self.assertEqual("VERIFIED", result.state, result.reason_codes)
                self.assertEqual(7, len(result.evidence_matrix))
                self.assertTrue(all(row.checked_state == "VERIFIED" for row in result.evidence_matrix))
                for flag in FLAGS:
                    self.assertIs(False, getattr(result, flag))
                receipt = result.to_dict()
                self.assertEqual("NOT_ESTABLISHED", receipt["source_authenticity"])
                self.assertEqual("CURSOR_MAIN", receipt["qualification_owner"])
                self.assertIn("NO_REAL_DATA_ENTITLEMENT", receipt["qualification_blockers"])
                self.assertEqual("BLOCKED_DATA_FOR_HISTORICAL_OPTION_PNL", receipt["historical_option_pnl"])
                for flag in ("eligible", "actionable", "execution_allowed", "historical_replay_allowed"):
                    self.assertIs(False, receipt["analysis"][flag])

    def test_stage1_synthetic_friction_bracket_matches_units_once(self):
        value = self.mapped().to_dict()["analysis"]["friction"]["value"]
        self.assertEqual(50, value["intended_units"])
        for key, expected in (("ask_plus_impact_estimate", "102.00"),
                              ("indicative_premium_stop", "66.30"),
                              ("indicative_premium_target", "166.30"),
                              ("gross_premium_risk_inr", "1785.00"),
                              ("snapshot_friction_inr", "25.00")):
            self.assertEqual(expected, value[key])
        self.assertEqual("NOT_EXECUTED", value["fill_status"])

    def test_result_and_input_are_immutable_and_serialization_is_fresh(self):
        fixture = synthetic_fixture()
        original = deepcopy(fixture)
        result = self.mapped(fixture)
        self.assertEqual(original, fixture)
        first = result.to_dict()
        first["source_qualified"] = True
        first["analysis"]["actionable"] = True
        first["evidence_matrix"][0]["checked_state"] = "FORGED"
        second = result.to_dict()
        self.assertFalse(second["source_qualified"])
        self.assertFalse(second["analysis"]["actionable"])
        self.assertEqual("VERIFIED", second["evidence_matrix"][0]["checked_state"])
        json.dumps(second, allow_nan=False)
        with self.assertRaises(FrozenInstanceError):
            result.source_qualified = True
        with self.assertRaises(TypeError):
            MappingResult("VERIFIED", (), source_qualified=True)

    def test_no_file_or_network_side_effect_is_needed_for_mapping(self):
        fixture = synthetic_fixture()
        with patch("socket.getaddrinfo", side_effect=AssertionError("network forbidden")), \
                patch("socket.socket.connect", side_effect=AssertionError("network forbidden")), \
                patch("builtins.open", side_effect=AssertionError("file access forbidden")):
            self.assertEqual("VERIFIED", self.mapped(fixture).state)

    def test_real_capture_and_complete_d1_fixture_are_outside_d2_scope(self):
        fixture = synthetic_fixture()
        fixture["provenance"] = "UNVERIFIED_CAPTURE"
        self.assertBlocked(fixture, "UNAVAILABLE", "REAL_CAPTURE_NOT_SUPPORTED_D2")
        fixture = synthetic_fixture()
        fixture["schema_version"] = "tradepulse.option-fixture.d1.v1"
        self.assertBlocked(fixture, "INVALID", "UNSUPPORTED_MAPPING_FIXTURE_SCHEMA")

    def test_caller_authority_assertions_never_grant_permission(self):
        for flag in FLAGS:
            for value in (True, "false", 1, None):
                with self.subTest(flag=flag, value=value):
                    fixture = synthetic_fixture()
                    fixture[flag] = value
                    self.assertBlocked(fixture, "INVALID")
        fixture = synthetic_fixture()
        evidence(fixture, "DATA_RIGHTS")["source_qualified"] = True
        self.assertBlocked(fixture, "INVALID")

    def test_documentation_and_observation_states_are_distinct_axes(self):
        for doc in ("CONDITIONAL", "UNVERIFIED", "UNAVAILABLE", "CONTRADICTORY"):
            with self.subTest(documentation_state=doc):
                fixture = synthetic_fixture()
                evidence(fixture, "BOOK_SOURCE_CLOCKS")["documentation_state"] = doc
                result = self.assertBlocked(fixture, "NOT_ESTABLISHED")
                row = next(row for row in result.evidence_matrix if row.requirement == "BOOK_SOURCE_CLOCKS")
                self.assertEqual(doc, row.documentation_state)
                self.assertEqual("VERIFIED", row.declared_observed_state)
                self.assertEqual("NOT_ESTABLISHED", row.checked_state)
                self.assertIsNone(result.analysis_json)
                if doc == "CONTRADICTORY":
                    self.assertIn("DOCUMENTATION_CONTRADICTORY", row.reason_codes)
        fixture = synthetic_fixture()
        evidence(fixture, "BOOK_SOURCE_CLOCKS")["documentation_state"] = "VERIFIED"
        self.assertBlocked(fixture, "INVALID", "EVIDENCE_STATE_AXIS_MISMATCH")

    def test_documented_field_does_not_promote_missing_stale_or_invalid_observation(self):
        for state in ("UNAVAILABLE", "STALE", "INVALID", "NOT_ESTABLISHED"):
            with self.subTest(observed_state=state):
                fixture = synthetic_fixture()
                evidence(fixture, "PREMIUM_TICK")["observed_state"] = state
                result = self.assertBlocked(fixture, state)
                row = next(row for row in result.evidence_matrix if row.requirement == "PREMIUM_TICK")
                self.assertEqual("DOCUMENTED", row.documentation_state)
                self.assertEqual(state, row.declared_observed_state)
                self.assertIsNone(result.analysis_json)

    def test_missing_mandatory_evidence_is_retained_with_unavailable_row(self):
        fixture = synthetic_fixture()
        fixture["evidence"] = [row for row in fixture["evidence"] if row["requirement"] != "DATA_RIGHTS"]
        result = self.assertBlocked(fixture, "UNAVAILABLE", "MANDATORY_EVIDENCE_MISSING")
        row = next(row for row in result.evidence_matrix if row.requirement == "DATA_RIGHTS")
        self.assertIsNone(row.documentation_state)
        self.assertEqual("UNAVAILABLE", row.checked_state)

    def test_duplicate_evidence_ids_requirements_and_wrong_provider_are_invalid(self):
        fixture = synthetic_fixture()
        fixture["evidence"][1]["evidence_id"] = fixture["evidence"][0]["evidence_id"]
        self.assertBlocked(fixture, "INVALID")
        fixture = synthetic_fixture()
        fixture["evidence"][1]["requirement"] = fixture["evidence"][0]["requirement"]
        self.assertBlocked(fixture, "INVALID")
        fixture = synthetic_fixture()
        evidence(fixture, "PREMIUM_TICK")["provider"] = "dhan"
        self.assertBlocked(fixture, "INVALID", "EVIDENCE_PROVIDER_MISMATCH")

    def test_evidence_future_availability_expiry_and_scope_fail_closed(self):
        cases = ((dict(available_at="2026-11-03T10:00:00.000001+05:30"), "UNAVAILABLE"),
                 (dict(effective_until=DECISION), "STALE"),
                 (dict(effective_from="2026-11-03T10:00:01+05:30"), "STALE"),
                 (dict(scope="INDEPENDENT_PUBLISHER_PROOF"), "INVALID"))
        for change, state in cases:
            with self.subTest(change=change):
                fixture = synthetic_fixture()
                evidence(fixture, "PREMIUM_TICK").update(change)
                self.assertBlocked(fixture, state)

    def test_partial_master_effective_interval_cannot_widen_to_whole_day(self):
        fixture = synthetic_fixture()
        evidence(fixture, "DATED_MASTER")["effective_from"] = "2026-11-03T09:00:00+05:30"
        self.assertBlocked(fixture, "NOT_ESTABLISHED")

    def test_source_hash_detects_tampering_but_hash_never_proves_authority(self):
        fixture = synthetic_fixture()
        fixture["source"]["quote"]["ask"] = "102.05"
        self.assertBlocked(fixture, "INVALID", "SOURCE_ARTIFACT_DIGEST_MISMATCH")
        rehash(fixture)
        result = self.mapped(fixture)
        self.assertEqual("VERIFIED", result.state)
        self.assertFalse(result.source_qualified)

    def test_mapping_rows_cannot_infer_missing_fields_or_fallback_to_ltp(self):
        fixture = synthetic_fixture()
        fixture["mapping"] = [row for row in fixture["mapping"] if row["target_path"] != "contract.tick_size"]
        self.assertBlocked(fixture, "UNAVAILABLE", "MANDATORY_MAPPING_MISSING")
        fixture = synthetic_fixture()
        mapping(fixture, "quote.ask")["source_path"] = "quote.last_price"
        self.assertBlocked(fixture, "INVALID", "UNREVIEWED_FIELD_RENAME_OR_FALLBACK")

    def test_duplicate_unknown_targets_and_wrong_evidence_requirement_are_invalid(self):
        fixture = synthetic_fixture()
        fixture["mapping"].append(deepcopy(fixture["mapping"][0]))
        self.assertBlocked(fixture, "INVALID")
        fixture = synthetic_fixture()
        fixture["mapping"][0]["target_path"] = "contract.source_qualified"
        self.assertBlocked(fixture, "INVALID")
        fixture = synthetic_fixture()
        mapping(fixture, "contract.tick_size")["evidence_ids"] = ["AUTHORED_DATA_RIGHTS"]
        self.assertBlocked(fixture, "INVALID", "WRONG_EVIDENCE_REQUIREMENT_FOR_FIELD")

    def test_absent_null_and_zero_are_not_interchangeable_for_mandatory_quote(self):
        for presence in ("ABSENT", "NULL"):
            with self.subTest(presence=presence):
                fixture = synthetic_fixture()
                quote = fixture["source"]["quote"]
                if presence == "ABSENT":
                    del quote["ask_size"]
                else:
                    quote["ask_size"] = None
                mapping(fixture, "quote.ask_size")["presence"] = presence
                self.assertBlocked(rehash(fixture), "UNAVAILABLE", "MANDATORY_FIELD_" + presence)
        fixture = synthetic_fixture()
        fixture["source"]["quote"]["ask_size"] = 0
        self.assertBlocked(rehash(fixture), "UNAVAILABLE", "INSUFFICIENT_DISPLAYED_SIZE")
        fixture = synthetic_fixture()
        fixture["source"]["quote"]["ask"] = "0"
        self.assertBlocked(rehash(fixture), "INVALID")

    def test_false_presence_declarations_and_unknown_units_do_not_create_values(self):
        fixture = synthetic_fixture()
        fixture["source"]["master"]["tick_size"] = None
        self.assertBlocked(rehash(fixture), "INVALID", "FIELD_PRESENCE_MISMATCH")
        fixture = synthetic_fixture()
        mapping(fixture, "contract.tick_size")["unit"] = "PAISA"
        self.assertBlocked(fixture, "NOT_ESTABLISHED", "MAPPING_UNIT_NOT_ESTABLISHED")
        fixture = synthetic_fixture()
        fixture["source"]["quote"]["quantity_unit"] = "UNKNOWN"
        self.assertBlocked(rehash(fixture), "NOT_ESTABLISHED")

    def test_exact_contract_ref_provider_revision_cannot_use_display_symbol_join(self):
        for name, value in (("contract_id", None), ("contract_id", "other"),
                            ("provider", "dhan"), ("source_revision", "other")):
            with self.subTest(name=name, value=value):
                fixture = synthetic_fixture()
                fixture["source"]["quote"][name] = value
                if value is None:
                    mapping(fixture, "quote."+name)["presence"] = "NULL"
                self.assertBlocked(rehash(fixture), "UNAVAILABLE" if value is None else "INVALID")

    def test_book_trade_or_provider_time_is_not_a_valid_book_source_clock(self):
        for meaning in (None, "TRADE", "PROVIDER_GENERATED", "PROVIDER_RECEIVED", "CLIENT_RECEIVED"):
            with self.subTest(meaning=meaning):
                fixture = synthetic_fixture()
                fixture["source"]["book_time_meaning"] = meaning
                self.assertBlocked(rehash(fixture), "NOT_ESTABLISHED", "BOOK_CLOCK_SEMANTICS_NOT_ESTABLISHED")

    def test_bid_ask_age_boundary_isolated_from_leg_skew(self):
        for at, expected in (("2026-11-03T09:59:57+05:30", "VERIFIED"),
                             ("2026-11-03T09:59:56.999999+05:30", "STALE")):
            with self.subTest(at=at):
                fixture = synthetic_fixture()
                fixture["source"]["quote"].update(observed_at=at, bid_at=at, ask_at=at)
                fixture["source"]["size_at"] = at
                result = self.mapped(rehash(fixture))
                self.assertEqual(expected, result.state, result.reason_codes)
                self.assertFalse(result.source_qualified)

    def test_independent_liquidity_clock_is_required_and_cannot_be_refreshed_by_receipt(self):
        fixture = synthetic_fixture()
        del fixture["source"]["size_at"]
        self.assertBlocked(rehash(fixture), "UNAVAILABLE")
        fixture = synthetic_fixture()
        fixture["source"]["size_at"] = "2026-11-03T09:59:56+05:30"
        self.assertBlocked(rehash(fixture), "STALE", "LIQUIDITY_SOURCE_CLOCK_STALE")
        fixture = synthetic_fixture()
        fixture["source"]["size_at"] = "2026-11-03T10:00:00.000001+05:30"
        self.assertBlocked(rehash(fixture), "INVALID", "LIQUIDITY_CLOCK_ORDER_INVALID")

    def test_quote_future_availability_and_wrong_grid_phase_are_not_repaired(self):
        fixture = synthetic_fixture()
        fixture["source"]["quote"]["available_at"] = "2026-11-03T10:00:00.000001+05:30"
        self.assertBlocked(rehash(fixture), "UNAVAILABLE")
        fixture = synthetic_fixture()
        fixture["source"]["session"]["phase"] = "SPECIAL"
        self.assertBlocked(rehash(fixture), "NOT_ESTABLISHED")
        fixture = synthetic_fixture()
        fixture["source"]["session"]["close_at"] = "2026-11-03T15:40:00+05:30"
        self.assertBlocked(rehash(fixture), "INVALID")

    def test_invalid_book_geometry_displayed_size_and_whole_lot_request(self):
        for changes in (dict(bid="102.05"), dict(bid="102.00"),
                        dict(ask="102.001"), dict(ask_size=-1), dict(ask_size="50.5")):
            with self.subTest(changes=changes):
                fixture = synthetic_fixture()
                fixture["source"]["quote"].update(changes)
                self.assertBlocked(rehash(fixture), "INVALID")
        fixture = synthetic_fixture()
        fixture["source"]["quote"]["ask_size"] = 49
        self.assertBlocked(rehash(fixture), "UNAVAILABLE", "INSUFFICIENT_DISPLAYED_SIZE")
        fixture = synthetic_fixture()
        fixture["intended_lots"] = 0
        self.assertBlocked(fixture, "INVALID")

    def test_no_fee_default_and_read_only_flag_cannot_be_coerced(self):
        fixture = synthetic_fixture()
        fixture["source"]["assumptions"]["round_trip_fees_inr"] = None
        mapping(fixture, "assumptions.round_trip_fees_inr")["presence"] = "NULL"
        self.assertBlocked(rehash(fixture), "UNAVAILABLE", "MANDATORY_FIELD_NULL")
        fixture = synthetic_fixture()
        fixture["read_only"] = 1
        self.assertBlocked(fixture, "INVALID", "READ_ONLY_FIXTURE_REQUIRED")

    def test_missing_optional_context_stays_unavailable_without_quote_veto(self):
        result = self.mapped()
        self.assertEqual("VERIFIED", result.state)
        self.assertEqual("UNAVAILABLE", result.to_dict()["analysis"]["context"]["common_evidence"]["state"])

    def test_optional_field_presence_and_unit_normalization_preserve_observed_zero(self):
        fixture = synthetic_fixture()
        context = optional_context(fixture)
        context["fields"]["gamma"] = None
        del context["fields"]["iv"]
        fixture["source"].update(context=context, context_max_age_seconds=3)
        result = self.mapped(rehash(fixture))
        self.assertEqual("VERIFIED", result.state)
        fields = result.to_dict()["analysis"]["context"]["fields"]
        self.assertEqual(("ABSENT", "NULL", "OBSERVED"),
                         (fields["iv"]["presence"], fields["gamma"]["presence"], fields["oi"]["presence"]))
        self.assertEqual("0", fields["oi"]["value"])
        self.assertEqual("950.0", fields["vega"]["value"])
        self.assertEqual("-3.4", fields["theta"]["value"])

    def test_invalid_optional_identity_or_unit_cannot_become_verified_context(self):
        for change in ("identity", "theta_basis", "vega_unit"):
            with self.subTest(change=change):
                fixture = synthetic_fixture()
                context = optional_context(fixture)
                if change == "identity":
                    context["contract_id"] = "other"
                elif change == "theta_basis":
                    del context["theta_calendar_basis"]
                else:
                    context["units"]["vega"] = "UNKNOWN"
                fixture["source"].update(context=context, context_max_age_seconds=3)
                result = self.mapped(rehash(fixture))
                self.assertEqual("VERIFIED", result.state)
                fields = result.to_dict()["analysis"]["context"]["fields"]
                name = "delta" if change == "identity" else "theta" if change == "theta_basis" else "vega"
                self.assertNotEqual("VERIFIED", fields[name]["evidence"]["state"])
                self.assertIsNone(fields[name]["value"])


if __name__ == "__main__":
    unittest.main()

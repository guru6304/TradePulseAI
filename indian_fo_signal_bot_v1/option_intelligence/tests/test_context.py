"""Deterministic optional context arithmetic; all records are authored fixtures."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from decimal import Decimal
import json
import unittest

from option_intelligence.context import (
    DELTA_UNIT, GAMMA_UNIT, THETA_DAY_UNIT, THETA_YEAR_UNIT, VEGA_FRACTION_UNIT,
    VEGA_POINT_UNIT, greek_scenario, inspect_context, oi_delta,
)
from option_intelligence.evidence import IST
from option_intelligence.identity import validate_contract
from option_intelligence.tests.test_identity import DECISION, contract_record


def option_contract(**changes):
    return validate_contract(contract_record(**changes), decision_at=DECISION).contract


def context_record(contract=None, **changes):
    contract = contract or option_contract()
    observed = DECISION-timedelta(seconds=2)
    record = dict(contract_id=contract.contract_id, provider=contract.provider,
        source_revision=contract.source_revision, source_id="AUTHORED:SYNTHETIC:CONTEXT",
        observed_at=observed, received_at=DECISION-timedelta(seconds=1), available_at=DECISION,
        fields=dict(iv="20", delta=".50", gamma=".002", vega="9.50", theta="-3.40",
                    oi="1200", volume="800"),
        units=dict(iv="PERCENT", delta=DELTA_UNIT, gamma=GAMMA_UNIT,
                   vega=VEGA_POINT_UNIT, theta=THETA_DAY_UNIT,
                   oi="CONTRACTS", volume="CONTRACTS"),
        volume_window=dict(start_at=observed-timedelta(minutes=5), end_at=observed), kind="CURRENT")
    record.update(changes)
    return record


class TestOptionIntelligenceContext(unittest.TestCase):
    def inspect(self, record=None, contract=None, **changes):
        return inspect_context(record if record is not None else context_record(),
            contract or option_contract(), decision_at=changes.pop("decision_at", DECISION),
            max_age_seconds=changes.pop("max_age_seconds", 3), **changes)

    def test_explicit_units_normalize_without_source_or_qualification_claim(self):
        result = self.inspect()
        self.assertEqual("VERIFIED", result.common_evidence.state)
        self.assertEqual(Decimal(".20"), result.iv.value)
        self.assertEqual(Decimal("950"), result.vega.value)
        self.assertEqual(Decimal("-3.40"), result.theta.value)
        self.assertEqual(Decimal(60000), result.oi.value)
        self.assertEqual(Decimal(40000), result.volume.value)
        self.assertFalse(result.actionable)
        self.assertEqual("NOT_ESTABLISHED", result.source_authenticity)
        self.assertEqual("OPTIONAL_CONTEXT_ONLY", result.to_dict()["qualification_effect"])

    def test_absent_null_and_observed_zero_remain_distinct(self):
        record = context_record()
        del record["fields"]["iv"]
        record["fields"]["gamma"] = None
        record["fields"]["oi"] = 0
        result = self.inspect(record)
        self.assertEqual(("ABSENT", "NULL", "OBSERVED"),
                         (result.iv.presence, result.gamma.presence, result.oi.presence))
        self.assertEqual(("UNAVAILABLE", "UNAVAILABLE", "VERIFIED"),
                         (result.iv.state, result.gamma.state, result.oi.state))
        self.assertIsNone(result.iv.value)
        self.assertIsNone(result.gamma.value)
        self.assertEqual(Decimal(0), result.oi.value)

    def test_supplied_oi_change_preserves_presence_and_needs_baseline(self):
        record = context_record()
        self.assertEqual("ABSENT", self.inspect(record).oi_change.presence)
        record["fields"]["oi_change"] = None
        self.assertEqual("NULL", self.inspect(record).oi_change.presence)
        record["units"]["oi_change"] = "CONTRACTS"
        for value in (0, "-100", "200"):
            with self.subTest(value=value):
                record["fields"]["oi_change"] = value
                field = self.inspect(record).oi_change
                self.assertEqual("OBSERVED", field.presence)
                self.assertEqual(value, field.raw_value)
                self.assertEqual("CONTRACTS", field.raw_unit)
                self.assertEqual("NOT_ESTABLISHED", field.state)
                self.assertIn("OI_CHANGE_BASELINE_REQUIRED", field.reason_codes)
                self.assertIsNone(field.value)

    def test_supplied_oi_change_units_and_signed_integer_are_checked(self):
        record = context_record()
        record["fields"]["oi_change"] = "-100"
        self.assertIn("OPTIONAL_UNIT_NOT_ESTABLISHED", self.inspect(record).oi_change.reason_codes)
        record["units"]["oi_change"] = "PERCENT"
        self.assertEqual("INVALID", self.inspect(record).oi_change.state)
        record["units"]["oi_change"] = "CONTRACTS"
        for value in ("1.5", True, [], float("nan")):
            with self.subTest(value_type=type(value).__name__):
                record["fields"]["oi_change"] = value
                self.assertEqual("INVALID", self.inspect(record).oi_change.state)

    def test_input_immutability_frozen_dtos_and_native_float_serialization(self):
        record = context_record()
        record["fields"]["delta"] = .5
        original = deepcopy(record)
        result = self.inspect(record)
        self.assertEqual(original, record)
        self.assertIsInstance(result.delta.raw_value, float)
        self.assertEqual(.5, result.to_dict()["fields"]["delta"]["raw_value"])
        json.dumps(result.to_dict(), allow_nan=False)
        with self.assertRaises(FrozenInstanceError):
            result.delta.value = Decimal(0)
        record["fields"]["delta"] = .9
        self.assertEqual(.5, result.delta.raw_value)

    def test_iv_fraction_and_percent_are_equal_without_iv_percentile(self):
        first = self.inspect()
        record = context_record()
        record["fields"]["iv"], record["units"]["iv"] = ".20", "FRACTION"
        second = self.inspect(record)
        self.assertEqual(first.iv.value, second.iv.value)
        self.assertNotIn("percentile", json.dumps(second.to_dict()).lower())
        for invalid in (0, -1):
            record["fields"]["iv"] = invalid
            self.assertEqual("INVALID", self.inspect(record).iv.state)

    def test_vega_percentage_point_and_fraction_math_cannot_silently_mix(self):
        first = self.inspect()
        record = context_record()
        record["fields"]["vega"], record["units"]["vega"] = "950", VEGA_FRACTION_UNIT
        self.assertEqual(first.vega.value, self.inspect(record).vega.value)
        record["units"]["vega"] = "UNKNOWN"
        self.assertEqual("INVALID", self.inspect(record).vega.state)

    def test_annual_theta_needs_declared_365_calendar_basis(self):
        record = context_record()
        record["fields"]["theta"] = "-1241"
        record["units"]["theta"] = THETA_YEAR_UNIT
        self.assertEqual("NOT_ESTABLISHED", self.inspect(record).theta.state)
        for invalid in (252, True, "365"):
            record["theta_calendar_basis"] = invalid
            self.assertEqual("NOT_ESTABLISHED", self.inspect(record).theta.state)
        record["theta_calendar_basis"] = 365
        self.assertEqual(Decimal("-3.4"), self.inspect(record).theta.value)
        record["fields"]["theta"] = "365"
        self.assertEqual(Decimal(1), self.inspect(record).theta.value)

    def test_signed_delta_call_put_and_boundaries(self):
        for side, valid, invalid in (("CE", (0, ".5", 1), ("-.01", "1.01")),
                                     ("PE", (0, "-.5", -1), (".01", "-1.01"))):
            contract = option_contract(option_type=side)
            for value in valid+invalid:
                with self.subTest(side=side, value=value):
                    record = context_record(contract)
                    record["fields"]["delta"] = value
                    result = self.inspect(record, contract)
                    self.assertEqual("VERIFIED" if value in valid else "INVALID", result.delta.state)

    def test_gamma_vega_nonnegative_theta_signed_and_zero_is_observed(self):
        for name in ("gamma", "vega"):
            record = context_record()
            record["fields"][name] = -1
            self.assertEqual("INVALID", self.inspect(record).field(name).state)
        record = context_record()
        for name in ("delta", "gamma", "vega", "theta"):
            record["fields"][name] = 0
        result = self.inspect(record)
        for name in ("delta", "gamma", "vega", "theta"):
            self.assertEqual("OBSERVED", result.field(name).presence)
            self.assertEqual(Decimal(0), result.field(name).value)

    def test_missing_units_source_time_and_explicit_freshness_are_unavailable(self):
        record = context_record()
        del record["units"]["delta"]
        self.assertEqual("NOT_ESTABLISHED", self.inspect(record).delta.state)
        self.assertEqual("VERIFIED", self.inspect(record).oi.state)
        record = context_record()
        del record["observed_at"]
        self.assertEqual("NOT_ESTABLISHED", self.inspect(record).common_evidence.state)
        self.assertIsNone(self.inspect(record).delta.value)
        self.assertEqual("NOT_ESTABLISHED", self.inspect(max_age_seconds=None).delta.state)

    def test_stale_fields_keep_raw_values_but_no_normalized_value(self):
        result = self.inspect(max_age_seconds=1)
        self.assertEqual("STALE", result.delta.state)
        self.assertEqual(".50", result.delta.raw_value)
        self.assertIsNone(result.delta.value)
        self.assertEqual("VERIFIED", self.inspect(max_age_seconds=2).delta.state)

    def test_identity_provider_revision_and_contract_reference_must_match(self):
        for change in (dict(contract_id="other"), dict(provider="angelone"),
                       dict(source_revision="other")):
            with self.subTest(change=change):
                result = self.inspect(context_record(**change))
                self.assertEqual("INVALID", result.common_evidence.state)
                self.assertIn("CONTEXT_IDENTITY_MISMATCH", result.delta.reason_codes)

    def test_availability_and_offset_clock_order(self):
        for change, state in ((dict(available_at=DECISION+timedelta(seconds=1)), "UNAVAILABLE"),
                              (dict(received_at=DECISION-timedelta(seconds=3)), "INVALID"),
                              (dict(observed_at=DECISION.replace(tzinfo=None)), "INVALID")):
            with self.subTest(change=change):
                self.assertEqual(state, self.inspect(context_record(**change)).delta.state)

    def test_contract_master_must_be_available_and_lot_units_cannot_be_tampered(self):
        contract = option_contract()
        for changes, state in ((dict(available_at=DECISION+timedelta(seconds=1)), "UNAVAILABLE"),
                               (dict(lot_size=0), "INVALID"), (dict(lot_size=True), "INVALID"),
                               (dict(option_type="UNKNOWN"), "INVALID"),
                               (dict(quantity_unit="CONTRACTS"), "INVALID")):
            with self.subTest(changes=changes):
                changed = replace(contract, **changes)
                result = self.inspect(context_record(changed), changed)
                self.assertEqual(state, result.common_evidence.state)
                self.assertIsNone(result.oi.value)

    def test_invalid_raw_types_nonfinite_and_oversize_are_bounded_and_explicit(self):
        for value in (True, [], {"x": [1, 2]}, "1"*200, float("nan"), float("inf"), Decimal("NaN")):
            with self.subTest(value_type=type(value).__name__):
                record = context_record()
                record["fields"]["delta"] = value
                result = self.inspect(record)
                self.assertEqual("INVALID", result.delta.state)
                self.assertEqual("OBSERVED", result.delta.presence)
                self.assertIsNone(result.delta.value)
                json.dumps(result.to_dict(), allow_nan=False)

    def test_volume_needs_time_window_and_explicit_quantity_unit(self):
        record = context_record()
        del record["volume_window"]
        self.assertEqual("NOT_ESTABLISHED", self.inspect(record).volume.state)
        record = context_record()
        record["volume_window"]["end_at"] = DECISION
        self.assertEqual("INVALID", self.inspect(record).volume.state)
        record = context_record()
        record["fields"]["oi"] = "1.5"
        self.assertEqual("INVALID", self.inspect(record).oi.state)
        record["fields"]["oi"] = -1
        self.assertEqual("INVALID", self.inspect(record).oi.state)

    def test_scenario_has_exact_signed_unit_components_not_execution_price(self):
        result = greek_scenario(self.inspect(), underlying_change_inr=10,
                                iv_change_fraction=".01", elapsed_calendar_days=2)
        self.assertEqual("VERIFIED", result.state)
        self.assertEqual(Decimal("7.8"), result.value.premium_change_inr_per_underlying_unit)
        self.assertEqual((Decimal(5), Decimal(".1"), Decimal("9.5"), Decimal("-6.8")),
            (result.value.delta_component, result.value.gamma_component,
             result.value.vega_component, result.value.theta_component))
        self.assertIn("NOT_EXECUTION_PRICE", result.value.approximation)
        self.assertEqual("SUPPLIED_INPUT_VALIDATION_ONLY", result.scope)

    def test_put_scenario_uses_negative_delta_not_absolute_delta(self):
        contract = option_contract(option_type="PE")
        record = context_record(contract)
        record["fields"]["delta"] = "-.50"
        result = greek_scenario(self.inspect(record, contract), underlying_change_inr=-10,
                                iv_change_fraction=0, elapsed_calendar_days=0)
        self.assertEqual(Decimal(5), result.value.delta_component)
        self.assertEqual(Decimal("5.1"), result.value.premium_change_inr_per_underlying_unit)

    def test_missing_invalid_stale_greeks_never_fallback_to_zero_in_scenario(self):
        for value in (None, "bad", -.5):
            record = context_record()
            record["fields"]["gamma"] = value
            result = greek_scenario(self.inspect(record), underlying_change_inr=10,
                                    iv_change_fraction=".01", elapsed_calendar_days=2)
            self.assertIsNone(result.value)
        stale = greek_scenario(self.inspect(max_age_seconds=1), underlying_change_inr=10,
                               iv_change_fraction=0, elapsed_calendar_days=0)
        self.assertEqual("STALE", stale.state)
        invalid = greek_scenario(self.inspect(), underlying_change_inr=0,
                                 iv_change_fraction=0, elapsed_calendar_days=-1)
        self.assertEqual("INVALID", invalid.state)


class TestOptionIntelligenceOI(unittest.TestCase):
    def setUp(self):
        self.contract = option_contract()
        self.current = context_record(self.contract)
        observed = DECISION-timedelta(seconds=302)
        self.baseline = context_record(self.contract, kind="INTRADAY", source_id="SYNTH:BASELINE",
            observed_at=observed, received_at=observed, available_at=observed,
            fields=dict(oi="1000"), units=dict(oi="CONTRACTS"))

    def compare(self, **policy):
        return oi_delta(self.current, self.baseline, self.contract,
            decision_at=DECISION, max_age_seconds=policy.pop("max_age_seconds", 3),
            max_alignment_seconds=policy.pop("max_alignment_seconds", 300), **policy)

    def test_explicit_contracts_normalize_by_dated_lot_then_delta(self):
        before = deepcopy((self.current, self.baseline))
        result = self.compare()
        self.assertEqual("VERIFIED", result.state)
        self.assertEqual((Decimal(60000), Decimal(50000), Decimal(10000)),
            (result.value.current_underlying_units, result.value.baseline_underlying_units,
             result.value.change_underlying_units))
        self.assertEqual(before, (self.current, self.baseline))
        self.assertIn("NOT_ORDER_AGGRESSION_OR_DIRECTION", result.value.interpretation)
        self.assertEqual("NOT_ESTABLISHED", result.value.source_authenticity)
        json.dumps(result.to_dict(), allow_nan=False)

    def test_supplied_change_must_match_comparable_baseline_after_unit_conversion(self):
        self.current["fields"]["oi_change"] = "200"
        self.current["units"]["oi_change"] = "CONTRACTS"
        result = self.compare()
        self.assertEqual("VERIFIED", result.state)
        self.assertEqual(Decimal(10000), result.value.supplied_change_underlying_units)
        self.assertEqual("MATCHED_SUPPLIED_BASELINE", result.value.supplied_change_status)
        self.current["fields"]["oi_change"] = "199"
        result = self.compare()
        self.assertEqual("INVALID", result.state)
        self.assertIn("OI_CHANGE_BASELINE_MISMATCH", result.reason_codes)
        self.assertIsNone(result.value)

    def test_signed_negative_supplied_change_and_observed_zero_are_valid_when_matched(self):
        self.current["fields"].update(oi="900", oi_change="-100")
        self.current["units"]["oi_change"] = "CONTRACTS"
        result = self.compare()
        self.assertEqual("VERIFIED", result.state)
        self.assertEqual(Decimal(-5000), result.value.supplied_change_underlying_units)
        self.current["fields"].update(oi="1000", oi_change=0)
        self.assertEqual(Decimal(0), self.compare().value.supplied_change_underlying_units)

    def test_missing_or_null_supplied_change_does_not_block_independent_baseline_delta(self):
        first = self.compare()
        self.assertEqual("VERIFIED", first.state)
        self.assertEqual("ABSENT", first.value.supplied_change_status)
        self.assertIsNone(first.value.supplied_change_underlying_units)
        self.current["fields"]["oi_change"] = None
        second = self.compare()
        self.assertEqual("VERIFIED", second.state)
        self.assertEqual("NULL", second.value.supplied_change_status)
        self.assertIsNone(second.value.supplied_change_underlying_units)
        self.assertEqual(first.value.change_underlying_units, second.value.change_underlying_units)

    def test_supplied_change_wrong_missing_units_or_invalid_count_never_join(self):
        self.current["fields"]["oi_change"] = "200"
        self.assertEqual("NOT_ESTABLISHED", self.compare().state)
        self.current["units"]["oi_change"] = "UNDERLYING_UNITS"
        result = self.compare()
        self.assertEqual("INVALID", result.state)
        self.assertIn("OI_CHANGE_UNIT_MISMATCH", result.reason_codes)
        self.current["units"]["oi_change"] = "CONTRACTS"
        self.current["fields"]["oi_change"] = "200.5"
        self.assertEqual("INVALID", self.compare().state)

    def test_underlying_unit_counts_are_not_multiplied_again(self):
        for record in (self.current, self.baseline):
            record["units"]["oi"] = "UNDERLYING_UNITS"
        self.assertEqual(Decimal(200), self.compare().value.change_underlying_units)

    def test_observed_zero_and_negative_oi_change_are_valid(self):
        self.current["fields"]["oi"] = 0
        self.assertEqual(Decimal(-50000), self.compare().value.change_underlying_units)
        self.baseline["fields"]["oi"] = 0
        self.assertEqual(Decimal(0), self.compare().value.change_underlying_units)
        self.assertNotIn("percentage", json.dumps(self.compare().to_dict()).lower())

    def test_unit_contract_revision_and_identity_mismatch_never_join(self):
        for change in (dict(provider="angelone"), dict(source_revision="v2"), dict(contract_id="other")):
            with self.subTest(change=change):
                original = deepcopy(self.baseline)
                self.baseline.update(change)
                self.assertEqual("INVALID", self.compare().state)
                self.baseline = original
        self.baseline["units"]["oi"] = "UNDERLYING_UNITS"
        self.assertIn("OI_UNIT_MISMATCH", self.compare().reason_codes)

    def test_missing_oi_units_or_baseline_semantics_do_not_create_change(self):
        for field_value in ({}, dict(oi=None)):
            self.baseline["fields"] = field_value
            result = self.compare()
            self.assertEqual("UNAVAILABLE", result.state)
            self.assertIsNone(result.value)
        self.setUp()
        self.baseline["kind"] = "UNKNOWN"
        self.assertEqual("NOT_ESTABLISHED", self.compare().state)
        self.setUp()
        del self.baseline["units"]["oi"]
        self.assertEqual("NOT_ESTABLISHED", self.compare().state)

    def test_intraday_age_alignment_and_order_are_explicit(self):
        self.assertEqual("STALE", self.compare(max_age_seconds=1).state)
        self.assertEqual("INVALID", self.compare(max_alignment_seconds=299).state)
        self.baseline.update(observed_at=self.current["observed_at"],
                             received_at=self.current["received_at"], available_at=DECISION)
        self.assertIn("OI_BASELINE_NOT_PRIOR", self.compare().reason_codes)

    def test_prior_close_needs_declared_previous_session_and_exact_close_time(self):
        close = datetime(2026, 11, 2, 15, 30, tzinfo=IST)
        self.baseline.update(kind="PRIOR_CLOSE", observed_at=close,
                             received_at=close, available_at=close)
        self.assertEqual("NOT_ESTABLISHED", self.compare().state)
        result = self.compare(prior_session_date="2026-11-02")
        self.assertEqual("VERIFIED", result.state)
        self.assertEqual(Decimal(10000), result.value.change_underlying_units)
        self.assertEqual("INVALID", self.compare(prior_session_date="2026-11-01").state)
        wrong = close-timedelta(seconds=1)
        self.baseline.update(observed_at=wrong, received_at=wrong, available_at=wrong)
        self.assertEqual("INVALID", self.compare(prior_session_date="2026-11-02").state)


if __name__ == "__main__":
    unittest.main()

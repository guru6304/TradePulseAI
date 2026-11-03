"""Offline indicative math only, with literal false operational permissions."""
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from decimal import Decimal as D
import json
import unittest

from option_intelligence import OPTION_INTELLIGENCE_ENABLED
from option_intelligence.fitness import FrictionAssumptions, analyze_option, estimate_friction
from option_intelligence.identity import validate_contract
from .test_identity import DECISION, contract_record
from .test_quotes import contract, inspect, policy, quote_record, session


def assumptions(**changes):
    values = dict(version="SYNTHETIC_FRICTION_V1", source_reference="SYNTHETIC_ALL_IN_FEES",
        effective_from=date(2026,1,1), effective_to=date(2026,12,31), available_at=DECISION,
        entry_impact=D(".02"), exit_impact=D(".02"), round_trip_fees_inr=D(10),
        risk_budget_inr=D(2000), capital_budget_inr=D(10000))
    values.update(changes)
    return FrictionAssumptions(**values)


def analyze(**changes):
    values = dict(decision_at=DECISION,intended_lots=1,policy=policy(),session=session(),
        assumptions=assumptions(), enabled=True, provenance="SYNTHETIC_FIXTURE")
    raw_contract = changes.pop("contract_record",contract_record())
    raw_quote = changes.pop("quote_record",quote_record())
    values.update(changes)
    return analyze_option(raw_contract,raw_quote,**values)


class TestOptionFitness(unittest.TestCase):
    def test_default_off_and_only_explicit_true_calculates(self):
        self.assertFalse(OPTION_INTELLIGENCE_ENABLED)
        for flag in (False,1,"true",None):
            self.assertEqual("DISABLED",analyze(enabled=flag).status)
        result = analyze_option(None,None,decision_at=None,intended_lots=0,policy=None,session=None)
        self.assertEqual("DISABLED",result.status)

    def test_tick_rounded_current_friction_and_spread_counted_once(self):
        value = analyze().friction.value
        self.assertEqual(D("100.55"),value.ask_plus_impact_estimate)
        self.assertEqual(D("99.95"),value.current_bid_minus_impact_estimate)
        self.assertEqual(D(25),value.spread_cost_inr)
        self.assertEqual(D(5),value.additional_impact_and_rounding_inr)
        self.assertEqual(D(40),value.snapshot_friction_inr)
        self.assertEqual("NOT_EXECUTED",value.fill_status)

    def test_stage1_premium_example(self):
        raw = quote_record(bid=101,ask=102)
        value = analyze(quote_record=raw,assumptions=assumptions(entry_impact=D(0),exit_impact=D(0),round_trip_fees_inr=D(0))).friction.value
        self.assertEqual(D("66.30"),value.indicative_premium_stop)
        self.assertEqual(D("166.30"),value.indicative_premium_target)
        self.assertEqual(D(1785),value.gross_premium_risk_inr)

    def test_all_three_loss_variants_are_independent_scenarios(self):
        risks=[]
        for fraction in (".25",".35",".45"):
            value = analyze(assumptions=assumptions(premium_loss_fraction=D(fraction))).friction.value
            risks.append(value.gross_premium_risk_inr)
        self.assertLess(risks[0],risks[1])
        self.assertLess(risks[1],risks[2])
        self.assertEqual("INVALID",analyze(assumptions=assumptions(premium_loss_fraction=D(".30"))).friction.state)

    def test_cost_effective_date_availability_and_missing_states(self):
        for a,state,code in ((None,"UNAVAILABLE","COST_ASSUMPTIONS_UNAVAILABLE"),
            (assumptions(effective_to=date(2025,1,1)),"INVALID","INVALID_COST_VALIDITY"),
            (assumptions(effective_from=date(2025,1,1),effective_to=date(2025,12,31)),"UNAVAILABLE","DATED_COST_ASSUMPTIONS_UNAVAILABLE"),
            (assumptions(available_at=DECISION+timedelta(seconds=1)),"UNAVAILABLE","COST_ASSUMPTIONS_NOT_AVAILABLE"),
            (assumptions(entry_impact=D(-1)),"INVALID","NEGATIVE_COST_ASSUMPTION")):
            with self.subTest(code=code):
                evidence = analyze(assumptions=a).friction
                self.assertEqual(state,evidence.state)
                self.assertIn(code,evidence.reason_codes)

    def test_lot_risk_capital_and_budget_sensitivity_are_not_entry_permissions(self):
        normal = analyze().friction.value
        expensive = analyze(assumptions=assumptions(round_trip_fees_inr=D(20),risk_budget_inr=D(1),capital_budget_inr=D(1))).friction.value
        self.assertGreater(expensive.friction_per_gross_risk,normal.friction_per_gross_risk)
        self.assertFalse(expensive.within_declared_risk_budget)
        self.assertFalse(expensive.within_declared_capital_budget)
        self.assertFalse(analyze().eligible)

    def test_stale_missing_and_insufficient_quote_never_get_friction(self):
        for raw in (quote_record(bid_at=DECISION-timedelta(seconds=4)),
                    quote_record(bid=None),quote_record(ask_size=0)):
            result = analyze(quote_record=raw)
            self.assertEqual("UNAVAILABLE",result.friction.state)
            self.assertIsNone(result.friction.value)

    def test_missing_and_invalid_optional_context_do_not_veto_quote(self):
        no_context = analyze()
        invalid_context = analyze(context_record={"provider":"wrong"},context_max_age_seconds=3)
        self.assertEqual("VERIFIED",no_context.quote.evidence.state)
        self.assertEqual("UNAVAILABLE",no_context.context.common_evidence.state)
        self.assertEqual("VERIFIED",invalid_context.quote.evidence.state)
        self.assertEqual("VERIFIED",invalid_context.friction.state)
        self.assertNotEqual("VERIFIED",invalid_context.context.common_evidence.state)

    def test_unknown_source_authority_and_historical_block_always_explicit(self):
        for provenance in ("SYNTHETIC_FIXTURE","UNVERIFIED_CAPTURE"):
            value = analyze(provenance=provenance).to_dict()
            self.assertEqual("NOT_ESTABLISHED",value["source_authenticity"]["state"])
            self.assertEqual("NOT_ESTABLISHED",value["listing_authority"]["state"])
            self.assertEqual(["BLOCKED_DATA_FOR_HISTORICAL_OPTION_PNL"],value["historical_option_pnl"]["reason_codes"])
            for flag in ("actionable","eligible","execution_allowed","historical_replay_allowed"):
                self.assertIs(value[flag],False)

    def test_frozen_results_deterministic_configs_and_finite_json(self):
        result = analyze()
        json.dumps(result.to_dict(),allow_nan=False)
        self.assertEqual(result.config_hash,analyze().config_hash)
        self.assertNotEqual(result.config_hash,analyze(assumptions=assumptions(entry_impact=D(0))).config_hash)
        self.assertEqual(result.to_dict()["analysis_id"],analyze().to_dict()["analysis_id"])
        self.assertEqual(quote_record()["observed_at"].isoformat(),result.to_dict()["as_of"])
        with self.assertRaises(FrozenInstanceError):
            result.actionable=True
        with self.assertRaises(ValueError):
            replace(result,actionable=True)

    def test_missing_tick_and_wrong_contract_stop_before_quote_analysis(self):
        raw=contract_record()
        raw.pop("tick_size")
        result=analyze(contract_record=raw)
        self.assertEqual("UNAVAILABLE",result.identity.state)
        self.assertIsNone(result.quote)
        self.assertEqual("INVALID",analyze(quote_record=quote_record(contract_id="wrong")).quote.evidence.state)

    def test_provenance_must_not_self_assert_broker_verification(self):
        result=analyze(provenance="VERIFIED_BROKER")
        self.assertEqual("INVALID",result.status)

    def test_unserializable_configuration_returns_invalid_evidence(self):
        result=analyze(policy=object())
        self.assertEqual("INVALID",result.status)
        self.assertEqual(("INVALID_RESEARCH_CONFIGURATION",),result.identity.reason_codes)

    def test_public_friction_helper_binds_contract_whole_lots_and_decision(self):
        q = inspect()
        other = contract(identifier="NSE_FO|999998")
        result = estimate_friction(other,q,assumptions(),decision_at=DECISION)
        self.assertEqual(("FRICTION_QUOTE_CONTRACT_MISMATCH",),result.reason_codes)
        fractional = replace(q,metrics=replace(q.metrics,requested_units=49))
        result = estimate_friction(contract(),fractional,assumptions(),decision_at=DECISION)
        self.assertEqual(("FRICTION_QUANTITY_NOT_WHOLE_LOTS",),result.reason_codes)
        result = estimate_friction(contract(),q,assumptions(),decision_at=DECISION+timedelta(seconds=1))
        self.assertEqual(("FRICTION_QUOTE_DECISION_MISMATCH",),result.reason_codes)

    def test_economic_identity_is_invariant_to_decimal_representation(self):
        original = contract()
        equivalent = contract(strike="25000.00",tick_size="0.050")
        self.assertEqual(original.contract_id,equivalent.contract_id)
        self.assertNotEqual(original.contract_id,contract(strike="25000.05").contract_id)


if __name__ == "__main__":
    unittest.main()

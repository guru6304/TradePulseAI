"""Synthetic supplied declarations, never proof these contracts are listed."""
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import unittest
from zoneinfo import ZoneInfo

from option_intelligence.identity import ContractResult, nearest_two_expiries, validate_contract


IST = ZoneInfo("Asia/Kolkata")
DECISION = datetime(2026, 11, 3, 10, 0, tzinfo=IST)


def contract_record(**changes):
    record = dict(
        provider="upstox", identifier="NSE_FO|999999", symbol="NIFTY26NOV0525000CE",
        underlying="NIFTY", underlying_identifier="NSE_INDEX|Nifty 50", exchange="NFO",
        segment="NSE_FO_INDEX", instrument_type="OPTIDX", option_type="CE",
        expiry="2026-11-05", strike="25000", lot_size=50, tick_size="0.05", multiplier=1,
        price_unit="INR", quantity_unit="UNDERLYING_UNITS", valid_from="2026-11-01",
        valid_to="2026-11-05", contract_status="ACTIVE", source="AUTHORED_SYNTHETIC",
        source_revision="synthetic-master-v1", master_id="synthetic-master-1",
        master_sha256="1" * 64, source_observed_at=DECISION - timedelta(seconds=2),
        received_at=DECISION - timedelta(seconds=1), available_at=DECISION,
    )
    record.update(changes)
    return record


def stock_contract_record(**changes):
    record = contract_record(
        identifier="NSE_FO|888888", symbol="RELIANCE26NOV052000CE", underlying="RELIANCE",
        underlying_identifier="NSE_EQ|INE002A01018", segment="NSE_FO_STOCK", instrument_type="OPTSTK",
        strike="2000", lot_size=500,
    )
    record.update(changes)
    return record


def stock_membership_record(**changes):
    record = dict(provider="upstox", underlying="RELIANCE", underlying_identifier="NSE_EQ|INE002A01018",
                  universe="NIFTY200", ordinary_equity=True, source="AUTHORED_SYNTHETIC",
                  source_revision="synthetic-universe-v1", valid_from="2026-10-01",
                  valid_to="2026-11-30", available_at=DECISION - timedelta(days=1))
    record.update(changes)
    return record


class TestOptionIntelligenceIdentity(unittest.TestCase):
    def assertResult(self, raw, state, code, *, decision_at=DECISION, membership=None):
        result = validate_contract(raw, decision_at=decision_at, membership=membership)
        self.assertEqual(state, result.evidence.state)
        self.assertIn(code, result.evidence.reason_codes)
        if state in ("INVALID", "UNAVAILABLE", "STALE"):
            self.assertIsNone(result.contract)
        return result

    def test_supplied_active_contract_is_structurally_checked_only(self):
        result = self.assertResult(contract_record(), "VERIFIED", "SUPPLIED_CONTRACT_FACTS_VALIDATED")
        contract = result.contract
        self.assertEqual(date(2026, 11, 5), contract.expiry)
        self.assertEqual(Decimal("0.05"), contract.tick_size)
        self.assertEqual(Decimal("25000"), contract.strike)
        self.assertEqual("NOT_ESTABLISHED", contract.source_authenticity)
        self.assertEqual("NOT_ESTABLISHED", contract.listing_authority)
        self.assertIn("LISTING_AUTHORITY_NOT_ESTABLISHED", result.evidence.reason_codes)
        self.assertEqual("SUPPLIED_INPUT_VALIDATION_ONLY", result.evidence.scope)

    def test_exact_dated_terms_and_master_reference_change_contract_id(self):
        base = validate_contract(contract_record(), decision_at=DECISION).contract
        for changes in (dict(expiry="2026-11-12", valid_to="2026-11-12"), dict(lot_size=100),
                        dict(tick_size="0.10"), dict(option_type="PE"), dict(strike="25100"),
                        dict(source_revision="v2"), dict(master_id="master2"),
                        dict(master_sha256="2" * 64), dict(identifier="NSE_FO|999998")):
            with self.subTest(changes=changes):
                changed = validate_contract(contract_record(**changes), decision_at=DECISION).contract
                self.assertNotEqual(base.contract_id, changed.contract_id)

    def test_contract_id_stable_reobservation_and_input_order(self):
        raw = contract_record()
        first = validate_contract(raw, decision_at=DECISION).contract
        raw = dict(reversed(tuple(raw.items())))
        raw.update(source_observed_at=DECISION - timedelta(seconds=3),
                   received_at=DECISION - timedelta(seconds=2), available_at=DECISION - timedelta(seconds=1))
        second = validate_contract(raw, decision_at=DECISION).contract
        self.assertEqual(first.contract_id, second.contract_id)

    def test_frozen_contract_and_result(self):
        result = validate_contract(contract_record(), decision_at=DECISION)
        with self.assertRaises(FrozenInstanceError):
            result.contract.lot_size = 0
        with self.assertRaises(FrozenInstanceError):
            result.contract = None

    def test_no_inferred_expiry_tick_lot_or_source_fields(self):
        for field in ("expiry", "identifier", "tick_size", "lot_size", "source_revision", "master_id",
                      "master_sha256", "source_observed_at", "received_at", "available_at"):
            with self.subTest(field=field):
                raw = contract_record()
                del raw[field]
                self.assertResult(raw, "UNAVAILABLE", "MISSING_" + field.upper())

    def test_null_is_unavailable_while_zero_is_invalid(self):
        self.assertResult(contract_record(strike=None), "UNAVAILABLE", "MISSING_STRIKE")
        self.assertResult(contract_record(strike=0), "INVALID", "INVALID_STRIKE")
        self.assertResult(contract_record(tick_size=0), "INVALID", "INVALID_TICK_SIZE")

    def test_no_spot_or_futures_contract_substitution(self):
        self.assertResult(contract_record(exchange="NSE"), "INVALID", "OPTION_EXCHANGE_MISMATCH")
        self.assertResult(contract_record(instrument_type="FUTIDX"), "INVALID", "UNSUPPORTED_OPTION_TYPE")
        self.assertResult(contract_record(segment="NSE_EQUITY_INTRADAY"), "INVALID", "OPTION_SEGMENT_MISMATCH")
        self.assertResult(contract_record(symbol="NIFTY"), "INVALID", "EXACT_CONTRACT_LABEL_REQUIRED")
        self.assertResult(contract_record(identifier="NSE_INDEX|Nifty 50"), "INVALID", "INVALID_PROVIDER_IDENTIFIER")

    def test_supported_provider_token_shapes_remain_distinct(self):
        for provider, option, underlying in (("angelone", "77777", "99926000"),
                                              ("dhan", "77777", "13"),
                                              ("upstox", "NSE_FO|77777", "NSE_INDEX|Nifty 50")):
            with self.subTest(provider=provider):
                self.assertResult(contract_record(provider=provider, identifier=option,
                                                  underlying_identifier=underlying),
                                  "VERIFIED", "SUPPLIED_CONTRACT_FACTS_VALIDATED")
        self.assertResult(contract_record(provider="unknown"), "INVALID", "UNSUPPORTED_PROVIDER")

    def test_malformed_provider_tokens_and_same_token(self):
        for provider, identifier, underlying in (("angelone", "abc", "99926000"),
                                                  ("dhan", "１２３", "13"),
                                                  ("upstox", "NSE_FO|A23", "NSE_INDEX|Nifty 50"),
                                                  ("upstox", "NSE_FO|1|2", "NSE_INDEX|Nifty 50"),
                                                  ("upstox", "NSE_FO|123", "NSE_EQ|INE002A01018")):
            with self.subTest(identifier=identifier):
                self.assertResult(contract_record(provider=provider, identifier=identifier,
                                                  underlying_identifier=underlying),
                                  "INVALID", "INVALID_PROVIDER_IDENTIFIER")
        self.assertResult(contract_record(provider="angelone", identifier="99926000",
                                          underlying_identifier="99926000"),
                          "INVALID", "SPOT_CONTRACT_SUBSTITUTION")

    def test_exact_integer_lot_and_multiplier(self):
        for lot in (0, -1, True, 50.0, "50", Decimal(50), 2**53):
            with self.subTest(lot=lot):
                self.assertResult(contract_record(lot_size=lot), "INVALID", "INVALID_LOT_SIZE")
        self.assertResult(contract_record(multiplier=True), "INVALID", "INVALID_MULTIPLIER")
        self.assertResult(contract_record(multiplier=2), "INVALID", "UNSUPPORTED_CONTRACT_UNITS")

    def test_finite_positive_strike_and_tick(self):
        for value in (True, "NaN", "Infinity", float("inf"), -1):
            with self.subTest(value=value):
                result = validate_contract(contract_record(strike=value), decision_at=DECISION)
                self.assertEqual("INVALID", result.evidence.state)
                self.assertIsNone(result.contract)

    def test_expiry_day_and_expired_contracts_reject(self):
        self.assertResult(contract_record(expiry="2026-11-03", valid_to="2026-11-03"),
                          "INVALID", "EXPIRY_DAY_INELIGIBLE")
        self.assertResult(contract_record(expiry="2026-11-02", valid_to="2026-11-02"),
                          "INVALID", "EXPIRED_CONTRACT")

    def test_reversed_outside_and_expiry_overrun_validity(self):
        self.assertResult(contract_record(valid_from="2026-11-06"), "INVALID", "INVALID_CONTRACT_VALIDITY")
        self.assertResult(contract_record(valid_to="2026-11-06"), "INVALID", "INVALID_CONTRACT_VALIDITY")
        self.assertResult(contract_record(valid_from="2026-11-04"), "UNAVAILABLE", "DATED_CONTRACT_UNAVAILABLE")
        self.assertResult(contract_record(valid_to="2026-11-02"), "UNAVAILABLE", "DATED_CONTRACT_UNAVAILABLE")

    def test_canonical_dates_and_offset_timestamps_required(self):
        for expiry in ("20261105", "2026-11-05T00:00:00+05:30", datetime(2026, 11, 5), "2026-02-30"):
            with self.subTest(expiry=expiry):
                result = validate_contract(contract_record(expiry=expiry), decision_at=DECISION)
                self.assertEqual("INVALID", result.evidence.state)
        self.assertResult(contract_record(), "INVALID", "OFFSET_TIMESTAMP_REQUIRED",
                          decision_at=DECISION.replace(tzinfo=None))
        self.assertResult(contract_record(source_observed_at="2026-11-03 09:59:58"),
                          "INVALID", "OFFSET_TIMESTAMP_REQUIRED")

    def test_source_time_order_and_future_availability(self):
        self.assertResult(contract_record(source_observed_at=DECISION + timedelta(seconds=1)),
                          "INVALID", "INVALID_CONTRACT_CLOCK_ORDER")
        self.assertResult(contract_record(received_at=DECISION + timedelta(seconds=1),
                                          available_at=DECISION + timedelta(seconds=2)),
                          "UNAVAILABLE", "CONTRACT_NOT_YET_AVAILABLE")

    def test_ist_date_from_offset_not_host_timezone(self):
        instant = "2026-11-02T19:00:00+00:00"  # 00:30 on 3 November IST.
        self.assertResult(contract_record(source_observed_at=instant, received_at=instant, available_at=instant,
                                          expiry="2026-11-03", valid_to="2026-11-03"),
                          "INVALID", "EXPIRY_DAY_INELIGIBLE", decision_at=instant)

    def test_unknown_and_inactive_trading_status(self):
        result = self.assertResult(contract_record(contract_status="UNKNOWN"),
                                   "NOT_ESTABLISHED", "TRADING_STATUS_NOT_ESTABLISHED")
        self.assertIsNotNone(result.contract)
        for status in ("INACTIVE", "SUSPENDED", "EXPIRED"):
            with self.subTest(status=status):
                self.assertResult(contract_record(contract_status=status), "INVALID", "CONTRACT_NOT_ACTIVE")
        self.assertResult(contract_record(contract_status="LISTED"), "INVALID", "INVALID_TRADING_STATUS")

    def test_units_side_labels_and_master_digest(self):
        self.assertResult(contract_record(quantity_unit="LOTS"), "INVALID", "UNSUPPORTED_CONTRACT_UNITS")
        self.assertResult(contract_record(price_unit="PAISE"), "INVALID", "UNSUPPORTED_CONTRACT_UNITS")
        self.assertResult(contract_record(option_type="CALL"), "INVALID", "INVALID_OPTION_SIDE")
        self.assertResult(contract_record(symbol="Nifty option"), "INVALID", "EXACT_CONTRACT_LABEL_REQUIRED")
        self.assertResult(contract_record(master_sha256="not-a-digest"), "INVALID", "INVALID_MASTER_SHA256")

    def test_stock_requires_actual_separate_dated_membership_declaration(self):
        self.assertResult(stock_contract_record(), "UNAVAILABLE", "POINT_IN_TIME_NIFTY200_MEMBERSHIP_UNAVAILABLE")
        result = self.assertResult(stock_contract_record(), "VERIFIED", "SUPPLIED_CONTRACT_FACTS_VALIDATED",
                                   membership=stock_membership_record())
        self.assertEqual("OPTSTK", result.contract.instrument_type)
        self.assertResult(stock_contract_record(underlying="NIFTY"), "INVALID", "UNDERLYING_TYPE_MISMATCH",
                          membership=stock_membership_record())

    def test_stock_membership_does_not_imply_derivative_listing(self):
        raw = stock_contract_record()
        del raw["identifier"]
        self.assertResult(raw, "UNAVAILABLE", "MISSING_IDENTIFIER", membership=stock_membership_record())
        self.assertResult(stock_contract_record(contract_status="UNKNOWN"), "NOT_ESTABLISHED",
                          "TRADING_STATUS_NOT_ESTABLISHED", membership=stock_membership_record())

    def test_stock_mapping_identity_must_match_asof(self):
        for changes in (dict(provider="dhan"), dict(underlying="WRONG"),
                        dict(underlying_identifier="NSE_EQ|WRONG")):
            with self.subTest(changes=changes):
                self.assertResult(stock_contract_record(), "INVALID", "MEMBERSHIP_IDENTITY_MISMATCH",
                                  membership=stock_membership_record(**changes))

    def test_stock_membership_effective_dates_and_availability(self):
        for changes, state, code in (
            (dict(valid_to="2026-10-31"), "UNAVAILABLE", "DATED_NIFTY200_MEMBERSHIP_UNAVAILABLE"),
            (dict(valid_from="2026-11-04"), "UNAVAILABLE", "DATED_NIFTY200_MEMBERSHIP_UNAVAILABLE"),
            (dict(available_at=DECISION + timedelta(seconds=1)), "UNAVAILABLE", "MEMBERSHIP_NOT_YET_AVAILABLE"),
            (dict(ordinary_equity=False), "INVALID", "ORDINARY_EQUITY_REQUIRED"),
            (dict(universe="CURRENT_NIFTY200"), "INVALID", "UNSUPPORTED_MEMBERSHIP_UNIVERSE"),
        ):
            with self.subTest(code=code):
                self.assertResult(stock_contract_record(), state, code,
                                  membership=stock_membership_record(**changes))

    def test_missing_membership_evidence_not_defaulted(self):
        member = stock_membership_record()
        del member["source_revision"]
        self.assertResult(stock_contract_record(), "UNAVAILABLE", "MISSING_SOURCE_REVISION", membership=member)

    def test_authenticity_and_listing_flags_cannot_self_certify(self):
        result = validate_contract(contract_record(source_authenticity="VERIFIED", listing_authority="VERIFIED",
                                                  broker_accepted=True), decision_at=DECISION)
        self.assertEqual("NOT_ESTABLISHED", result.contract.source_authenticity)
        self.assertEqual("NOT_ESTABLISHED", result.contract.listing_authority)

    def test_nearest_two_dates_only_within_supplied_scope(self):
        results = tuple(validate_contract(contract_record(expiry=expiry, valid_to=expiry,
                                                          identifier="NSE_FO|" + str(900000 + index)),
                                          decision_at=DECISION)
                        for index, expiry in enumerate(("2026-11-26", "2026-11-05", "2026-11-12")))
        selection = nearest_two_expiries(results, decision_at=DECISION)
        self.assertEqual((date(2026, 11, 5), date(2026, 11, 12)), selection.expiries)
        self.assertEqual("NOT_ESTABLISHED", selection.evidence.state)
        self.assertEqual("SUPPLIED_CONTRACT_RECORDS_ONLY", selection.scope)
        self.assertFalse(selection.complete_universe_established)

    def test_nearest_selection_reports_partial_and_excluded_records(self):
        good = validate_contract(contract_record(), decision_at=DECISION)
        bad = validate_contract(contract_record(lot_size=0), decision_at=DECISION)
        selection = nearest_two_expiries((good, bad), decision_at=DECISION)
        self.assertEqual((date(2026, 11, 5),), selection.expiries)
        self.assertIn("FEWER_THAN_TWO_ELIGIBLE_SUPPLIED_EXPIRIES", selection.evidence.reason_codes)
        self.assertIn("UNUSABLE_SUPPLIED_RECORDS_EXCLUDED", selection.evidence.reason_codes)

    def test_nearest_selection_deduplicates_same_expiry_and_excludes_expiry_day(self):
        one = validate_contract(contract_record(), decision_at=DECISION)
        two = validate_contract(contract_record(identifier="NSE_FO|777777", option_type="PE"), decision_at=DECISION)
        selection = nearest_two_expiries((one, two), decision_at=DECISION)
        self.assertEqual((date(2026, 11, 5),), selection.expiries)
        selection = nearest_two_expiries((one,), decision_at=DECISION + timedelta(days=2))
        self.assertEqual("UNAVAILABLE", selection.evidence.state)
        self.assertEqual((), selection.expiries)

    def test_nearest_selection_rejects_mixed_underlying_or_provider(self):
        one = validate_contract(contract_record(), decision_at=DECISION)
        for raw in (contract_record(underlying="BANKNIFTY", underlying_identifier="NSE_INDEX|Nifty Bank"),
                    contract_record(provider="dhan", identifier="77777", underlying_identifier="13")):
            two = validate_contract(raw, decision_at=DECISION)
            selection = nearest_two_expiries((one, two), decision_at=DECISION)
            self.assertEqual("INVALID", selection.evidence.state)
            self.assertIn("MIXED_CONTRACT_SELECTION_SCOPE", selection.evidence.reason_codes)

    def test_invalid_record_and_selection_inputs(self):
        self.assertResult(None, "INVALID", "INVALID_CONTRACT_RECORD")
        self.assertResult([], "INVALID", "INVALID_CONTRACT_RECORD")
        self.assertResult(contract_record(symbol="bad\nlabel"), "INVALID", "INVALID_SYMBOL")
        for inputs in (None, [None], [contract_record()]):
            selection = nearest_two_expiries(inputs, decision_at=DECISION)
            self.assertEqual("INVALID", selection.evidence.state)
        self.assertEqual("UNAVAILABLE", nearest_two_expiries((), decision_at=DECISION).evidence.state)


if __name__ == "__main__":
    unittest.main()

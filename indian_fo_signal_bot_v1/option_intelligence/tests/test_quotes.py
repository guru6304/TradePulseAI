"""Synthetic source-identity, quote-clock, spread, lot and displayed-depth cases."""
from dataclasses import replace
from datetime import datetime, time, timedelta
from decimal import Decimal as D
import unittest

from option_intelligence.evidence import IST
from option_intelligence.identity import validate_contract
from option_intelligence.quotes import (QuotePolicy, SessionWindow, inspect_depth, inspect_quote)
from .test_identity import DECISION, contract_record, stock_contract_record, stock_membership_record


def contract(**changes):
    return validate_contract(contract_record(**changes), decision_at=DECISION).contract


def policy(**changes):
    values = dict(source_id="AUTHORED_QUOTE", evidence_reference="SYNTHETIC_CLOCK_AND_CADENCE",
        available_at=DECISION-timedelta(days=1), documented_cadence_seconds=D(1),
        timestamp_resolution_seconds=D(".001"))
    values.update(changes)
    return QuotePolicy(**values)


def session(**changes):
    values = dict(session_date=DECISION.date(),
        open_at=datetime.combine(DECISION.date(), time(9,15), IST),
        close_at=datetime.combine(DECISION.date(), time(15,30), IST),
        phase="NORMAL", source_reference="SYNTHETIC_DECLARED_CALENDAR",
        available_at=DECISION-timedelta(days=1))
    values.update(changes)
    return SessionWindow(**values)


def quote_record(c=None, **changes):
    c = c or contract()
    values = dict(quote_id="AUTHORED_QUOTE_1", provider=c.provider,
        contract_id=c.contract_id, source_revision=c.source_revision, source_id="AUTHORED_QUOTE",
        observed_at=DECISION-timedelta(seconds=1), received_at=DECISION-timedelta(milliseconds=500),
        available_at=DECISION, bid_at=DECISION-timedelta(seconds=1),
        ask_at=DECISION-timedelta(seconds=1), bid="100.00", ask="100.50",
        bid_size=c.lot_size, ask_size=c.lot_size,
        price_unit="INR", quantity_unit="UNDERLYING_UNITS")
    values.update(changes)
    return values


def inspect(raw=None, c=None, **changes):
    c = c or contract()
    args = dict(decision_at=DECISION, intended_lots=1, policy=policy(), session=session())
    args.update(changes)
    return inspect_quote(raw if raw is not None else quote_record(c), c, **args)


def depth_record(c=None, **changes):
    c = c or contract()
    raw = quote_record(c)
    for field in ("bid", "ask", "bid_size", "ask_size", "bid_at", "ask_at", "quote_id"):
        raw.pop(field)
    raw.update(bids=[dict(price="100", quantity=c.lot_size), dict(price="99.95", quantity=c.lot_size)],
               asks=[dict(price="100.50", quantity=c.lot_size), dict(price="100.55", quantity=c.lot_size)])
    raw.update(changes)
    return raw


class TestOptionQuotes(unittest.TestCase):
    def assertEvidence(self, result, state, code):
        evidence = result.evidence if hasattr(result, "evidence") else result
        self.assertEqual(state, evidence.state)
        self.assertIn(code, evidence.reason_codes)

    def test_valid_supplied_book_math_and_no_fillability_claim(self):
        result = inspect()
        self.assertEqual("VERIFIED", result.evidence.state)
        self.assertEqual(D("100.25"), result.metrics.mid)
        self.assertEqual(D(".5"), result.metrics.spread)
        self.assertEqual(D(".5")/D("100.25"), result.metrics.relative_spread)
        self.assertEqual(D(1), result.metrics.displayed_size_ratio)
        self.assertEqual("NOT_ESTABLISHED", result.metrics.fillability)

    def test_identity_provider_revision_and_source_are_exact(self):
        for key,value,code in (("contract_id","wrong","QUOTE_CONTRACT_IDENTITY_MISMATCH"),
            ("provider","angelone","QUOTE_CONTRACT_IDENTITY_MISMATCH"),
            ("source_revision","different","QUOTE_CONTRACT_IDENTITY_MISMATCH"),
            ("source_id","other","QUOTE_SOURCE_MISMATCH")):
            with self.subTest(key=key):
                self.assertEvidence(inspect(quote_record(**{key:value})), "INVALID", code)

    def test_no_ltp_or_underlying_or_missing_bid_fallback(self):
        raw = quote_record(ltp=101, underlying_spot=25000)
        raw.pop("bid")
        self.assertEvidence(inspect(raw), "UNAVAILABLE", "BID_UNAVAILABLE")
        self.assertEvidence(inspect(quote_record(ask=None)), "UNAVAILABLE", "ASK_UNAVAILABLE")

    def test_zero_crossed_and_locked_books(self):
        for values,code in ((dict(bid=0),"NONPOSITIVE_OR_CROSSED_BOOK"),
            (dict(bid=101),"NONPOSITIVE_OR_CROSSED_BOOK"),
            (dict(ask=100),"LOCKED_BOOK_EXCLUDED_BY_RESEARCH_POLICY")):
            with self.subTest(values=values):
                self.assertEvidence(inspect(quote_record(**values)), "INVALID", code)

    def test_numerical_tick_and_unit_errors(self):
        for values,code in ((dict(bid=True),"INVALID_NUMERIC_INPUT"),
            (dict(bid="NaN"),"INVALID_NUMERIC_INPUT"),
            (dict(bid="1e9999999"),"NUMERIC_INPUT_OUT_OF_BOUNDS"),
            (dict(bid="1e-9999999"),"NUMERIC_INPUT_OUT_OF_BOUNDS"),
            (dict(bid="100.01"),"QUOTE_PRICE_OFF_TICK"),
            (dict(price_unit="INDEX_POINTS"),"QUOTE_PRICE_UNIT_MISMATCH"),
            (dict(bid_size=".5"),"INVALID_QUOTE_SIZE"),
            (dict(bid_size=-1),"INVALID_QUOTE_SIZE")):
            with self.subTest(values=values):
                self.assertEvidence(inspect(quote_record(**values)), "INVALID", code)

    def test_exact_three_second_age_and_just_stale(self):
        raw = quote_record(bid_at=DECISION-timedelta(seconds=3), ask_at=DECISION-timedelta(seconds=3),
                           observed_at=DECISION-timedelta(seconds=3))
        self.assertEqual("VERIFIED", inspect(raw).evidence.state)
        raw.update(bid_at=DECISION-timedelta(seconds=3,microseconds=1))
        self.assertEvidence(inspect(raw), "STALE", "QUOTE_TOO_OLD")

    def test_leg_skew_and_future_availability(self):
        self.assertEvidence(inspect(quote_record(bid_at=DECISION-timedelta(seconds=2,microseconds=1))),
                            "STALE", "QUOTE_LEGS_NOT_SYNCHRONIZED")
        self.assertEvidence(inspect(quote_record(available_at=DECISION+timedelta(seconds=1))),
                            "UNAVAILABLE", "QUOTE_NOT_YET_AVAILABLE")

    def test_clock_order_naive_and_missing_source_time(self):
        self.assertEvidence(inspect(quote_record(received_at=DECISION-timedelta(seconds=2))),
                            "INVALID", "INVALID_QUOTE_CLOCK_ORDER")
        self.assertEvidence(inspect(quote_record(bid_at=DECISION.replace(tzinfo=None))),
                            "INVALID", "OFFSET_TIMESTAMP_REQUIRED")
        self.assertEvidence(inspect(quote_record(bid_at=None)), "UNAVAILABLE", "BID_AT_UNAVAILABLE")

    def test_previous_session_is_stale(self):
        self.assertEvidence(inspect(quote_record(observed_at=DECISION-timedelta(days=1))),
                            "STALE", "QUOTE_SESSION_STALE")

    def test_cadence_clock_evidence_is_mandatory_for_age_claim(self):
        for kwargs in (dict(evidence_reference=None), dict(documented_cadence_seconds=None),
                       dict(timestamp_resolution_seconds=None)):
            self.assertEvidence(inspect(policy=policy(**kwargs)), "NOT_ESTABLISHED",
                                "QUOTE_CADENCE_OR_CLOCK_EVIDENCE_NOT_ESTABLISHED")
        self.assertEvidence(inspect(policy=policy(documented_cadence_seconds=D(5))),
                            "NOT_ESTABLISHED", "QUOTE_CADENCE_OR_CLOCK_UNSUPPORTED")
        self.assertEvidence(inspect(policy=policy(max_leg_skew_seconds=D(0))),
                            "NOT_ESTABLISHED", "LEG_ALIGNMENT_PRECISION_UNSUPPORTED")

    def test_declared_closed_special_and_unknown_calendar(self):
        self.assertEvidence(inspect(session=session(phase="CLOSED")), "UNAVAILABLE", "CLOSED_SESSION")
        self.assertEvidence(inspect(session=session(phase="SPECIAL")), "NOT_ESTABLISHED",
                            "SPECIAL_SESSION_POLICY_NOT_ESTABLISHED")
        self.assertEvidence(inspect(session=None), "NOT_ESTABLISHED", "SESSION_CALENDAR_NOT_ESTABLISHED")

    def test_unit_conversion_is_explicit_and_lot_multiples_exact(self):
        result = inspect(quote_record(quantity_unit="CONTRACTS", bid_size=2, ask_size=2), intended_lots=2)
        self.assertEqual(100, result.metrics.bid_units)
        self.assertEqual(100, result.metrics.requested_units)
        self.assertEqual("VERIFIED", result.evidence.state)
        self.assertEvidence(inspect(quote_record(quantity_unit="UNKNOWN")), "NOT_ESTABLISHED",
                            "QUANTITY_UNIT_NOT_ESTABLISHED")
        self.assertEvidence(inspect(intended_lots=True), "INVALID", "INVALID_LOT_COUNT")

    def test_insufficient_size_preserves_numbers_and_does_not_fake_liquidity(self):
        for values in (dict(bid_size=0), dict(ask_size=49)):
            result = inspect(quote_record(**values))
            self.assertEvidence(result, "UNAVAILABLE", "INSUFFICIENT_DISPLAYED_SIZE")
            self.assertIsNotNone(result.metrics)

    def test_index_pilot_spread_boundary_is_comparison_not_source_validity(self):
        exact = inspect(quote_record(bid="99.5", ask="100.5"))
        self.assertTrue(exact.metrics.within_pilot_spread)
        wide = inspect(quote_record(bid="99.45", ask="100.55"))
        self.assertFalse(wide.metrics.within_pilot_spread)
        self.assertEqual("VERIFIED", wide.evidence.state)

    def test_stock_pilot_spread_boundary(self):
        c = validate_contract(stock_contract_record(), decision_at=DECISION,
                              membership=stock_membership_record()).contract
        result = inspect(quote_record(c, bid=99, ask=101), c)
        self.assertEqual(D(".02"), result.metrics.relative_spread)
        self.assertTrue(result.metrics.within_pilot_spread)

    def test_depth_missing_sorted_totals_and_not_executed_flow(self):
        c, q = contract(), inspect().metrics
        self.assertEqual("UNAVAILABLE", inspect_depth(None,c,q,decision_at=DECISION,policy=policy()).state)
        depth = inspect_depth(depth_record(),c,q,decision_at=DECISION,policy=policy())
        self.assertEqual("VERIFIED", depth.state)
        self.assertEqual(100, depth.value.bid_total_units)
        self.assertEqual("NOT_ESTABLISHED", depth.value.execution_guarantee)

    def test_depth_mismatched_top_unsorted_stale_and_wrong_source(self):
        c,q = contract(),inspect().metrics
        cases = ((depth_record(bids=[dict(price=100,quantity=49)]), "INVALID", "DEPTH_TOP_QUOTE_MISMATCH"),
            (depth_record(bids=[dict(price=100,quantity=50),dict(price=101,quantity=50)]),
             "INVALID", "UNSORTED_OR_DUPLICATE_DEPTH"),
            (depth_record(observed_at=DECISION-timedelta(seconds=4)), "STALE", "DEPTH_TOO_OLD"),
            (depth_record(source_id="wrong"), "INVALID", "QUOTE_SOURCE_MISMATCH"))
        for raw,state,code in cases:
            with self.subTest(code=code):
                self.assertEvidence(inspect_depth(raw,c,q,decision_at=DECISION,policy=policy()),state,code)

    def test_deeper_depth_does_not_replace_missing_top_size(self):
        q = inspect(quote_record(bid_size=49,ask_size=49))
        d = depth_record(bids=[dict(price=100,quantity=49),dict(price="99.95",quantity=1000)],
                         asks=[dict(price="100.5",quantity=49),dict(price="100.55",quantity=1000)])
        depth = inspect_depth(d,contract(),q.metrics,decision_at=DECISION,policy=policy())
        self.assertTrue(depth.value.bid_displayed_coverage)
        self.assertEqual("UNAVAILABLE", q.evidence.state)

    def test_depth_cannot_join_quote_of_another_contract_or_decision(self):
        other = contract(identifier="NSE_FO|999998")
        result = inspect_depth(depth_record(other),other,inspect().metrics,
                               decision_at=DECISION,policy=policy())
        self.assertEvidence(result,"INVALID","DEPTH_QUOTE_CONTRACT_MISMATCH")
        result = inspect_depth(depth_record(),contract(),inspect().metrics,
                               decision_at=DECISION+timedelta(seconds=1),policy=policy())
        self.assertEvidence(result,"UNAVAILABLE","DEPTH_QUOTE_DECISION_MISMATCH")


if __name__ == "__main__":
    unittest.main()

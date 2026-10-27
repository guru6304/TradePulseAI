"""Authored native-shaped option fixtures; no provider or execution acceptance."""
import copy
import hashlib
import json
import os
import sys
import unittest
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]

from instrument_identity import CONTRACT_MASTER_SCHEMA, prepare_contract_master
from option_observations import (
    ANGEL_GREEKS, UPSTOX_V2_CHAIN, UPSTOX_V3_GREEKS, ObservationError,
    compare_oi, inspect_depth, parse_option_capture,
)


def setUpModule():
    guard = patch.dict(os.environ, _fixtures._test_config_defaults)
    guard.start()
    unittest.addModuleCleanup(guard.stop)


class TestOptionObservations(unittest.TestCase):
    def setUp(self):
        self.times = dict(received_at="2026-10-16T10:00:00+05:30",
                          available_at="2026-10-16T10:00:01+05:30",
                          decision_at="2026-10-16T10:00:02+05:30")
        self.master = self.make_master("upstox")
        self.angel_master = self.make_master("angelone")
        self.request = dict(underlying_key="NSE_INDEX|Nifty 50", expiry_date="2026-10-29")

    def make_master(self, provider, *, captured_at="2026-10-16T09:00:00+05:30", valid_from="2026-10-01"):
        index_key = "NSE_INDEX|Nifty 50" if provider == "upstox" else "99926000"
        prefix = "NSE_FO|" if provider == "upstox" else ""
        common = dict(exchange="NSE", segment="NSE_FO_INDEX", instrument_type="INDEX_SPOT",
            symbol="NIFTY", identifier=index_key, price_unit="INDEX_POINTS", quantity_unit="NOT_EXECUTABLE",
            valid_from=valid_from, valid_to="2026-10-29", contract_status="ACTIVE")
        records = [common]
        for token, side in (("50001", "CE"), ("50002", "PE")):
            records.append(dict(exchange="NFO", segment="NSE_FO_INDEX", instrument_type="OPTIDX",
                symbol="NIFTY29OCT202625000" + side, identifier=prefix + token,
                underlying="NIFTY", underlying_identifier=index_key, expiry="2026-10-29", strike=25000,
                option_type=side, lot_size=25, multiplier=1, price_unit="INR", quantity_unit="UNDERLYING_UNITS",
                valid_from=valid_from, valid_to="2026-10-29", contract_status="ACTIVE"))
        # Normalized-master LIVE defaults are declarations required by the existing
        # identity parser. This authored capture remains SYNTHETIC_FIXTURE.
        raw = json.dumps(dict(schema_version=CONTRACT_MASTER_SCHEMA, provider=provider, records=records)).encode()
        master = prepare_contract_master(raw, provider=provider, source_reference="offline-authored-option-master.json",
            source_version="synthetic-option-fixture-v1", captured_at=captured_at)
        self.assertEqual(master["status"], "BLOCKED_UNQUALIFIED_MASTER")
        return master

    def chain(self):
        def leg(token, delta):
            return dict(instrument_key="NSE_FO|" + token,
                market_data=dict(ltp=125.5, volume=1000, oi=2000, prev_oi=1800,
                                 bid_price=125, bid_qty=75, ask_price=126, ask_qty=100),
                option_greeks=dict(delta=delta, gamma=0.002, theta=-3.4, vega=9.5, iv=12.5, pop=0.61))
        return dict(status="success", data=[dict(expiry="2026-10-29", strike_price=25000,
            underlying_key="NSE_INDEX|Nifty 50", underlying_spot_price=25010, pcr=1.2,
            call_options=leg("50001", 0.45), put_options=leg("50002", -0.55))])

    def v3(self):
        def row(token, delta):
            return dict(instrument_token="NSE_FO|" + token, last_price=125.5, ltq=25, volume=1000,
                        cp=120, oi=2000, iv=0.125, delta=delta, gamma=0.002, theta=-3.4, vega=9.5)
        return dict(status="success", data={"NFO:arbitrary_call_label": row("50001", 0.45),
                                            "NFO:arbitrary_put_label": row("50002", -0.55)})

    def angel(self):
        def row(side, delta):
            return dict(name="NIFTY", expiry="29OCT2026", strikePrice="25000.000000", optionType=side,
                delta=delta, gamma="0.002", theta="-3.4", vega="9.5", impliedVolatility="12.5", tradeVolume="1000.00")
        return dict(status=True, message="SUCCESS", errorcode="", data=[row("CE", "0.450000"), row("PE", "-0.550000")])

    def parse(self, payload=None, *, endpoint=UPSTOX_V2_CHAIN, request=None, master=None, raw=None,
              provenance="SYNTHETIC_FIXTURE", **times):
        if payload is None and raw is None:
            payload = self.chain()
        if request is None:
            request = (self.request if endpoint == UPSTOX_V2_CHAIN else
                       dict(instrument_keys=["NSE_FO|50001", "NSE_FO|50002"]) if endpoint == UPSTOX_V3_GREEKS else
                       dict(name="NIFTY", expirydate="29OCT2026"))
        if master is None:
            master = self.angel_master if endpoint == ANGEL_GREEKS else self.master
        arguments = dict(self.times, **times)
        return parse_option_capture(raw if raw is not None else json.dumps(payload).encode(),
            endpoint=endpoint, request=request, master=master, provenance=provenance, **arguments)

    def assert_rejected(self, *args, **kwargs):
        with self.assertRaises(ObservationError) as caught:
            self.parse(*args, **kwargs)
        self.assertIsInstance(caught.exception.code, str)
        self.assertTrue(caught.exception.code)

    def test_native_chain_preserves_exact_identities_raw_binding_and_unavailable_units(self):
        payload = self.chain()
        raw = json.dumps(payload).encode()
        result = self.parse(raw=raw)
        self.assertEqual(result["schema_version"], "tradepulse.option-capture.v1")
        self.assertEqual(result["status"], "STRUCTURALLY_VALID_UNQUALIFIED")
        self.assertEqual(result["raw_text"], raw.decode())
        self.assertEqual(result["raw_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["raw_size_bytes"], len(raw))
        self.assertEqual(result["master_id"], self.master["master_id"])
        self.assertEqual(result["master_sha256"], self.master["metadata"]["original_sha256"])
        self.assertEqual(result["master_metadata"], self.master["metadata"])
        self.assertEqual({row["identity"]["identifier"] for row in result["observations"]},
                         {"NSE_FO|50001", "NSE_FO|50002"})
        for row in result["observations"]:
            self.assertEqual(row["underlying_identity"]["identifier"], "NSE_INDEX|Nifty 50")
            self.assertIsNone(row["source_time"])
            self.assertTrue(row["locator"])
            for field in row["fields"].values():
                self.assertIsNone(field["normalized_value"])
                self.assertEqual(field["unit_status"], "UNAVAILABLE_UNIT_CONTRACT")
                if field["presence"] != "ABSENT":
                    self.assertTrue(field["raw_path"])
        for key in ("actionable", "eligible", "historical_replay_allowed"):
            self.assertIs(result[key], False)

    def test_absent_null_and_observed_zero_remain_distinct(self):
        payload = self.chain()
        call = payload["data"][0]["call_options"]
        del call["option_greeks"]["iv"]
        call["option_greeks"]["gamma"] = None
        call["market_data"]["oi"] = 0
        row = next(row for row in self.parse(payload)["observations"] if row["identity"]["option_type"] == "CE")
        fields = row["fields"]
        self.assertEqual(fields["iv"]["presence"], "ABSENT")
        self.assertEqual(fields["gamma"]["presence"], "NULL")
        self.assertIsNone(fields["iv"]["numeric_value"])
        self.assertIsNone(fields["gamma"]["numeric_value"])
        self.assertEqual(fields["oi"]["presence"], "OBSERVED")
        self.assertEqual(fields["oi"]["raw_value"], 0)
        self.assertEqual(fields["oi"]["numeric_value"], 0)

    def test_v3_nested_tokens_resolve_and_cp_is_previous_price_not_previous_oi(self):
        result = self.parse(self.v3(), endpoint=UPSTOX_V3_GREEKS)
        self.assertEqual(result["missing_identifiers"], [])
        for row in result["observations"]:
            self.assertIn(row["identity"]["identifier"], ("NSE_FO|50001", "NSE_FO|50002"))
            self.assertEqual(row["fields"]["previous_close"]["numeric_value"], 120)
            self.assertEqual(row["fields"]["previous_oi"]["presence"], "ABSENT")
            self.assertEqual(row["fields"]["bid_price"]["presence"], "ABSENT")
            self.assertEqual(row["fields"]["iv"]["numeric_value"], 0.125)
            self.assertIsNone(row["fields"]["iv"]["normalized_value"])

    def test_v3_partial_scope_reports_missing_identifiers_without_fabricating_rows(self):
        payload = self.v3()
        del payload["data"]["NFO:arbitrary_put_label"]
        result = self.parse(payload, endpoint=UPSTOX_V3_GREEKS)
        self.assertEqual(result["missing_identifiers"], ["NSE_FO|50002"])
        self.assertEqual(len(result["observations"]), 1)
        self.assertFalse(result["eligible"])

    def test_angel_numeric_strings_and_signed_greeks_keep_raw_values(self):
        result = self.parse(self.angel(), endpoint=ANGEL_GREEKS)
        self.assertEqual(len(result["observations"]), 2)
        put = next(row for row in result["observations"] if row["identity"]["option_type"] == "PE")
        self.assertEqual(put["identity"]["identifier"], "50002")
        self.assertEqual(put["fields"]["delta"]["raw_value"], "-0.550000")
        self.assertAlmostEqual(put["fields"]["delta"]["numeric_value"], -0.55)
        self.assertAlmostEqual(put["fields"]["theta"]["numeric_value"], -3.4)
        self.assertEqual(put["fields"]["volume"]["numeric_value"], 1000)
        self.assertEqual(put["fields"]["ltp"]["presence"], "ABSENT")
        self.assertIsNone(put["source_time"])

    def test_endpoint_iv_magnitudes_are_never_guessed_into_a_common_scale(self):
        chain = self.parse()["observations"][0]["fields"]["iv"]
        greek = self.parse(self.v3(), endpoint=UPSTOX_V3_GREEKS)["observations"][0]["fields"]["iv"]
        self.assertEqual((chain["numeric_value"], greek["numeric_value"]), (12.5, 0.125))
        self.assertIsNone(chain["normalized_value"])
        self.assertIsNone(greek["normalized_value"])

    def test_nonzero_iv_underflow_rejects_while_smallest_positive_float_survives(self):
        payload = self.chain()
        payload["data"][0]["call_options"]["option_greeks"]["iv"] = "5e-324"
        call = next(row for row in self.parse(payload)["observations"] if row["identity"]["option_type"] == "CE")
        self.assertEqual(call["fields"]["iv"]["presence"], "OBSERVED")
        self.assertEqual(call["fields"]["iv"]["raw_value"], "5e-324")
        self.assertEqual(call["fields"]["iv"]["numeric_value"], float("5e-324"))
        self.assertGreater(call["fields"]["iv"]["numeric_value"], 0)
        self.assertIsNone(call["fields"]["iv"]["normalized_value"])
        payload["data"][0]["call_options"]["option_greeks"]["iv"] = "1e-999"
        self.assert_rejected(payload)

    def test_excessive_exponents_and_numeric_strings_raise_observation_errors(self):
        for value in ("1e999999999", "1e-999999999", "9" * 65, " 12.5", "12.5 ", "1e+"):
            with self.subTest(value=value):
                payload = self.angel()
                payload["data"][0]["impliedVolatility"] = value
                self.assert_rejected(payload, endpoint=ANGEL_GREEKS)

    def test_boolean_nonfinite_malformed_negative_and_fractional_counts_reject(self):
        for field, value in (("ltp", True), ("ltp", "NaN"), ("ltp", float("nan")),
                             ("ltp", "1.2.3"), ("ltp", -1), ("volume", 1.5),
                             ("oi", "10.5"), ("bid_qty", False), ("ask_qty", -1)):
            with self.subTest(field=field, value=value):
                payload = self.chain()
                payload["data"][0]["call_options"]["market_data"][field] = value
                self.assert_rejected(payload)
        for value in (True, "Infinity", "invalid", float("inf")):
            with self.subTest(greek=value):
                payload = self.angel()
                payload["data"][0]["delta"] = value
                self.assert_rejected(payload, endpoint=ANGEL_GREEKS)

    def test_raw_duplicate_fields_malformed_encoding_and_byte_limit_reject(self):
        for raw in (b'{"status":"success","status":"success","data":[]}', b'\xff', b'{',
                    b'{"status":"success","data":NaN}', b' ' * (2 * 1024 * 1024 + 1)):
            with self.subTest(raw_prefix=raw[:50]):
                self.assert_rejected(raw=raw)

    def test_chain_wrong_underlying_expiry_strike_token_and_leg_side_reject(self):
        for field, value in (("underlying_key", "NSE_INDEX|Nifty Bank"), ("expiry", "2026-11-05"),
                             ("strike_price", 25100), ("strike_price", True)):
            with self.subTest(field=field):
                payload = self.chain()
                payload["data"][0][field] = value
                self.assert_rejected(payload)
        for token in ("NSE_FO|99999", "NSE_FO|50002", "NSE_INDEX|Nifty 50"):
            with self.subTest(token=token):
                payload = self.chain()
                payload["data"][0]["call_options"]["instrument_key"] = token
                self.assert_rejected(payload)

    def test_duplicate_chain_rows_and_v3_unsolicited_or_duplicate_tokens_reject(self):
        payload = self.chain()
        payload["data"].append(copy.deepcopy(payload["data"][0]))
        self.assert_rejected(payload)
        for token in ("NSE_FO|50001", "NSE_FO|99999"):
            with self.subTest(token=token):
                payload = self.v3()
                payload["data"]["NFO:arbitrary_put_label"]["instrument_token"] = token
                self.assert_rejected(payload, endpoint=UPSTOX_V3_GREEKS)
        self.assert_rejected(self.v3(), endpoint=UPSTOX_V3_GREEKS,
                             request=dict(instrument_keys=["NSE_FO|50001", "NSE_FO|50001"]))

    def test_angel_exact_echo_terms_and_unique_contracts_are_required(self):
        for field, value in (("name", "BANKNIFTY"), ("expiry", "05NOV2026"),
                             ("strikePrice", "25100"), ("optionType", "FUT")):
            with self.subTest(field=field):
                payload = self.angel()
                payload["data"][0][field] = value
                self.assert_rejected(payload, endpoint=ANGEL_GREEKS)
        payload = self.angel()
        payload["data"].append(copy.deepcopy(payload["data"][0]))
        self.assert_rejected(payload, endpoint=ANGEL_GREEKS)

    def test_missing_naive_future_or_reversed_local_clocks_reject(self):
        for change in (dict(received_at=None), dict(received_at="2026-10-16T10:00:00"),
                       dict(available_at="2026-10-16T09:59:59+05:30"),
                       dict(decision_at="2026-10-16T10:00:00+05:30"),
                       dict(received_at="2026-10-16T08:59:59+05:30")):
            with self.subTest(change=change):
                self.assert_rejected(**change)
        undated = self.make_master("upstox", captured_at=None)
        self.assert_rejected(master=undated)

    def test_received_exchange_date_not_utc_calendar_date_resolves_master(self):
        master = self.make_master("upstox", captured_at="2026-10-15T19:00:00+00:00", valid_from="2026-10-16")
        result = self.parse(master=master, received_at="2026-10-15T20:00:00+00:00",
            available_at="2026-10-15T20:00:01+00:00", decision_at="2026-10-15T20:00:02+00:00")
        self.assertEqual(len(result["observations"]), 2)

    def test_master_normalized_fact_or_bytes_tamper_and_wrong_provider_reject(self):
        altered = copy.deepcopy(self.master)
        option = next(row for row in altered["records"] if row["instrument_type"] == "OPTIDX")
        option["strike"] = 25100
        self.assert_rejected(master=altered)
        altered = copy.deepcopy(self.master)
        altered["original_bytes"] += b' '
        self.assert_rejected(master=altered)
        self.assert_rejected(master=self.angel_master)

    def test_expired_and_not_yet_effective_master_contracts_reject(self):
        self.assert_rejected(received_at="2026-10-30T10:00:00+05:30",
            available_at="2026-10-30T10:00:01+05:30", decision_at="2026-10-30T10:00:02+05:30")
        self.assert_rejected(master=self.make_master("upstox", valid_from="2026-10-17"))

    def test_capture_is_deterministic_does_not_mutate_inputs_or_infer_source_time(self):
        payload = self.chain()
        master, request = copy.deepcopy(self.master), copy.deepcopy(self.request)
        before = copy.deepcopy((payload, master, request))
        with patch("urllib.request.urlopen", side_effect=AssertionError("No provider transport")), \
                patch("socket.create_connection", side_effect=AssertionError("No provider transport")):
            first = self.parse(payload, master=master, request=request)
            repeated = self.parse(payload, master=master, request=request)
        self.assertEqual(first, repeated)
        self.assertEqual((payload, master, request), before)
        self.assertTrue(all(row["source_time"] is None for row in first["observations"]))
        for provenance in ("SYNTHETIC_FIXTURE", "UNVERIFIED_CAPTURE"):
            result = self.parse(provenance=provenance)
            self.assertFalse(result["actionable"])
            self.assertFalse(result["eligible"])
            self.assertFalse(result["historical_replay_allowed"])
        self.assert_rejected(provenance="VERIFIED_PROVIDER")

    def test_native_json_numeric_precision_cannot_hide_zero_or_fractional_counts(self):
        encoded = json.dumps(self.chain())
        for old, new in (('"iv": 12.5', '"iv": 1e-999'),
                         ('"volume": 1000', '"volume": 1.00000000000000001'),
                         ('"oi": 2000', '"oi": 1e-999')):
            with self.subTest(replacement=new):
                self.assertIn(old, encoded)
                with self.assertRaises(ObservationError):
                    self.parse(raw=encoded.replace(old, new).encode())
        # Canonical native finite decimals remain usable as unqualified facts.
        observed = self.parse(raw=encoded.replace('"iv": 12.5', '"iv": 0.1').encode())
        self.assertEqual(observed["observations"][0]["fields"]["iv"]["raw_value"], 0.1)

    def test_invalid_offset_minutes_cannot_be_silently_normalized(self):
        with self.assertRaises(ObservationError):
            self.parse(received_at="2026-10-16T11:00:00+05:99",
                       available_at="2026-10-16T11:00:01+05:99",
                       decision_at="2026-10-16T11:00:02+05:99")

    def test_actual_option_execution_rejects_snapshot_even_with_replay_labels(self):
        from backtest_engine import BacktestEligibilityError
        from test_option_execution import TestOptionExecution
        fixture = TestOptionExecution()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        capture = self.parse()
        fixture.data = capture
        with self.assertRaises(BacktestEligibilityError):
            fixture.replay()
        fixture.data = dict(capture, schema_version="tradepulse.option-observations.v1", symbol="NIFTY",
            provider="upstox", data_mode="SIMULATED", is_simulated=True, evidence_class="SYNTHETIC_FIXTURE")
        with self.assertRaises(BacktestEligibilityError):
            fixture.replay()


class TestOptionDepthObservations(unittest.TestCase):
    def setUp(self):
        self.bids = [dict(price=100, quantity=25), dict(price=99.5, quantity=50)]
        self.asks = [dict(price=100.5, quantity=30), dict(price=101, quantity=40)]

    def test_unknown_or_unverified_quantity_units_never_compute_coverage(self):
        for kwargs in ({}, dict(quantity_unit="CONTRACTS", requested_units=50),
                       dict(quantity_unit="UNDERLYING_UNITS", requested_units=50)):
            with self.subTest(kwargs=kwargs):
                result = inspect_depth(self.bids, self.asks, **kwargs)
                self.assertIsNone(result["coverage"])
                self.assertFalse(result["eligible"])
                self.assertFalse(result["actionable"])

    def test_explicit_synthetic_units_report_depth_sums_without_fill_claim(self):
        result = inspect_depth(self.bids, self.asks, quantity_unit="UNDERLYING_UNITS",
                               requested_units=75, provenance="SYNTHETIC_FIXTURE")
        self.assertEqual(result["coverage"], dict(bid=True, ask=False))
        self.assertFalse(result["eligible"])
        self.assertFalse(result["actionable"])
        self.assertEqual(inspect_depth(self.bids, self.asks, quantity_unit="UNDERLYING_UNITS",
            requested_units=70, provenance="SYNTHETIC_FIXTURE")["coverage"], dict(bid=True, ask=True))

    def test_crossed_unsorted_duplicate_price_and_fractional_depth_reject(self):
        for bids, asks in ((list(reversed(self.bids)), self.asks), (self.bids, list(reversed(self.asks))),
                          ([dict(price=101, quantity=25)], self.asks),
                          ([self.bids[0], copy.deepcopy(self.bids[0])], self.asks),
                          ([dict(price=100, quantity=1.5)], self.asks),
                          ([dict(price=100, quantity=True)], self.asks),
                          ([dict(price=float("nan"), quantity=25)], self.asks),
                          ([dict(price=0, quantity=25)], self.asks),
                          ([dict(price=100, quantity=-1)], self.asks)):
            with self.subTest(bids=bids, asks=asks), self.assertRaises(ObservationError):
                inspect_depth(bids, asks)

    def test_depth_level_limit_and_input_immutability(self):
        original = copy.deepcopy((self.bids, self.asks))
        first = inspect_depth(self.bids, self.asks)
        self.assertEqual(inspect_depth(self.bids, self.asks), first)
        self.assertEqual((self.bids, self.asks), original)
        with self.assertRaises(ObservationError):
            inspect_depth([dict(price=100 - index, quantity=1) for index in range(31)], self.asks)


class TestOptionOIObservations(unittest.TestCase):
    def setUp(self):
        fixture = TestOptionObservations()
        fixture.setUp()
        identity = next(row for row in fixture.master["records"] if row.get("option_type") == "CE")
        self.current = dict(identity=copy.deepcopy(identity), value=1200, quantity_unit="CONTRACTS",
            observed_at="2026-10-16T10:00:00+05:30", available_at="2026-10-16T10:00:01+05:30",
            session_date="2026-10-16", source_reference="authored-current-oi", provenance="SYNTHETIC_FIXTURE", kind="CURRENT")
        self.baseline = dict(identity=copy.deepcopy(identity), value=1000, quantity_unit="CONTRACTS",
            observed_at="2026-10-16T09:55:00+05:30", available_at="2026-10-16T09:55:01+05:30",
            session_date="2026-10-16", source_reference="authored-baseline-oi", provenance="SYNTHETIC_FIXTURE", kind="INTRADAY")
        self.policy = dict(decision_at="2026-10-16T10:01:00+05:30", max_age_seconds=120, max_alignment_seconds=600)

    def compare(self, **policy):
        return compare_oi(self.current, self.baseline, **dict(self.policy, **policy))

    def test_synthetic_same_unit_intraday_arithmetic_is_non_actionable_and_immutable(self):
        original = copy.deepcopy((self.current, self.baseline))
        result = self.compare()
        self.assertEqual(result["delta"], 200)
        self.assertEqual(result["status"], "SYNTHETIC_MECHANICS_ONLY")
        self.assertEqual(result["current"], self.current)
        self.assertEqual(result["baseline"], self.baseline)
        self.assertEqual(self.compare(), result)
        self.assertEqual((self.current, self.baseline), original)
        for key in ("actionable", "eligible", "historical_replay_allowed"):
            self.assertIs(result[key], False)
        self.current["value"] = 0
        self.assertEqual(self.compare()["delta"], -1000)

    def test_unverified_sources_unknown_units_or_baseline_kind_never_compute_delta(self):
        original = copy.deepcopy((self.current, self.baseline))
        for current_change, baseline_change in ((dict(provenance="UNVERIFIED_CAPTURE"), {}),
                ({}, dict(provenance="UNVERIFIED_CAPTURE")),
                (dict(quantity_unit="UNKNOWN"), dict(quantity_unit="UNKNOWN")),
                (dict(quantity_unit=None), dict(quantity_unit=None)), ({}, dict(kind="UNKNOWN"))):
            with self.subTest(current=current_change, baseline=baseline_change):
                self.current, self.baseline = copy.deepcopy(original)
                self.current.update(current_change)
                self.baseline.update(baseline_change)
                result = self.compare()
                self.assertIsNone(result["delta"])
                self.assertFalse(result["eligible"])

    def test_mismatched_contract_revision_expiry_or_units_cannot_join(self):
        original = copy.deepcopy(self.baseline)
        for identity_change in (dict(identifier="NSE_FO|50002"), dict(expiry="2026-11-05"),
                                dict(source_revision="a" * 64), dict(option_type="PE")):
            with self.subTest(change=identity_change):
                self.baseline = copy.deepcopy(original)
                self.baseline["identity"].update(identity_change)
                with self.assertRaises(ObservationError):
                    self.compare()
        self.baseline = copy.deepcopy(original)
        self.baseline["quantity_unit"] = "UNDERLYING_UNITS"
        with self.assertRaises(ObservationError):
            self.compare()

    def test_stale_current_future_availability_and_intraday_misalignment_reject(self):
        with self.assertRaises(ObservationError):
            self.compare(decision_at="2026-10-16T10:03:00+05:30")
        with self.assertRaises(ObservationError):
            self.compare(max_alignment_seconds=299)
        original = copy.deepcopy(self.current)
        for change in (dict(available_at="2026-10-16T10:01:01+05:30"),
                       dict(available_at="2026-10-16T09:59:59+05:30"),
                       dict(observed_at="2026-10-16T10:00:00"), dict(session_date="2026-10-15")):
            with self.subTest(change=change):
                self.current = dict(copy.deepcopy(original), **change)
                with self.assertRaises(ObservationError):
                    self.compare()

    def prior_close(self):
        self.current["prior_session_date"] = "2026-10-15"
        self.baseline.update(kind="PRIOR_CLOSE", session_date="2026-10-15",
            observed_at="2026-10-15T15:30:00+05:30", available_at="2026-10-15T15:30:01+05:30")

    def test_explicit_synthetic_prior_close_requires_exact_baseline_session_and_time(self):
        self.prior_close()
        self.assertEqual(self.compare()["delta"], 200)
        self.assertFalse(self.compare()["historical_replay_allowed"])
        original = copy.deepcopy(self.baseline)
        for change in (dict(observed_at="2026-10-15T15:29:59+05:30"), dict(session_date="2026-10-14"),
                       dict(kind="PREVIOUS_OI")):
            with self.subTest(change=change):
                self.baseline = dict(copy.deepcopy(original), **change)
                with self.assertRaises(ObservationError):
                    self.compare()
        self.baseline = copy.deepcopy(original)
        del self.current["prior_session_date"]
        with self.assertRaises(ObservationError):
            self.compare()

    def test_oi_boolean_fractional_and_negative_values_do_not_enter_arithmetic(self):
        for value in (True, -1, 1000.5, "NaN"):
            with self.subTest(value=value):
                self.current["value"] = value
                with self.assertRaises(ObservationError):
                    self.compare()


if __name__ == "__main__":
    unittest.main()

"""Authored offline benchmark alignment mechanics; no market-data acceptance."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest
from unittest.mock import patch

from benchmark_observations import BenchmarkObservationError, align_benchmark_windows


IST = timezone(timedelta(hours=5, minutes=30))


def observation(role="asset", *, start="2026-10-23T09:15:00+05:30", count=3, closes=None):
    clock = datetime.fromisoformat(start)
    values = closes or ([100, 101, 102] if role == "asset" else [200, 201, 202])
    bars = []
    for index in range(count):
        price = values[index % len(values)]
        timestamp = clock + timedelta(minutes=5 * index)
        bar = dict(timestamp=timestamp.isoformat(), available_at=(timestamp + timedelta(minutes=5)).isoformat(),
            is_complete=True, open=price, high=price + 2, low=price - 2, close=price)
        if role == "asset":
            bar["volume"] = 1000
        bars.append(bar)
    return dict(identity=dict(instrument_type="EQ" if role == "asset" else "INDEX_SPOT",
        symbol="RELIANCE" if role == "asset" else "NIFTY", identifier="fixture-equity" if role == "asset" else "fixture-index",
        provider="authored-fixture", source_revision="fixture-v1"), role=role, interval_minutes=5,
        price_unit="INR" if role == "asset" else "INDEX_POINTS", adjustment="UNADJUSTED",
        session_date=clock.date().isoformat(), source_reference=dict(fixture="authored-" + role),
        provenance="SYNTHETIC_FIXTURE", bars=bars)


class TestBenchmarkObservations(unittest.TestCase):
    def setUp(self):
        self.asset, self.benchmark = observation(), observation("benchmark")

    def align(self, **kwargs):
        return align_benchmark_windows(self.asset, self.benchmark,
            decision_at=kwargs.pop("decision_at", "2026-10-23T09:30:05+05:30"),
            max_age_seconds=kwargs.pop("max_age_seconds", 60), **kwargs)

    def rejected(self, code, **kwargs):
        with self.assertRaises(BenchmarkObservationError) as caught:
            self.align(**kwargs)
        self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual(caught.exception.reason_code, code)
        self.assertEqual(str(caught.exception), code)

    def test_invalid_offset_minutes_cannot_be_silently_normalized(self):
        # Python accepts +05:99 as +06:39. This instant otherwise matches the
        # valid09:30:05 decision, so ordinary freshness cannot catch the defect.
        self.rejected("AWARE_DECISION_TIMESTAMP_REQUIRED", decision_at="2026-10-23T10:39:05+05:99")

    def test_equal_completed_windows_compute_only_descriptive_returns(self):
        result = self.align()
        self.assertAlmostEqual(result["asset"]["return_pct"], 2)
        self.assertAlmostEqual(result["benchmark"]["return_pct"], 1)
        self.assertAlmostEqual(result["relative_return_percentage_points"], 1)
        self.assertEqual(result["bar_count"], 3)
        self.assertEqual(result["window"]["first_close_at"], "2026-10-23T09:20:00+05:30")
        self.assertEqual(result["window"]["end"], "2026-10-23T09:30:00+05:30")
        self.assertEqual(result["alignment"]["latest_end_age_seconds"], 5)
        self.assertEqual(result["factor_status"], "SYNTHETIC_MECHANICS_ONLY")
        for name in ("actionable", "eligible", "empirical_acceptance"):
            self.assertIs(result[name], False)

    def test_capture_and_mixed_sources_cannot_be_promoted_by_caller_fields(self):
        for left, right in (("SYNTHETIC_FIXTURE", "UNVERIFIED_CAPTURE"),
                ("UNVERIFIED_CAPTURE", "SYNTHETIC_FIXTURE"), ("UNVERIFIED_CAPTURE", "UNVERIFIED_CAPTURE")):
            with self.subTest(provenance=(left, right)):
                self.asset.update(provenance=left, eligible=True, empirical_acceptance=True)
                self.benchmark.update(provenance=right, actionable=True)
                result = self.align()
                self.assertEqual(result["factor_status"], "UNQUALIFIED_SOURCE")
                self.assertEqual(result["asset"]["provenance"], left)
                self.assertFalse(result["actionable"] or result["eligible"] or result["empirical_acceptance"])
                self.assertIn("NO_SECTOR_CONSTITUENT_CLAIM", result["limitations"])

    def test_source_hashes_bind_entire_input_are_key_order_stable_and_detached(self):
        before = deepcopy(self.asset)
        result = self.align()
        expected = hashlib.sha256(json.dumps(before, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        self.assertEqual(result["asset"]["input_sha256"], expected)
        self.asset = dict(reversed(list(self.asset.items())))
        self.assertEqual(self.align()["asset"]["input_sha256"], expected)
        self.asset["source_reference"]["revision"] = "new"
        self.assertNotEqual(self.align()["asset"]["input_sha256"], expected)
        result["asset"]["identity"]["symbol"] = "MUTATED_RESULT"
        result["asset"]["source_reference"]["fixture"] = "MUTATED_RESULT"
        self.assertEqual(before["identity"], self.asset["identity"])
        self.assertEqual(self.asset["source_reference"]["fixture"], before["source_reference"]["fixture"])

    def test_equivalent_offsets_align_by_instant_and_keep_raw_input_hash(self):
        original = self.align()["benchmark"]["input_sha256"]
        for bar in self.benchmark["bars"]:
            for name in ("timestamp", "available_at"):
                bar[name] = datetime.fromisoformat(bar[name]).astimezone(timezone.utc).isoformat()
        result = self.align(decision_at="2026-10-23T04:00:05Z")
        self.assertEqual(result["alignment"]["candle_timestamps"][0], "2026-10-23T09:15:00+05:30")
        self.assertNotEqual(result["benchmark"]["input_sha256"], original)

    def test_two_bars_and_full_weekday_session_are_valid_boundaries(self):
        for count, decision in ((2, "2026-10-23T09:25:00+05:30"), (75, "2026-10-23T15:30:00+05:30")):
            with self.subTest(count=count):
                self.asset, self.benchmark = observation(count=count), observation("benchmark", count=count)
                self.assertEqual(self.align(decision_at=decision, max_age_seconds=0)["bar_count"], count)

    def test_zero_and_negative_descriptive_changes_are_retained_without_signal(self):
        self.asset = observation(closes=[100, 100, 100])
        self.benchmark = observation("benchmark", closes=[200, 199, 198])
        result = self.align()
        self.assertEqual(result["asset"]["return_pct"], 0)
        self.assertAlmostEqual(result["benchmark"]["return_pct"], -1)
        self.assertAlmostEqual(result["relative_return_percentage_points"], 1)
        self.assertFalse(result["eligible"])

    def test_stale_boundary_is_inclusive_and_zero_age_requires_exact_completion(self):
        self.assertEqual(self.align(decision_at="2026-10-23T09:31:00+05:30")["alignment"]["latest_end_age_seconds"], 60)
        self.rejected("LATEST_COMPLETED_CANDLE_STALE", decision_at="2026-10-23T09:31:00.000001+05:30")
        self.rejected("LATEST_COMPLETED_CANDLE_STALE", max_age_seconds=0)

    def test_subset_shifted_and_disjoint_windows_are_not_intersected_or_filled(self):
        for benchmark in (observation("benchmark", count=2),
                observation("benchmark", start="2026-10-23T09:20:00+05:30"),
                observation("benchmark", start="2026-10-23T10:00:00+05:30")):
            with self.subTest(start=benchmark["bars"][0]["timestamp"]):
                self.benchmark = benchmark
                self.rejected("EXACT_EQUAL_CANDLE_WINDOWS_REQUIRED", decision_at="2026-10-23T10:15:00+05:30", max_age_seconds=3600)

    def test_gaps_duplicates_and_reverse_order_are_rejected_without_sorting(self):
        for indices in ([0, 2], [0, 0, 1], [2, 1, 0]):
            with self.subTest(indices=indices):
                self.asset = observation()
                original = self.asset["bars"]
                self.asset["bars"] = [deepcopy(original[index]) for index in indices]
                before = deepcopy(self.asset)
                self.rejected("CANDLE_WINDOW_NOT_CONTIGUOUS_CHRONOLOGICAL")
                self.assertEqual(self.asset, before)

    def test_forming_and_unavailable_later_candles_are_not_looked_ahead(self):
        self.rejected("CANDLE_NOT_COMPLETED_AT_DECISION", decision_at="2026-10-23T09:29:59+05:30")
        self.asset["bars"][-1]["available_at"] = "2026-10-23T09:30:06+05:30"
        self.rejected("CANDLE_NOT_AVAILABLE_AT_DECISION")
        self.asset["bars"][-1]["available_at"] = "2026-10-23T09:29:59+05:30"
        self.rejected("CANDLE_AVAILABLE_BEFORE_COMPLETION")

    def test_missing_naive_and_invalid_clocks_are_rejected_for_each_role(self):
        for field, code in (("timestamp", "AWARE_CANDLE_TIMESTAMP_REQUIRED"),
                ("available_at", "AWARE_AVAILABILITY_TIMESTAMP_REQUIRED")):
            for invalid in (None, "", "2026-10-23T09:15:00", "not-a-clock", 1792727700):
                with self.subTest(field=field, value=invalid):
                    self.asset = observation()
                    self.asset["bars"][0][field] = invalid
                    self.rejected(code)
        self.asset = observation()
        for decision in (None, "", "2026-10-23T09:30:05", "not-a-clock"):
            with self.subTest(decision=decision):
                self.rejected("AWARE_DECISION_TIMESTAMP_REQUIRED", decision_at=decision)

    def test_session_weekday_dates_and_five_minute_grid_are_enforced(self):
        for start, decision, code in (
                ("2026-10-24T09:15:00+05:30", "2026-10-24T09:30:05+05:30", "WEEKDAY_SESSION_REQUIRED"),
                ("2026-10-23T09:10:00+05:30", "2026-10-23T09:30:05+05:30", "CANDLE_OUTSIDE_SESSION"),
                ("2026-10-23T15:20:00+05:30", "2026-10-23T15:40:05+05:30", "CANDLE_OUTSIDE_SESSION"),
                ("2026-10-23T09:16:00+05:30", "2026-10-23T09:35:05+05:30", "CANDLE_NOT_FIVE_MINUTE_ALIGNED"),
                ("2026-10-23T09:15:00.000001+05:30", "2026-10-23T09:35:05+05:30", "CANDLE_NOT_FIVE_MINUTE_ALIGNED")):
            with self.subTest(start=start):
                self.asset = observation(start=start)
                self.rejected(code, decision_at=decision)
        self.asset = observation()
        self.rejected("DECISION_SESSION_MISMATCH", decision_at="2026-10-26T09:30:05+05:30", max_age_seconds=86400)
        self.benchmark["session_date"] = "2026-10-22"
        self.rejected("DECISION_SESSION_MISMATCH")

    def test_identity_roles_types_units_and_adjustment_cannot_be_inferred(self):
        cases = [("role", "benchmark", "OBSERVATION_ROLE_MISMATCH"),
            ("interval_minutes", 1, "FIVE_MINUTE_INTERVAL_REQUIRED"),
            ("interval_minutes", True, "FIVE_MINUTE_INTERVAL_REQUIRED"),
            ("price_unit", "INDEX_POINTS", "OBSERVATION_PRICE_UNIT_MISMATCH"),
            ("adjustment", "ADJUSTED", "UNADJUSTED_OBSERVATIONS_REQUIRED"),
            ("provenance", "LIVE", "EXPLICIT_UNQUALIFIED_PROVENANCE_REQUIRED"),
            ("source_reference", {}, "SOURCE_REFERENCE_REQUIRED"),
            ("source_reference", " ", "SOURCE_REFERENCE_REQUIRED"),
            ("session_date", "2026-13-23", "SESSION_DATE_REQUIRED")]
        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                self.asset = observation()
                self.asset[field] = value
                self.rejected(code)
        for field in ("symbol", "identifier", "provider", "source_revision"):
            self.asset = observation()
            del self.asset["identity"][field]
            self.rejected("EXPLICIT_INSTRUMENT_IDENTITY_REQUIRED")
        self.asset = observation()
        self.asset["identity"]["instrument_type"] = "OPTION"
        self.rejected("ASSET_EQ_REQUIRED")
        self.asset = observation()
        self.benchmark["identity"]["instrument_type"] = "EQ"
        self.rejected("BENCHMARK_INDEX_SPOT_REQUIRED")

    def test_same_symbol_or_provider_identifier_cannot_be_its_own_benchmark(self):
        for field in ("symbol", "identifier"):
            with self.subTest(field=field):
                self.benchmark = observation("benchmark")
                self.benchmark["identity"][field] = self.asset["identity"][field]
                self.rejected("DISTINCT_ASSET_AND_BENCHMARK_REQUIRED")

    def test_prices_and_geometry_are_validated_on_all_candles_not_only_endpoints(self):
        for invalid in (0, -1, True, "100", None, float("nan"), float("inf"), 10 ** 1000):
            with self.subTest(invalid=repr(invalid)[:40]):
                self.asset = observation()
                self.asset["bars"][1]["close"] = invalid
                self.rejected("CANDLE_PRICE_INVALID")
        for field, value in (("low", 104), ("high", 99), ("open", 105), ("close", 98)):
            with self.subTest(field=field):
                self.asset = observation()
                self.asset["bars"][1][field] = value
                self.rejected("CANDLE_OHLC_GEOMETRY_INVALID")

    def test_volume_is_required_for_equity_optional_for_index_and_never_invented(self):
        self.assertNotIn("volume", self.benchmark["bars"][0])
        self.align()
        del self.asset["bars"][0]["volume"]
        self.rejected("ASSET_VOLUME_REQUIRED")
        for role in ("asset", "benchmark"):
            for invalid in (-1, 1.5, True, "1000", None, float("nan"), float("inf")):
                with self.subTest(role=role, volume=invalid):
                    self.asset, self.benchmark = observation(), observation("benchmark")
                    getattr(self, role)["bars"][0]["volume"] = invalid
                    self.rejected("CANDLE_VOLUME_INVALID")
        self.asset, self.benchmark = observation(), observation("benchmark")
        self.asset["bars"][0]["volume"] = 0
        self.benchmark["bars"][0]["volume"] = 0
        self.align()

    def test_completed_flag_window_limits_and_max_age_are_explicit(self):
        for invalid in (False, None, 1, "true"):
            self.asset = observation()
            self.asset["bars"][0]["is_complete"] = invalid
            self.rejected("EXPLICIT_COMPLETED_CANDLE_REQUIRED")
        for count in (0, 1, 376):
            self.asset = observation(count=count)
            self.rejected("OBSERVATION_WINDOW_SIZE_INVALID")
        self.asset = observation()
        for age in (-1, True, 1.5, "60", None):
            with self.subTest(age=age):
                self.rejected("NONNEGATIVE_INTEGER_MAX_AGE_REQUIRED", max_age_seconds=age)

    def test_non_json_metadata_and_non_string_keys_cannot_weaken_source_hash(self):
        for value in ({1: "coerced-key"}, {"nan": float("nan")}, {"tuple": (1, 2)}, {"opaque": object()}):
            with self.subTest(value=repr(value)):
                self.asset = observation()
                self.asset["source_reference"] = value
                self.rejected("INPUT_NOT_CANONICAL_JSON")

    def test_malformed_envelopes_fail_with_stable_value_error_codes(self):
        for value in (None, [], "not-an-envelope"):
            with self.subTest(envelope=value):
                self.asset = value
                self.rejected("OBSERVATION_ENVELOPE_REQUIRED")
        for field, value, code in (("identity", [], "EXPLICIT_INSTRUMENT_IDENTITY_REQUIRED"),
                ("bars", {}, "OBSERVATION_WINDOW_SIZE_INVALID"),
                ("bars", [None, None], "CANDLE_OBJECT_REQUIRED"),
                ("provenance", [], "EXPLICIT_UNQUALIFIED_PROVENANCE_REQUIRED"),
                ("provenance", {}, "EXPLICIT_UNQUALIFIED_PROVENANCE_REQUIRED")):
            with self.subTest(field=field, value=value):
                self.asset = observation()
                self.asset[field] = value
                self.rejected(code)

    def test_input_text_node_and_serialized_byte_budgets_bound_extension_metadata(self):
        cases = [
            ("one_string", "x" * 65537, "INPUT_TEXT_LIMIT_EXCEEDED"),
            ("aggregate_text", ["x" * 65536] * 17, "INPUT_TEXT_LIMIT_EXCEEDED"),
            ("too_many_nodes", [0] * 20001, "INPUT_NODE_LIMIT_EXCEEDED"),
            # Canonical JSON escapes these characters: the aggregate character
            # count remains allowed while the serialized byte budget is exceeded.
            ("encoded_bytes", ["\u0905" * 50000] * 8, "INPUT_BYTES_LIMIT_EXCEEDED"),
        ]
        for name, value, code in cases:
            with self.subTest(case=name):
                self.asset = observation()
                self.asset["source_reference"]["extension"] = value
                self.rejected(code)
        self.asset = observation()
        self.asset["extension"] = {"x" * 65537: "oversized-key"}
        self.rejected("INPUT_TEXT_LIMIT_EXCEEDED")

    def test_clock_syntax_is_strict_iso_t_with_seconds_and_explicit_offset(self):
        invalid = ["2026-10-23 09:30:05+05:30", "20261023T09:30:05+05:30",
            "2026-10-23T09:30+05:30", "2026-10-23T09:30:05+0530",
            "2026-10-23T09:30:05+05:30:00", "2026-10-23T09:30:05+05:60",
            "2026-10-23T09:30:05.1234567+05:30", "2026-10-23T09:30:05,123+05:30",
            "2026-10-23T09:30:05z", " 2026-10-23T09:30:05+05:30",
            "2026-10-23T09:30:05+05:30 "]
        for value in invalid:
            with self.subTest(clock=value):
                self.rejected("AWARE_DECISION_TIMESTAMP_REQUIRED", decision_at=value)
                self.asset = observation()
                self.asset["bars"][0]["timestamp"] = value
                self.rejected("AWARE_CANDLE_TIMESTAMP_REQUIRED")
                self.asset = observation()
                self.asset["bars"][0]["available_at"] = value
                self.rejected("AWARE_AVAILABILITY_TIMESTAMP_REQUIRED")
                self.asset = observation()
        self.assertEqual(self.align(decision_at="2026-10-23T09:30:05.123456+05:30")
            ["alignment"]["latest_end_age_seconds"], 5.123456)

    def test_max_age_policy_is_bounded_to_one_day(self):
        self.assertEqual(self.align(max_age_seconds=86400)["alignment"]["max_age_seconds"], 86400)
        for value in (86401, 10 ** 100):
            with self.subTest(max_age=value):
                self.rejected("MAX_AGE_SECONDS_EXCEEDS_SESSION_BOUND", max_age_seconds=value)

    def test_extreme_finite_prices_cannot_produce_infinite_descriptive_return(self):
        for bar, close in zip(self.asset["bars"], (1e-300, 1.0, 1e300)):
            bar.update(open=close, high=close, low=close, close=close)
        self.rejected("DESCRIPTIVE_RETURN_NONFINITE")

    def test_no_transport_file_or_database_access_is_needed_for_alignment(self):
        with patch("builtins.open", side_effect=AssertionError("FILE_IO_FORBIDDEN")), \
                patch("socket.socket", side_effect=AssertionError("NETWORK_FORBIDDEN")), \
                patch("sqlite3.connect", side_effect=AssertionError("DATABASE_FORBIDDEN")):
            result = self.align()
        self.assertFalse(result["eligible"])


if __name__ == "__main__":
    unittest.main()

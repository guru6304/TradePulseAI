"""Strict offline input decoding and authored fixture evidence boundaries."""
import ast
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import unittest

from option_source_research.fixtures import example_vectors, refresh_source_digest, synthetic_fixture
from option_source_research.mapping import decode_fixture, map_synthetic_fixture
from option_intelligence.evidence import CheckError


class TestSourceMappingDecoder(unittest.TestCase):
    def test_named_examples_match_explicit_outcomes(self):
        for name, fixture, state, reason in example_vectors():
            with self.subTest(name=name):
                result = map_synthetic_fixture(fixture, enabled=True)
                self.assertEqual(state, result.state)
                self.assertIn(reason, result.reason_codes)
                self.assertFalse(result.source_qualified)
                self.assertFalse(result.forward_entry_allowed)

    def test_bytes_hash_covers_original_bytes_not_canonical_reencoding(self):
        encoded = json.dumps(synthetic_fixture(), indent=2).encode()
        result = map_synthetic_fixture(encoded, enabled=True)
        self.assertEqual("VERIFIED", result.state)
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), result.original_bytes_sha256)
        compact = json.dumps(synthetic_fixture(), separators=(",", ":")).encode()
        other = map_synthetic_fixture(compact, enabled=True)
        self.assertEqual(result.fixture_digest, other.fixture_digest)
        self.assertNotEqual(result.original_bytes_sha256, other.original_bytes_sha256)

    def test_duplicate_nonfinite_bad_utf8_and_nonobject_rejected(self):
        for raw, reason in ((b'{"a":1,"a":2}', "DUPLICATE_JSON_KEY"),
                            (b'{"a":NaN}', "NONFINITE_JSON_CONSTANT"),
                            (b'\xff', "INVALID_JSON_FIXTURE"),
                            (b'[]', "FIXTURE_OBJECT_REQUIRED")):
            with self.subTest(reason=reason):
                result = map_synthetic_fixture(raw, enabled=True)
                self.assertEqual("INVALID", result.state)
                self.assertIn(reason, result.reason_codes)

    def test_decoder_never_resolves_url_or_path(self):
        for text in ("https://example.invalid/marketfeed", "C:/private/example.json"):
            self.assertEqual("INVALID", map_synthetic_fixture(text, enabled=True).state)

    def test_exported_decoder_rejects_exponent_overflow_and_underflow(self):
        for raw in (b'{"a":1e999}', b'{"a":1e-999}', b'{"a":9007199254740992}'):
            with self.subTest(raw=raw):
                with self.assertRaises(CheckError):
                    decode_fixture(raw)

    def test_numeric_token_cannot_round_an_off_tick_value_into_valid_data(self):
        for value in ("101.50000000000000000001", "0.100000000000000000001"):
            with self.subTest(value=value):
                result=map_synthetic_fixture('{"value":'+value+'}',enabled=True)
                self.assertEqual(("INEXACT_JSON_NUMBER_USE_DECIMAL_STRING",),result.reason_codes)

    def test_evidence_must_cover_source_events_as_well_as_decision(self):
        fixture=synthetic_fixture()
        row=next(item for item in fixture["evidence"] if item["requirement"]=="BOOK_SOURCE_CLOCKS")
        row["effective_from"]="2026-11-03T09:59:59.500000+05:30"
        result=map_synthetic_fixture(fixture,enabled=True)
        self.assertEqual("NOT_ESTABLISHED",result.state)
        self.assertEqual(("BOOK_SOURCE_CLOCKS_SOURCE_EVENT_NOT_COVERED",),result.reason_codes)

    def test_oversize_and_deep_input_rejected(self):
        self.assertEqual(("FIXTURE_TOO_LARGE",), map_synthetic_fixture(b' '*262145,enabled=True).reason_codes)
        fixture=synthetic_fixture()
        nested={}
        for _ in range(40):
            nested={"next":nested}
        fixture["nested"]=nested
        self.assertEqual(("FIXTURE_NESTING_TOO_DEEP",),map_synthetic_fixture(fixture,enabled=True).reason_codes)

    def test_authority_flags_cannot_be_constructor_or_replacement_arguments(self):
        result=map_synthetic_fixture(synthetic_fixture(),enabled=True)
        with self.assertRaises(ValueError):
            replace(result,source_qualified=True)
        with self.assertRaises(FrozenInstanceError):
            result.source_qualified=True
        payload=result.to_dict()
        payload["source_qualified"]=True
        self.assertFalse(result.to_dict()["source_qualified"])

    def test_original_d1_schema_and_vector_are_not_this_mapping_envelope(self):
        for schema in ("tradepulse.option-fixture.d1.v1", "tradepulse.option-fixture-test-vector.d1.v1"):
            fixture=synthetic_fixture()
            fixture["schema_version"]=schema
            self.assertEqual(("UNSUPPORTED_MAPPING_FIXTURE_SCHEMA",),map_synthetic_fixture(fixture,enabled=True).reason_codes)

    def test_combined_size_book_leg_skew_cannot_pass_pairwise_checks(self):
        fixture=synthetic_fixture()
        quote=fixture["source"]["quote"]
        quote.update(bid_at="2026-11-03T09:59:58+05:30",ask_at="2026-11-03T09:59:58+05:30",
                     received_at="2026-11-03T10:00:00+05:30")
        fixture["source"]["size_at"]="2026-11-03T10:00:00+05:30"
        refresh_source_digest(fixture)
        self.assertEqual(("LIQUIDITY_BOOK_CLOCK_MISALIGNED",),map_synthetic_fixture(fixture,enabled=True).reason_codes)

    def test_fractional_clock_limit_is_exact_decimal_seconds(self):
        fixture=synthetic_fixture()
        quote=fixture["source"]["quote"]
        for name in ("observed_at","bid_at","ask_at"):
            quote[name]="2026-11-03T09:59:59.900000+05:30"
        quote["received_at"]="2026-11-03T10:00:00+05:30"
        fixture["source"]["size_at"]="2026-11-03T09:59:59.900000+05:30"
        fixture["source"]["policy"].update(max_age_seconds=".1",max_leg_skew_seconds=".1",documented_cadence_seconds=".1")
        refresh_source_digest(fixture)
        self.assertEqual("VERIFIED",map_synthetic_fixture(fixture,enabled=True).state)

    def test_runtime_mapper_has_no_transport_file_or_production_import(self):
        package=Path(__file__).resolve().parents[1]
        forbidden={"brokers","config","storage","server","scanner_engine","paper_portfolio",
            "forward_paper","option_preflight","option_execution","requests","socket","http","urllib","os","subprocess","pathlib"}
        for filename in ("mapping.py","fixtures.py","__init__.py"):
            tree=ast.parse((package/filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0],forbidden)
                if isinstance(node,ast.ImportFrom) and node.level == 0:
                    self.assertNotIn(node.module.split(".")[0],forbidden)
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
                    self.assertNotIn(node.func.id,{"open","exec","eval","__import__"})


if __name__ == "__main__":
    unittest.main()

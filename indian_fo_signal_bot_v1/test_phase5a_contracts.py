"""Offline synthetic declarations for the existing identity/store boundary.

Derivative identifiers below are test fixtures, never a current F&O universe or
publisher evidence. A successful structural check must still be ineligible.
"""

import copy
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot  # noqa: F401 -- use the established offline bootstrap

_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    environment = patch.dict(os.environ, _fixtures._test_config_defaults)
    environment.start()
    unittest.addModuleCleanup(environment.stop)


from instrument_identity import (CONTRACT_MASTER_SCHEMA, EQUITIES, INDICES, IdentityValidationError,
                                 prepare_contract_master, resolve_contract_identity, validate_contract_identity)


def contract_fixture_records(provider):
    """Provider-shaped normalized records, including synthetic derivative tokens."""
    field = {"angelone": "angel_token", "dhan": "dhan_id", "upstox": "upstox_key"}[provider]
    stock_id = str(EQUITIES["RELIANCE"][field])
    index_field = "dhan_security_id" if provider == "dhan" else field
    index_id = str(INDICES["NIFTY"][index_field])
    common = dict(provider=provider, valid_from="2026-10-01", valid_to="2026-12-31", contract_status="ACTIVE")
    records = [dict(common, symbol="RELIANCE", identifier=stock_id, exchange="NSE",
                    segment="NSE_EQUITY_INTRADAY", instrument_type="EQ", price_unit="INR",
                    quantity_unit="SHARES", lot_size=1, multiplier=1),
               dict(common, symbol="NIFTY", identifier=index_id, exchange="NSE", segment="NSE_FO_INDEX",
                    instrument_type="INDEX_SPOT", price_unit="INDEX_POINTS", quantity_unit="NOT_EXECUTABLE")]
    for number, kind in enumerate(("FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK"), 700001):
        index = kind.endswith("IDX")
        underlying = "NIFTY" if index else "RELIANCE"
        token = str(number) if provider != "upstox" else "NSE_FO|" + str(number)
        record = dict(common, symbol=underlying+"20OCT2026"+("25000CE" if kind.startswith("OPT") else "FUT"),
            identifier=token, exchange="NFO", segment="NSE_FO_INDEX" if index else "NSE_FO_STOCK",
            instrument_type=kind, underlying=underlying, underlying_identifier=index_id if index else stock_id,
            expiry="2026-10-20", valid_to="2026-10-20", price_unit="INR", quantity_unit="UNDERLYING_UNITS",
            lot_size=75 if index else 250, multiplier=1)
        if kind.startswith("OPT"):
            record.update(strike=25000, option_type="CE")
        records.append(record)
    return records


class TestPhase5AContractDeclarations(unittest.TestCase):
    PROVIDERS = ("angelone", "dhan", "upstox")

    def setUp(self):
        guard = patch("urllib.request.urlopen", side_effect=AssertionError("Broker transport forbidden"))
        guard.start()
        self.addCleanup(guard.stop)

    def _bytes(self, provider="angelone", records=None, **extra):
        payload = dict(schema_version=CONTRACT_MASTER_SCHEMA, provider=provider,
                       evidence_class="SYNTHETIC_FIXTURE", records=records if records is not None else contract_fixture_records(provider))
        payload.update(extra)
        return json.dumps(payload, sort_keys=True, allow_nan=False).encode()

    def _prepare(self, provider="angelone", records=None, raw=None, **extra):
        return prepare_contract_master(raw if raw is not None else self._bytes(provider, records), provider=provider,
            source_reference="OFFLINE_SYNTHETIC_FIXTURE_NOT_PROVIDER_MASTER", source_version="offline-fixture-v1",
            captured_at="2026-10-16T09:00:00+05:30", **extra)

    def _resolve(self, master, **query):
        params = dict(provider=master["metadata"]["provider"], instrument_type="OPTIDX", as_of="2026-10-16")
        params.update(query)
        return resolve_contract_identity(master, **params)

    def test_all_six_types_have_explicit_type_specific_units_and_identity(self):
        for provider in self.PROVIDERS:
            for raw in contract_fixture_records(provider):
                with self.subTest(provider=provider, kind=raw["instrument_type"]):
                    identity = validate_contract_identity(raw, provider=provider, as_of="2026-10-16")
                    self.assertIsInstance(identity, dict)
                    for field in ("provider", "symbol", "identifier", "exchange", "segment", "instrument_type",
                                  "price_unit", "quantity_unit", "valid_from", "valid_to"):
                        self.assertEqual(identity[field], raw[field])
                    self.assertEqual(identity["historical_validity"], "NOT_ESTABLISHED")
                    self.assertEqual(identity["source"], "LOCAL_NORMALIZED_MASTER_DECLARATION")
                    if raw["instrument_type"] == "INDEX_SPOT":
                        self.assertNotIn("lot_size", identity)
                        self.assertNotIn("multiplier", identity)
                    else:
                        self.assertEqual(identity["lot_size"], raw["lot_size"])
                        self.assertEqual(identity["multiplier"], 1)

    def test_every_provider_and_type_remains_blocked_after_unique_structural_resolution(self):
        for provider in self.PROVIDERS:
            master = self._prepare(provider)
            self.assertEqual(master["status"], "BLOCKED_UNQUALIFIED_MASTER")
            self.assertEqual(master["record_count"], 6)
            for raw in contract_fixture_records(provider):
                with self.subTest(provider=provider, kind=raw["instrument_type"]):
                    result = self._resolve(master, instrument_type=raw["instrument_type"], identifier=raw["identifier"])
                    self.assertEqual(result["status"], "BLOCKED_UNQUALIFIED_MASTER", result)
                    self.assertEqual(result["identity"]["identifier"], raw["identifier"])
                    self.assertFalse(result["eligible"])
                    self.assertFalse(result["historical_replay_allowed"])

    def test_forged_verification_flags_and_source_fields_cannot_grant_trust(self):
        records = contract_fixture_records("angelone")
        for record in records:
            record.update(verified=True, qualified=True, source="OFFICIAL_PROVIDER_VERIFIED",
                          source_revision="FORGED_REVISION", historical_validity="VERIFIED")
        raw = self._bytes(records=records, verified=True, qualified=True, live_eligible=True,
                          publisher_authenticity="VERIFIED", historical_replay_allowed=True)
        master = self._prepare(raw=raw)
        self.assertEqual(master["metadata"]["publisher_authenticity"], "NOT_ESTABLISHED")
        self.assertEqual(master["metadata"]["effective_date_evidence"], "DECLARED_ONLY")
        result = self._resolve(master)
        self.assertEqual(result["status"], "BLOCKED_UNQUALIFIED_MASTER")
        self.assertEqual(result["identity"]["source"], "LOCAL_NORMALIZED_MASTER_DECLARATION")
        self.assertEqual(result["identity"]["historical_validity"], "NOT_ESTABLISHED")
        self.assertFalse(result["eligible"])

    def test_candidate_record_metadata_byte_and_status_tampering_is_rejected(self):
        original = self._prepare()
        mutations = (
            lambda item: item["records"][0].update(identifier="123456"),
            lambda item: item["metadata"].update(source_version="FORGED_VERSION"),
            lambda item: item["metadata"].update(original_sha256="0"*64),
            lambda item: item.update(original_bytes=item["original_bytes"]+b" "),
            lambda item: item.update(normalized_sha256="0"*64),
            lambda item: item.update(record_count=1),
            lambda item: item.update(master_id="0"*64),
            lambda item: item.update(status="ACCEPTED"),
            lambda item: item.update(eligible=True),
            lambda item: item.update(historical_replay_allowed=True),
        )
        for mutation in mutations:
            candidate = copy.deepcopy(original)
            mutation(candidate)
            with self.subTest(mutation=mutation):
                result = self._resolve(candidate)
                self.assertEqual(result["status"], "INVALID_MASTER_INTEGRITY")
                self.assertIsNone(result["identity"])
                self.assertFalse(result["eligible"])

    def test_original_bytes_and_bom_are_retained_and_bound_to_master_identity(self):
        raw = self._bytes()
        plain, bom = self._prepare(raw=raw), self._prepare(raw=b"\xef\xbb\xbf"+raw)
        self.assertEqual(plain["original_bytes"], raw)
        self.assertEqual(bom["original_bytes"], b"\xef\xbb\xbf"+raw)
        self.assertNotEqual(plain["master_id"], bom["master_id"])
        self.assertNotEqual(plain["metadata"]["original_sha256"], bom["metadata"]["original_sha256"])
        self.assertEqual([row["identifier"] for row in plain["records"]], [row["identifier"] for row in bom["records"]])

    def test_rejected_bytes_are_retained_without_partial_contract_activation(self):
        for raw in (b"not JSON", b"<html>PRIVATE_RAW_BODY</html>", b"{", b"\xff",
                    b'{"schema_version":"x","schema_version":"y"}', b'{"records":[NaN]}'):
            with self.subTest(raw_kind=raw[:1]):
                master = self._prepare(raw=raw)
                self.assertEqual(master["status"], "REJECTED")
                self.assertEqual(master["records"], [])
                self.assertEqual(master["original_bytes"], raw)
                self.assertFalse(master["eligible"])
                rendered = json.dumps({key: value for key, value in master.items() if key != "original_bytes"})
                self.assertNotIn("PRIVATE_RAW_BODY", rendered)
                self.assertIsNone(self._resolve(master)["identity"])

    def test_wrong_schema_provider_empty_and_nonlist_records_reject(self):
        for changes in (dict(schema_version="native-provider-format"), dict(provider="upstox"),
                        dict(records=[]), dict(records={}), dict(records=[None])):
            master = self._prepare(raw=self._bytes(**changes))
            with self.subTest(changes=changes):
                self.assertEqual(master["status"], "REJECTED")
                self.assertEqual(master["records"], [])

    def test_declared_synthetic_or_unknown_mode_never_becomes_live_contract_evidence(self):
        for changes in (dict(is_simulated=True), dict(data_mode="SIMULATED"), dict(data_mode="UNKNOWN")):
            with self.subTest(changes=changes):
                self.assertEqual(self._prepare(raw=self._bytes(**changes))["validation"]["reason_code"], "INVALID_PROVENANCE")
                records = contract_fixture_records("angelone")
                records[-1].update(changes)
                self.assertEqual(self._prepare(records=records)["validation"]["reason_code"], "INVALID_PROVENANCE")

    def test_missing_and_ambiguous_contract_queries_are_explicit(self):
        master = self._prepare()
        missing = self._resolve(master, identifier="999999")
        self.assertEqual(missing["status"], "MISSING_CONTRACT")
        rows = contract_fixture_records("angelone")
        later = dict(rows[-2], identifier="700101", symbol="NIFTY27OCT202625000CE",
                     expiry="2026-10-27", valid_to="2026-10-27")
        rows.append(later)
        master = self._prepare(records=rows)
        self.assertEqual(self._resolve(master)["status"], "AMBIGUOUS_CONTRACT")
        chosen = self._resolve(master, expiry="2026-10-27", strike=25000, option_type="CE", underlying="NIFTY")
        self.assertEqual(chosen["status"], "BLOCKED_UNQUALIFIED_MASTER")
        self.assertEqual(chosen["identity"]["identifier"], "700101")

    def test_duplicate_identifier_and_conflicting_contract_terms_reject_whole_artifact(self):
        rows = contract_fixture_records("angelone")
        for extra, expected in ((copy.deepcopy(rows[-1]), "CONFLICTING_IDENTIFIER"),
                                (dict(rows[-1], identifier="700099"), "AMBIGUOUS_CONTRACT")):
            with self.subTest(expected=expected):
                master = self._prepare(records=rows+[extra])
                self.assertEqual(master["status"], "REJECTED")
                self.assertEqual(master["validation"]["reason_code"], expected)
                self.assertEqual(master["records"], [])

    def test_expired_stale_future_and_inactive_declarations_have_distinct_results(self):
        master = self._prepare()
        self.assertEqual(self._resolve(master, as_of="2026-10-21")["status"], "EXPIRED_CONTRACT")
        self.assertEqual(self._resolve(master, instrument_type="EQ", as_of="2027-01-01")["status"], "STALE_MASTER")
        self.assertEqual(self._resolve(master, as_of="2026-09-30")["status"], "CONTRACT_NOT_YET_EFFECTIVE")
        rows = contract_fixture_records("angelone")
        rows[-2]["contract_status"] = "SUSPENDED"
        self.assertEqual(self._resolve(self._prepare(records=rows))["status"], "INACTIVE_CONTRACT")

    def test_unsupported_and_cross_provider_requests_never_resolve_a_contract(self):
        master = self._prepare()
        for query, expected in ((dict(provider="unknown"), "UNSUPPORTED_PROVIDER"),
                                (dict(provider="upstox"), "CONTRACT_PROVIDER_MISMATCH"),
                                (dict(instrument_type="UNKNOWN"), "UNSUPPORTED_CONTRACT_TYPE")):
            with self.subTest(query=query):
                result = self._resolve(master, **query)
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["eligible"])
        self.assertEqual(resolve_contract_identity(None, provider="angelone", instrument_type="EQ",
                                                  as_of="2026-10-16")["status"], "MASTER_NOT_AVAILABLE")

    def test_malformed_dates_naive_clock_and_type_inapplicable_query_terms_reject(self):
        master = self._prepare()
        for query in (dict(as_of="20261016"), dict(as_of="2026-02-30"), dict(as_of=True),
                      dict(as_of=datetime(2026, 10, 16)), dict(expiry="2026-13-20"),
                      dict(strike=float("inf")), dict(strike=True), dict(option_type="CALL"),
                      dict(instrument_type="FUTIDX", strike=25000)):
            with self.subTest(query=query):
                result = self._resolve(master, **query)
                self.assertNotEqual(result["status"], "BLOCKED_UNQUALIFIED_MASTER")
                self.assertIsNone(result["identity"])
        aware = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
        self.assertEqual(self._resolve(master, as_of=aware)["status"], "BLOCKED_UNQUALIFIED_MASTER")

    def test_derivative_requires_matching_underlying_identity_and_declared_coverage(self):
        rows = contract_fixture_records("angelone")
        missing = self._prepare(records=[record for record in rows if record["instrument_type"] != "EQ"])
        self.assertEqual(missing["validation"]["reason_code"], "MISSING_UNDERLYING_IDENTITY")
        mismatch = copy.deepcopy(rows)
        mismatch[-1]["underlying_identifier"] = "1333"
        self.assertEqual(self._prepare(records=mismatch)["validation"]["reason_code"], "MISSING_UNDERLYING_IDENTITY")
        mismatch = copy.deepcopy(rows)
        mismatch[0]["valid_from"] = "2026-10-10"
        self.assertEqual(self._prepare(records=mismatch)["validation"]["reason_code"], "UNDERLYING_DATE_MISMATCH")

    def test_spot_and_derivatives_cannot_exchange_type_segment_or_identifier(self):
        for raw in contract_fixture_records("angelone"):
            for changes in (dict(exchange="BSE"), dict(segment="OTHER_SEGMENT"), dict(is_index=not (raw["instrument_type"] == "INDEX_SPOT"))):
                with self.subTest(kind=raw["instrument_type"], changes=changes), self.assertRaises(IdentityValidationError):
                    validate_contract_identity(dict(raw, **changes), provider="angelone")
        future = contract_fixture_records("angelone")[2]
        for changes in (dict(identifier="99926000"), dict(identifier=future["underlying_identifier"]),
                        dict(underlying="RELIANCE"), dict(symbol="NIFTY"), dict(strike=25000), dict(option_type="CE")):
            with self.subTest(changes=changes), self.assertRaises(IdentityValidationError):
                validate_contract_identity(dict(future, **changes), provider="angelone")

    def test_missing_terms_nonfinite_strike_and_lot_multiplier_units_are_not_inferred(self):
        option = contract_fixture_records("angelone")[-1]
        for field in ("symbol", "identifier", "exchange", "segment", "underlying", "underlying_identifier",
                      "expiry", "strike", "option_type", "lot_size", "multiplier", "price_unit", "quantity_unit",
                      "valid_from", "valid_to"):
            record = dict(option)
            del record[field]
            with self.subTest(field=field), self.assertRaises(IdentityValidationError):
                validate_contract_identity(record, provider="angelone")
        for changes in (dict(strike=float("inf")), dict(strike=float("nan")), dict(strike=True), dict(strike=0),
                        dict(option_type="CALL"), dict(lot_size=0), dict(lot_size=True), dict(lot_size=1.5),
                        dict(multiplier=2), dict(multiplier=True), dict(quantity_unit="LOTS"), dict(price_unit="PAISE"),
                        dict(valid_to="2026-10-21"), dict(expiry="2026-02-30")):
            with self.subTest(changes=changes), self.assertRaises(IdentityValidationError):
                validate_contract_identity(dict(option, **changes), provider="angelone")

    def test_cash_and_index_spot_cannot_carry_executable_derivative_terms(self):
        equity, index = contract_fixture_records("angelone")[:2]
        for record in (equity, index):
            for changes in (dict(expiry="2026-10-20"), dict(underlying="RELIANCE"), dict(strike=25000), dict(option_type="CE")):
                with self.subTest(kind=record["instrument_type"], changes=changes), self.assertRaises(IdentityValidationError):
                    validate_contract_identity(dict(record, **changes), provider="angelone")
        with self.assertRaises(IdentityValidationError):
            validate_contract_identity(dict(equity, lot_size=250), provider="angelone")
        for changes in (dict(lot_size=75), dict(multiplier=1)):
            with self.subTest(changes=changes), self.assertRaises(IdentityValidationError):
                validate_contract_identity(dict(index, **changes), provider="angelone")

    def test_provider_identifier_prefix_and_decimal_tokens_are_checked(self):
        for provider in self.PROVIDERS:
            record = contract_fixture_records(provider)[2]
            for identifier in ("", "../OTHER", "TOKEN_CANARY", "NSE_EQ|INE002A01018",
                               "NSE_FO| 700001", "NSE_FO|٧٠٠٠٠١", "NSE_FO|700001?query"):
                with self.subTest(provider=provider, identifier=identifier), self.assertRaises(IdentityValidationError):
                    validate_contract_identity(dict(record, identifier=identifier), provider=provider)

    def test_metadata_size_encoding_control_and_capture_time_boundaries(self):
        raw = self._bytes()
        base = dict(provider="angelone", source_reference="OFFLINE_FIXTURE", source_version="v1")
        for changes in (dict(provider="paper_sim"), dict(source_reference=""), dict(source_reference="bad\nref"),
                        dict(source_version=""), dict(source_version="x"*129), dict(captured_at="2026-10-16 09:00:00"),
                        dict(captured_at="bad")):
            with self.subTest(changes=changes), self.assertRaises(IdentityValidationError):
                prepare_contract_master(raw, **dict(base, **changes))
        for bad_bytes in (b"", "not bytes", bytearray(raw)):
            with self.subTest(value_type=type(bad_bytes).__name__), self.assertRaises(IdentityValidationError):
                prepare_contract_master(bad_bytes, **base)
        with patch("instrument_identity.MAX_CONTRACT_MASTER_BYTES", len(raw)-1), self.assertRaises(IdentityValidationError):
            prepare_contract_master(raw, **base)
        with patch("instrument_identity.MAX_CONTRACT_MASTER_RECORDS", 5):
            self.assertEqual(prepare_contract_master(raw, **base)["status"], "REJECTED")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Authored declarations prove mechanics only; no source acceptance or entry."""
import copy
import json
import unittest

from instrument_identity import prepare_contract_master, digest
from option_preflight import prospective_preflight, IDENTITY_FIELDS
import test_option_observations as fixtures


class TestOptionPreflight(unittest.TestCase):
    def setUp(self):
        old = fixtures.TestOptionObservations().make_master("upstox")
        data = json.loads(old["original_bytes"])
        for r in data["records"]:
            if r["instrument_type"] == "OPTIDX":
                r["tick_size"] = 0.05
        self.master = prepare_contract_master(json.dumps(data).encode(), provider="upstox",
            source_reference="authored-offline", source_version="fixture-v1",
            captured_at="2026-10-16T09:00:00+05:30")
        # Records may be sorted by identifier: select the exact CE explicitly.
        identity = next(r for r in self.master["records"] if r.get("option_type") == "CE")
        self.now = "2026-10-16T10:00:02+05:30"
        self.d = dict(scope="PROSPECTIVE_PREMIUM", data_mode="LIVE", is_simulated=False,
            identity=copy.deepcopy(identity), quantity_units=25, tick_size=0.05,
            quote_identity_digest=digest(identity), source_revision=identity["source_revision"],
            bid=125, ask=126, bid_size_units=50, ask_size_units=25,
            quantity_unit="UNDERLYING_UNITS", price_unit="INR")
        for k in ("quote_at", "bid_at", "ask_at", "liquidity_at", "received_at", "available_at"):
            self.d[k] = "2026-10-16T10:00:01+05:30"

    def check(self, d=None, master=None):
        out = prospective_preflight(self.d if d is None else d,
            master=self.master if master is None else master, decision_at=self.now)
        self.assertFalse(out["prospective_ready"])
        self.assertFalse(out["forward_entry_allowed"])
        self.assertFalse(out["source_qualified"])
        return out

    def test_valid_declaration_still_blocked(self):
        out = self.check()
        self.assertTrue(out["declaration_valid"])
        self.assertEqual(out["reason_code"], "INDEPENDENT_SOURCE_QUALIFICATION_UNAVAILABLE")

    def test_every_required_field_missing(self):
        for k in self.d:
            with self.subTest(k=k):
                d = copy.deepcopy(self.d)
                del d[k]
                self.assertEqual(self.check(d)["reason_code"], "MISSING_"+k.upper())
        for k in IDENTITY_FIELDS:
            with self.subTest(identity=k):
                d = copy.deepcopy(self.d)
                del d["identity"][k]
                self.assertEqual(self.check(d)["reason_code"], "MISSING_IDENTITY_"+k.upper())

    def test_identity_and_revision_mismatches(self):
        for key, value in (("identifier", "NSE_FO|50002"), ("expiry", "2026-10-28"),
                ("strike", 25100), ("option_type", "PE"), ("lot_size", 50),
                ("source_revision", "wrong"), ("quantity_unit", "LOTS")):
            with self.subTest(key=key):
                d = copy.deepcopy(self.d)
                d["identity"][key] = value
                self.assertFalse(self.check(d)["declaration_valid"])
        for key in ("quote_identity_digest", "source_revision"):
            d = copy.deepcopy(self.d)
            d[key] = "wrong"
            self.assertEqual(self.check(d)["reason_code"], "QUOTE_IDENTITY_OR_REVISION_MISMATCH")

    def test_bad_prices_depth_units(self):
        for key, value in (("bid", 127), ("ask", 140), ("ask", 126.01), ("bid", float("nan")),
                ("tick_size", 0.1), ("ask_size_units", 24), ("bid_size_units", True),
                ("quantity_units", 1), ("quantity_units", True), ("quantity_unit", "LOTS")):
            with self.subTest(key=key, value=value):
                d = copy.deepcopy(self.d)
                d[key] = value
                self.assertFalse(self.check(d)["declaration_valid"])

    def test_stale_future_naive_unsynchronized_clocks(self):
        for key in ("quote_at", "bid_at", "ask_at", "liquidity_at", "received_at", "available_at"):
            for value in ("2026-10-15T10:00:01+05:30", "2026-10-16T10:00:03+05:30", "2026-10-16T10:00:01"):
                with self.subTest(key=key, value=value):
                    d = copy.deepcopy(self.d)
                    d[key] = value
                    self.assertFalse(self.check(d)["declaration_valid"])
        d = copy.deepcopy(self.d)
        d["bid_at"] = "2026-10-16T09:59:59+05:30"
        self.assertEqual(self.check(d)["reason_code"], "UNSYNCHRONIZED_PREMIUM_EVIDENCE")

    def test_replay_chain_underlying_simulation_cannot_authorize(self):
        for scope in ("HISTORICAL_RESEARCH", "SIMULATED_TEST", "INSPECTION_ONLY", "UNDERLYING_BARS"):
            d = copy.deepcopy(self.d)
            d["scope"] = scope
            self.assertEqual(self.check(d)["reason_code"], "NON_PROSPECTIVE_PREMIUM_EVIDENCE")
        d = copy.deepcopy(self.d)
        d["is_simulated"] = True
        self.assertFalse(self.check(d)["declaration_valid"])
        for raw in ({"underlying_candles": []}, {"premiums": []}, {"eligible": True}, []):
            self.assertFalse(self.check(raw)["declaration_valid"])
        out = prospective_preflight(decision_at=self.now)
        self.assertEqual(out["reason_code"], "QUALIFIED_PROSPECTIVE_PREMIUM_REQUIRED")

    def test_master_integrity_and_tick_missing(self):
        bad = copy.deepcopy(self.master)
        bad["records"][0]["symbol"] = "CORRUPT"
        self.assertEqual(self.check(master=bad)["reason_code"], "INVALID_MASTER_INTEGRITY")
        old = fixtures.TestOptionObservations().make_master("upstox")
        d = copy.deepcopy(self.d)
        d["identity"] = next(r for r in old["records"] if r.get("option_type") == "CE")
        d["source_revision"] = d["identity"]["source_revision"]
        d["quote_identity_digest"] = digest(d["identity"])
        self.assertEqual(self.check(d, old)["reason_code"], "MASTER_TICK_SIZE_UNAVAILABLE")

    def test_option_cannot_be_added_to_cash_allowlist(self):
        from paper_portfolio import PaperAccountConfig, PaperPortfolioError
        # Existing account constructor independently rejects any option activation.
        with self.assertRaises(PaperPortfolioError):
            PaperAccountConfig(account_id="offline", run_id="offline", provider="paper_sim",
                source_data_mode="SIMULATED", allowed_strategies=("strat_3_option_apex_oi",))

    def test_recursive_or_oversized_declarations_fail_closed(self):
        d = copy.deepcopy(self.d)
        d["recursive"] = d
        self.assertFalse(self.check(d)["declaration_valid"])
        d = copy.deepcopy(self.d)
        d["extra"] = "x" * 65537
        self.assertFalse(self.check(d)["declaration_valid"])

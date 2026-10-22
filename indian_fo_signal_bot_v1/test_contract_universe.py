"""Synthetic schema fixtures only; no contract source qualification or download."""
import copy
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import test_bot
from instrument_identity import prepare_contract_master, resolve_contract_identity
from storage import SQLitePersistenceStore
from strategies import IST


class TestNativeContractUniverse(unittest.TestCase):
    def setUp(self):
        self.store = SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 21, 12, tzinfo=IST)

    def rows(self):
        expiry = datetime(2026, 10, 29, 23, 59, 59, tzinfo=IST)
        rows = []
        for number, (symbol, key, kind) in enumerate((
                ("EXAMPLECO", "NSE_EQ|OFFLINE_EQ1", "EQUITY"),
                ("NIFTY", "NSE_INDEX|Nifty 50", "INDEX"),
                ("BANKNIFTY", "NSE_INDEX|Nifty Bank", "INDEX"))):
            rows.append(dict(segment="NSE_EQ" if kind=="EQUITY" else "NSE_INDEX", exchange="NSE",
                instrument_type="EQ" if kind=="EQUITY" else "INDEX", instrument_key=key,
                trading_symbol=symbol, lot_size=1))
            for side_number, side in enumerate(("FUT", "CE", "PE")):
                token = str(900000 + number*10 + side_number)
                rows.append(dict(segment="NSE_FO", exchange="NSE", instrument_type=side,
                    instrument_key="NSE_FO|"+token, exchange_token=token, underlying_symbol=symbol,
                    underlying_key=key, underlying_type=kind, expiry=int(expiry.timestamp()*1000),
                    lot_size=10+number, minimum_lot=10+number, strike_price=0 if side=="FUT" else 100,
                    trading_symbol=symbol+(" FUT 29 OCT 26" if side=="FUT" else " 100 "+side+" 29 OCT 26")))
        return rows

    def raw(self, rows=None):
        return json.dumps(self.rows() if rows is None else rows).encode()

    def refresh(self, rows=None, now=None, capture=None):
        return self.store.refresh_contract_cache(self.raw(rows), provider="upstox",
            source_reference="OFFLINE_SYNTHETIC_SCHEMA_FIXTURE", source_version="offline-test-v1",
            captured_at=(capture or self.now).isoformat(), now=now or self.now)

    def test_general_stock_and_index_native_terms_are_retained_but_not_qualified(self):
        candidate = prepare_contract_master(self.raw(), provider="upstox",
            source_reference="OFFLINE_SYNTHETIC_SCHEMA_FIXTURE", source_version="offline-v1", captured_at=self.now.isoformat())
        self.assertEqual(candidate["observed_record_count"], 9)
        self.assertEqual({r["instrument_type"] for r in candidate["observed_records"]},
                         {"FUTSTK", "OPTSTK", "FUTIDX", "OPTIDX"})
        self.assertFalse(candidate["eligible"])
        inspected = resolve_contract_identity(candidate, provider="upstox", instrument_type="OPTSTK",
            as_of=self.now, underlying="EXAMPLECO", strike=100, option_type="CE")
        self.assertEqual(inspected["observed_contract"]["identifier"], "NSE_FO|900001")
        self.assertFalse(inspected["eligible"])

    def test_invalid_terms_identity_duplicates_pairs_dates_and_units_reject(self):
        mutations = (lambda r: r.append(copy.deepcopy(r[1])), lambda r: r[1].update(exchange="BSE"),
            lambda r: r[1].update(expiry=True), lambda r: r[2].update(strike_price=-1),
            lambda r: r[1].update(underlying_key="NSE_EQ|MISSING"), lambda r: r[3].update(lot_size=11),
            lambda r: r[1].update(trading_symbol="EXAMPLECO FUT 30 OCT 26"),
            lambda r: r[1].update(lot_size=0), lambda r: r[1].update(instrument_key="NSE_EQ|900000"),
            lambda r: r[5].update(underlying_key="NSE_INDEX|Nifty Bank"))
        for mutation in mutations:
            rows = self.rows()
            mutation(rows)
            candidate = prepare_contract_master(self.raw(rows), provider="upstox",
                source_reference="OFFLINE_SYNTHETIC_SCHEMA_FIXTURE", source_version="offline-v1")
            with self.subTest(mutation=mutations.index(mutation)):
                self.assertEqual(candidate["status"], "REJECTED")
                self.assertFalse(candidate["eligible"])

    def test_atomic_cache_refresh_and_repeat_are_idempotent(self):
        first = self.refresh()
        self.assertEqual(first["status"], "PASS")
        self.assertFalse(first["eligible"])
        self.assertEqual(self.refresh()["master_id"], first["master_id"])
        inspected = self.store.inspect_cached_contract("upstox", now=self.now, instrument_type="OPTSTK",
            underlying="EXAMPLECO", strike=100, option_type="CE")
        self.assertEqual(inspected["observed_contract"]["identifier"], "NSE_FO|900001")
        self.assertFalse(inspected["eligible"])

    def test_bad_or_older_refresh_keeps_last_good_but_records_rejection(self):
        first = self.refresh()
        rows = self.rows()
        rows[1]["lot_size"] = 0
        self.assertEqual(self.refresh(rows)["status"], "FAIL")
        self.assertEqual(self.refresh(capture=self.now-timedelta(minutes=5))["status"], "FAIL")
        cached = self.store.contract_cache_status("upstox", now=self.now)
        self.assertEqual(cached["master_id"], first["master_id"])
        with self.store.paper_transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM contract_master_refreshes WHERE status='FAIL'").fetchone()[0], 2)

    def test_future_stale_and_expired_cache_never_claims_current_contract(self):
        self.assertEqual(self.refresh(capture=self.now+timedelta(minutes=1))["status"], "FAIL")
        self.refresh()
        status = self.store.contract_cache_status("upstox", now=self.now+timedelta(days=1))
        self.assertEqual(status["status"], "STALE")
        result = self.store.inspect_cached_contract("upstox", now=self.now+timedelta(days=1),
            instrument_type="OPTSTK", identifier="NSE_FO|900001")
        self.assertNotIn("observed_contract", result)
        self.assertFalse(result["eligible"])

    def test_refresh_interruption_rolls_back_new_pointer_and_candidate(self):
        original = self.refresh()
        rows = self.rows()
        for row in rows:
            if row.get("segment")=="NSE_FO":
                row["lot_size"] *= 2
                row["minimum_lot"] *= 2
        with patch.object(self.store, "_contract_cache_checkpoint", side_effect=RuntimeError("OFFLINE interruption")), self.assertRaises(RuntimeError):
            self.refresh(rows, now=self.now+timedelta(minutes=1), capture=self.now+timedelta(minutes=1))
        self.assertEqual(self.store.contract_cache_status("upstox", now=self.now)["master_id"], original["master_id"])
        with self.store.paper_transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM contract_master_candidates").fetchone()[0], 1)

    def test_equivalent_numeric_strikes_cannot_hide_ambiguous_terms(self):
        rows = self.rows()
        duplicate = dict(rows[2], instrument_key="NSE_FO|999999", exchange_token="999999", strike_price=100.0)
        rows.append(duplicate)
        candidate = prepare_contract_master(self.raw(rows), provider="upstox",
            source_reference="OFFLINE_SYNTHETIC_SCHEMA_FIXTURE", source_version="offline-v1")
        self.assertEqual(candidate["status"], "REJECTED")

    def test_timezone_canonicalization_concurrent_ingestion_and_tamper_rejection(self):
        from datetime import timezone
        capture = self.now.astimezone(timezone.utc)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.refresh(capture=capture), range(8)))
        self.assertTrue(all(r["status"]=="PASS" for r in results))
        self.assertEqual(self.store.contract_cache_status("upstox", now=self.now)["status"], "PASS")
        with self.store.paper_transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM contract_master_cache").fetchone()[0], 1)
            conn.execute("UPDATE contract_master_cache SET content_digest='tampered'")
        with self.assertRaisesRegex(ValueError, "INTEGRITY_FAILURE"):
            self.store.contract_cache_status("upstox", now=self.now)

    def test_file_restart_and_expiry_transition_keep_exact_retained_version(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory)/"native.sqlite")
            with SQLitePersistenceStore(database) as store:
                first = store.refresh_contract_cache(self.raw(), provider="upstox",
                    source_reference="OFFLINE_SYNTHETIC_SCHEMA_FIXTURE", source_version="offline-v1",
                    captured_at=self.now.isoformat(), now=self.now)
            with SQLitePersistenceStore(database) as restarted:
                self.assertEqual(restarted.contract_cache_status("upstox", now=self.now)["master_id"], first["master_id"])
                self.assertEqual(restarted.contract_cache_status("upstox", now=self.now+timedelta(days=9))["status"], "STALE")
                old = restarted.get_contract_master_candidate(first["master_id"], include_original=True)
                result = resolve_contract_identity(old, provider="upstox", instrument_type="OPTSTK",
                    as_of=self.now+timedelta(days=9), identifier="NSE_FO|900001")
                self.assertFalse(result["eligible"])
                self.assertNotIn("observed_contract", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)

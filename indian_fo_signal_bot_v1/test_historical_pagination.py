"""Offline chronological storage snapshots, not qualified historical performance."""
import copy
from datetime import datetime, timedelta
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import test_bot
from config import BotConfig
from storage import SQLitePersistenceStore
from strategies import IST


class TestHistoricalPagination(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name)/"history.sqlite")
        self.store = SQLitePersistenceStore(self.database)
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 21, 16, tzinfo=IST)

    def bars(self, sessions=2):
        from test_bot import TestIndianFOSignalBotPhase3A
        day, result = datetime(2026, 1, 2, tzinfo=IST), []
        while len(result) < sessions*75:
            if day.weekday() < 5:
                result.extend(TestIndianFOSignalBotPhase3A._build_session_bars(day.date().isoformat(), data_mode="SIMULATED"))
            day += timedelta(days=1)
        return result

    def ingest(self, bars):
        return self.store.save_historical_candle_dataset(bars, "RELIANCE", provider="offline_fixture",
            instrument_token="2885", data_mode="SIMULATED", reference_time_ist=self.now)

    def page(self, **kwargs):
        return self.store.query_historical_candle_page("RELIANCE", data_mode="SIMULATED", provider="offline_fixture", **kwargs)

    def test_more_than_ten_thousand_rows_have_exact_order_and_no_truncation(self):
        bars = self.bars(134)
        self.ingest(bars)
        loaded = self.store.read_historical_snapshot("RELIANCE", data_mode="SIMULATED", provider="offline_fixture")
        self.assertEqual((loaded["total_count"], len(loaded["items"])), (10050, 10050))
        self.assertEqual([r["timestamp"] for r in loaded["items"]], [b["timestamp"] for b in bars])
        self.assertGreater(loaded["pages_read"], 1)
        self.assertEqual(len({r["dedup_key"] for r in loaded["items"]}), 10050)

    def test_cursor_survives_restart_excludes_new_ingestion_and_covers_all_original_rows(self):
        bars = self.bars()
        self.ingest(bars)
        first = self.page(limit=37)
        self.assertEqual(len(first["items"]), 37)
        self.ingest(self.bars(3)[150:])
        self.store.close()
        self.store = SQLitePersistenceStore(self.database)
        self.addCleanup(self.store.close)
        rows, cursor = list(first["items"]), first["next_cursor"]
        while cursor:
            page = self.page(limit=37, cursor=cursor)
            self.assertEqual(page["snapshot_digest"], first["snapshot_digest"])
            rows.extend(page["items"])
            cursor = page["next_cursor"]
        self.assertEqual([r["timestamp"] for r in rows], [b["timestamp"] for b in bars])
        self.assertEqual(self.page()["total_count"], 225)

    def test_changed_or_deleted_snapshot_rows_and_wrong_scope_are_rejected(self):
        self.ingest(self.bars())
        first = self.page(limit=37)
        with self.assertRaises(ValueError):
            self.store.query_historical_candle_page("INFY", data_mode="SIMULATED", provider="offline_fixture", cursor=first["next_cursor"])
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE historical_candles SET volume=volume+1 WHERE id=1")
        with self.assertRaisesRegex(ValueError, "SNAPSHOT_CHANGED"):
            self.page(cursor=first["next_cursor"])

    def test_invalid_cursors_and_limits_fail_without_writes(self):
        self.ingest(self.bars())
        for kwargs in ({"limit": 0}, {"limit": True}, {"limit": 10001}, {"cursor": "not-a-cursor"}, {"cursor": "A"*5000}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.page(**kwargs)
        self.assertEqual(self.page()["total_count"], 150)

    def test_paged_store_backtest_matches_direct_observation_outcomes(self):
        from backtest_engine import DeterministicBacktestEngine
        bars = self.bars()
        self.ingest(bars)
        config = BotConfig(active_broker="paper_sim", telegram_dry_run=True, enable_background_scheduler=False)
        engine = DeterministicBacktestEngine(bot_config=config, store=self.store, clock=lambda: self.now)
        direct = engine.run_backtest("strat_4_orb_filtered", "RELIANCE", candles=copy.deepcopy(bars),
                                    provider="offline_fixture", data_mode="SIMULATED")
        reader = self.store.read_historical_snapshot
        with patch.object(self.store, "read_historical_snapshot", side_effect=lambda *a, **k: reader(*a, page_size=37, **k)):
            stored = engine.run_backtest("strat_4_orb_filtered", "RELIANCE", provider="offline_fixture", data_mode="SIMULATED")
        self.assertEqual(stored["dataset_checksum"], direct["dataset_checksum"])
        self.assertEqual(stored["metrics"], direct["metrics"])
        self.assertEqual(stored["ending_capital_inr"], direct["ending_capital_inr"])
        self.assertEqual(stored["assumptions"]["storage_snapshot"]["pages_read"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)

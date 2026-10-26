"""Offline health acceptance reads share one snapshot without cached verdicts."""
import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

if 'test_bot' not in sys.modules:
    import test_bot
_fixtures = sys.modules['test_bot']


def setUpModule():
    guard = patch.dict(os.environ, _fixtures._test_config_defaults)
    guard.start()
    unittest.addModuleCleanup(guard.stop)


class TestAstraHealthReads(unittest.TestCase):
    def setUp(self):
        from config import BotConfig
        from storage import SQLitePersistenceStore
        from strategies import IST
        self.config = BotConfig(active_broker='paper_sim', database_url=':memory:',
            telegram_dry_run=True, enable_background_scheduler=False)
        self.store = SQLitePersistenceStore(':memory:')
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        self.symbols = [m['symbol'] for m in self.config.equity_watchlist]

    def test_health_checks_every_symbol_using_one_fresh_read_snapshot(self):
        from server import DashboardRequestHandler
        from readiness_policy import live_acceptance
        handler = object.__new__(DashboardRequestHandler)
        handler.engine = SimpleNamespace(config=self.config, store=self.store,
            get_broker_status=lambda: dict(connection_state='SIMULATED'),
            last_scan_summary=None, clock=lambda: self.now)
        handler.scheduler = SimpleNamespace(get_status=lambda: dict(running=False))
        handler.paper_portfolio = None
        expected = {s: live_acceptance(self.config, self.store, 'paper_sim', s, self.now) for s in self.symbols}
        with patch.object(self.store, 'load_live_acceptance_evidence', wraps=self.store.load_live_acceptance_evidence) as read:
            code, payload = handler._handle_health()
        self.assertEqual(code, 200)
        self.assertEqual(payload['live_acceptance']['by_symbol'], expected)
        self.assertFalse(payload['live_acceptance']['accepted'])
        self.assertEqual(read.call_count, len(self.symbols))
        connections = [call.kwargs.get('connection') for call in read.call_args_list]
        self.assertTrue(all(conn is not None for conn in connections))
        self.assertTrue(all(conn is connections[0] for conn in connections))

    def test_bulk_reads_preserve_individual_validation_and_reread_later_changes(self):
        from readiness_policy import live_acceptance, live_acceptance_for_symbols
        symbols = self.symbols[:2]
        self.store._save_live_acceptance_evidence('angelone', symbols[0], {'invalid': 'fixture'})
        expected = {s: live_acceptance(self.config, self.store, 'angelone', s, self.now) for s in symbols}
        self.assertEqual(live_acceptance_for_symbols(self.config, self.store, 'angelone', symbols, self.now), expected)
        with self.store.paper_transaction() as conn:
            conn.execute('UPDATE live_acceptance_evidence SET evidence_json=? WHERE provider=? AND symbol=?',
                         ('{invalid', 'angelone', symbols[0]))
        later = live_acceptance_for_symbols(self.config, self.store, 'angelone', symbols, self.now)
        self.assertEqual(later[symbols[0]]['reason_code'], 'ACCEPTANCE_EVIDENCE_UNREADABLE')
        self.assertEqual(later[symbols[1]], expected[symbols[1]])
        self.store._revoke_live_acceptance_evidence('angelone', symbols[0])
        self.assertEqual(live_acceptance_for_symbols(self.config, self.store, 'angelone', symbols, self.now)[symbols[0]], expected[symbols[1]])

    def test_missing_store_and_failed_read_snapshot_remain_unavailable(self):
        from readiness_policy import live_acceptance, live_acceptance_for_symbols
        self.assertEqual(live_acceptance_for_symbols(self.config, None, 'angelone', self.symbols, self.now),
            {s: live_acceptance(self.config, None, 'angelone', s, self.now) for s in self.symbols})
        with patch.object(self.store, 'lineage_read', side_effect=RuntimeError('offline fixture')):
            actual = live_acceptance_for_symbols(self.config, self.store, 'angelone', self.symbols, self.now)
        self.assertTrue(all(v['accepted'] is False and v['reason_code'] == 'ACCEPTANCE_EVIDENCE_UNREADABLE' for v in actual.values()))

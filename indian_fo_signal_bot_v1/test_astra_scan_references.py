"""Offline scanner metadata reuse must retain exact input and mutation boundaries."""
import copy
from datetime import datetime, timedelta
import os
import sys
import unittest
from unittest.mock import patch

if 'test_bot' not in sys.modules and not hasattr(sys.modules.get('__main__'), '_test_config_defaults'):
    import test_bot
_fixtures = sys.modules.get('test_bot') or sys.modules['__main__']


def setUpModule():
    guard = patch.dict(os.environ, _fixtures._test_config_defaults)
    guard.start()
    unittest.addModuleCleanup(guard.stop)


class TestAstraScanReferences(unittest.TestCase):
    def setUp(self):
        from brokers import MultiBrokerScanner, SimulatedNSEAdapter
        from config import BotConfig
        from scanner_engine import IntradayBotEngine
        from strategies import IST
        self.now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        cfg = BotConfig(active_broker='paper_sim', database_url=':memory:',
            telegram_dry_run=True, enable_background_scheduler=False, fo_indices={})
        cfg.equity_watchlist = [m for m in cfg.equity_watchlist if m['symbol'] == 'RELIANCE']
        self.scanner = MultiBrokerScanner(cfg, clock=lambda: self.now)
        self.scanner.adapters['paper_sim'] = _fixtures._BidirectionalFixtureAdapter(
            SimulatedNSEAdapter(seed=42, clock=lambda: self.now))
        self.engine = IntradayBotEngine(cfg, broker_scanner=self.scanner, clock=lambda: self.now)
        self.addCleanup(self.engine.close)

    def test_each_distinct_input_is_normalized_once_and_all_references_match(self):
        import scanner_engine
        from candle_lineage import digest
        from strategies import filter_completed_candles
        captured = []
        fetch = self.scanner.fetch_candles
        def capture(*args, **kwargs):
            rows = fetch(*args, **kwargs)
            captured.append(copy.deepcopy(rows))
            return rows
        with patch.object(self.scanner, 'fetch_candles', side_effect=capture), \
                patch('scanner_engine.filter_completed_candles', wraps=scanner_engine.filter_completed_candles) as normalize:
            scan = self.engine.run_single_scan()
        self.assertEqual(scan['scan_status'], 'COMPLETED')
        self.assertEqual(len(scan['strategy_evaluations']), 4)
        # One breadth normalization plus one source-reference normalization,
        # independent of the number of strategies and resulting candidates.
        self.assertEqual(normalize.call_count, 2)
        expected = filter_completed_candles(captured[0], interval_min=5, now=self.now)
        retained = self.engine.store.load_scan_evaluations(scan['run_id'])
        for row in scan['strategy_evaluations'] + scan['candidate_evaluations']:
            self.assertEqual(row['source_reference']['candle_digest'], digest(expected))
            self.assertEqual(row['source_reference']['candle_timestamps'], [r['timestamp'] for r in expected])
        self.assertEqual(retained['strategy_evaluations'], scan['strategy_evaluations'])
        self.assertEqual(retained['candidate_evaluations'], scan['candidate_evaluations'])

    def test_returned_metadata_is_independent_and_next_scan_rebuilds_it(self):
        first = self.engine.run_single_scan()
        refs = [row['source_reference'] for row in first['strategy_evaluations']]
        before = copy.deepcopy(refs[1])
        old_digest = refs[0]['candle_digest']
        refs[0]['candle_timestamps'].append('CALLER_MUTATION')
        refs[0]['instrument_identity']['test'] = 'CALLER_MUTATION'
        self.assertEqual(refs[1], before)
        self.now += timedelta(minutes=5)
        fetch = self.scanner.fetch_candles
        def changed(*args, **kwargs):
            rows = fetch(*args, **kwargs)
            rows[-1]['volume'] += 321
            return rows
        with patch.object(self.scanner, 'fetch_candles', side_effect=changed):
            second = self.engine.run_single_scan()
        new = second['strategy_evaluations'][0]['source_reference']
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertNotEqual(old_digest, new['candle_digest'])
        self.assertNotIn('CALLER_MUTATION', new['candle_timestamps'])

    def test_evaluator_input_mutation_invalidates_metadata_reuse(self):
        import scanner_engine
        from candle_lineage import digest
        from strategies import filter_completed_candles
        original = scanner_engine.evaluate_vwap_pullback
        expected = []
        def mutate(**kwargs):
            # Exercise a test/future evaluator override; unchanged later input
            # must not reuse the source metadata for the earlier content.
            rows = kwargs['candles']
            rows[-1]['volume'] += 123
            expected.append(digest(filter_completed_candles(rows, interval_min=5, now=self.now)))
            return original(**kwargs)
        with patch('scanner_engine.evaluate_vwap_pullback', side_effect=mutate):
            scan = self.engine.run_single_scan()
        self.assertEqual(scan['scan_status'], 'COMPLETED')
        traces = {row['strategy_id']: row for row in scan['strategy_evaluations']}
        self.assertNotEqual(traces['strat_1_order_block']['source_reference']['candle_digest'], expected[0])
        for name in ('strat_2_vwap_pullback', 'strat_4_orb_filtered', 'strat_5_supertrend_pullback'):
            self.assertEqual(traces[name]['source_reference']['candle_digest'], expected[0])
        self.assertTrue(all(row['actionable'] is False for row in scan['candidate_evaluations']))

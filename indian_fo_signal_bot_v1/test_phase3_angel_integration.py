"""Angel feed application handoff and bounded-control safety; no external I/O."""
import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from datetime import datetime

import test_bot
from angel_feed_control import load_current_instrument, preflight, smoke
from brokers import AngelOneSmartAPIAdapter, BrokerDataError
from config import BotConfig
from scanner_engine import IntradayBotEngine
from strategies import IST


class UnavailableAngelFeed:
    def __init__(self, provider='angelone'):
        self.provider, self.stopped = provider, False

    def status(self):
        return dict(provider=self.provider, status='STALE', live_signal_allowed=False)

    def get_candles(self, *args, **kwargs):
        raise ValueError('OFFLINE_PRIVATE_TOKEN_DO_NOT_PRINT')

    def stop(self):
        self.stopped = True


class TestAngelPhase3Integration(unittest.TestCase):
    def config(self, **changes):
        return BotConfig(**dict(dict(active_broker='paper_sim', database_url=':memory:',
            telegram_dry_run=True, enable_background_scheduler=False, angel_api_key='OFFLINE_KEY',
            angel_client_code='OFFLINE_CLIENT', angel_pin='7531',
            angel_totp_secret='JBSWY3DPEHPK3PXP', angel_scrip_master_path=''), **changes))

    def row(self, **changes):
        return dict(dict(token='2885', symbol='RELIANCE-EQ', name='RELIANCE', expiry='',
                    strike='-1.000000', lotsize='1', instrumenttype='', exch_seg='NSE', tick_size='5.000000'), **changes)

    def test_current_master_original_hash_bound_and_conflicting_records_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'master.json'
            rows = [self.row()]
            path.write_text(json.dumps(rows), encoding='utf-8')
            adapter = AngelOneSmartAPIAdapter(self.config())
            verified = load_current_instrument(adapter, 'RELIANCE', path)
            self.assertEqual(verified['instrument_identity']['identifier'], '2885')
            self.assertEqual(len(verified['current_master_sha256']), 64)
            for invalid in ([self.row(), self.row()], [self.row(token='999')],
                            [self.row(lotsize='2')], [self.row(symbol='RELIANCE-BE')],
                            [self.row(name='WRONG')]):
                path.write_text(json.dumps(invalid), encoding='utf-8')
                with self.subTest(invalid=invalid), self.assertRaises(Exception):
                    load_current_instrument(adapter, 'RELIANCE', path)

    def test_preflight_explicit_runtime_provider_preserves_saved_provider_and_never_authenticates(self):
        cfg = self.config()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'master.json'
            path.write_text(json.dumps([self.row()]), encoding='utf-8')
            with (patch('urllib.request.urlopen', side_effect=AssertionError('No request')),
                  patch.object(AngelOneSmartAPIAdapter, 'authenticate', side_effect=AssertionError('No auth'))):
                self.assertIn('EXPLICIT_ANGEL_DATA_PROVIDER_REQUIRED', preflight(cfg, 'RELIANCE', path)['blockers'])
                result = preflight(cfg, 'RELIANCE', path, 'angelone')
            self.assertEqual(result['status'], 'PASS')
            self.assertEqual(result['execution_mode'], 'PAPER_ONLY')
            self.assertEqual(cfg.active_broker, 'paper_sim')
            self.assertFalse(result['live_requests'])
            self.assertFalse(result['live_feed_accepted'])
            self.assertNotIn('OFFLINE_KEY', json.dumps(result))

    def test_probe_rejects_unsafe_flags_duration_scope_and_invalid_stage_before_io(self):
        cfg = self.config()
        with (patch('urllib.request.urlopen', side_effect=AssertionError('No request')),
              patch.object(AngelOneSmartAPIAdapter, 'authenticate', side_effect=AssertionError('No auth'))):
            for seconds in (0, 31, True):
                self.assertFalse(smoke(cfg, 'RELIANCE', provider='angelone', seconds=seconds, stage='offline')['live_requests'])
            self.assertFalse(smoke(cfg, 'RELIANCE', provider='angelone', stage='../private')['live_requests'])
            for changes in (dict(telegram_dry_run=False), dict(enable_background_scheduler=True),
                            dict(angel_api_key='')):
                result = smoke(self.config(**changes), 'RELIANCE', provider='angelone',
                               fetch_master=True, stage='offline')
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertFalse(result['live_requests'])

    def test_long_observation_requires_explicit_consent_and_cannot_exceed_seven_minutes(self):
        cfg = self.config()
        with patch('urllib.request.urlopen', side_effect=AssertionError('No requests')):
            denied = smoke(cfg, 'RELIANCE', provider='angelone', seconds=420, stage='offline')
            self.assertEqual(denied['blockers'], ['EXTENDED_OBSERVATION_AUTHORIZATION_REQUIRED'])
            for duration in (421, 3600):
                denied = smoke(cfg, 'RELIANCE', provider='angelone', seconds=duration,
                               stage='offline', extended_observation_authorized=True)
                self.assertEqual(denied['blockers'], ['OBSERVATION_DURATION_OUTSIDE_AUTHORIZED_BOUND'])
            # Consent only changes the time limit; it cannot bypass mapping/preflight.
            denied = smoke(cfg, 'RELIANCE', provider='angelone', seconds=420,
                           stage='offline', extended_observation_authorized=True)
            self.assertIn('ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED', denied['blockers'])
            self.assertFalse(denied['live_requests'])

    def test_attach_is_inert_rejects_provider_mismatch_and_cannot_replace_existing_feed(self):
        adapter = AngelOneSmartAPIAdapter(self.config())
        feed = UnavailableAngelFeed()
        with patch('socket.socket.connect', side_effect=AssertionError('No network')):
            adapter.attach_live_feed(feed)
            self.assertIs(adapter.live_feed, feed)
            with self.assertRaises(BrokerDataError):
                adapter.attach_live_feed(UnavailableAngelFeed())
            with self.assertRaises(BrokerDataError):
                AngelOneSmartAPIAdapter(self.config()).attach_live_feed(UnavailableAngelFeed('dhan'))
        adapter.close()
        self.assertTrue(feed.stopped)
        self.assertIsNone(adapter.live_feed)

    def test_stream_failure_never_calls_rest_or_other_provider_or_leaks_transport_error(self):
        cfg = self.config(active_broker='angelone')
        adapter = AngelOneSmartAPIAdapter(cfg)
        adapter.attach_live_feed(UnavailableAngelFeed())
        with (patch.object(adapter, '_request_json', side_effect=AssertionError('No REST')),
              patch('urllib.request.urlopen', side_effect=AssertionError('No other provider'))):
            with self.assertRaises(BrokerDataError) as failure:
                adapter.get_intraday_candles(cfg.equity_watchlist[0])
        self.assertNotIn('OFFLINE_PRIVATE_TOKEN', str(failure.exception))
        self.assertEqual(adapter.get_feed_status()['status'], 'STALE')
        adapter.close()

    def test_stream_health_blocks_old_verified_connection_and_engine_shutdown_stops_angel(self):
        engine = IntradayBotEngine(self.config(active_broker='angelone'),
                                   clock=lambda: datetime(2026, 10, 23, 10, 30, tzinfo=IST))
        self.addCleanup(engine.close)
        feed = UnavailableAngelFeed()
        adapter = engine.broker.adapters['angelone']
        engine.last_broker_verified_at = '2026-10-23T10:29:00+05:30'
        adapter.attach_live_feed(feed)
        with patch('urllib.request.urlopen', side_effect=AssertionError('Status no requests')):
            result = engine.get_broker_status()
        self.assertEqual(result['connection_state'], 'STREAM_UNAVAILABLE')
        self.assertFalse(result['connectivity_verified'])
        self.assertFalse(result['live_signals_allowed'])
        self.assertEqual(result['stream']['provider'], 'angelone')
        engine.close()
        self.assertTrue(feed.stopped)
        self.assertIsNone(adapter.live_feed)

    def test_bounded_control_uses_one_login_explicit_angel_data_and_closes_without_acceptance(self):
        cfg = self.config()
        instrument = AngelOneSmartAPIAdapter(cfg).resolve_instrument('RELIANCE')
        instrument['current_master_sha256'] = 'a'*64
        transport = Mock()
        transport.status.return_value = dict(provider='angelone', status='LIVE',
            reason_code='OBSERVATIONS_RECEIVED', last_event_at='2026-10-23T10:30:00+05:30',
            live_signal_allowed=False)

        def authenticate(adapter):
            self.assertEqual(adapter.config.active_broker, 'angelone')
            self.assertFalse(adapter.session_recovery_enabled)
            adapter.jwt_token, adapter.feed_token = 'OFFLINE_JWT', 'OFFLINE_FEED'
            adapter.last_http_status = 200
            return True

        with tempfile.TemporaryDirectory() as directory:
            with (patch('angel_feed_control.PRIVATE', Path(directory)/'private'),
                  patch('angel_feed_control.preflight', return_value=dict(status='PASS', blockers=[])),
                  patch('angel_feed_control.load_current_instrument', return_value=instrument),
                  patch('angel_feed_control.time.monotonic', side_effect=itertools.count(0, 2)),
                  patch.object(AngelOneSmartAPIAdapter, 'authenticate', autospec=True, side_effect=authenticate) as login,
                  patch.object(AngelOneSmartAPIAdapter, 'refresh_access_token', side_effect=AssertionError('No refresh')),
                  patch('angel_feed.AngelLiveFeed', return_value=transport) as factory,
                  patch('urllib.request.urlopen', side_effect=AssertionError('No external requests'))):
                report = smoke(cfg, 'RELIANCE', provider='angelone', master_path='offline', seconds=1, stage='offline')
            self.assertEqual(report['status'], 'OBSERVED')
            self.assertEqual(login.call_count, 1)
            self.assertEqual(factory.call_args.kwargs['max_reconnects'], 0)
            transport.connect.assert_called_once()
            transport.stop.assert_called_once()
            self.assertTrue(report['clean_shutdown'])
            self.assertFalse(report['live_feed_accepted'])
            self.assertEqual(report['execution_mode'], 'PAPER_ONLY')
            self.assertEqual(cfg.active_broker, 'paper_sim')
            self.assertNotIn('OFFLINE_JWT', json.dumps(report))
            self.assertNotIn('OFFLINE_FEED', json.dumps(report))

    def test_historical_capture_follows_stream_stop_and_cannot_erase_observed_feed_result(self):
        cfg = self.config()
        instrument = AngelOneSmartAPIAdapter(cfg).resolve_instrument('RELIANCE')
        instrument['current_master_sha256'] = 'a'*64
        events = []
        feed = Mock()
        feed.status.return_value = dict(provider='angelone', last_event_at='offline', reason_code='OBSERVATIONS_RECEIVED')
        feed.stop.side_effect = lambda: events.append('STOP')

        def capture(*args, **kwargs):
            self.assertEqual(events, ['STOP'])
            events.append('HISTORY')
            return dict(blocker_code='ANGEL_HISTORICAL_CANDLE_REQUEST_REJECTED', http_status=403)

        with tempfile.TemporaryDirectory() as directory:
            with (patch('angel_feed_control.PRIVATE', Path(directory)/'private'),
                  patch('angel_feed_control.preflight', return_value=dict(status='PASS', blockers=[])),
                  patch('angel_feed_control.load_current_instrument', return_value=instrument),
                  patch('angel_feed_control.time.monotonic', side_effect=itertools.count(0, 2)),
                  patch.object(AngelOneSmartAPIAdapter, 'authenticate', return_value=True),
                  patch('angel_feed.AngelLiveFeed', return_value=feed),
                  patch('angel_history_capture.capture_one_history', side_effect=capture)):
                result = smoke(cfg, 'RELIANCE', provider='angelone', master_path='offline',
                               seconds=1, stage='offline', history_session='2026-10-22')
        self.assertEqual(events, ['STOP', 'HISTORY'])
        self.assertEqual(result['status'], 'OBSERVED')
        self.assertIn('ANGEL_HISTORICAL_CANDLE_REQUEST_REJECTED', result['blockers'])
        self.assertEqual(result['history']['http_status'], 403)

    def test_existing_scanner_snapshot_preserves_feed_event_links_without_source_authority(self):
        from test_cash_lineage import TestCashLineage
        from candle_lineage import make_snapshot
        from instrument_identity import bind_candles, spot_identity
        from storage import SQLitePersistenceStore
        cfg, rows, now = TestCashLineage().fixture()
        cfg.active_broker = 'angelone'
        identity = spot_identity(cfg.equity_watchlist[0], 'angelone')
        for row in rows:
            row.pop('instrument_identity', None)
            row.pop('provider', None)
            row.update(source='angel_websocket_v2', source_event_ids=['offline_event'],
                       volume_baseline_event_id='offline_baseline', connection_id='offline_connection',
                       current_master_sha256='a'*64, source_authenticity='AUTHENTICATED_TLS_FEED')
        rows = bind_candles(rows, identity)
        snapshot = make_snapshot(cfg, {'RELIANCE': rows}, {}, {},
            {'NSE_EQUITY_INTRADAY': set(), 'NSE_FO_INDEX': set()}, now)
        with SQLitePersistenceStore(':memory:') as store:
            store.prepare_cash_scan('offline-angel-links', snapshot)
            batch = store.load_cash_scan('offline-angel-links')['snapshot']['batches'][0]
        bar = batch['content']['candles'][0]
        self.assertEqual(bar['source_event_ids'], ['offline_event'])
        self.assertEqual(bar['volume_baseline_event_id'], 'offline_baseline')
        self.assertEqual(bar['connection_id'], 'offline_connection')
        self.assertEqual(bar['current_master_sha256'], 'a'*64)
        self.assertEqual(batch['source_authenticity'], 'NOT_ESTABLISHED')

    def test_complete_candle_subgate_does_not_falsely_report_insufficient_window_or_accept_scanner(self):
        cfg = self.config()
        instrument = AngelOneSmartAPIAdapter(cfg).resolve_instrument('RELIANCE')
        instrument['current_master_sha256'] = 'a'*64
        feed = Mock()
        feed.status.return_value = dict(provider='angelone', last_event_at='offline',
            reason_code='OBSERVATIONS_RECEIVED', live_signal_allowed=True,
            complete_candle_counts={'1': 6, '5': 1})
        with tempfile.TemporaryDirectory() as directory:
            with (patch('angel_feed_control.PRIVATE', Path(directory)/'private'),
                  patch('angel_feed_control.preflight', return_value=dict(status='PASS', blockers=[])),
                  patch('angel_feed_control.load_current_instrument', return_value=instrument),
                  patch('angel_feed_control.time.monotonic', side_effect=itertools.count(0, 1000)),
                  patch.object(AngelOneSmartAPIAdapter, 'authenticate', return_value=True),
                  patch('angel_feed.AngelLiveFeed', return_value=feed)):
                result = smoke(cfg, 'RELIANCE', provider='angelone', master_path='offline',
                    seconds=420, stage='offline', extended_observation_authorized=True)
        self.assertEqual(result['completed_candle_subgate'], 'PASS')
        self.assertNotIn('OBSERVATION_WINDOW_INSUFFICIENT', result['blockers'])
        self.assertNotIn('ANGEL_CANDLE_ACCEPTANCE_INSUFFICIENT', result['blockers'])
        self.assertEqual(result['blockers'], ['LIVE_SCANNER_CONSUMER_ACCEPTANCE_NOT_ESTABLISHED'])
        self.assertFalse(result['live_feed_accepted'])


if __name__ == '__main__':
    unittest.main()

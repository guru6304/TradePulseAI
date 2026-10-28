"""Explicit single-instrument, read-only Angel feed acceptance control.

Defaults to local checks. --provider angelone is an explicit runtime data-source
selection, independent of the saved provider and existing paper-only execution.
No scheduler, general engine, Telegram sender or order API is instantiated here.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import time
import urllib.request
import urllib.error

MASTER_URL = 'https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json'
APP = Path(__file__).resolve().parent
PRIVATE = APP/'.local/phase3-angel'


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def load_current_instrument(adapter, symbol, master_path):
    """Cross-check canonical pins against one exact record in original master bytes."""
    from instrument_identity import canonical_symbol
    symbol = canonical_symbol(symbol)
    path = Path(master_path)
    age = time.time()-path.stat().st_mtime
    if not -5 <= age <= float(adapter.config.angel_scrip_master_max_age_hours)*3600:
        raise ValueError('ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED')
    if not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError('ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED')
    raw = path.read_bytes()
    records = json.loads(raw)
    if not isinstance(records, list):
        raise ValueError('ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED')
    matches = [r for r in records if isinstance(r, dict) and
               str(r.get('exch_seg', '')).upper() == 'NSE' and
               (str(r.get('symbol', '')).upper() == symbol+'-EQ' or
                str(r.get('name', '')).upper() == symbol and
                str(r.get('symbol', '')).upper().endswith('-EQ'))]
    if len(matches) != 1:
        raise ValueError('ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED')
    row = matches[0]
    token_matches = [r for r in records if isinstance(r, dict) and
                     str(r.get('exch_seg', '')).upper() == 'NSE' and
                     str(r.get('token', '')).strip() == str(row.get('token', '')).strip()]
    if len(token_matches) != 1:
        raise ValueError('ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED')
    if (row.get('symbol') != symbol+'-EQ' or row.get('name') != symbol or
            str(row.get('instrumenttype', '')).upper() not in ('', 'EQ') or
            str(row.get('lotsize')) != '1' or row.get('expiry') not in ('', None)):
        raise ValueError('ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED')
    adapter.load_scrip_master([row], strict=True)
    descriptor = adapter.resolve_instrument(symbol)
    descriptor.update(current_master_sha256=hashlib.sha256(raw).hexdigest(),
                      master_record=dict(adapter._scrip_master_equities[symbol]))
    return descriptor


def preflight(config, symbol, master_path=None, provider=None):
    selected = provider if provider is not None else config.active_broker
    result = dict(scope='LOCAL_ANGEL_FEED_PREFLIGHT', status='BLOCKED', live_requests=False,
                  provider='angelone' if selected == 'angelone' else 'NOT_SELECTED',
                  execution_mode='PAPER_ONLY', instrument_count=1,
                  authentication='NOT_TESTED', live_feed_accepted=False, blockers=[])
    if selected != 'angelone':
        result['blockers'].append('EXPLICIT_ANGEL_DATA_PROVIDER_REQUIRED')
    if config.telegram_dry_run is not True or config.enable_background_scheduler is not False:
        result['blockers'].append('SAFETY_GUARD_FAILURE:SAFE_RUNTIME_FLAGS')
    try:
        replace(config, active_broker='angelone').validate(require_live_credentials=False)
    except Exception:
        result['blockers'].append('ANGEL_CONFIGURATION_MISSING_OR_INVALID')
    if not config.is_broker_credentials_configured('angelone'):
        result['blockers'].append('ANGEL_CONFIGURATION_MISSING_OR_INVALID')
    try:
        ws_ver = importlib.metadata.version('websockets')
        if not (ws_ver.startswith('15.') or ws_ver.startswith('16.')):
            raise ValueError()
    except (importlib.metadata.PackageNotFoundError, ValueError):
        result['blockers'].append('PINNED_WEBSOCKET_RUNTIME_REQUIRED')
    try:
        from brokers import AngelOneSmartAPIAdapter
        adapter = AngelOneSmartAPIAdapter(replace(config, angel_scrip_master_path=''))
        descriptor = load_current_instrument(adapter, symbol, master_path or config.angel_scrip_master_path)
        result.update(instrument_identity=descriptor['instrument_identity'],
                      current_master_sha256=descriptor['current_master_sha256'])
    except Exception:
        result['blockers'].append('ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED')
    result['blockers'] = list(dict.fromkeys(result['blockers']))
    result['status'] = 'PASS' if not result['blockers'] else 'BLOCKED'
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def capture_master(directory):
    """One public HTTPS download; retain originals independently of normalized mapping."""
    path = Path(directory)/'master.original.json'
    if path.exists():
        raise ValueError('ORIGINAL_ARTIFACT_ALREADY_EXISTS')
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(urllib.request.Request(MASTER_URL, headers={'Accept': 'application/json'}), timeout=15) as response:
            raw = response.read(64 * 1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 64 * 1024 * 1024:
                raise ValueError('ANGEL_PUBLIC_MASTER_CAPTURE_REJECTED')
    except urllib.error.HTTPError as error:
        error.close()
        raise ValueError('ANGEL_PUBLIC_MASTER_CAPTURE_REJECTED') from None
    if not isinstance(json.loads(raw), list):
        raise ValueError('ANGEL_PUBLIC_MASTER_CAPTURE_REJECTED')
    with path.open('xb') as stream:
        stream.write(raw)
    receipt = dict(endpoint=MASTER_URL, captured_at=timestamp(), http_status=200,
                   original_sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                   evidence_type='AUTHENTICATED_TLS_CAPTURE', publisher_detached_signature=False,
                   historical_authority='NOT_ESTABLISHED')
    with (Path(directory)/'master.capture.json').open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2)
    return path, receipt


def smoke(config, symbol, *, provider=None, master_path=None, fetch_master=False,
          seconds=15, stage=None, history_session=None, extended_observation_authorized=False):
    """One login/instrument; a window beyond 30s needs separate explicit consent."""
    report = dict(scope='READ_ONLY_ANGEL_FEED_SMOKE', status='BLOCKED', live_requests=False,
                  live_feed_accepted=False, blockers=[], started_at=timestamp(),
                  execution_mode='PAPER_ONLY', clean_shutdown=True)
    limit = 420 if extended_observation_authorized is True else 30
    if type(seconds) is not int or not 1 <= seconds <= limit:
        return dict(report, blockers=['EXTENDED_OBSERVATION_AUTHORIZATION_REQUIRED' if
                    type(seconds) is int and 30 < seconds <= 420 else
                    'OBSERVATION_DURATION_OUTSIDE_AUTHORIZED_BOUND'])
    report['extended_observation_authorized'] = extended_observation_authorized is True
    if not isinstance(stage, str) or re.fullmatch(r'[a-z0-9_]{1,48}', stage) is None:
        return dict(report, blockers=['EXCLUSIVE_VALID_STAGE_REQUIRED'])
    # All safety/credential/provider checks happen before public or private I/O.
    check = preflight(config, symbol, master_path, provider)
    if [b for b in check['blockers'] if b != 'ANGEL_INSTRUMENT_IDENTITY_UNVERIFIED']:
        return dict(report, preflight=check, blockers=check['blockers'])
    if not fetch_master and check['status'] != 'PASS':
        return dict(report, preflight=check, blockers=check['blockers'])
    directory = PRIVATE/stage
    for ancestor in (PRIVATE.parent, PRIVATE):
        if ancestor.is_symlink() or getattr(ancestor, 'is_junction', lambda: False)():
            return dict(report, blockers=['PRIVATE_LOCAL_RESEARCH_ROOT_REQUIRED'])
    if directory.exists():
        return dict(report, blockers=['ORIGINAL_ARTIFACT_ALREADY_EXISTS_USE_NEW_STAGE'])
    directory.mkdir(parents=True, exist_ok=False)
    adapter = feed = store = None
    try:
        if fetch_master:
            report['live_requests'] = True
            master_path, report['master_capture'] = capture_master(directory)
        check = preflight(config, symbol, master_path, provider)
        report['preflight'] = check
        if check['status'] != 'PASS':
            report['blockers'] = check['blockers']
            return report
        from brokers import AngelOneSmartAPIAdapter
        from angel_feed import AngelLiveFeed
        from storage import SQLitePersistenceStore
        runtime = replace(config, active_broker='angelone', angel_scrip_master_path='')
        adapter = AngelOneSmartAPIAdapter(runtime)
        adapter.session_recovery_enabled = False
        instrument = load_current_instrument(adapter, symbol, master_path or config.angel_scrip_master_path)
        report.update(live_requests=True, instrument_identity=instrument['instrument_identity'],
                      current_master_sha256=instrument['current_master_sha256'],
                      observation_seconds_authorized=seconds, saved_provider_unchanged=config.active_broker,
                      authentication=dict(endpoint='/rest/auth/angelbroking/user/v1/loginByPassword',
                                          status='NOT_TESTED', started_at=timestamp()))
        try:
            adapter.authenticate()
        except Exception:
            report['authentication'].update(status='REJECTED', http_status=adapter.last_http_status,
                error_category=adapter.last_error_category, ended_at=timestamp())
            report['blockers'] = ['ANGEL_AUTHENTICATION_REJECTED']
            return report
        report['authentication'].update(status='PASS', http_status=adapter.last_http_status, ended_at=timestamp())
        store = SQLitePersistenceStore(str(directory/'live.sqlite3'))
        feed = AngelLiveFeed(runtime, store, instrument, credentials=dict(auth_token=adapter.jwt_token,
                api_key=runtime.angel_api_key, client_code=runtime.angel_client_code, feed_token=adapter.feed_token),
                max_reconnects=0)
        adapter.attach_live_feed(feed)
        report['stream_started_at'] = timestamp()
        deadline = time.monotonic() + seconds
        try:
            feed.connect()
            while time.monotonic() < deadline:
                feed.poll_once()
            report['status'] = 'OBSERVED' if feed.status().get('last_event_at') else 'INCOMPLETE'
        except Exception:
            report['status'] = 'FAIL'
        report['feed'] = feed.status()
        report['stream_stop_requested_at'] = timestamp()
        # Historical HTTP observation must not extend the authorized socket window.
        try:
            adapter.detach_live_feed()
        except Exception:
            report.update(status='FAIL', clean_shutdown=False,
                          blockers=['SAFETY_GUARD_FAILURE:FEED_SHUTDOWN'])
            return report
        report['stream_ended_at'] = timestamp()
        counts = report['feed'].get('complete_candle_counts', {})
        candle_gate = (report['feed'].get('live_signal_allowed') is True and
                       all(type(counts.get(str(n))) is int and counts[str(n)] > 0 for n in (1, 5)))
        report['completed_candle_subgate'] = 'PASS' if candle_gate else 'NOT_ESTABLISHED'
        report['blockers'] = (['LIVE_SCANNER_CONSUMER_ACCEPTANCE_NOT_ESTABLISHED'] if candle_gate else
                              ['OBSERVATION_WINDOW_INSUFFICIENT', 'ANGEL_CANDLE_ACCEPTANCE_INSUFFICIENT'])
        reason = report['feed'].get('reason_code', '')
        if reason not in ('OBSERVATIONS_RECEIVED', 'SUBSCRIPTION_UNCONFIRMED'):
            report['blockers'].insert(0, reason)
        # No short-probe receipt mints live recommendation or historical-study acceptance.
        if history_session:
            from angel_history_capture import capture_one_history
            try:
                report['history'] = capture_one_history(adapter, instrument, history_session,
                    directory/'history', stage, allow_live_request=True)
                if report['history'].get('blocker_code'):
                    report['blockers'].append(report['history']['blocker_code'])
            except Exception:
                report['history'] = dict(status='BLOCKED', live_requests=False,
                    blocker_code='ANGEL_HISTORICAL_CAPTURE_PREFLIGHT_OR_STORAGE_FAILURE')
                report['blockers'].append(report['history']['blocker_code'])
    except Exception:
        report.update(status='FAIL', blockers=['ANGEL_PROVIDER_UNAVAILABLE'])
    finally:
        try:
            if adapter is not None:
                adapter.close()
            elif feed is not None:
                feed.stop()
        except Exception:
            report.update(status='FAIL', clean_shutdown=False,
                          blockers=['SAFETY_GUARD_FAILURE:FEED_SHUTDOWN'])
        try:
            if store is not None:
                store.close()
        except Exception:
            report.update(status='FAIL', clean_shutdown=False,
                          blockers=['SAFETY_GUARD_FAILURE:STORE_SHUTDOWN'])
        report['ended_at'] = timestamp()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['angelone'])
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--master')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--fetch-master', action='store_true')
    parser.add_argument('--seconds', type=int, default=15)
    parser.add_argument('--extended-observation-authorized', action='store_true',
                        help='Use only with explicit operator approval; permits at most 420 seconds')
    parser.add_argument('--stage')
    parser.add_argument('--history-session')
    args = parser.parse_args(argv)
    from config import BotConfig
    cfg = BotConfig()
    report = (smoke(cfg, args.symbol, provider=args.provider, master_path=args.master,
                    fetch_master=args.fetch_master, seconds=args.seconds, stage=args.stage,
                    history_session=args.history_session,
                    extended_observation_authorized=args.extended_observation_authorized) if args.smoke else
              preflight(cfg, args.symbol, args.master, args.provider))
    if args.stage and re.fullmatch(r'[a-z0-9_]{1,48}', args.stage):
        target = APP/'docs/evidence'/('phase3_angel_probe_'+args.stage+'.json')
        with target.open('x', encoding='utf-8') as out:
            json.dump(report, out, indent=2, allow_nan=False)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report['status'] in ('PASS', 'OBSERVED') else 1


if __name__ == '__main__':
    raise SystemExit(main())

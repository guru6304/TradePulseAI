"""Offline fixture timing probe. Instrumented observations are not latency acceptance."""
import argparse
from collections import defaultdict
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import functools
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
import warnings

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import offline_network, source_snapshot, ExecutionResult, case_ids, python_result, digest, timestamp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True)
    args = parser.parse_args()
    assert args.stage.replace('_', '').isalnum()
    target = APP / 'docs/evidence' / ('astra_http_latency_' + args.stage)
    receipt, log = target.with_suffix('.json'), target.with_suffix('.txt')
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump(dict(status='IN_PROGRESS'), stream)
    measurements, lock = defaultdict(list), threading.Lock()
    source = source_snapshot(APP)
    started = timestamp()
    with log.open('x', encoding='utf-8') as stream, redirect_stdout(stream), redirect_stderr(stream), ExitStack() as stack:
        offline_network(stack)
        warnings.simplefilter('error', ResourceWarning)
        import test_bot
        from storage import SQLitePersistenceStore
        from server import DashboardRequestHandler
        from scanner_engine import IntradayBotEngine
        targets = [(IntradayBotEngine, '_attach_context'), (IntradayBotEngine, 'enrich_context'),
                   (SQLitePersistenceStore, 'enqueue_context_alert'),
                   (SQLitePersistenceStore, 'enrich_scan_context'),
                   (SQLitePersistenceStore, 'load_live_acceptance_evidence'),
                   (SQLitePersistenceStore, 'list_notification_outbox'),
                   (DashboardRequestHandler, '_handle_health'), (DashboardRequestHandler, '_handle_scan')]
        def wrapper(original, name):
            @functools.wraps(original)
            def timed(*args, **kwargs):
                begin = time.perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    with lock:
                        measurements[name].append(time.perf_counter() - begin)
            return timed
        for owner, name in targets:
            stack.enter_context(patch.object(owner, name, wrapper(getattr(owner, name), owner.__name__ + '.' + name)))
        suite = unittest.defaultTestLoader.loadTestsFromName('test_bot.TestIndianFOSignalBotPhase1F')
        expected = list(case_ids(suite))
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=ExecutionResult).run(suite)
    output = dict(scope='INSTRUMENTED_OFFLINE_HTTP_FIXTURE_NO_ACCEPTANCE_OR_PROVIDER_REQUEST',
        started_at=started, completed_at=timestamp(), execution=python_result(result, expected),
        measurements={name: dict(calls=len(values), total_seconds=sum(values), maximum_seconds=max(values),
                                durations_seconds=values) for name, values in sorted(measurements.items())},
        source_before=source, source_after=source_snapshot(APP), log=log.relative_to(APP).as_posix(),
        log_sha256=digest(log), helper_sha256=digest(Path(__file__)))
    receipt.write_text(json.dumps(output, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(dict(execution=output['execution']['status'], measurements={k: {p: v[p] for p in ('calls','total_seconds','maximum_seconds')}
        for k,v in output['measurements'].items()})))
    return output['execution']['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())

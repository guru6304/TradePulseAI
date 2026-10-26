"""Profile real offline scan/read paths; no timings confer acceptance."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import cProfile
import json
from pathlib import Path
import pstats
import sys
import time
import warnings

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import offline_network, source_snapshot, digest, timestamp


def main():
    target = APP / 'docs/evidence/astra_scan_profile_20261026_01'
    receipt, log = target.with_suffix('.json'), target.with_suffix('.txt')
    source = source_snapshot(APP)
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump(dict(status='IN_PROGRESS'), stream)
    results = []
    with log.open('x', encoding='utf-8') as stream, redirect_stdout(stream), redirect_stderr(stream), ExitStack() as stack:
        offline_network(stack)
        warnings.simplefilter('error', ResourceWarning)
        import test_bot
        from config import BotConfig
        from brokers import MultiBrokerScanner, SimulatedNSEAdapter
        from scanner_engine import IntradayBotEngine
        from datetime import datetime
        from strategies import IST
        now = datetime(2026, 10, 16, 10, 35, tzinfo=IST)
        cfg = BotConfig(active_broker='paper_sim', database_url=':memory:',
            telegram_dry_run=True, enable_background_scheduler=False)
        scanner = MultiBrokerScanner(cfg, clock=lambda: now)
        scanner.adapters['paper_sim'] = test_bot._BidirectionalFixtureAdapter(SimulatedNSEAdapter(seed=42, clock=lambda: now))
        engine = IntradayBotEngine(config=cfg, broker_scanner=scanner, clock=lambda: now)
        try:
            for name, action in [('scan', engine.run_single_scan),
                    ('scans_read', lambda: engine.store.query_scan_runs(limit=15)),
                    ('outbox_read', lambda: engine.store.list_notification_outbox(limit=1))]:
                profile = cProfile.Profile()
                wall, cpu = time.perf_counter(), time.process_time()
                result = profile.runcall(action)
                entry = dict(path=name, wall_seconds=time.perf_counter()-wall,
                    cpu_seconds=time.process_time()-cpu, status=result.get('scan_status', result.get('status')))
                stats = pstats.Stats(profile, stream=stream)
                print('\nPROFILE', name)
                stats.sort_stats('cumulative').print_stats(32)
                entry['top_functions'] = [dict(file=Path(k[0]).name, line=k[1], function=k[2],
                    primitive_calls=v[0], calls=v[1], total_cpu_seconds=v[2], cumulative_seconds=v[3])
                    for k, v in sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)[:32]]
                results.append(entry)
        finally:
            engine.close()
    report = dict(status='COMPLETED_DIAGNOSTIC_NOT_ACCEPTANCE', recorded_at=timestamp(),
        source_before=source, source_after=source_snapshot(APP), results=results,
        helper_sha256=digest(Path(__file__)), log_sha256=digest(log), provider_requests=0)
    receipt.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps([{k:v for k,v in r.items() if k!='top_functions'} for r in results]))


if __name__ == '__main__':
    main()

"""Bounded OFFLINE software benchmark; reuses labelled repository test fixtures.

This developer tool imports the existing offline test bootstrap, uses temporary
stores and guards transport. It never loads a production account or measures
strategy profitability. Timing has no pass threshold or production SLA meaning.
"""
import argparse
import copy
import json
import math
import os
import platform
import statistics
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


def sample_statistics(values):
    if not values or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<0 for v in values):
        raise ValueError('Finite nonnegative timing samples required.')
    ordered=sorted(values)
    return dict(samples=len(values),median_ms=round(statistics.median(ordered),6),max_ms=round(ordered[-1],6),
                p95_ms=round(ordered[math.ceil(.95*len(ordered))-1],6) if len(ordered)>=20 else None,
                p95_method='EMPIRICAL_NEAREST_RANK' if len(ordered)>=20 else 'OMITTED_FEWER_THAN_20_SAMPLES')


def run_offline_benchmark(samples=5,large_events=10000):
    if type(samples) is not int or not 3<=samples<=30 or large_events not in (100,1000,10000):
        raise ValueError('Use 3-30 repeats and a bounded 100/1000/10000-event fixture.')
    # Intentional developer-fixture dependency; no alternative trading engine.
    from test_phase5c_recovery import TestPhase5CRecovery
    from test_phase5a_provenance import TestPhase5AHistoricalProvenance
    from test_phase4_e2e import TestPhase4OfflineEndToEnd
    from config import BotConfig
    from brokers import MultiBrokerScanner,BrokerDataError,assess_live_candle_batch
    from instrument_identity import spot_identity,bind_candles
    from instrument_archive import prepare_archive
    from source_qualification import assess_source_evidence
    from paper_portfolio import FORWARD_FILL_POLICY,PaperPortfolio,PaperPortfolioError
    from scanner_engine import IntradayBotEngine
    from storage import SQLitePersistenceStore
    from strategies import validate_candles
    import scanner_engine
    import telegram_bot
    original_delivery=telegram_bot.TelegramSignalDispatcher.send_signal
    fixture=TestPhase5CRecovery()
    fixture.setUp()
    stages={}
    scan_results=[]
    def measure(name,action):
        started=time.perf_counter_ns()
        try:
            return action()
        finally:
            stages.setdefault(name,[]).append((time.perf_counter_ns()-started)/1e6)
    def timed_evaluator(name,original):
        def evaluate(*args,**kwargs):
            return measure('candidate_evaluation.'+name,lambda:original(*args,**kwargs))
        return evaluate
    def only_dry_run(dispatcher,*args,**kwargs):
        if dispatcher.config.telegram_dry_run is not True:
            raise AssertionError('Live delivery forbidden')
        return original_delivery(dispatcher,*args,**kwargs)
    try:
        base=fixture.f
        with ExitStack() as stack:
            stack.enter_context(patch('telegram_bot.TelegramSignalDispatcher.send_signal',new=only_dry_run))
            stack.enter_context(patch('scanner_engine.MarketScanScheduler.start',side_effect=AssertionError('No scheduler')))
            for name in ('evaluate_order_block_fvg','evaluate_vwap_pullback','evaluate_orb_breakout','evaluate_supertrend_pullback'):
                stack.enter_context(patch('scanner_engine.'+name,new=timed_evaluator(name,getattr(scanner_engine,name))))
            for count in (1,5,15):
                cfg=BotConfig(active_broker='paper_sim',telegram_dry_run=True,enable_background_scheduler=False,
                    enable_persistence=True,database_url=str(Path(base.temporary.name)/f'scan{count}.sqlite'),angel_scrip_master_path='')
                cfg.fo_indices={}
                cfg.equity_watchlist=cfg.equity_watchlist[:count]
                store=SQLitePersistenceStore(cfg.database_url)
                try:
                    engine=IntradayBotEngine(cfg,clock=lambda:base.now,broker_scanner=MultiBrokerScanner(cfg,clock=lambda:base.now),store=store)
                    try:
                        statuses=[]
                        for _ in range(samples):
                            result=measure(f'scanner.{count}_symbols',engine.run_single_scan)
                            if result['scan_status'] not in ('COMPLETED','COMPLETED_EMPTY') or result['instrument_errors']:
                                raise AssertionError('Offline scanner fixture failed; no timing acceptance may be claimed.')
                            statuses.append(result['scan_status'])
                        scan_results.append(dict(symbols=count,source='SIMULATED_NSE_ADAPTER',statuses=statuses))
                    finally:
                        engine.close()
                finally:
                    store.close()
        # Independent costs for data boundaries; these are not broker acceptance.
        scenario=TestPhase4OfflineEndToEnd()
        scenario.setUp()
        try:
            raw=scenario._fixture()[:-1]
            wire=[{k:b[k] for k in ('timestamp','open','high','low','close','volume')} for b in raw]
            identity=spot_identity({'symbol':'RELIANCE','upstox_key':'NSE_EQ|INE002A01018'},'upstox')
            archive_bytes=json.dumps(TestPhase5AHistoricalProvenance()._payload('upstox')).encode()
            archive=prepare_archive(archive_bytes,'upstox','offline.json','OFFLINE_SYNTHETIC_DECLARATION')
            for _ in range(samples):
                measure('normalization.60_bars',lambda:validate_candles(raw,deduplicate=False,sort_chronologically=False,
                    interval_min=5,now=scenario.now,default_is_simulated=True))
                measure('identity_binding.60_mocked_wire_bars',lambda:bind_candles(wire,identity))
                _,fresh=measure('freshness.60_mocked_bars',lambda:assess_live_candle_batch(
                    wire,
                    interval_min=5,now_ist=scenario.now,provider='upstox',symbol='RELIANCE',context='DIAGNOSTIC'))
                if not fresh['is_fresh']:
                    raise AssertionError('Controlled freshness fixture did not pass its parser gate.')
                qualification=measure('source_qualification.blocked_declaration',lambda:assess_source_evidence(archive,archive_bytes))
                if qualification['historical_eligibility']['allowed']:
                    raise AssertionError('A fixture must never qualify as historical source evidence.')
            # Actual adapter/scanner failure path, transport intercepted by fixture.
            failed=scenario._engine('upstox')
            scenario.failures['upstox']='transport'
            for _ in range(samples):
                try:
                    failure=measure('scanner.mocked_provider_error',failed.run_single_scan)
                except BrokerDataError:
                    failure=failed.last_scan_summary
                if failure['scan_status']!='FAILED' or failure['signals']:
                    raise AssertionError('Provider failure must not yield fixture fallback/signals.')
        finally:
            scenario.doCleanups()
        for index in range(samples):
            base._set_time('10:10')
            paper=base._service(account_id=f'latency{index}',fill_policy=FORWARD_FILL_POLICY,cost_model_json='{}')
            candidate=base._candidate(paper)
            result=measure('paper.entry',lambda:paper.enter(candidate,base._bar(candidate),'entry'))
            base._set_time('10:15')
            measure('paper.mark',lambda:paper.process_bar(result['position_id'],base._bar(candidate,stamp='10:10'),'mark'))
            base._set_time('10:20')
            measure('paper.exit',lambda:paper.process_bar(result['position_id'],base._bar(candidate,stamp='10:15',high=125,low=99,close=121),'exit'))
            persisted=copy.deepcopy(candidate)
            from datetime import timedelta
            persisted.timestamp=(base.now.replace(hour=13,minute=0,second=0)+timedelta(minutes=5*index)).strftime('%Y-%m-%d %H:%M:%S')
            measure('persistence.new_signal',lambda:fixture.store.save_signal(persisted,broker='OFFLINE_BENCHMARK',now_ist=base.now))
            measure('persistence.duplicate_signal',lambda:fixture.store.save_signal(persisted,broker='OFFLINE_BENCHMARK',now_ist=base.now))
            base._set_time('10:10')
            missing=base._service(account_id=f'missing{index}',fill_policy=FORWARD_FILL_POLICY)
            absent,candidate=fixture.enter(missing)
            base._set_time('10:20')
            before=missing.snapshot()
            try:
                measure('paper.missing_observation_rejection',lambda:missing.process_bar(absent['position_id'],base._bar(candidate,stamp='10:15'),'gap'))
                raise AssertionError('Missing interval must freeze, not invent a mark.')
            except PaperPortfolioError as error:
                if error.reason_code!='MISSING_OR_OUT_OF_ORDER_POSITION_BAR':raise
            if missing.snapshot()!=before:
                raise AssertionError('Rejected observation changed accounting.')
        large=base._service(account_id='large_benchmark',fill_policy=FORWARD_FILL_POLICY,cost_model_json='{}')
        fixture.seed_lifecycle(large,large_events)
        for _ in range(samples):
            def restart():
                store=SQLitePersistenceStore(base.database)
                try:
                    PaperPortfolio(store,large.config,clock=lambda:base.now)
                finally:
                    store.close()
            measure('startup.existing_store',restart)
            if measure('paper.large_reconciliation',large.reconcile)['status']!='OK':
                raise AssertionError('Large ledger did not reconcile.')
            measure('paper.large_summary',large.snapshot)
            measure('paper.event_page',lambda:fixture.store.query_paper_ledger('large_benchmark',limit=100))
        tracemalloc.start()
        try:
            large.snapshot()
            _,peak=tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        concurrency=[]
        for workers in (1,2,4):
            stores=[SQLitePersistenceStore(base.database) for _ in range(workers)]
            try:
                barrier=threading.Barrier(workers)
                def worker(store):
                    barrier.wait(timeout=10)
                    times=[]
                    for _ in range(8):
                        started=time.perf_counter_ns()
                        page=store.query_paper_ledger('large_benchmark',limit=100)
                        if len(page['items'])!=100:
                            raise AssertionError('Incomplete bounded fixture page')
                        times.append((time.perf_counter_ns()-started)/1e6)
                    return times
                started=time.perf_counter()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    batches=list(pool.map(worker,stores))
                elapsed=time.perf_counter()-started
                times=[v for batch in batches for v in batch]
                concurrency.append(dict(workers=workers,requests=len(times),elapsed_seconds=round(elapsed,6),
                    throughput_requests_per_second=round(len(times)/elapsed,3),**sample_statistics(times)))
            finally:
                for store in stores:store.close()
        return dict(status='OFFLINE_MEASURED',evidence_class='SIMULATED_AND_MOCKED_SOFTWARE_ONLY',sla_accepted=False,
            host=dict(os=platform.system(),machine=platform.machine(),python=platform.python_version(),logical_cpus=os.cpu_count()),
            method='perf_counter_ns; repeated sequential timings; independent-store read concurrency; no latency threshold',
            large_account_events=large_events,large_account_positions=large_events//4,scanner=scan_results,
            timings={name:sample_statistics(values) for name,values in stages.items()},read_concurrency=concurrency,
            python_summary_peak_bytes=peak,memory_method='tracemalloc separate summary run; excludes SQLite/native/RSS allocations',
            provider_error_status=failure['scan_status'],source_qualification='BLOCKED',signal_quality='NOT_TESTED',
            no_live_transport=True,no_live_telegram=True,scheduler_started=False)
    finally:
        fixture.doCleanups()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=5)
    parser.add_argument('--events',type=int,choices=(100,1000,10000),default=10000)
    args=parser.parse_args(argv)
    if not 3<=args.samples<=30:
        parser.error('Use 3-30 repeats and a supported bounded fixture size.')
    report=run_offline_benchmark(args.samples,args.events)
    print(json.dumps(report,sort_keys=True,allow_nan=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())

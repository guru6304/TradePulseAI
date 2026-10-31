"""Capture actual backend response shapes from an isolated synthetic scanner run."""
import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP))
import test_bot
from test_astra_paper_triggers import ORBScannerFixture
from scanner_engine import MarketScanScheduler
from server import DashboardRequestHandler
from verify_offline import offline_network, source_snapshot


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',required=True)
    args=parser.parse_args()
    if not re.fullmatch('[a-z0-9_]{2,64}',args.stage):
        parser.error('unique simple stage required')
    target=APP/'docs/evidence'/(args.stage+'.json')
    log=target.with_suffix('.txt')
    if target.exists() or log.exists():
        parser.error('immutable stage exists')
    captured={}
    before=source_snapshot()

    class Capture(unittest.TestCase):
        def test_capture(self):
            stack=ExitStack();self.addCleanup(stack.close)
            stack.enter_context(patch.dict(os.environ,test_bot._test_config_defaults))
            offline_network(stack)
            fixture=ORBScannerFixture(self)
            first=fixture.scan()
            self.assertEqual(first['scan_status'],'COMPLETED')
            handler=DashboardRequestHandler.__new__(DashboardRequestHandler)
            handler.engine=fixture.engine
            handler.scheduler=MarketScanScheduler(fixture.engine)
            handler.paper_portfolio=None
            code,current=handler._handle_opportunity_rankings({'limit':['100'],'offset':['0']})
            self.assertEqual(code,200)
            self.assertEqual(current['status'],'CURRENT_CANDIDATE_PRIORITY')
            self.assertEqual(len(current['current_rows']),1)
            row=current['current_rows'][0]
            self.assertGreater(len(row['candidate_id']),160)
            self.assertTrue(row['candidate_id'].startswith('signal:v2:'))
            code,signals=handler._handle_signals({'symbol':[row['symbol']],
                'strategy_id':[row['strategy_id']],'provider':[row['instrument_identity']['provider']],
                'segment':[row['instrument_identity']['segment']],
                'start_time':[row['source_data_watermark']],'end_time':[row['source_data_watermark']]})
            self.assertEqual(code,200)
            self.assertEqual(len(signals['items']),1)
            self.assertEqual(signals['items'][0]['dedup_key'],row['candidate_id'])
            code,lineage=handler._handle_cash_lineage({'run_id':[first['run_id']]})
            self.assertEqual(code,200)
            batches=[b for b in lineage['batches'] if b['identity']==row['instrument_identity']]
            self.assertEqual(len(batches),1)
            code,candles=handler._handle_cash_lineage({'run_id':[first['run_id']],
                'batch_id':[batches[0]['batch_id']],'limit':['100'],'offset':['0']},candles=True)
            self.assertEqual(code,200)
            captured.update(current_rankings=current,signal_page=signals,lineage=lineage,candle_page=candles)
            fixture.append_bar(open=102,high=102.3,low=101.5,close=102.1,volume=1000)
            empty=fixture.scan()
            self.assertEqual(empty['scan_status'],'COMPLETED_EMPTY')
            fixture.scenario.now+=timedelta(seconds=1)
            code,archived=handler._handle_opportunity_rankings({'limit':['100'],'offset':['0']})
            self.assertEqual(code,200)
            self.assertEqual(archived['status'],'STALE_OR_FUTURE_SNAPSHOT')
            self.assertEqual(archived['pagination']['total'],0)
            self.assertEqual(archived['snapshot']['reference'],archived['snapshot']['valid_until'])
            self.assertEqual(archived['current_rows'],[])
            self.assertEqual(archived['historical_rows'],[])
            captured.update(archived_empty_rankings=archived,
                            mocked_transport_call_count=len(fixture.scenario.requests))

    with log.open('x',encoding='utf-8') as stream,redirect_stdout(stream),redirect_stderr(stream):
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(Capture('test_capture'))
    after=source_snapshot()
    passed=result.wasSuccessful() and result.testsRun==1 and not result.skipped and before==after
    data=dict(kind='SYNTHETIC_REAL_SCANNER_AND_HANDLER_RESPONSE_FIXTURE',status='PASS' if passed else 'FAIL',
        scope='OFFLINE_AUTHORED_INPUT_NOT_GENUINE_MARKET_DATA_OR_LIVE_ACCEPTANCE',
        captured_at=datetime.now(timezone.utc).isoformat(),source_before=before,source_after=after,
        actual_external_requests=0,operational_database_accessed=False,configuration_files_changed=False,
        executed_test_methods=result.testsRun,helper_sha256=sha(Path(__file__)),
        log=log.relative_to(APP).as_posix(),log_sha256=sha(log),payloads=captured)
    with target.open('x',encoding='utf-8') as stream:
        json.dump(data,stream,indent=2);stream.write('\n')
    row=(captured.get('current_rankings',{}).get('current_rows') or [{}])[0]
    print(json.dumps(dict(status=data['status'],candidate_id_length=len(row.get('candidate_id','')),
                         sha256=sha(target),fixture=str(target))))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())

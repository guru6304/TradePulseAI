"""Execute offline focused regressions, retaining exact failures as well as passes."""
import argparse
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import json
from pathlib import Path
import sys
import unittest
import warnings

APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP))
from verify_offline import timestamp,source_snapshot,offline_network,case_ids,ExecutionResult,python_result,digest

parser=argparse.ArgumentParser()
parser.add_argument('--stage',required=True)
parser.add_argument('modules',nargs='+')
args=parser.parse_args()
import re
if not re.fullmatch('[a-z0-9_]{1,40}',args.stage):
    parser.error('Unique lowercase stage required')
prefix=APP/'docs/evidence'/('phase4_implementation_focused_'+args.stage)
receipt=prefix.with_suffix('.json')
with receipt.open('x',encoding='utf-8') as out:
    json.dump(dict(status='RUNNING'),out)
before=source_snapshot(APP)
log=prefix.with_suffix('.txt')
unraisable=[]
with log.open('x',encoding='utf-8') as out,redirect_stdout(out),redirect_stderr(out),ExitStack() as stack:
    offline_network(stack)
    old=sys.unraisablehook
    sys.unraisablehook=lambda e:unraisable.append(type(e.exc_value).__name__)
    stack.callback(setattr,sys,'unraisablehook',old)
    warnings.simplefilter('error',ResourceWarning)
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in args.modules)
    expected=list(case_ids(suite))
    result=unittest.TextTestRunner(stream=out,verbosity=2,resultclass=ExecutionResult).run(suite)
data=python_result(result,expected)
data.update(command=[sys.executable,'-B','-W','error::ResourceWarning',str(Path(__file__).relative_to(APP)),
                     '--stage',args.stage,*args.modules],recorded_at=timestamp(),
            source_before=before,source_after=source_snapshot(APP),unraisable_errors=unraisable,
            log=log.relative_to(APP).as_posix(),log_sha256=digest(log),scope='OFFLINE_FIXTURE_NO_OPERATIONAL_ACCEPTANCE')
receipt.write_text(json.dumps(data,indent=2),encoding='utf-8')
print(json.dumps({k:data[k] for k in ('status','executed','passed','failures','errors','skipped')}))
raise SystemExit(data['exit_code'] or bool(unraisable))

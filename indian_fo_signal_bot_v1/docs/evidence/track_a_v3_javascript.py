"""Source-bound terminal DOM regressions. Authored readers only; not a browser."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

APP = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--test', required=True)
    args = parser.parse_args()
    if not re.fullmatch('[a-z0-9_]{2,64}', args.stage) or not re.fullmatch('test_terminal_[a-z0-9_]+[.]js', args.test):
        parser.error('simple unique stage and root terminal test required')
    target = APP/'docs/evidence'/(args.stage+'.json')
    log = target.with_suffix('.txt')
    if target.exists() or log.exists():
        parser.error('immutable stage exists')
    files = ['public/terminal.html','public/terminal.css','public/terminal.js',args.test]
    before = {name:sha(APP/name) for name in files}
    command = ['node','--test','--test-reporter=tap',args.test]
    started = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(command,cwd=APP,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
    output = result.stdout+result.stderr
    with log.open('x',encoding='utf-8') as stream:
        stream.write(output)
    counts = {}
    for word in ('tests','pass','fail','cancelled','skipped','todo'):
        match = re.search(r'^# '+word+r' (\d+)\s*$',output,re.MULTILINE)
        counts[word] = int(match[1]) if match else None
    after = {name:sha(APP/name) for name in files}
    passed = (result.returncode==0 and bool(counts.get('tests')) and counts['pass']==counts['tests']
              and all(counts[key]==0 for key in ('fail','cancelled','skipped','todo')) and before==after)
    data = dict(kind='EXECUTED_TERMINAL_DOM_REGRESSION',status='PASS' if passed else 'FAIL',
        started_at=started,completed_at=datetime.now(timezone.utc).isoformat(),command=command,
        exit_code=result.returncode,counts=counts,source_before=before,source_after=after,
        helper_sha256=sha(Path(__file__)),log=log.relative_to(APP).as_posix(),log_sha256=sha(log),
        scope='AUTHORED_READER_AND_DOM_DOUBLE_NOT_BROWSER_OR_LIVE_ACCEPTANCE',
        operational_database_accessed=False,environment_files_read=False)
    with target.open('x',encoding='utf-8') as stream:
        json.dump(data,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(status=data['status'],counts=counts,receipt=str(target))))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())

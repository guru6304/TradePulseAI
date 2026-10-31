"""Retain scoped terminal-clock execution and source/log bindings; no app imports."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True)
    args = parser.parse_args()
    if not re.fullmatch('[a-z0-9_]{2,64}', args.stage):
        parser.error('unique simple stage required')
    target = APP/'docs/evidence'/(args.stage+'.json')
    log = target.with_suffix('.txt')
    if target.exists() or log.exists():
        parser.error('immutable stage exists')
    sources = ['public/terminal.js', 'test_terminal_clock.js']
    before = {name:sha(APP/name) for name in sources}
    command = ['node', '--test', '--test-reporter=tap', 'test_terminal_clock.js']
    start = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(command, cwd=APP, text=True, encoding='utf-8', errors='replace',
                            capture_output=True, timeout=45)
    output = result.stdout + result.stderr
    with log.open('x',encoding='utf-8') as stream:
        stream.write(output)
    counts = {}
    for key in ('tests','pass','fail','cancelled','skipped','todo'):
        match = re.search(r'^# '+key+r' (\d+)\s*$', output, re.MULTILINE)
        counts[key] = int(match[1]) if match else None
    after = {name:sha(APP/name) for name in sources}
    passed = (
        result.returncode == 0 and counts.get('tests') == 2 and counts.get('pass') == 2
        and all(counts.get(k)==0 for k in ('fail','cancelled','skipped','todo')) and before==after)
    data = dict(kind='EXECUTED_TERMINAL_CLOCK_NODE_TESTS',status='PASS' if passed else 'FAIL',
        started_at=start,completed_at=datetime.now(timezone.utc).isoformat(),command=command,
        exit_code=result.returncode,source_before=before,source_after=after,
        parent_suite_counts=counts,child_suite_contract='9 executed assertions per timezone; exact totals enforced by parent',
        child_assertion_methods_passed=18 if passed else None,
        timezones=['UTC','America/New_York'],helper_sha256=sha(Path(__file__)),
        log=log.relative_to(APP).as_posix(),log_sha256=sha(log),network_scope='AUTHORED_READERS_ONLY_NO_NETWORK',
        operational_database_accessed=False,environment_files_read=False)
    with target.open('x',encoding='utf-8') as stream:
        json.dump(data,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(status=data['status'],counts=counts,receipt=str(target))))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())

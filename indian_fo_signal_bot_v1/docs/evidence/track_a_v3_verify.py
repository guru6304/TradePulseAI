"""Small, source-bound offline recovery/focused verifier. Never contacts providers."""
import argparse
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import warnings

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import (ExecutionResult, case_ids, digest, offline_network,
    python_result, source_snapshot, timestamp, validate_evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--tests', nargs='+')
    args = parser.parse_args()
    if not args.stage.replace('_', '').isalnum():
        parser.error('simple unique stage required')
    target = APP / 'docs/evidence' / (args.stage + '.json')
    if target.exists():
        parser.error('stage exists; historical receipts are immutable')
    started, before = timestamp(), source_snapshot()
    if args.recover:
        prior = APP / 'docs/evidence/master_astra_b01_vwap_20261029_01.json'
        proof = validate_evidence(prior)
        repo = APP.parent
        git = lambda *a: subprocess.check_output(['git', *a], cwd=repo, text=True)
        docs = {p.relative_to(APP).as_posix(): digest(p) for p in (APP/'docs').rglob('*') if p.is_file()}
        old = APP / 'docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md'
        data = dict(kind='RECOVERED_SOURCE_MATCHED_CHECKPOINT', status='PASS',
            started_at=started, completed_at=timestamp(), source_before=before,
            source_after=source_snapshot(), branch=git('branch','--show-current').strip(),
            head=git('rev-parse','HEAD').strip(), git_status=git('status','--porcelain=v1').splitlines(),
            prior_receipt=prior.relative_to(APP).as_posix(), prior_receipt_sha256=digest(prior),
            prior_python=proof['python']['passed'], documents=docs,
            previous_checkpoint=old.read_text(encoding='utf-8'),
            next_task='B01.5b', external_requests=0, operational_database_opened=False)
        # Preserve owner files by content metadata only; never report secret values/hashes.
        data['protected_config_present'] = {label: path.is_file() for label,path in
            [('workspace_env',repo/'.env'), ('app_env',APP/'.env')]}
    else:
        if not args.tests:
            parser.error('--tests required')
        log = target.with_suffix('.txt')
        unraisable = []
        with log.open('x',encoding='utf-8') as out, redirect_stdout(out), redirect_stderr(out), ExitStack() as stack:
            offline_network(stack)
            stack.enter_context(patch('sys.unraisablehook', side_effect=lambda e: unraisable.append(type(e.exc_value).__name__)))
            warnings.simplefilter('error',ResourceWarning)
            suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in args.tests)
            expected = list(case_ids(suite))
            result = unittest.TextTestRunner(stream=out,verbosity=2,resultclass=ExecutionResult).run(suite)
            outcome = python_result(result,expected)
        after = source_snapshot()
        data = dict(kind='EXECUTED_FOCUSED_OFFLINE_VERIFICATION',started_at=started,
            completed_at=timestamp(), status='PASS' if outcome['status']=='PASS' and before==after and not unraisable else 'FAIL',
            source_before=before, source_after=after, python=outcome, unraisable_errors=unraisable,
            tests=args.tests, log=log.relative_to(APP).as_posix(), log_sha256=digest(log),
            external_requests=0, operational_database_opened=False)
    with target.open('x',encoding='utf-8') as out:
        json.dump(data,out,indent=2); out.write('\n')
    print(json.dumps(dict(status=data['status'],receipt=str(target),
        tests=data.get('python',{}).get('executed'), passed=data.get('python',{}).get('passed'))))
    return 0 if data['status']=='PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())

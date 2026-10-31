"""Verify this engineering freeze and preserve scoped handoff bindings."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import validate_evidence


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((APP/name).read_text(encoding='utf-8'))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canonical', required=True)
    parser.add_argument('--stage', required=True)
    args = parser.parse_args()
    if not args.stage.replace('_','').isalnum():
        parser.error('simple unique stage required')
    target = APP/'docs/evidence'/(args.stage+'.json')
    if target.exists():
        parser.error('immutable stage exists')
    canonical = validate_evidence(APP/args.canonical)
    ids = canonical['python']['passed_ids']
    modules = ('test_astra_vwap_execution.', 'test_track_a_order_block_execution.',
               'test_track_a_supertrend_execution.', 'test_track_a_security.', 'test_track_a_terminal_http.')
    require(all(any(item.startswith(module) for item in ids) for module in modules), 'REQUIRED_EXECUTED_SCOPE_MISSING')
    bindings = {args.canonical:sha(APP/args.canonical)}
    for browser in ('chrome','edge'):
        name = 'docs/evidence/track_a_v3_browser_v4_'+browser+'_clock_20261029_01.json'
        proof = read(name)
        require(proof['status']=='PASS' and proof['exit_code']==0 and proof['checks']
                and all(case['passed'] is True for case in proof['checks']), 'BROWSER_CHECK_FAILURE')
        require(proof['source_before']==proof['source_after'] and
                all(sha(APP/path)==value for path,value in proof['source_before'].items()), 'BROWSER_SOURCE_CHANGED')
        require(sha(APP/proof['log'])==proof['log_sha256'] and len(proof['screenshots'])==4,
                'BROWSER_LOG_OR_CAPTURE_FAILURE')
        require(proof['helper_sha256']==sha(APP/'docs/evidence/track_a_v3_browser_v4.py')
                and proof['syntax_preflight']['exit_code']==0, 'BROWSER_HELPER_CHANGED')
        require(proof.get('browser_exit_code')==0 and proof.get('server_thread_stopped') is True
                and proof.get('temporary_profile_removed') is True, 'BROWSER_CLEANUP_FAILURE')
        for capture in proof['screenshots']:
            require(sha(APP/capture['file'])==capture['sha256'], 'SCREENSHOT_CHANGED')
            bindings[capture['file']]=capture['sha256']
        bindings[name]=sha(APP/name)
    node_name = 'docs/evidence/track_a_v3_clock_after_20261029_02.json'
    node = read(node_name)
    require(node['status']=='PASS' and node['child_assertion_methods_passed']==18 and
            node['source_before']==node['source_after'] and
            all(sha(APP/path)==value for path,value in node['source_before'].items()) and
            sha(APP/node['log'])==node['log_sha256'] and
            sha(APP/'docs/evidence/track_a_v3_node.py')==node['helper_sha256'], 'CLOCK_PROOF_CHANGED')
    bindings[node_name]=sha(APP/node_name)
    baseline = read('docs/evidence/track_a_v3_recovery_20261029_01.json')
    exceptions = {'docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md'}
    protected = {path:value for path,value in baseline['documents'].items() if path not in exceptions}
    require(all((APP/path).is_file() and sha(APP/path)==value for path,value in protected.items()),
            'PREEXISTING_DOCUMENT_CHANGED')
    permitted = {'forward_paper.py','paper_portfolio.py','paper_triggers.py','vwap_paper_triggers.py',
                 'release_management.py','verify_offline.py','test_bot.py','test_astra_vwap_paper_triggers.py','server.py'}
    protected_source = {path:value for path,value in baseline['source_before'].items() if path not in permitted}
    require(all((APP/path).is_file() and sha(APP/path)==value for path,value in protected_source.items()),
            'UNRELATED_STARTING_SOURCE_CHANGED')
    documents = ['TRADEPULSE_MASTER_STATUS.md','TRADEPULSE_MASTER_EXECUTION_REPORT.md',
                 'TRADEPULSE_ASTRA_CHECKPOINT.md','SECURITY_REVIEW.md','COMPETITOR_ACCEPTANCE.md',
                 'CLEANUP_AND_PACKAGE_MANIFEST.md','ui-evidence/README.md']
    for name in documents:
        path = 'docs/project/'+name
        bindings[path]=sha(APP/path)
    data = dict(kind='SCOPED_ENGINEERING_FREEZE_CLOSEOUT',status='PASS',
        recorded_at=datetime.now(timezone.utc).isoformat(),canonical=args.canonical,
        source_revision=canonical.get('source_revision'),source_count=len(canonical['source_after']),
        python_passed=canonical['python']['passed'],
        node_checks=[{key:check[key] for key in ('command','executed','passed','scope') if key in check}
                     for check in canonical['checks'] if isinstance(check['command'],list) and '--check' not in check['command']],
        protected_old_document_count=len(protected),protected_starting_source_count=len(protected_source),
        allowed_legacy_checkpoint_update=True,bindings=bindings,helper_sha256=sha(Path(__file__)),
        release_status='NOT_BUILT',external_gates=dict(X01='BLOCKED_EXTERNAL',X02='BLOCKED_EXTERNAL',X03='BLOCKED_EXTERNAL'),
        limitations=['Engineering freeze only; not whole-mission, live, empirical or launch acceptance.',
                     'No claim about current operational database contents or concurrent external application activity.'])
    with target.open('x',encoding='utf-8') as stream:
        json.dump(data,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(status='PASS',python=data['python_passed'],bindings=len(bindings),receipt=str(target))))


if __name__ == '__main__':
    main()

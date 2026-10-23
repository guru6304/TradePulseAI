"""Bind the actual offline implementation, preserved inputs and public release.

Never contacts a provider or opens an operational database. All outputs use
exclusive creation; --validate only reads the completed artifacts.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import validate_evidence, source_snapshot, timestamp
from release_management import ReleasePackager

E = APP / 'docs/evidence'
BASE = E / 'phase4_implementation_baseline_20261023_01.json'
PROOF = E / 'master_phase4_implementation_20261023_02.json'
ZIP = E / 'phase4_implementation_release_20261023_02.zip'
CLOSE = E / 'phase4_implementation_closeout_20261023_01.json'
ACCEPT = E / 'phase4_implementation_acceptance_20261023_01.json'
REPORT = APP / 'docs/reports/phase4_implementation_completion_20261023_01.md'
QA = APP / 'docs/reports/phase4_implementation_qa_20261023_01.md'
HANDOVER = APP / 'docs/TRADEPULSE_PHASE4_IMPLEMENTATION_20261023.md'
ALLOWED = {'angel_feed.py', 'candle_lineage.py', 'scanner_engine.py', 'strategies.py',
    'storage.py', 'server.py', 'release_management.py', 'public/index.html',
    'test_cash_dashboard.js', 'test_cash_lineage.py', 'test_bot.py',
    'test_phase4_explanations.py', 'test_phase4_recommendations.py',
    'test_phase4_feed_history.py', 'test_phase4_evaluation_storage.py'}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write(path, data):
    with path.open('x', encoding='utf-8') as out:
        json.dump(data, out, indent=2)
        out.write('\n')

def preservation():
    baseline = read(BASE)
    prior = baseline['prior_documents']
    assert all((APP / name).is_file() and sha(APP / name) == checksum for name, checksum in prior.items()), 'PRIOR_DOCUMENT_CHANGED'
    assert all(sha(APP.parent / name) == checksum for name, checksum in baseline['configuration_hashes'].items()), 'SAVED_CONFIGURATION_CHANGED'
    source = source_snapshot(APP)
    delta = {name for name in set(source) | set(baseline['source']) if source.get(name) != baseline['source'].get(name)}
    assert delta <= ALLOWED, 'UNASSIGNED_SOURCE_CHANGE'
    assert set(baseline['source']) <= set(source), 'SOURCE_REMOVED'
    settings = {}
    for name in baseline['configuration_hashes']:
        fields = {}
        for line in (APP.parent / name).read_text(encoding='utf-8-sig').splitlines():
            if '=' not in line or line.lstrip().startswith('#'):
                continue
            key,value = line.split('=',1)
            key,value = key.strip(),value.strip().strip('\"\'').lower()
            if key == 'ACTIVE_BROKER':
                fields[key] = value if value in ('paper_sim','sim','simulated','angelone','upstox','dhan') else 'UNRECOGNIZED'
            elif key in ('TELEGRAM_DRY_RUN','ENABLE_BACKGROUND_SCHEDULER'):
                fields[key] = value if value in ('true','false','0','1','yes','no','on','off') else 'UNRECOGNIZED'
        settings[name] = fields
    return dict(prior_documents_checked=len(prior), prior_documents_unchanged=True,
        configuration_hashes=baseline['configuration_hashes'], configuration_unchanged=True,
        saved_categorical_settings=settings,
        changed_source=sorted(delta), source=source,
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=APP,text=True).strip(),
        database_handling='OPERATIONAL_DATABASES_NOT_OPENED_OR_HASHED_CONTENTS_NOT_ATTESTED',
        git_handling='NO_AGENT_GIT_MUTATIONS_INDEX_ACTIVITY_NOT_ATTESTED')

def strict_proof():
    proof = validate_evidence(PROOF)
    assert proof['status'] == 'PASS' and proof['source_before'] == proof['source_after'] == source_snapshot(APP)
    ids = proof['python']['executed_ids']
    modules = Counter(name.split('.')[0] for name in ids)
    assert all(modules[name] > 0 for name in ('test_phase4_explanations','test_phase4_recommendations',
        'test_phase4_feed_history','test_phase4_evaluation_storage'))
    return dict(receipt=PROOF.relative_to(APP).as_posix(), sha256=sha(PROOF),
        python=proof['python']['executed'], failures=proof['python']['failures'],
        errors=proof['python']['errors'], skipped=proof['python']['skipped'],
        unraisable=proof['unraisable_errors'], checks=proof['checks'],
        phase4_modules={k:v for k,v in modules.items() if k in
            ('test_phase4_explanations','test_phase4_recommendations','test_phase4_feed_history','test_phase4_evaluation_storage')})

def focused():
    checked = {}
    for path in sorted(E.glob('phase4_implementation_focused_*.json')):
        data = read(path)
        assert data['expected_ids'] == data['executed_ids'] and len(set(data['executed_ids'])) == data['executed']
        assert sha(APP / data['log']) == data['log_sha256']
        assert data['exit_code'] == (0 if data['status'] == 'PASS' else 1)
        assert not data['unraisable_errors']
        checked[path.relative_to(APP).as_posix()] = dict(sha256=sha(path), status=data['status'],
            executed=data['executed'], passed=data['passed'], source_stable=data['source_before'] == data['source_after'])
    for stage in ('disconnect_before_01','breadth_before_01'):
        assert read(E / ('phase4_implementation_focused_'+stage+'.json'))['status'] == 'FAIL'
    for stage in ('disconnect_after_01','independent_qa_02','integrated_02'):
        assert read(E / ('phase4_implementation_focused_'+stage+'.json'))['status'] == 'PASS'
    return checked

def release_inspection():
    packager = ReleasePackager(APP)
    inspection = packager.inspect_bundle(ZIP)
    with zipfile.ZipFile(ZIP) as archive:
        manifest = json.loads(archive.read('RELEASE_MANIFEST.json'))
        expected = set(packager.CORE_MODULES + packager.REQUIRED_ASSETS + packager.PUBLIC_DOCUMENTS + ['README.md'])
        expected.update(p.name for p in APP.glob('test_*.py'))
        expected.update(p.name for p in APP.glob('test_*.js'))
        assert set(manifest['files']) == expected
        assert all(archive.read(name) == (APP / name).read_bytes() for name in expected), 'RELEASE_DIFFERS_FROM_CURRENT_FILES'
        assert all(not any(piece.startswith('.') for piece in Path(name).parts)
                   for name in expected if name != '.env.example')
        assert all(not name.endswith(('.db','.sqlite','.sqlite3','.db-wal','.db-shm')) for name in expected)
        # Compare long configured credential values privately. Never report keys
        # or values, include .env bytes, or echo a matching secret.
        templates = {}
        for line in (APP / '.env.example').read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value = line.split('=',1)
                templates[key.strip()] = value.strip().strip('\"\'')
        secrets, template_matches = set(), set()
        for path in (APP / '.env', APP.parent / '.env'):
            if path.is_file():
                for line in path.read_text(encoding='utf-8-sig').splitlines():
                    if '=' not in line or line.lstrip().startswith('#'):
                        continue
                    key,value = line.split('=',1)
                    value = value.strip().strip('\"\'')
                    if any(tag in key.upper() for tag in ('SECRET','TOKEN','PASSWORD','API_KEY','CLIENT_CODE','PIN','CHAT_ID')) and len(value) >= 12:
                        if (templates.get(key.strip()) == value and any(marker in value.upper()
                                for marker in ('YOUR_','REPLACE','PLACEHOLDER','EXAMPLE','CHANGEME'))):
                            template_matches.add(key.strip())
                            continue
                        secrets.add(value.encode('utf-8'))
        for name in expected:
            body = archive.read(name)
            assert not any(value in body for value in secrets), 'CONFIGURED_CREDENTIAL_IN_PUBLIC_RELEASE'
    inspection.update(exact_current_files=True, private_paths_excluded=True, configured_credential_scan='PASS',
        exact_template_placeholders_excluded=len(template_matches))
    return inspection

def build():
    state = preservation()
    proof = strict_proof()
    result = ReleasePackager(APP).build_bundle(ZIP)
    result.update(operation='ReleasePackager.build_bundle', operation_exit_code=0,
        recorded_at=timestamp(), source=state['source'], proof_sha256=proof['sha256'])
    write(E / 'phase4_implementation_release_build_20261023_02.json', result)
    inspection = release_inspection()
    inspection.update(recorded_at=timestamp(), exit_code=0)
    write(E / 'phase4_implementation_release_inspect_20261023_02.json', inspection)
    print(json.dumps(dict(status='PASS', release_sha256=inspection['sha256'], files=inspection['files'])))

def inspect_existing():
    state, proof, inspection = preservation(), strict_proof(), release_inspection()
    inspection.update(command=[sys.executable,'-B','-W','error::ResourceWarning',str(Path(__file__).relative_to(APP)),'--inspect-release'],
        exit_code=0, recorded_at=timestamp(), source=state['source'], proof_sha256=proof['sha256'])
    write(E / 'phase4_implementation_release_inspect_20261023_01.json', inspection)
    correction = dict(status='PASS', previous_wrapper_command_exit_code=1,
        previous_archive_build_operation='PASS', previous_build_receipt_wrapper_exit_code='INCORRECT_NOT_USED_AS_COMMAND_SUCCESS_PROOF',
        previous_build_receipt='docs/evidence/phase4_implementation_release_build_20261023_01.json',
        reason='Initial private-value scan matched one exact template placeholder in .env.example; not a real credential.',
        correction='Exclude only same-key, identical template values carrying an explicit placeholder marker.',
        exact_template_placeholders_excluded=inspection['exact_template_placeholders_excluded'],
        corrected_scan='PASS', archive_unchanged=True, release_sha256=inspection['sha256'],
        recorded_at=timestamp(), current_command_exit_code=0)
    write(E / 'phase4_implementation_release_scan_correction_20261023_01.json', correction)
    print(json.dumps(dict(status='PASS',release_sha256=inspection['sha256'],files=inspection['files'],
        configured_credential_scan=inspection['configured_credential_scan'])))

def closeout():
    state, proof, tests, release = preservation(), strict_proof(), focused(), release_inspection()
    codes = dict(A='Scanner integration',B='Strategy integration',C='Warm-up integrity',D='Candidate generation',
        E='Explanations',F='Ranking',G='Risk/reward',H='Persistence and output',I='Compatibility',J='Safety',K='Verification')
    locators = {
        'A':['test_valid_fixture_uses_actual_scanner_and_excludes_forming_tail_from_lineage',
             'test_invalid_candle_inputs_never_reach_actual_strategy_or_outputs'],
        'B':['test_all_five_bidirectional_actual_signals_match_direct_evaluation',
             'test_p1c_backward_compatibility_and_scanner_bidirectional_dispatch'],
        'C':['test_stream_capacity_must_cover_existing_two_hundred_bar_requirement',
             'test_three_session_packets_pass_200_bar_warmup_but_lack_session_opening_coverage',
             'test_fully_warmed_supertrend_reaches_actual_scanner_without_relaxing_lookback'],
        'D':['test_detected_setup_with_invalid_target_is_preserved_as_rejected_not_ranked'],
        'E':['test_real_scanner_candidate_has_numeric_risk_rank_and_supported_rule_explanations'],
        'F':['test_ranking_all_permutations_and_exact_identity_ties_are_reproducible'],
        'G':['test_attractive_quality_cannot_admit_invalid_risk_geometry'],
        'H':['test_existing_api_history_and_scan_routes_expose_same_reconciled_candidate',
             'test_explanation_persistence_and_idempotent_retry_keep_same_source_and_candidate'],
        'I':['test_p1c_backward_compatibility_and_scanner_bidirectional_dispatch'],
        'J':['test_shutdown_stops_attached_fixture_and_preserves_safe_configuration',
             'test_disconnect_after_actual_evaluation_blocks_commit_and_notification'],
        'K':[]}
    ids = read(PROOF)['python']['executed_ids']
    gates = {}
    for code,label in codes.items():
        matches = []
        for locator in locators[code]:
            found = [name for name in ids if name.endswith('.'+locator)]
            assert len(found) == 1, 'MATRIX_TEST_LOCATOR_MISSING'
            matches.extend(found)
        gates[code] = dict(status='PASS_OFFLINE_ENGINEERING', requirement=label,
            executed_test_ids=matches, strict_receipt=PROOF.relative_to(APP).as_posix())
    matrix = dict(verdict='PHASE_4_IMPLEMENTATION_ACCEPTED', scope='OFFLINE_ENGINEERING_ONLY',
        gates=gates,
        strict_verification=proof, external_provider_requests=0, orders=0, external_messages=0,
        operational_acceptance=False, profitability_claim=False)
    assert 'PHASE_4_IMPLEMENTATION_ACCEPTED' in REPORT.read_text(encoding='utf-8')
    write(ACCEPT, matrix)
    artifacts = [BASE,PROOF,REPORT,QA,HANDOVER,ACCEPT,Path(__file__),
        E / 'phase4_implementation_release_build_20261023_02.json',
        E / 'phase4_implementation_release_scan_correction_20261023_01.json',
        E / 'phase4_implementation_release_inspect_20261023_02.json']
    artifacts.extend(E.glob('phase4_implementation_focused_*'))
    artifacts.extend(E.glob('phase4_implementation_contract_example_*'))
    artifacts.extend(E.glob('phase4_implementation_*.py'))
    artifacts.extend(E.glob('master_phase4_implementation_20261023_01*'))
    artifacts.extend(APP / name for name in read(PROOF)['logs'])
    data = dict(status='PASS',verdict=matrix['verdict'],recorded_at=timestamp(),
        preservation=state,strict_verification=proof,focused=tests,release=release,
        artifacts={p.relative_to(APP).as_posix():sha(p) for p in artifacts if p.is_file()},
        command=[sys.executable,'-B','-W','error::ResourceWarning',str(Path(__file__).relative_to(APP)),'--closeout'],exit_code=0)
    write(CLOSE,data)
    print(json.dumps(dict(status='PASS',verdict=matrix['verdict'],python=proof['python'],release_files=release['files'])))

def validate():
    data = read(CLOSE)
    assert all(sha(APP / name) == checksum for name,checksum in data['artifacts'].items()), 'CLOSEOUT_ARTIFACT_CHANGED'
    assert preservation()['source'] == data['preservation']['source']
    assert strict_proof() == data['strict_verification']
    assert focused() == data['focused']
    assert release_inspection() == data['release']
    assert read(ACCEPT)['verdict'] == data['verdict'] == 'PHASE_4_IMPLEMENTATION_ACCEPTED'
    result = dict(status='PASS',recorded_at=timestamp(),closeout_sha256=sha(CLOSE),
        source_files=len(data['preservation']['source']), prior_documents_checked=data['preservation']['prior_documents_checked'],
        command=[sys.executable,'-B','-W','error::ResourceWarning',str(Path(__file__).relative_to(APP)),'--validate'],exit_code=0)
    write(E / 'phase4_implementation_closeout_validation_20261023_01.json',result)
    print(json.dumps(result))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--build-release',action='store_true')
    mode.add_argument('--closeout',action='store_true')
    mode.add_argument('--validate',action='store_true')
    mode.add_argument('--inspect-release',action='store_true')
    args=parser.parse_args()
    if args.build_release:
        build()
    elif args.inspect_release:
        inspect_existing()
    elif args.closeout:
        closeout()
    else:
        validate()

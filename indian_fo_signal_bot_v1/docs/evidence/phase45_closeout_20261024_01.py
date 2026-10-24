"""Independent source/log, preservation, acceptance and public archive checks.

Only current public source, explicit evidence and configuration hashes/credential
comparisons are read. No operational database, source request or delivery occurs.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP))
from verify_offline import source_snapshot,validate_evidence,timestamp
from release_management import ReleasePackager

E=APP/'docs/evidence'
BASE=E/'phase45_baseline_20261023_01.json'
PROOF=E/'master_phase45_20261024_03.json'
ARCHIVE=E/'phase45_release_20261024_01.zip'
CLOSE=E/'phase45_closeout_20261024_01.json'
VALIDATION=E/'phase45_closeout_validation_20261024_01.json'
MATRIX=E/'phase45_acceptance_20261024_01.json'
REPORTS=[APP/'docs/reports'/name for name in ('phase45_phase4_closure_20261024_01.md',
    'phase45_phase5_completion_20261024_01.md','phase45_integration_acceptance_20261024_01.md')]
ALLOWED={'angel_feed.py','candle_lineage.py','notification_outbox.py','public/index.html',
    'release_management.py','scanner_engine.py','server.py','storage.py','strategies.py','telegram_bot.py',
    'test_bot.py','test_cash_dashboard.js','context_data.py','context_workflow.py','test_context_alerts.py',
    'test_context_data.py','test_context_http.py','test_context_workflow.py',
    'test_phase45_integration.py','test_phase45_scanner_gaps.py','test_cash_lineage.py'}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write(path,value):
    with path.open('x',encoding='utf-8') as out:
        json.dump(value,out,indent=2)
        out.write('\n')

def preservation():
    baseline=read(BASE)
    prior=baseline['prior_documents']
    assert all((APP/name).is_file() and sha(APP/name)==checksum for name,checksum in prior.items()), 'PRIOR_EVIDENCE_CHANGED'
    assert all(sha(APP.parent/name)==checksum for name,checksum in baseline['configuration_hashes'].items()), 'CONFIGURATION_CHANGED'
    source=source_snapshot(APP)
    delta=sorted(name for name in set(source)|set(baseline['source']) if source.get(name)!=baseline['source'].get(name))
    assert set(delta)<=ALLOWED and set(baseline['source'])<=set(source), 'UNASSIGNED_SOURCE_CHANGE'
    return dict(prior_documents_checked=len(prior),prior_documents_unchanged=True,
        configuration_hashes=baseline['configuration_hashes'],configuration_unchanged=True,
        source=source,changed_source=delta,
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=APP,text=True).strip(),
        worktree=subprocess.check_output(['git','status','--short'],cwd=APP,text=True),
        database_handling='OPERATIONAL_DATABASE_WAL_SHM_NOT_OPENED_OR_HASHED_CONTENTS_NOT_ATTESTED',
        git_handling='NO_AGENT_GIT_MUTATIONS')

def strict():
    proof=validate_evidence(PROOF)
    assert proof['status']=='PASS' and proof['source_before']==proof['source_after']==source_snapshot(APP)
    modules=Counter(case.split('.')[0] for case in proof['python']['executed_ids'])
    new=('test_phase45_scanner_gaps','test_context_data','test_context_workflow','test_context_alerts','test_phase45_integration','test_context_http')
    assert all(modules[name]>0 for name in new)
    return dict(path=PROOF.relative_to(APP).as_posix(),sha256=sha(PROOF),
        python=proof['python']['executed'],passed=proof['python']['passed'],failures=proof['python']['failures'],
        errors=proof['python']['errors'],skipped=proof['python']['skipped'],unraisable_errors=proof['unraisable_errors'],
        checks=proof['checks'],new_test_modules={name:modules[name] for name in new})

def focused():
    result={}
    for path in sorted(E.glob('phase45_alerts_*.json')):
        value=read(path)
        assert value['expected_ids']==value['executed_ids'] and len(set(value['executed_ids']))==value['executed']
        assert sha(APP/value['log'])==value['log_sha256']
        # Failed historical stages retain their actual warnings/errors. Only
        # accepted executions must satisfy the zero-unraisable requirement.
        if value['status']=='PASS':
            assert not value['unraisable_errors']
        assert value['exit_code']==(0 if value['status']=='PASS' else 1)
        result[path.relative_to(APP).as_posix()]=dict(sha256=sha(path),status=value['status'],
            executed=value['executed'],passed=value['passed'],unraisable_errors=value['unraisable_errors'],
            source_stable=value['source_before']==value['source_after'])
    for name in ('integrity_before_01','integration_before_01','http_timeout_before_01',
                 'sqlite_before_01','corrupt_payload_before_01','corrupt_followup_before_01'):
        assert read(E/('phase45_alerts_'+name+'.json'))['status']=='FAIL'
    for name in ('integrity_after_01','integrated_final_01','lifecycle_02','http_after_03',
                 'repair_verification_03','corrupt_payload_after_01','corrupt_followup_after_01'):
        assert read(E/('phase45_alerts_'+name+'.json'))['status']=='PASS'
    return result

def browser():
    path=E/'phase45_browser_20261024_04.json'
    value=read(path)
    assert value['status']=='PASS' and value['exit_code']==0 and value['source_unchanged']
    assert all(check['passed'] for check in value['checks'])
    assert value['chrome_exit_code']==0 and value['server_thread_stopped'] and value['temporary_profile_removed']
    assert all(sha(APP/name)==checksum for name,checksum in value['source_after'].items())
    assert sha(E/value['log_file'])==value['log_sha256']
    assert sha(E/'phase45_browser_verify_20261024_01.py')==value['helper_sha256']
    assert not value['runtime_exceptions'] and value['requests']['blocked_external']>=1
    return dict(path=path.relative_to(APP).as_posix(),sha256=sha(path),checks=len(value['checks']),
        status=value['status'],browser=value['browser'],scope=value['fixture_scope'],limitations=value['limitations'])

def release():
    packager=ReleasePackager(APP)
    inspection=packager.inspect_bundle(ARCHIVE)
    with zipfile.ZipFile(ARCHIVE) as archive:
        manifest=json.loads(archive.read('RELEASE_MANIFEST.json'))
        expected=set(packager.CORE_MODULES+packager.REQUIRED_ASSETS+packager.PUBLIC_DOCUMENTS+['README.md'])
        expected.update(p.name for p in APP.glob('test_*.py'))
        expected.update(p.name for p in APP.glob('test_*.js'))
        assert set(manifest['files'])==expected
        assert all(archive.read(name)==(APP/name).read_bytes() for name in expected), 'ARCHIVE_SOURCE_MISMATCH'
        assert all(not any(part.startswith('.') for part in Path(name).parts) for name in expected if name!='.env.example')
        assert all(not name.endswith(('.db','.sqlite','.sqlite3','.db-wal','.db-shm')) for name in expected)
        templates={}
        for line in (APP/'.env.example').read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1)
                templates[key.strip()]=value.strip().strip('\"\'')
        values,excluded=set(),set()
        for path in (APP/'.env',APP.parent/'.env'):
            if not path.is_file():
                continue
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if '=' not in line or line.lstrip().startswith('#'):
                    continue
                key,value=line.split('=',1)
                value=value.strip().strip('\"\'')
                if any(tag in key.upper() for tag in ('SECRET','TOKEN','PASSWORD','API_KEY','CLIENT_CODE','PIN','CHAT_ID')) and len(value)>=12:
                    if templates.get(key.strip())==value and any(marker in value.upper() for marker in ('YOUR_','REPLACE','PLACEHOLDER','EXAMPLE','CHANGEME')):
                        excluded.add(key.strip())
                    else:
                        values.add(value.encode('utf-8'))
        assert all(not any(value in archive.read(name) for value in values) for name in expected), 'CONFIGURED_SECRET_IN_ARCHIVE'
    inspection.update(exact_current_files=True,private_files_excluded=True,configured_credential_scan='PASS',
        exact_template_placeholders_excluded=len(excluded))
    return inspection

def independent_release():
    path=E/'phase45_release_independent_20261024_01.json'
    helper=E/'phase45_release_independent_check_20261024_01.py'
    value=read(path)
    assert value['status']=='PASS' and value['exit_code']==0
    assert value['archive_sha256']==sha(ARCHIVE) and value['files']==111
    assert value['helper_sha256']==sha(helper)
    assert value['source_unchanged'] and value['source']==source_snapshot(APP) and value['exact_current_zip']
    assert not any(value[key] for key in ('operational_database_opened','configuration_or_credentials_read',
                                        'application_imported','network_or_message_action'))
    return dict(path=path.relative_to(APP).as_posix(),sha256=sha(path),
        helper_sha256=sha(helper),status='PASS',files=value['files'],archive_sha256=value['archive_sha256'])

def matrix():
    proof=read(PROOF)
    ids=proof['python']['executed_ids']
    p4={
      'A':('Strategy integrity',['test_all_five_bidirectional_actual_signals_match_direct_evaluation']),
      'B':('Buffer and history',['test_actual_ring_evicts_one_of_301_without_losing_current_session_open','test_raw_preopen_lineage_reaches_201_bar_strategy_diagnostic_without_live_promotion']),
      'C':('Scanner input',['test_invalid_candle_inputs_never_reach_actual_strategy_or_outputs']),
      'D':('Candidate states',['test_rejected_detected_candidate_stays_rejected_with_qualified_context']),
      'E':('Explanations',['test_real_scanner_candidate_has_numeric_risk_rank_and_supported_rule_explanations']),
      'F':('Risk geometry',['test_ranker_rejects_derived_infinite_ratio_before_returning_candidate']),
      'G':('Ranking',['test_ranking_all_permutations_and_exact_identity_ties_are_reproducible']),
      'H':('Persistence and APIs',['test_rehashed_snapshot_corruption_fails_context_and_existing_history_routes']),
      'I':('Dashboard',[]),'J':('Compatibility and safety',['test_foreign_origin_cannot_import_or_enrich_and_reads_are_inert']),
      'K':('Evidence',[])}
    p5={
      'A':('Context contract',['test_real_signature_and_separate_local_policy_qualify_only_informationally']),
      'B':('Provenance and qualification',['test_policy_signature_tamper_revocation_scope_and_rights_fail_closed']),
      'C':('Candidate linkage',['test_actual_candidate_import_context_api_and_preview_preserve_phase4_result']),
      'D':('No actionability bypass',['test_rejected_detected_candidate_stays_rejected_with_qualified_context']),
      'E':('Explainability',['test_candidate_and_original_records_are_never_mutated']),
      'F':('Dashboard integration',[]),
      'G':('Alert lifecycle',['test_sqlite_restart_restores_pending_and_ack_without_duplicate_render',
                            'test_failures_back_off_and_stop_at_dead_without_fourth_attempt',
                            'test_rehashed_suppression_or_policy_reason_is_recomputed_from_sources']),
      'H':('Source resilience',['test_duplicate_json_nonfinite_and_invalid_structures_are_rejected',
                              'test_timeout_in_both_new_body_readers_returns_bounded_unavailable',
                              'test_oversized_or_nontext_stored_snapshot_is_rejected_before_decoding',
                              'test_integer_or_oversized_original_bytes_rejected_before_source_validator',
                              'test_corrupt_existing_import_inventory_returns_storage_failure',
                              'test_corrupt_receipt_type_or_size_is_rejected_before_decoding']),
      'I':('Security and permissions',['test_no_request_can_supply_trust_mapping_or_intake_time']),
      'J':('Regression compatibility',[]),'K':('Evidence and release',[])}
    def gates(mapping):
        result={}
        for code,(name,methods) in mapping.items():
            matched=[]
            for method in methods:
                found=[case for case in ids if case.endswith('.'+method)]
                assert len(found)==1, 'MISSING_MATRIX_EXECUTION_'+method
                matched.extend(found)
            result[code]=dict(requirement=name,status='IMPLEMENTED_AND_VERIFIED',
                acceptance='PASS_OFFLINE_ENGINEERING',executed_test_ids=matched,
                strict_evidence=PROOF.relative_to(APP).as_posix())
        return result
    return dict(scope='OFFLINE_ENGINEERING_ONLY',phase4_verdict='PHASE_4_IMPLEMENTATION_ACCEPTED',
        phase5_verdict='PHASE_5_IMPLEMENTATION_ACCEPTED',phase4_gates=gates(p4),phase5_gates=gates(p5),
        operational_source_acceptance=False,live_market_acceptance=False,profitability_claim=False,
        source_dependency_status='BLOCKED_BY_EXTERNAL_DEPENDENCY',
        dependencies=['No genuine context publisher authority, approved use rights or operator trust policy supplied',
                      'No external source acquisition or real delivery authorized or executed',
                      'Unsupported depth, fills and net target RR remain unavailable'],
        roadmap='Original six phases unchanged; Phase 6 implementation not started',
        browser=browser(),strict_verification=strict())

def build():
    preservation()
    proof=strict()
    browser()
    ReleasePackager(APP).build_bundle(ARCHIVE)
    checked=release()
    result=dict(status='PASS',recorded_at=timestamp(),release=checked,strict_sha256=proof['sha256'],
        command=[sys.executable,'-B','-W','error::ResourceWarning',str(Path(__file__).relative_to(APP)),'--build-release'],exit_code=0)
    write(E/'phase45_release_inspect_20261024_01.json',result)
    print(json.dumps(dict(status='PASS',files=checked['files'],sha256=checked['sha256'])))

def closeout():
    state,proof,focused_proof,browser_proof,archive=preservation(),strict(),focused(),browser(),release()
    independent_archive=independent_release()
    accepted=matrix()
    assert all(path.is_file() for path in REPORTS)
    assert 'PHASE_4_IMPLEMENTATION_ACCEPTED' in REPORTS[0].read_text(encoding='utf-8')
    assert 'PHASE_5_IMPLEMENTATION_ACCEPTED' in REPORTS[1].read_text(encoding='utf-8')
    write(MATRIX,accepted)
    paths=set(REPORTS+[BASE,PROOF,MATRIX,Path(__file__),APP/'docs/TRADEPULSE_PHASE45_HANDOVER_20261024.md'])
    paths.update(p for p in E.glob('phase45_*') if p.is_file() and p not in (CLOSE,VALIDATION))
    paths.update(p for p in E.glob('master_phase45_*') if p.is_file())
    paths.update(p for p in (APP/'docs/reports').glob('phase45_*') if p.is_file())
    value=dict(status='PASS',recorded_at=timestamp(),phase4_verdict=accepted['phase4_verdict'],
        phase5_verdict=accepted['phase5_verdict'],preservation=state,strict_verification=proof,
        focused=focused_proof,browser=browser_proof,release=archive,independent_release=independent_archive,
        artifacts={p.relative_to(APP).as_posix():sha(p) for p in sorted(paths)},
        command=[sys.executable,'-B','-W','error::ResourceWarning',str(Path(__file__).relative_to(APP)),'--closeout'],exit_code=0)
    write(CLOSE,value)
    print(json.dumps(dict(status='PASS',phase4=value['phase4_verdict'],phase5=value['phase5_verdict'],python=proof['python'])))

def validate():
    value=read(CLOSE)
    assert all(sha(APP/name)==checksum for name,checksum in value['artifacts'].items()), 'CLOSEOUT_BYTES_CHANGED'
    assert preservation()['source']==value['preservation']['source']
    assert strict()==value['strict_verification'] and focused()==value['focused']
    assert browser()==value['browser'] and release()==value['release'] and matrix()==read(MATRIX)
    assert independent_release()==value['independent_release']
    result=dict(status='PASS',recorded_at=timestamp(),closeout_sha256=sha(CLOSE),
        source_files=len(value['preservation']['source']),prior_documents_checked=value['preservation']['prior_documents_checked'],
        command=[sys.executable,'-B','-W','error::ResourceWarning',str(Path(__file__).relative_to(APP)),'--validate'],exit_code=0)
    write(VALIDATION,result)
    print(json.dumps(result))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--build-release',action='store_true')
    mode.add_argument('--closeout',action='store_true')
    mode.add_argument('--validate',action='store_true')
    args=parser.parse_args()
    if args.build_release:
        build()
    elif args.closeout:
        closeout()
    else:
        validate()

"""Read-only source/release audit; writes only exclusive new audit evidence.

No broker, scanner engine, scheduler, Telegram client or database is instantiated.
An existing strict test run is validated, never relabelled as newly executed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

APP = Path(__file__).resolve().parents[2]
EVIDENCE = APP/'docs/evidence'
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence

PREFIX = 'phase4_gate_readiness_'
BASELINE = EVIDENCE/'phase4_gate_readiness_baseline_20261023_01.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    with path.open('x', encoding='utf-8') as out:
        json.dump(data, out, indent=2, allow_nan=False)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=APP, text=True).strip()


def inventory():
    paths = [p for p in (APP/'docs').rglob('*') if p.is_file() and not p.is_symlink()
             and p.resolve().is_relative_to(APP.resolve()) and
             not p.name.startswith((PREFIX, 'phase4_readiness_')) and '__pycache__' not in p.parts]
    return {p.relative_to(APP).as_posix(): sha(p) for p in paths}


def environment_hashes():
    return {p.relative_to(APP.parent).as_posix(): sha(p) for p in (APP/'.env', APP.parent/'.env') if p.is_file()}


def safe_configuration():
    from config import BotConfig
    cfg = BotConfig()
    try:
        cfg.validate(require_live_credentials=False)
        valid = True
    except Exception:
        valid = False
    return dict(saved_provider=cfg.active_broker if cfg.active_broker in
        ('paper_sim','angelone','dhan','upstox') else 'INVALID', telegram_dry_run=cfg.telegram_dry_run,
        enable_background_scheduler=cfg.enable_background_scheduler, local_configuration_valid=valid,
        execution_architecture='EXISTING_PAPER_PORTFOLIO_AND_READ_ONLY_DATA_ADAPTERS')


def baseline():
    report = dict(captured_at=datetime.now(timezone.utc).isoformat(), repository=str(APP), head=git('rev-parse','HEAD'),
        worktree=git('status','--short'), source=source_snapshot(APP), documents=inventory(),
        configuration_file_sha256s=environment_hashes(), configuration=safe_configuration(),
        database_handling='PRESERVED_UNOPENED_NOT_HASHED_NO_CHECKPOINT_OR_PROCESS_CONTROL',
        database_sidecar_presence={name: (APP/name).is_file() for name in
            ('tradepulse_phase1d.db','tradepulse_phase1d.db-wal','tradepulse_phase1d.db-shm')},
        provider_requests=0, phase4_production_changes=0)
    write(BASELINE, report)
    print(json.dumps(dict(status='RECORDED', head=report['head'], source_files=len(report['source']),
                          preserved_document_files=len(report['documents']), configuration=report['configuration'])))


def finalize():
    before = json.loads(BASELINE.read_text(encoding='utf-8'))
    logpath = EVIDENCE/'phase4_gate_readiness_verification_20261023_01.txt'
    command = [sys.executable, '-B', 'verify_offline.py', '--validate-evidence',
               'docs/evidence/master_phase3_angel_20261023_03.json']
    result = subprocess.run(command, cwd=APP, capture_output=True, text=True, check=False)
    with logpath.open('x', encoding='utf-8') as out:
        out.write('Command: '+subprocess.list2cmdline(command)+'\nExit: '+str(result.returncode)+'\n')
        out.write(result.stdout+result.stderr)
    if result.returncode != 0:
        raise ValueError('CURRENT_OFFLINE_PROOF_INVALID')
    proof = validate_evidence(APP/'docs/evidence/master_phase3_angel_20261023_03.json')
    after = source_snapshot(APP)
    old_docs = {name: (APP/name).is_file() and sha(APP/name) == value for name,value in before['documents'].items()}
    preserved = all(old_docs.values()) and before['source'] == after and before['configuration_file_sha256s'] == environment_hashes()
    phase3 = json.loads((EVIDENCE/'phase3_angel_acceptance_20261023_02.json').read_text())
    closeout = json.loads((EVIDENCE/'phase3_angel_closeout_validation_20261023_03.json').read_text())
    bound = {name: (APP/name).is_file() and sha(APP/name) == value for name,value in closeout['bound_files'].items()}
    if closeout['source_snapshot'] != after or closeout['status'] != 'PASS' or not all(bound.values()):
        raise ValueError('PRIOR_CLOSEOUT_SOURCE_OR_BOUND_FILE_MISMATCH')
    # Historical database preservation assertions describe their original run only.
    # Never open a user's active database or its WAL/SHM to recreate that assertion.
    from release_management import ReleasePackager
    package = EVIDENCE/'phase3_angel_release_20261023_02.zip'
    release = ReleasePackager(str(APP)).inspect_bundle(package)
    prior_inspect = json.loads((EVIDENCE/'phase3_angel_release_inspect_20261023_03.json').read_text())
    if release != prior_inspect:
        raise ValueError('RETAINED_RELEASE_RECEIPT_MISMATCH')
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read('RELEASE_MANIFEST.json'))
        packaged_current = all((APP/name).is_file() and sha(APP/name) == meta['sha256'] for name,meta in manifest['files'].items())
        excluded = all(not ('.local/' in name or name.endswith(('.db','.db-wal','.db-shm','.sqlite','.sqlite3'))
            or Path(name).name == '.env' or name.startswith('docs/evidence/')) for name in archive.namelist())
    newer = []
    for path in sorted(EVIDENCE.glob('*.json')):
        if path.name.startswith(PREFIX) or path.stat().st_size > 8*1024*1024:
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        except (ValueError, UnicodeError):
            continue
        if isinstance(data,dict) and 'phase3_status' in data:
            newer.append(dict(path=path.relative_to(APP).as_posix(), sha256=sha(path), phase3_status=data['phase3_status']))
    stage = 'market_open_authorized_01'
    stage_state = dict(stage=stage,
        public_probe_receipt_present=(EVIDENCE/('phase3_angel_probe_'+stage+'.json')).is_file(),
        private_stage_directory_present=(APP/'.local/phase3-angel'/stage).is_dir(),
        performed_in_this_audit=False, additional_provider_authorization_granted_by_phase4_prompt=False)
    config = safe_configuration()
    safety = config['telegram_dry_run'] is True and config['enable_background_scheduler'] is False
    accepted = phase3.get('phase3_status') in ('PASS','PHASE_3_ACCEPTED') and all(g['status']=='PASS' for g in phase3['gates'])
    if accepted:
        raise ValueError('PHASE3_GATE_CHANGED_REASSESS_IMPLEMENTATION_AUTHORIZATION')
    if not (preserved and packaged_current and excluded):
        raise ValueError('PRESERVATION_OR_RELEASE_SCOPE_FAILURE')
    audit_files = sorted([p for p in (APP/'docs').rglob('*') if p.is_file() and
                          p.name.startswith((PREFIX,'phase4_readiness_')) and '__pycache__' not in p.parts])
    from config import BotConfig
    cfg = BotConfig()
    values = [str(getattr(cfg,key) or '').encode() for key in
        ('angel_api_key','angel_client_code','angel_totp_secret','dhan_client_id','dhan_access_token',
         'upstox_access_token','telegram_bot_token','gemini_api_key')]
    values = [value for value in values if len(value)>=8]
    if any(value in p.read_bytes() for value in values for p in audit_files):
        raise ValueError('NEW_AUDIT_ARTIFACT_SECRET_MATCH')
    matrix = [dict(gate=1,name='Phase3 dependency',status='BLOCKED',evidence=phase3['phase3_status'])]
    names = ['Correct scanner input','Strategy integration','Explainable candidate generation','Ranking correctness',
             'Risk/reward and invalidation','Fail-closed LIVE behavior','Persistence and output integration','Regression compatibility']
    matrix += [dict(gate=i,name=name,status='NOT_EVALUATED_PHASE3_GATE',
                    evidence='Existing source/readiness audited; no Phase4 implementation or acceptance run') for i,name in enumerate(names,2)]
    matrix += [dict(gate=10,name='Security and operating safety',status='PASS_AUDIT_ONLY' if safety else 'BLOCKED',
                    evidence='Saved profile preserved; no broker/scanner/scheduler/Telegram/database execution'),
               dict(gate=11,name='Evidence and reproducibility',status='PASS_AUDIT_ONLY',
                    evidence='Current source/log proof and retained ZIP independently revalidated; not Phase4 implementation acceptance')]
    write(EVIDENCE/'phase4_gate_readiness_acceptance_20261023_01.json',dict(
        verdict='PHASE_4_NOT_STARTED_PHASE_3_GATE',phase3_status=phase3['phase3_status'],gates=matrix,
        production_implementation_started=False,phase4_accepted=False,
        evidence='docs/evidence/phase4_gate_readiness_verification_20261023_01.json'))
    audit_files = sorted([p for p in (APP/'docs').rglob('*') if p.is_file() and
                          p.name.startswith((PREFIX,'phase4_readiness_')) and '__pycache__' not in p.parts])
    report = dict(kind='READ_ONLY_PHASE4_READINESS_AUDIT', status='PASS_AUDIT_ONLY',
        verdict='PHASE_4_NOT_STARTED_PHASE_3_GATE', phase3_status=phase3['phase3_status'],
        captured_at=datetime.now(timezone.utc).isoformat(), client_timezone='Asia/Calcutta', head=git('rev-parse','HEAD'),
        source_unchanged=before['source']==after, prior_document_files=len(old_docs), prior_documents_unchanged=all(old_docs.values()),
        prior_closeout_bound_files_unchanged=all(bound.values()), configuration=config, configuration_files_unchanged=True,
        database_handling=before['database_handling'], one_shot_stage=stage_state,
        new_full_test_suite_run=False, reused_test_proof=dict(path='docs/evidence/master_phase3_angel_20261023_03.json',
            sha256=sha(EVIDENCE/'master_phase3_angel_20261023_03.json'), python_executed=proof['python']['executed'],
            python_passed=proof['python']['passed'], original_checks=proof['checks'], scope=proof['scope']),
        fresh_validation_command=command, fresh_validation_exit=result.returncode, fresh_validation_log=logpath.relative_to(APP).as_posix(),
        fresh_validation_log_sha256=sha(logpath), prior_phase3_status_receipts=newer, release=release,
        retained_zip_matches_current_packaged_files=packaged_current, private_release_scope_excluded=excluded,
        new_release_built=False, new_secret_scan='PASS', source_snapshot=after, gates=matrix,
        production_changes=0, provider_requests=0, orders=0, telegram_sends=0, scheduler_starts=0,
        new_files={p.relative_to(APP).as_posix():sha(p) for p in audit_files}, scores_recalculated=False)
    write(EVIDENCE/'phase4_gate_readiness_verification_20261023_01.json',report)
    print(json.dumps(dict(verdict=report['verdict'],source_unchanged=True,prior_documents=len(old_docs),
        prior_closeout_bound_files_unchanged=True,reused_python=proof['python']['passed'],
        new_full_suite_run=False,release_files=release['files'],configuration=config,stage=stage_state)))


def validate_audit():
    path=EVIDENCE/'phase4_gate_readiness_verification_20261023_01.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    before=json.loads(BASELINE.read_text(encoding='utf-8'))
    validate_evidence(APP/data['reused_test_proof']['path'])
    if (data['source_snapshot']!=source_snapshot(APP) or data['source_snapshot']!=before['source']
        or any(sha(APP/name)!=expected for name,expected in data['new_files'].items())
        or any(sha(APP/name)!=expected for name,expected in before['documents'].items())
        or sha(APP/data['fresh_validation_log'])!=data['fresh_validation_log_sha256']
        or environment_hashes()!=before['configuration_file_sha256s']):
        raise ValueError('AUDIT_BINDING_OR_PRESERVATION_FAILURE')
    matrix=json.loads((EVIDENCE/'phase4_gate_readiness_acceptance_20261023_01.json').read_text())
    if matrix['gates']!=data['gates'] or matrix['verdict']!=data['verdict'] or matrix['phase4_accepted']:
        raise ValueError('AUDIT_GATE_BINDING_FAILURE')
    from release_management import ReleasePackager
    release=ReleasePackager(str(APP)).inspect_bundle(EVIDENCE/'phase3_angel_release_20261023_02.zip')
    if release!=data['release']:
        raise ValueError('AUDIT_RELEASE_BINDING_FAILURE')
    result=dict(status='PASS_READ_ONLY_AUDIT_INTEGRITY',verdict=data['verdict'],
        audit_receipt_sha256=sha(path),source_unchanged=True,prior_documents_unchanged=True,
        configuration_files_unchanged=True,new_artifact_hashes_verified=len(data['new_files']),
        release_sha256=release['sha256'],release_files=release['files'],
        provider_requests_in_audit=0,production_changes_in_audit=0,new_test_suite_run=False,
        verification_command=[sys.executable,'-B','-W','error::ResourceWarning',
            'docs/evidence/phase4_gate_readiness_audit_20261023_01.py','--validate-audit'])
    write(EVIDENCE/'phase4_gate_readiness_closeout_validation_20261023_01.json',result)
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--validate-audit',action='store_true')
    args=parser.parse_args()
    if args.baseline:
        baseline()
    elif args.validate_audit:
        validate_audit()
    else:
        finalize()

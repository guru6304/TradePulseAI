"""Render closeout from actual executed receipts; no market/auth/order calls."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
E = APP/'docs/evidence'
sys.path.insert(0, str(APP))
from verify_offline import validate_evidence


def write(path, obj):
    with path.open('x', encoding='utf-8') as out:
        json.dump(obj, out, indent=2, allow_nan=False)


def main():
    proof = validate_evidence(E/'master_phase3_angel_20261023_03.json')
    from release_management import ReleasePackager
    release = ReleasePackager(str(APP)).inspect_bundle(E/'phase3_angel_release_20261023_02.zip')
    probe_path = E/'phase3_angel_probe_live_20261023_01.json'
    probe = json.loads(probe_path.read_text())
    history = probe['history']
    auth = json.loads((E/'phase3_angel_observation_authorization_20261023_01.json').read_text())
    operator = json.loads((E/'task3_completion_track_a_20261023_01_angel_operator_01.json').read_text())
    offline_command = '.venv_phase4\\Scripts\\python.exe -B -W error::ResourceWarning verify_offline.py --stage phase3_angel_20261023_02'
    live_command = '.venv_phase4\\Scripts\\python.exe -B -W error::ResourceWarning angel_feed_control.py --provider angelone --symbol RELIANCE --smoke --fetch-master --seconds 15 --history-session 2026-10-22 --stage live_20261023_01'
    future_live = '.venv_phase4\\Scripts\\python.exe -B -W error::ResourceWarning angel_feed_control.py --provider angelone --symbol RELIANCE --smoke --fetch-master --seconds 420 --extended-observation-authorized --stage market_open_authorized_01'
    future_history = '.venv_phase4\\Scripts\\python.exe -B docs/evidence/task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage angel_operator_02'
    rejected = probe['feed']['last_rejected_event']
    if not (probe['authentication']['status'] == 'PASS' and rejected['packet_type'] == 3
            and rejected['security_id'] == '2885' and rejected['accepted'] is False
            and history['http_status'] == 200 and history['candidate_only'] is True):
        raise ValueError('UNEXPECTED_ACTUAL_PROBE_REVIEW_REQUIRED')
    gates = [
        ('1_SOURCE_COMPILE_REGRESSION', 'PASS', 'Executed current strict suite and source/log validator'),
        ('2_AUTHENTICATED_WEBSOCKET_SUBSCRIPTION', 'PASS', 'Genuine scoped binary SnapQuote proves connection/subscription; stale packet rejected'),
        ('3_CURRENT_INSTRUMENT_MAPPING', 'PASS', 'Current original public master unique NSE RELIANCE-EQ token2885 agrees with canonical pin'),
        ('4_FRESH_GENUINE_OBSERVATIONS', 'BLOCKED', 'Genuine stale packet retained; no accepted fresh event'),
        ('5_COMPLETE_1M_AND_5M_CANDLES', 'BLOCKED', 'Zero accepted complete live candles'),
        ('6_LIVE_COMPLETED_CANDLE_STORAGE_LINEAGE', 'OFFLINE_PASS_LIVE_PENDING', 'Raw rejected packet persisted; completed candle path has deterministic tests only'),
        ('7_SCANNER_VALIDATED_LIVE_INPUT', 'OFFLINE_PASS_LIVE_PENDING', 'Canonical handoff tested; no genuine completed input available'),
        ('8_FAILURE_NO_FALLBACK', 'PASS', 'Observed stale-packet rejection/close; offline REST/provider/fixture fallback denials'),
        ('9_HEALTH_DASHBOARD', 'OFFLINE_PASS_LIVE_PENDING', 'Existing generic stream renderer/health tested; no interactive browser acceptance claimed'),
        ('10_PAPER_SAFETY', 'PASS', 'Saved settings preserved; read-only isolated flow; dry-run/scheduler guards; no execution engine'),
        ('11_CURRENT_EVIDENCE_RELEASE', 'PASS', 'Final source/log receipt and inspected candidate PASS; separate finalizer binds preservation and secret audit')]
    blocks = []

    def block(code, gate, happened, correction, verification, expected, command=live_command, exit_code=1, evidence=probe_path.name):
        blocks.append(dict(code=code, affected_gate=gate, what_happened=happened, failed_command=command,
            exit_code=exit_code, sanitized_evidence='docs/evidence/'+evidence, actor='OPERATOR',
            required_correction=correction, safe_resolution_procedure=correction,
            verification_command=verification, expected_passing_result=expected))

    block('ANGEL_MARKET_OBSERVATIONS_INSUFFICIENT', 'Phase3 gates4-7',
        'After-market SnapQuote feed timestamp '+rejected['exchange_timestamp']+' received '+rejected['receive_timestamp']+' rejected as stale.',
        'Resume at an actually open configured NSE cash session. One up-to420-second RELIANCE read-only run is already authorized; do not ask again. Start near the final minute before a 5m boundary; keep paper execution/dry-run and scheduler false. No automatic scheduling or repeated runs authorized.',
        future_live, 'Fresh scoped events, complete valid1m/5m candles with durable raw-event links, guarded scanner handoff. Any missing trades/volume gaps must remain rejected.')
    block('ANGEL_CANDLE_ACCEPTANCE_INSUFFICIENT', 'Phase3 completed-candle and real consumer gates',
        'Accepted event count0; completed1m=0 and5m=0; scanner cannot consume this rejected packet.',
        'Use the same single authorized market-open run. Inspect event/volume continuity and both completed intervals before asserting acceptance; a connection or fixture cannot substitute.',
        future_live, 'Both completed intervals pass chronology/session/freshness/volume/provenance; actual durable scanner input binding reviewed.')
    check_evidence = 'task3_completion_track_a_20261023_01_angel_operator_01.json'
    check_command = operator['command']
    historical = [
        ('HISTORICAL_CASH_QUALIFIED_DATA_MISSING', '73 original bars captured privately;15:15/15:20 missing. Qualified operator cash/study files absent.', 'Supply authentic complete, sufficiently broad chronological sessions and frozen training/test plan; retain originals and missing intervals without fabrication.'),
        ('PUBLISHER_TRUST_ROOT_MISSING', 'No independently approved publisher root supplied.', 'Provide independently approved public Ed25519 roots with current validity/revocation policy in the separate operator directory. Never generate a key and label it Angel authority.'),
        ('PUBLISHER_AUTHENTICITY_UNVERIFIED', 'HTTPS captures supply acquisition integrity, not detached publisher signatures.', 'Obtain genuinely qualifying publisher manifests for exact cash/master artifact hashes, or an explicitly reviewed legitimate policy alternative. Current default policy remains unchanged.'),
        ('HISTORICAL_RIGHTS_DOCUMENT_MISSING', 'No reviewed actual rights document retained in the operator policy contract.', 'Retain the applicable original licence/rights terms privately and bind its hash; free API access alone grants no research/redistribution approval.'),
        ('HISTORICAL_RESEARCH_SCOPE_UNAPPROVED', 'No independent operator HISTORICAL_RESEARCH grant for the exact artifacts/symbols/time scope.', 'Provide a separately reviewed rights grant with reviewer/reference/current validity and exact document/artifact bindings.'),
        ('HISTORICAL_INSTRUMENT_MASTER_MISSING', 'Current master is byte-bound but no qualifying dated historical EQ master/manifest exists.', 'Supply authentic dated identity coverage for the requested historical sessions and qualifying manifests; do not assign historical authority to a current snapshot.')]
    for code, happened, correction in historical:
        block(code, 'Separate historical cash qualification/study', happened, correction, future_history,
              'Helper exits0 with source, rights, dated identity, coverage and cash-study-input checks PASS; no F&O acceptance implied.',
              command=check_command, exit_code=2, evidence=check_evidence)
    block('OPTION_EXECUTION_DATA_MISSING', 'Separate historical Strategy3; not a live Phase3 dependency',
        'No exact dated option contracts/premium executable bid-ask-depth and prior-close OI package supplied.',
        'Provide the separately qualified option request and explicit local trust/rights policy. Reuse historical_study.run_frozen_study with option_request and the existing frozen cost/chronological plan; cash candles cannot clear this gate.',
        future_history, 'Cash helper may pass but must retain BLOCKED_SEPARATE_DATA_DEPENDENCY for options. Real option acceptance additionally requires a qualifying retained run_frozen_study input/result evidence pair; no real option verification command is executable before that request/policy exists.',
        command=check_command, exit_code=2, evidence=check_evidence)
    acceptance = dict(schema_version='tradepulse.phase3-angel-acceptance.v1', captured_at=datetime.now(timezone.utc).isoformat(),
        source_receipt='docs/evidence/master_phase3_angel_20261023_03.json', live_probe='docs/evidence/'+probe_path.name,
        phase3_status='BLOCKED_REAL_COMPLETED_MARKET_CANDLES', overall_task3_status='BLOCKED_LIVE_AND_HISTORICAL_ACCEPTANCE',
        historical_study_status='BLOCKED_SOURCE_RIGHTS_IDENTITY_COVERAGE', phase4_authorized=False,
        gates=[dict(gate=g, status=s, evidence=e) for g,s,e in gates], blockers=blocks,
        extended_market_open_authorization=auth, private_probe_count=1, private_login_count=1,
        history_request_count=1, actual_probe_exit_code=1, historical_input_check_logical_exit_code=2,
        historical_input_check_powershell_wrapper_exit_code=1, orders=0, token_refresh=0, telegram_sends=0,
        scheduler_activations=0, dhan_requests=0, upstox_requests=0, historical_studies_run=0,
        preserved_historical_limitations=['Earlier Task2 Python log mismatch remains preserved historical evidence; current fresh receipt validates.'])
    write(E/'phase3_angel_acceptance_20261023_02.json', acceptance)
    with (E/'phase3_angel_operator_blockers_20261023_02.md').open('x', encoding='utf-8') as out:
        out.write('Angel Phase3 live acceptance and historical qualification remain separate.\n\n')
        for item in blocks:
            out.write('**'+item['code']+'**\n\n')
            out.write('\n\n'.join(key+': '+str(value) for key,value in item.items() if key!='code')+'\n\n')
    head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=APP, text=True).strip()
    tree = subprocess.check_output(['git','status','--short'], cwd=APP, text=True)
    summary = dict(head=head, repository=str(APP), working_tree=tree, current_source_receipt=acceptance['source_receipt'],
        python=proof['python']['passed'], checks=proof['checks'], phase3_status=acceptance['phase3_status'],
        overall_task3_status=acceptance['overall_task3_status'], phase4_authorized=False,
        source_and_logs_validated=True, probe=probe_path.name, probe_sha256=hashlib.sha256(probe_path.read_bytes()).hexdigest(),
        preserved_user_changes=['Both .env files','Untracked original tradepulse_phase1d.db','All prior evidence/reports/releases'],
        acceptance='phase3_angel_acceptance_20261023_02.json', release='phase3_angel_release_20261023_02.zip',
        final_integrity_receipt='phase3_angel_closeout_validation_20261023_02.json', scores_recalculated=False)
    write(E/'phase3_angel_closeout_20261023_02.json', summary)
    print(json.dumps(dict(status='WRITTEN_PENDING_FINAL_INTEGRITY', head=head, python=proof['python']['passed'],
                          phase3=acceptance['phase3_status'], open_blockers=len(blocks))))


if __name__ == '__main__':
    main()

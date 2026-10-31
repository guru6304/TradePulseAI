"""Root-reviewed B01.5a proof-gated cleanup preparation and handoff finalization.

Never runs tests, cleanup, application code, providers or operational databases.
Only prepare mode invokes one read-only Git tracked-file listing.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
E = APP / 'docs/evidence'
P = APP / 'docs/project'
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence

INVENTORY = 'astra_cleanup_inventory_b01_vwap_20261029_01.json'
SCRIPT = 'astra_cleanup_b01_vwap_apply_20261029_01.ps1'
PROOF = 'master_astra_b01_vwap_20261029_01.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def create(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True)+'\n')


def bound(mapping):
    for name, checksum in mapping.items():
        assert sha(APP / name) == checksum, 'preservation mismatch: '+name


def proof():
    current = validate_evidence(E / PROOF, APP)
    baseline = read(E / 'astra_b01_vwap_baseline_20261029_01.json')
    source = source_snapshot(APP)
    assert len(baseline['source']) == 106 and len(source) == 108
    assert set(source)-set(baseline['source']) == {'vwap_paper_triggers.py', 'test_astra_vwap_paper_triggers.py'}
    assert not set(baseline['source'])-set(source)
    assert {n for n in baseline['source'] if baseline['source'][n] != source[n]} == {'release_management.py', 'test_bot.py'}
    assert len(baseline['protected_documents']) == 1183
    for key in ('protected_documents', 'cached_public_assets', 'external_source_hashes'):
        bound(baseline[key])
    for name, checksum in baseline['saved_config_hashes'].items():
        assert sha(Path(name)) == checksum, 'saved configuration changed'
    return current, baseline


def no_reparse(path):
    for item in (path, *path.parents):
        if item.exists():
            assert not item.is_symlink() and not (item.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT), 'reparse path'


def prepare():
    proof()
    tracked = set(subprocess.check_output(['git', '-C', str(APP.parent), 'ls-files', '--full-name'],
                  text=True).replace('\\', '/').splitlines())
    rows = []
    for root in (APP / '__pycache__', E / '__pycache__'):
        no_reparse(root)
        if not root.exists():
            continue
        assert root.is_dir()
        for item in sorted(root.iterdir()):
            relative = item.relative_to(APP.parent).as_posix()
            if item.suffix.lower() not in ('.pyc', '.pyo') or relative in tracked:
                continue
            no_reparse(item)
            info = item.lstat()
            assert stat.S_ISREG(info.st_mode) and re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:pyc|pyo)', item.name)
            rows.append(dict(path=relative, absolute_path=str(item.absolute()), size_bytes=info.st_size,
                mtime_ns=info.st_mtime_ns, reason='UNTRACKED_REGENERABLE_PROJECT_PYTHON_BYTECODE', action='DELETE_CANDIDATE'))
    old = E / 'astra_cleanup_inventory_20261029_01.json'
    inventory = dict(schema='tradepulse.safe-cleanup-inventory.v1', status='PASS_READ_ONLY_INVENTORY',
        workspace=str(APP.parent), recorded_at=datetime.now(timezone.utc).isoformat(),
        candidate_file_count=len(rows), candidate_size_bytes=sum(r['size_bytes'] for r in rows),
        cache_deletion_candidates=rows, image_deletion_candidates=[], deletions=0,
        previous_inventory=old.name, previous_inventory_sha256=sha(old), source_helper_sha256=sha(Path(__file__)),
        provider_requests=0, environment_or_private_payloads_read=False)
    old_script = E / 'astra_cleanup_apply_20261029_01.ps1'
    data = old_script.read_bytes()
    for before, after in ((b'astra_cleanup_inventory_20261029_01.json', INVENTORY.encode()),
                          (b'astra_cleanup_apply_20261029_01.ps1', SCRIPT.encode()),
                          (b"'apply_20261029_01'", b"'b01_vwap_apply_20261029_01'"),
                          (b"'dryrun_20261029_01'", b"'b01_vwap_dryrun_20261029_01'"),
                          (b'-ne 105', ('-ne '+str(len(rows))).encode()),
                          (b'exactly 105 candidates', ('exactly '+str(len(rows))+' candidates').encode())):
        assert before in data
        data = data.replace(before, after)
    assert not (E / INVENTORY).exists() and not (E / SCRIPT).exists()
    create(E / INVENTORY, inventory)
    with (E / SCRIPT).open('xb') as stream:
        stream.write(data)
    print(json.dumps(dict(status='PASS', candidates=len(rows), bytes=inventory['candidate_size_bytes'])))


def finalize():
    current, baseline = proof()
    focused = read(E / 'astra_vwap_registered_20261029_01.json')
    assert focused['status'] == 'PASS' and focused['executed'] == focused['passed'] == 39 and focused['exit_code'] == 0
    assert focused['source_before'] == focused['source_after'] == source_snapshot(APP)
    assert focused['expected_ids'] == focused['executed_ids'] == focused['passed_ids']
    assert not any(focused[k] for k in ('failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes', 'unraisable_errors'))
    assert sha(APP / focused['log']) == focused['log_sha256']
    assert (APP / 'docs/reports/astra_b01_vwap_independent_review_20261029_01.md').is_file()
    cleanup = read(E / 'astra_cleanup_b01_vwap_apply_20261029_01.json')
    inventory = read(E / INVENTORY)
    assert cleanup['status'] == 'PASS' and cleanup['exit_code'] == 0 and not cleanup['errors']
    assert cleanup['all_targets_validated_before_deletion'] and cleanup['planned_files'] == inventory['candidate_file_count']
    assert cleanup['inventory_sha256_before'] == cleanup['inventory_sha256_after'] == sha(E / INVENTORY)
    assert cleanup['script_sha256'] == sha(E / SCRIPT) and sha(APP / cleanup['log']) == cleanup['log_sha256']
    assert cleanup['images_removed'] == cleanup['tracked_files_removed'] == 0 and not cleanup['recursive_delete_used']
    assert not cleanup['private_directories_descended'] and not inventory['image_deletion_candidates']
    assert set(map(Path, cleanup['allowed_cache_roots'])) == {APP / '__pycache__', E / '__pycache__'}
    assert {r['path'] for r in cleanup['file_results']} == {r['path'] for r in inventory['cache_deletion_candidates']}
    assert all(r['outcome'] in ('REMOVED', 'ALREADY_MISSING') for r in cleanup['file_results'])
    assert all(not Path(r['absolute_path']).exists() for r in inventory['cache_deletion_candidates'])
    assert cleanup['removed_files'] == sum(r['outcome'] == 'REMOVED' for r in cleanup['file_results'])
    assert cleanup['removed_bytes'] == sum(r['removed_bytes'] for r in cleanup['file_results'])
    node = sum(c.get('executed', 0) for c in current['checks'] if isinstance(c['command'], list) and c['command'][0] == 'node')
    compiled = sum(c.get('compiled_files', 0) for c in current['checks'])
    result = (f"B01.5a VERIFIED_COMPLETE_LIMITED: {current['python']['executed']} Python / {node} Node / {compiled} compile; "
              f"39 focused (11 VWAP +28 ORB). Fresh verification caches: {cleanup['removed_files']} files / {cleanup['removed_bytes']} bytes removed. "
              "Prior E02 cleanup105 remains separate retained history, not an aggregate claim.")
    scope = ("Isolated experimental cash VWAP build_contract/evaluate_observation evidence only; non-actionable, no accepted automatic fill policy, "
             "no capital reservation or position creation. Existing ORB automatic behavior unchanged. Actual retained scanner/detector pipeline and volume "
             "boundaries tested; mocked EMA/RSI boundaries are unit numerical checks only. Initial failure was absent-module ModuleNotFoundError; "
             "restricted temporary SQLite smoke failure was a sandbox limitation, followed by approved passing runs. No empirical, performance, live, "
             "provider admission or customer acceptance. Original mission INCOMPLETE; UI DEFERRED_OWNER_UI_REVAMP, no UI work.")
    next_task = ("B01.5b NOT_STARTED: explicit opt-in coordinator/portfolio integration with retained-source guards, atomic entry/rollback, "
                 "direct-enter bypass, concurrency and restart tests. No policy activation or account mutation yet.")
    report = APP / 'docs/reports/astra_b01_vwap_completion_20261029_01.md'
    archive = E / 'astra_b01_vwap_handoff_previous_20261029_01.json'
    assert not report.exists() and not archive.exists()
    handoffs = {n: (P / n).read_bytes() for n in baseline['handoff']}
    master_name = 'TRADEPULSE_ASTRA_MASTER_EXECUTION_REPORT.md'
    master = (P / master_name).read_text(encoding='utf-8')
    assert [int(n) for n in re.findall(r'^## (\d+)\.', master, re.M)] == list(range(1, 19))
    now = datetime.now(timezone.utc).isoformat()
    note = '\n'+result+'\n\n'+scope+'\n\n'+next_task+'\n'
    def replace_section(text, number, body):
        a = re.search(r'^## '+str(number)+r'\.[^\n]*\n', text, re.M)
        b = re.search(r'^## '+str(number+1)+r'\. ', text, re.M)
        assert a and b
        return text[:a.end()]+'\n'+body.strip()+'\n\n'+text[b.start():]
    master = ('# TradePulse Astra master execution report\n\n'
        'Original mission TRADEPULSE-ASTRA-OWNER-2026-10-24-V1; master mission INCOMPLETE.\n'
        'UI remains DEFERRED_OWNER_UI_REVAMP. Continue original functionality tasks.\n'
        'Updated UTC: '+now+'; client date2026-10-29, Asia/Kolkata.\n\n'+master[master.index('## 1.'):])
    master = replace_section(master, 1, result+'\n\n'+scope+'\n\n'
        'Current proof: '+PROOF+'. Completion/review: astra_b01_vwap_completion_20261029_01.md and '
        'astra_b01_vwap_independent_review_20261029_01.md. E02 ledger identity validation and its cleanup remain covered; '
        'prior source receipts are historical after new B01 files/registration.\n\n'+next_task)
    a = re.search(r'^## 2\.[^\n]*\n', master, re.M)
    master = master[:a.end()]+'\nThis B01 unit adds vwap_paper_triggers.py and test_astra_vwap_paper_triggers.py; existing edits are release_management.py/test_bot.py registration only. Baseline106 becomes108 source files;1183 prior documents, original four handoffs, saved settings and20cached public bodies remain preserved. Prior UI/API fixes are unchanged.\n'+master[a.end():]
    a = re.search(r'^## 10\.[^\n]*\n', master, re.M)
    master = master[:a.end()]+'\nB01.5a now supplies an isolated, non-actionable VWAP future-reclaim evidence contract. Automatic VWAP entries remain unsupported until B01.5b. The existing ORB entry/ledger mechanism below is unchanged and its28focused regressions passed.\n'+master[a.end():]
    master = re.sub(r'^\|B01 /6 /paper owner\|.*$', '|B01 /6 /paper owner|ORB + ISOLATED VWAP EVIDENCE VERIFIED; lifecycle INCOMPLETE|VWAP contract11tests/ORB28pass; integration5b and other strategies/contracts remain pending.|', master, flags=re.M)
    a = re.search(r'^## 15\.[^\n]*\n', master, re.M)
    master = master[:a.end()]+'\n**Current source:** '+PROOF+': '+result+'\n\nExact executed IDs, source-before/source-after and log hashes match. Previous E02/E01 verification below is historical at its own source boundary. No new UI verification was run.\n'+master[a.end():]
    master = master.replace('**Current original-master source:** `master_astra_backend_cleanup_20261029_01.json`', '**Historical E02 source:** `master_astra_backend_cleanup_20261029_01.json`')
    master = replace_section(master, 17, result+'\n\nNo command is running at this checkpoint. Master mission remains incomplete. '
        'UI is deferred; provider/order/send/operational database/Git actions were not performed.\n\n'+next_task+
        '\n\nUse astra_b01_pending_continuation_20261029_01.md and the completed5a contract as the starting point; do not restart the audit or reimplement completed work. Resume: CONTINUE FROM CHECKPOINT.')
    assert [int(n) for n in re.findall(r'^## (\d+)\.', master, re.M)] == list(range(1, 19))
    ledger = (P / 'TRADEPULSE_ASTRA_TASK_LEDGER.md').read_text(encoding='utf-8')
    for key, value in {
        'B01.5a': '|B01.5a|6|Isolated VWAP future-reclaim evidence|VERIFIED_COMPLETE_LIMITED|11 new tests;39 focused; current canonical; no activation|',
        'B01.5b': '|B01.5b|6|Opt-in VWAP coordinator/portfolio integration|NOT_STARTED|Exact next task: atomic guards/rollback/direct-enter/concurrency acceptance; no activation yet|',
        'F02.1': '|F02.1|6|Current-source canonical and preservation|VERIFIED_COMPLETE|'+str(current['python']['executed'])+'Python/'+str(node)+'Node/'+str(compiled)+'compile; B01.5a source/log/cleanup bindings|'
    }.items():
        pattern = r'^\|'+re.escape(key)+r'\|.*$'
        ledger = re.sub(pattern, lambda m: value, ledger, flags=re.M) if re.search(pattern, ledger, re.M) else ledger.rstrip()+'\n'+value+'\n'
    checkpoint = ('# Original Astra master - B01.5a verified, 2026-10-29\n\nUpdated UTC: '+now+'\n'+note+
        '\nCurrent proof: '+PROOF+'\nNo process is running. All1183baseline documents, saved configuration and private assets are preserved. '
        'UI is DEFERRED_OWNER_UI_REVAMP; dev/Antigravity work and Git remain untouched. '
        'No provider/order/send or operational database action. Broader B01/D01, empirical/live and release gates remain open.\n'
        'Previous checkpoint bytes are archived in astra_b01_vwap_handoff_previous_20261029_01.json.\n'
        'Resume instruction: CONTINUE FROM CHECKPOINT.\n')
    updates = {master_name: master, 'TRADEPULSE_ASTRA_CHECKPOINT.md': checkpoint,
        'TRADEPULSE_ASTRA_PROGRESS.md': (P / 'TRADEPULSE_ASTRA_PROGRESS.md').read_text(encoding='utf-8')+'\n## B01.5a - 2026-10-29\nUpdated UTC: '+now+'\n'+note,
        'TRADEPULSE_ASTRA_TASK_LEDGER.md': ledger}
    create(archive, {n: dict(sha256=hashlib.sha256(data).hexdigest(), original_bytes_base64=base64.b64encode(data).decode()) for n, data in handoffs.items()})
    create(report, '# Original master B01.5a completion — 2026-10-29\n'+note+'\nSource scope: new vwap_paper_triggers.py/test_astra_vwap_paper_triggers.py; release_management.py/test_bot.py registration only. '
        'Baseline106 ->108 source files;1183 prior documents, saved configuration and private/cached assets preserved. Prior UI/API fixes unchanged. '
        'No dev/Antigravity/Git writes. Proof: '+PROOF+'. Independent review: astra_b01_vwap_independent_review_20261029_01.md.\n')
    for name, content in updates.items():
        (P / name).write_text(content, encoding='utf-8', newline='\n')
    print(json.dumps(dict(status='PASS', python=current['python']['executed'], node=node, compiled=compiled, removed=cleanup['removed_files'])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-cleanup', action='store_true')
    mode.add_argument('--finalize', action='store_true')
    args = parser.parse_args()
    prepare() if args.prepare_cleanup else finalize()

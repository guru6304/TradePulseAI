"""Bind B01.5a evidence without executing application code, tests or cleanup.

Create a new closeout, or independently recompute it with --validate-only.
All outputs are exclusive creations. Saved configuration is hashed locally only.
"""
import argparse
import ast
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import sys

APP = Path(__file__).resolve().parents[2]
E = APP / 'docs/evidence'
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence

STEM = 'astra_b01_vwap_closeout_20261029_03'
VALIDATION = 'astra_b01_vwap_closeout_validation_20261029_03'
PROOF = 'master_astra_b01_vwap_20261029_01.json'
INVENTORY = 'astra_cleanup_inventory_b01_vwap_20261029_01.json'
SCRIPT = 'astra_cleanup_b01_vwap_apply_20261029_01.ps1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def local(name, root=APP):
    path = (root / name).resolve()
    assert path.is_relative_to(root.resolve()) and path.is_file(), 'missing/outside artifact: ' + str(name)
    return path


def bound(mapping):
    for name, checksum in mapping.items():
        assert sha(local(name)) == checksum, 'artifact changed: ' + name


def exclusive(path, receipt):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write('\n')


def no_reparse(path):
    """Inspect existing ancestors only; never enter an unknown directory."""
    for ancestor in (path, *path.parents):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        assert not stat.S_ISLNK(info.st_mode)
        assert not getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT


def cleanup():
    inventory_path = E / INVENTORY
    inventory = read(inventory_path)
    assert inventory['schema'] == 'tradepulse.safe-cleanup-inventory.v1'
    assert inventory['status'] == 'PASS_READ_ONLY_INVENTORY'
    assert Path(inventory['workspace']).resolve() == APP.parent
    candidates = inventory['cache_deletion_candidates']
    assert len(candidates) == inventory['candidate_file_count'] and candidates
    assert inventory['candidate_size_bytes'] == sum(r['size_bytes'] for r in candidates)
    allowed = {APP / '__pycache__', E / '__pycache__'}
    expected = {}
    for row in candidates:
        assert row['action'] == 'DELETE_CANDIDATE'
        assert row['reason'] == 'UNTRACKED_REGENERABLE_PROJECT_PYTHON_BYTECODE'
        assert re.fullmatch(r'indian_fo_signal_bot_v1/(?:__pycache__|docs/evidence/__pycache__)/[A-Za-z0-9_.-]+\.(?:pyc|pyo)', row['path'])
        path = Path(row['absolute_path'])
        no_reparse(path)
        assert path.resolve() == (APP.parent / row['path']).resolve()
        assert path.parent in allowed and row['path'] not in expected
        assert isinstance(row['size_bytes'], int) and row['size_bytes'] >= 0
        assert isinstance(row['mtime_ns'], int) and row['mtime_ns'] > 0
        expected[row['path']] = row
    script = (E / SCRIPT).read_text(encoding='utf-8-sig')
    # Bind the executed policy and verify its essential containment/type/tracked guards.
    for token in ('Assert-NoReparseChain', 'Assert-CacheTarget', '$tracked.Contains($RelativePath)',
                  'all_targets_validated_before_deletion', 'Assert-Contained',
                  'Remove-Item -LiteralPath $target.absolute_path', '[IO.Directory]::Delete($root, $false)'):
        assert token in script, 'cleanup guard missing: ' + token
    assert '-Recurse' not in script
    for name, apply in (('astra_cleanup_b01_vwap_dryrun_20261029_01.json', False),
                        ('astra_cleanup_b01_vwap_apply_20261029_01.json', True)):
        receipt = read(E / name)
        assert receipt['schema'] == 'tradepulse.exact-cache-cleanup.v1'
        assert receipt['status'] == ('PASS' if apply else 'PASS_DRY_RUN')
        assert receipt['mode'] == ('APPLY' if apply else 'DRY_RUN')
        assert receipt['exit_code'] == 0 and not receipt['errors']
        assert receipt['inventory'] == 'docs/evidence/' + INVENTORY
        assert receipt['inventory_sha256_before'] == receipt['inventory_sha256_after'] == sha(inventory_path)
        assert receipt['script_sha256'] == sha(E / SCRIPT)
        assert set(map(Path, receipt['allowed_cache_roots'])) == allowed
        assert receipt['all_targets_validated_before_deletion']
        rows = receipt['file_results']
        assert len(rows) == receipt['planned_files'] == len(expected)
        assert {r['path'] for r in rows} == set(expected)
        for row in rows:
            assert row['outcome'] in (('REMOVED', 'ALREADY_MISSING') if apply else ('WOULD_REMOVE', 'ALREADY_MISSING'))
            if 'inventory_size_bytes' in row:
                assert row['inventory_size_bytes'] == expected[row['path']]['size_bytes']
            assert row['removed_bytes'] >= 0
            if row['outcome'] != 'REMOVED':
                assert row['removed_bytes'] == 0
        assert receipt['removed_files'] == sum(r['outcome'] == 'REMOVED' for r in rows)
        assert receipt['removed_bytes'] == sum(r['removed_bytes'] for r in rows)
        if apply:
            assert all(not Path(row['absolute_path']).exists() for row in candidates)
        else:
            assert receipt['removed_files'] == receipt['removed_bytes'] == 0
        for key in ('provider_requests', 'tracked_files_removed', 'images_removed',
                    'operational_database_accessed', 'environment_or_private_payloads_read',
                    'private_directories_descended', 'recursive_delete_used'):
            assert not receipt[key], 'cleanup boundary violation: ' + key
        assert receipt['access_denied_history_directory'] == 'PRESERVED_UNINSPECTED'
        assert sha(local(receipt['log'])) == receipt['log_sha256']
    return len(expected)


def audit():
    baseline = read(E / 'astra_b01_vwap_baseline_20261029_01.json')
    source = source_snapshot(APP)
    assert len(baseline['source']) == 106
    added = {'vwap_paper_triggers.py', 'test_astra_vwap_paper_triggers.py'}
    assert set(source) - set(baseline['source']) == added
    assert not set(baseline['source']) - set(source)
    assert {n for n in baseline['source'] if source[n] != baseline['source'][n]} == {'release_management.py', 'test_bot.py'}
    assert len(baseline['protected_documents']) == 1183
    bound(baseline['protected_documents'])
    bound(baseline['external_source_hashes'])
    bound(baseline['cached_public_assets'])
    assert len(baseline['cached_public_assets']) == 20
    for name, checksum in baseline['saved_config_hashes'].items():
        assert sha(Path(name)) == checksum, 'saved configuration changed'
    assert len(baseline['handoff']) == 4
    for row in baseline['handoff'].values():
        original = base64.b64decode(row['original_bytes_base64'], validate=True)
        assert hashlib.sha256(original).hexdigest() == row['sha256']
    tree = ast.parse((APP / 'vwap_paper_triggers.py').read_text(encoding='utf-8'))
    assert {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')} == {'build_contract', 'evaluate_observation'}
    keywords = [kw for node in ast.walk(tree) if isinstance(node, ast.Call) for kw in node.keywords]
    for flag in ('accepted_fill_policy', 'actionable', 'financial_mutations'):
        values = [kw.value for kw in keywords if kw.arg == flag]
        assert values and all(isinstance(v, ast.Constant) and v.value is False for v in values)

    focused = read(E / 'astra_vwap_registered_20261029_01.json')
    assert focused['kind'] == 'EXECUTED_FOCUSED_OFFLINE_VERIFICATION'
    assert focused['status'] == 'PASS' and focused['exit_code'] == 0
    assert focused['passed'] == focused['executed'] == 39
    assert focused['expected_ids'] == focused['executed_ids'] == focused['passed_ids']
    assert len(set(focused['executed_ids'])) == focused['executed']
    assert sum(n.startswith('test_astra_vwap_paper_triggers.') for n in focused['executed_ids']) == 11
    assert sum(n.startswith('test_astra_paper_triggers.') for n in focused['executed_ids']) == 28
    assert not any(focused[k] for k in ('failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes', 'unraisable_errors'))
    assert focused['source_before'] == focused['source_after'] == source
    assert sha(local(focused['log'])) == focused['log_sha256']
    for filename, status, executed, errors in (
            ('astra_vwap_before_20261029_01.json', 'FAIL', 1, 1),
            ('astra_vwap_matrix_20261029_01.json', 'PASS', 10, 0),
            ('astra_vwap_root_smoke_20261029_01.json', 'FAIL', 1, 2),
            ('astra_vwap_root_smoke_20261029_02.json', 'PASS', 1, 0)):
        history = read(E / filename)
        assert (history['status'], history['executed'], history['errors']) == (status, executed, errors)
        assert sha(local(history['log'])) == history['log_sha256']
    canonical = validate_evidence(E / PROOF, APP)
    count = cleanup()
    required = ['docs/reports/astra_b01_vwap_' + n + '_20261029_01.md' for n in ('completion', 'independent_review')]
    required += ['docs/project/' + n for n in baseline['handoff']]
    for name in required:
        local(name)
    master = local('docs/project/TRADEPULSE_ASTRA_MASTER_EXECUTION_REPORT.md').read_text(encoding='utf-8')
    assert [int(n) for n in re.findall(r'^## (\d+)\.', master, re.M)] == list(range(1, 19))
    completion = local(required[0]).read_text(encoding='utf-8')
    assert 'DEFERRED_OWNER_UI_REVAMP' in completion and 'B01.5b' in completion and 'NOT_STARTED' in completion
    prefixes = ('astra_vwap_', 'astra_b01_vwap_', 'astra_cleanup_b01_vwap_', 'astra_cleanup_inventory_b01_vwap_')
    files = {p.relative_to(APP).as_posix(): sha(p) for p in E.iterdir()
             if p.is_file() and p.name.startswith(prefixes) and p.name not in (STEM + '.json', VALIDATION + '.json')}
    files.update({n: sha(local(n)) for n in required})
    files.update(canonical['logs'])
    files['docs/evidence/' + PROOF] = sha(E / PROOF)
    return dict(scope='B01.5a_ISOLATED_NON_ACTIONABLE_VWAP_EVIDENCE_ONLY', source=source, files=files,
                ui_status='DEFERRED_OWNER_UI_REVAMP', b01_5b_status='NOT_STARTED',
                accepted_fill_policy=False, actionable=False, financial_mutations=False,
                preserved_document_count=len(baseline['protected_documents']), archived_handoff_count=4,
                focused_executed=focused['executed'], python_executed=canonical['python']['executed'],
                canonical_checks=canonical['checks'], cleanup_candidate_count=count,
                failure_history='Initial missing-module import failure and sandbox temp failure retained; neither establishes an algorithmic defect.',
                limits='No automatic activation, empirical promotion, provider, live, financial, UI, or mission acceptance.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    result = audit()
    closeout = E / (STEM + '.json')
    if args.validate_only:
        assert read(closeout)['audit'] == result, 'current audit differs from closeout'
        output = E / (VALIDATION + '.json')
        receipt = dict(schema='tradepulse.b01-vwap-validation.v1', status='PASS',
                       closeout_sha256=sha(closeout), helper_sha256=sha(Path(__file__)),
                       source=result['source'], bound_file_count=len(result['files']))
    else:
        output = closeout
        receipt = dict(schema='tradepulse.b01-vwap-closeout.v1', status='PASS', audit=result)
    receipt['recorded_at'] = datetime.now(timezone.utc).isoformat()
    exclusive(output, receipt)
    print(json.dumps(dict(status='PASS', artifact=output.relative_to(APP).as_posix(),
                          bound_file_count=len(result['files']), ui_status=result['ui_status'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

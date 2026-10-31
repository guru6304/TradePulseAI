"""Read-only integrity audit; exclusively create closeout or separate validation receipt.

Does not run tests, browsers, cleanup, application modules, or Git commands.
Saved configuration is hashed locally; its values and hashes are never emitted.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

APP = Path(__file__).resolve().parents[2]
E = APP / 'docs/evidence'
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence

STEM = 'astra_backend_cleanup_closeout_20261029_01'
PREFIXES = ('astra_browser_journal_', 'astra_journal_cleanup_', 'astra_cleanup_',
            'astra_ledger_scope_', 'astra_backend_cleanup_')
SCOPE = 'ORIGINAL_MASTER_E02_LEDGER_IDENTITY_AND_REQUESTED_CACHE_CLEANUP'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def local(name, root=APP):
    p = (root / name).resolve()
    assert p.is_relative_to(root.resolve()) and p.is_file(), 'missing/outside artifact: ' + str(name)
    return p


def bound(mapping, root=APP):
    for name, checksum in mapping.items():
        assert sha(local(name, root)) == checksum, 'artifact changed: ' + name


def exclusive(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write('\n')


def image_bindings(value, image):
    """Recognize filename-to-hash maps and artifact objects without trusting names alone."""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and re.fullmatch('[0-9a-f]{64}', item):
                if key.replace('\\', '/').endswith(image):
                    yield item
            if key in ('path', 'file', 'name') and isinstance(item, str):
                if item.replace('\\', '/').endswith(image) and 'sha256' in value:
                    yield value['sha256']
            yield from image_bindings(item, image)
    elif isinstance(value, list):
        for item in value:
            yield from image_bindings(item, image)


def audit():
    baseline = read(E / 'astra_journal_cleanup_baseline_20261029_01.json')
    source = source_snapshot(APP)
    assert len(source) == len(baseline['source']) == 106
    assert set(source) == set(baseline['source'])
    assert {n for n in source if source[n] != baseline['source'][n]} == {
        'public/index.html', 'storage.py', 'test_phase5c_recovery.py'}
    assert len(baseline['protected_documents']) == 1121
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

    # Reversing exactly the two pre-stop class edits must recover every baseline byte.
    html = (APP / 'public/index.html').read_bytes()
    old = html.replace(b'id="storedReportsContainer" class="min-w-0 [overflow-wrap:anywhere]"',
                       b'id="storedReportsContainer"', 1)
    pattern = rb'(<div class="flex) flex-wrap( items-center gap-2 text-xs">\r?\n\s*<label for="filterScanStatus")'
    old, count = re.subn(pattern, rb'\1\2', old)
    assert count == 1 and old != html
    assert hashlib.sha256(old).hexdigest() == baseline['source']['public/index.html']
    scripts = lambda b: re.findall(rb'<script\b[^>]*>(.*?)</script>', b, re.S)
    assert scripts(html) == scripts(old), 'inline JavaScript changed'
    storage = (APP / 'storage.py').read_text(encoding='utf-8')
    guard = ('                    # These writers retain both identities in every payload.\n'
             '                    # Events instead retain command/result JSON without them.\n'
             '                    if collection in ("positions", "recovery_decisions") and (\n'
             '                            body.get("account_id") != account_id or body.get(key) != row["entity_id"]):\n'
             '                        raise ValueError()\n')
    assert storage.count(guard) == 1
    assert hashlib.sha256(storage.replace(guard, '', 1).encode()).hexdigest() == baseline['source']['storage.py']

    before = read(E / 'astra_ledger_scope_before_20261029_02.json')
    after = read(E / 'astra_ledger_scope_after_20261029_01.json')
    assert (before['status'], before['executed'], before['failures'], before['errors']) == ('FAIL', 2, 24, 0)
    assert after['status'] == 'PASS' and after['exit_code'] == 0
    assert after['executed'] == after['passed'] == 22
    assert after['expected_ids'] == after['executed_ids'] == after['passed_ids']
    assert len(set(after['executed_ids'])) == after['executed']
    assert not any(after[k] for k in ('failures', 'errors', 'skipped', 'unexpected_successes', 'expected_failures', 'unraisable_errors'))
    for receipt in (before, after):
        assert sha(local(receipt['log'])) == receipt['log_sha256']
        assert receipt['source_before'] == receipt['source_after']
    assert after['source_after'] == source
    canonical = validate_evidence(E / 'master_astra_backend_cleanup_20261029_01.json', APP)

    inventory_path = E / 'astra_cleanup_inventory_20261029_01.json'
    inventory = read(inventory_path)
    candidates = inventory['cache_deletion_candidates']
    assert len(candidates) == inventory['candidate_file_count'] == 105
    allowed = {APP / '__pycache__', E / '__pycache__'}
    expected = {}
    for row in candidates:
        p = Path(row['absolute_path']).resolve()
        assert p.parent in allowed and p.suffix.lower() in ('.pyc', '.pyo')
        assert p == (APP.parent / row['path']).resolve()
        assert row['path'] not in expected
        expected[row['path']] = p
    script = E / 'astra_cleanup_apply_20261029_01.ps1'
    for filename, apply in (('astra_cleanup_dryrun_20261029_01.json', False),
                            ('astra_cleanup_apply_20261029_01.json', True)):
        receipt = read(E / filename)
        assert receipt['exit_code'] == 0 and not receipt['errors']
        assert receipt['status'] == ('PASS' if apply else 'PASS_DRY_RUN')
        assert receipt['inventory_sha256_before'] == receipt['inventory_sha256_after'] == sha(inventory_path)
        assert receipt['script_sha256'] == sha(script)
        assert receipt['all_targets_validated_before_deletion']
        assert set(map(Path, receipt['allowed_cache_roots'])) == allowed
        rows = receipt['file_results']
        assert len(rows) == receipt['planned_files'] == len(expected)
        assert {r['path'] for r in rows} == set(expected)
        if apply:
            assert all(r['outcome'] in ('REMOVED', 'ALREADY_MISSING') for r in rows)
            assert all(not p.exists() for p in expected.values())
            assert receipt['removed_files'] == sum(r['outcome'] == 'REMOVED' for r in rows)
            assert receipt['removed_bytes'] == sum(r['removed_bytes'] for r in rows)
        else:
            assert receipt['removed_files'] == receipt['removed_bytes'] == 0
        assert receipt['images_removed'] == receipt['tracked_files_removed'] == 0
        assert not receipt['recursive_delete_used'] and not receipt['private_directories_descended']
        assert receipt['access_denied_history_directory'] == 'PRESERVED_UNINSPECTED'
        assert sha(local(receipt['log'])) == receipt['log_sha256']
    assert not inventory['image_deletion_candidates']
    assert len(inventory['images']) == inventory['image_hash_bound_count'] == 274
    for row in inventory['images']:
        p = local(row['path'], APP.parent)
        assert row['decision'] == 'KEEP_REQUIRED_EVIDENCE' and p.stat().st_size == row['size_bytes']
        hashes = {h for ref in row['hash_bound_by'] for h in
                  image_bindings(read(local(ref, APP.parent)), p.name)}
        assert hashes == {sha(p)}, 'image binding mismatch: ' + p.name
    unknown = APP / 'task2_history_m24ad64e'
    assert any(r['path'].endswith(unknown.name) and r['reason'] == 'ACCESS_DENIED_NOT_INSPECTED_OR_DELETED'
               for r in inventory['not_inspected'])
    assert unknown.exists(), 'uninspected folder missing'
    browser = read(E / 'astra_browser_journal_fixed_chrome_20261029_04.json')
    assert browser['status'] == 'PASS' and browser['assertions'] == {'passed': 52, 'total': 52}
    assert browser['exit_code'] == 0 and browser['browser_exit_code'] == 0
    bound(browser['source_sha256'])
    assert sha(local(browser['log_file'], E)) == browser['log_sha256']
    assert sha(E / 'astra_browser_journal_verify_20261029_04.py') == browser['helper_sha256']
    assert sha(E / 'astra_browser_journal_probes_20261029_04.py') == browser['probe_helper_sha256']
    for row in browser['screenshots']:
        assert sha(local(row['file'], E)) == row['sha256']

    required = ['docs/PROJECT_LAYOUT_AND_RETENTION.md'] + ['docs/reports/' + n + '.md' for n in (
        'astra_backend_and_cleanup_completion_20261029_01', 'astra_backend_cleanup_independent_review_20261029_01',
        'astra_cleanup_plan_20261029_01', 'astra_backend_next_review_20261029_01',
        'astra_b01_pending_continuation_20261029_01')]
    required += ['docs/project/' + n for n in baseline['handoff']]
    for name in required:
        local(name)
    master = local('docs/project/TRADEPULSE_ASTRA_MASTER_EXECUTION_REPORT.md').read_text(encoding='utf-8')
    assert [int(n) for n in re.findall(r'^## (\d+)\.', master, re.M)] == list(range(1, 19))
    files = {p.relative_to(APP).as_posix(): sha(p) for p in E.iterdir()
             if p.is_file() and p.name.startswith(PREFIXES) and p.name not in
             (STEM + '.json', STEM.replace('closeout_', 'closeout_validation_') + '.json')}
    files.update({name: sha(local(name)) for name in required})
    files.update(canonical['logs'])
    files['docs/evidence/master_astra_backend_cleanup_20261029_01.json'] = sha(E / 'master_astra_backend_cleanup_20261029_01.json')
    return dict(scope=SCOPE, ui_status='DEFERRED_OWNER_UI_REVAMP', source=source, files=files,
                preserved_document_count=1121, archived_handoff_count=4, preserved_image_count=274,
                python_executed=canonical['python']['executed'],
                canonical_checks=canonical['checks'], cleanup_candidate_count=len(expected),
                limitations=['Chrome journal history only; no Edge or whole UI acceptance.',
                             'No mission, live, provider, or customer acceptance.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    result = audit()
    target = E / (STEM + '.json')
    if args.validate_only:
        prior = read(target)
        assert prior['audit'] == result, 'closeout/current audit differs'
        output = E / (STEM.replace('closeout_', 'closeout_validation_') + '.json')
        receipt = dict(schema='tradepulse.backend-cleanup-validation.v1', status='PASS',
                       closeout_sha256=sha(target), helper_sha256=sha(Path(__file__)),
                       source=result['source'], bound_file_count=len(result['files']))
    else:
        output = target
        receipt = dict(schema='tradepulse.backend-cleanup-closeout.v1', status='PASS', audit=result)
    receipt['recorded_at'] = datetime.now(timezone.utc).isoformat()
    exclusive(output, receipt)
    print(json.dumps(dict(status='PASS', artifact=output.relative_to(APP).as_posix(),
                          bound_file_count=len(result['files']), ui_status=result['ui_status'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

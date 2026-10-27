"""Correct handoff date/history wording, retaining the prior bound bytes."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exclusive(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def main():
    evidence = APP / 'docs/evidence'
    parent_path = evidence / 'astra_rank_closeout_20261027_01.json'
    target = evidence / 'astra_rank_closeout_20261027_02.json'
    archive = evidence / 'astra_handoff_refinement_before_20261027_01.json'
    assert not target.exists() and not archive.exists()
    parent = json.loads(parent_path.read_text(encoding='utf-8'))
    validate_evidence(evidence / 'master_astra_rank_history_20261027_01.json')
    assert parent['source'] == source_snapshot(APP)
    assert all(sha(APP / name) == value for name, value in parent['files'].items())
    master = 'docs/project/TRADEPULSE_ASTRA_MASTER_EXECUTION_REPORT.md'
    ledger = 'docs/project/TRADEPULSE_ASTRA_TASK_LEDGER.md'
    checkpoint = 'docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md'
    paths = [master, ledger, checkpoint]
    now = datetime.now(timezone.utc).isoformat()
    exclusive(archive, dict(recorded_at=now, reason='Correct work-span date and distinguish historical environment preservation from owner-confirmed changes',
        sha256={name: sha(APP / name) for name in paths},
        original_bytes_base64={name: base64.b64encode((APP / name).read_bytes()).decode('ascii') for name in paths}))
    content = (APP / master).read_text(encoding='utf-8')
    assert 'Work spanning 2026-10-24–26' in content
    content = content.replace('Work spanning 2026-10-24–26', 'Work spanning 2026-10-24–27', 1)
    content = content.replace('`astra_rank_closeout_20261027_01.json` binds current report/checkpoints/proof/logs.',
        '`astra_rank_closeout_20261027_02.json` binds the current corrected handoff; its parent01 and original handoff bytes remain retained.')
    (APP / master).write_text(content, encoding='utf-8')
    content = (APP / ledger).read_text(encoding='utf-8')
    content = content.replace('Old archives match original source;522 old documents/env/BRD preserved',
        'Old archives/522 documents/BRD preserved; root env matches baseline, app env matches separately confirmed owner change')
    content = content.replace('32 Node tests; narrow renderer/read safety scope only',
        '38 current Node tests; narrow renderer/read safety scope, actual-browser scope separately listed')
    (APP / ledger).write_text(content, encoding='utf-8')
    content = (APP / checkpoint).read_text(encoding='utf-8')
    content = content.replace('Source/log validation and preservation PASS; source hashes in the receipt.',
        'Source/log validation and preservation PASS; source hashes in the receipt.\nCorrected handoff bindings: astra_rank_closeout_20261027_02.json; prior01 retained.\nHandoff refined UTC: ' + now, 1)
    (APP / checkpoint).write_text(content, encoding='utf-8')
    bindings = dict(parent['files'])
    for path in [APP / name for name in paths] + [archive, parent_path, Path(__file__).resolve()]:
        bindings[path.relative_to(APP).as_posix()] = sha(path)
    exclusive(target, dict(status='PASS', recorded_at=now, scope=parent['scope'], source=source_snapshot(APP),
        parent=parent_path.name, reason='Documentation-only refinement; no new source/test execution claim', files=bindings))
    assert all(sha(APP / name) == value for name, value in bindings.items())
    print(json.dumps(dict(status='PASS', files=len(bindings), closeout=target.name)))


if __name__ == '__main__':
    main()

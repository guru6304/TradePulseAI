"""Correct a report stage label while preserving every earlier bound artifact."""
import hashlib
import json
from pathlib import Path
import runpy

APP = Path(__file__).resolve().parents[2]
E = APP/'docs/evidence'


def main():
    report = (APP/'docs/reports/phase3_angel_completion_20261023_02.md').read_text(encoding='utf-8')
    report = report.replace('--stage phase3_angel_20261023_02', '--stage phase3_angel_20261023_03')
    report = report.replace('phase3_angel_closeout_validation_20261023_02',
                            'phase3_angel_closeout_validation_20261023_03')
    report += ('\nDocument correction: the preceding `_02` written report table labelled '
               'the final862-test command stage `_02`. Its authoritative actual receipt '
               'is `_03`; this report corrects that stage label. Earlier report files, '
               'test receipts, logs and release artifacts remain unchanged.\n')
    with (APP/'docs/reports/phase3_angel_completion_20261023_03.md').open('x', encoding='utf-8') as out:
        out.write(report)
    prior = json.loads((E/'phase3_angel_closeout_validation_20261023_02.json').read_text())
    if any(hashlib.sha256((APP/name).read_bytes()).hexdigest() != sha for name,sha in prior['bound_files'].items()):
        raise ValueError('PREVIOUS_CLOSEOUT_BOUND_FILES_CHANGED')
    script = (E/'phase3_angel_integrity_20261023_02.py').read_text(encoding='utf-8')
    script = script.replace('phase3_angel_release_build_20261023_02', 'phase3_angel_release_build_20261023_03')
    script = script.replace('phase3_angel_release_inspect_20261023_02', 'phase3_angel_release_inspect_20261023_03')
    script = script.replace('phase3_angel_closeout_validation_20261023_02', 'phase3_angel_closeout_validation_20261023_03')
    target = E/'phase3_angel_integrity_20261023_03.py'
    with target.open('x', encoding='utf-8') as out:
        out.write(script)
    runpy.run_path(str(target), run_name='__main__')


if __name__ == '__main__':
    main()

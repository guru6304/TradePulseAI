"""Update public handover docs from the final executed source receipt."""
import json
from pathlib import Path
import re
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import validate_evidence


def main():
    proof = validate_evidence(APP/'docs/evidence/master_phase3_angel_20261023_03.json')
    log = (APP/proof['python']['log']).read_text(encoding='utf-8')
    seconds = re.search(r'Ran \d+ tests in ([\d.]+)s', log).group(1)
    previous = APP/'docs/reports/phase3_angel_completion_20261023_01.md'
    report = previous.read_text(encoding='utf-8')
    replacements = {
        'master_phase3_angel_20261023_02': 'master_phase3_angel_20261023_03',
        'phase3_angel_closeout_validation_20261023_01': 'phase3_angel_closeout_validation_20261023_02',
        'phase3_angel_closeout_20261023_01.json': 'phase3_angel_closeout_20261023_02.json',
        'phase3_angel_release_inspect_20261023_01': 'phase3_angel_release_inspect_20261023_02',
        'phase3_angel_release_20261023_01.zip': 'phase3_angel_release_20261023_02.zip',
        'phase3_angel_acceptance_20261023_01': 'phase3_angel_acceptance_20261023_02',
        'phase3_angel_operator_blockers_20261023_01': 'phase3_angel_operator_blockers_20261023_02',
        '861/861': str(proof['python']['passed'])+'/'+str(proof['python']['executed']),
        '246.873s': seconds+'s',
        '10/10 final integration/control': '11/11 final integration/control',
        'The `_02` run additionally tests the explicitly authorized extended-window option.':
            'The final `_03` run also verifies truthful completed-candle versus scanner diagnostics. '
            'The preserved `_02` run verified861 tests for the extended-window guard; `_01` and `_02` remain historical snapshots.'}
    for old,new in replacements.items():
        report = report.replace(old,new)
    report += ('\nFinal review corrected a diagnostic-only issue: a future probe with valid complete '
               'candles now reports that sub-gate PASS while retaining the separate scanner-consumer '
               'acceptance requirement. It no longer falsely labels that case an insufficient window. '
               'The original real probe, previous closeout/report/release and their hashes are preserved; '
               'no second private probe occurred. Current release/acceptance/closeout names end in `_02`, '
               'and current full-source verification ends in `_03`.\n')
    with (APP/'docs/reports/phase3_angel_completion_20261023_02.md').open('x', encoding='utf-8') as out:
        out.write(report)
    runbook = APP/'docs/TRADEPULSE_OPERATIONS_RUNBOOK.md'
    text = runbook.read_text(encoding='utf-8').replace('master_phase3_angel_20261023_02','master_phase3_angel_20261023_03')
    text += ('\nCurrent Angel handover uses `phase3_angel_acceptance_20261023_02.json`, '
             '`phase3_angel_closeout_validation_20261023_02.json` and '
             '`phase3_angel_release_20261023_02.zip`. Earlier `_01` closeouts/releases '
             'are preserved historical snapshots. The current detailed repository report is '
             '`docs/reports/phase3_angel_completion_20261023_02.md`.\n')
    runbook.write_text(text, encoding='utf-8')
    location = APP/'docs/RELEASE_EVIDENCE_LOCATION.md'
    text = location.read_text(encoding='utf-8')
    for old,new in replacements.items():
        text = text.replace(old,new)
    text += ('\nThe current `_03` full receipt includes the final completed-candle/scanner '
             'diagnostic correction. `_01` and `_02` full receipts and the `_01` '
             'release/closeout remain preserved historical snapshots. Actual private '
             'probe evidence remains `phase3_angel_probe_live_20261023_01.json`.\n')
    location.write_text(text, encoding='utf-8')
    ledger = APP/'docs/TRADEPULSE_EXECUTION_LEDGER.md'
    with ledger.open('a', encoding='utf-8') as out:
        out.write('\nFinal Angel diagnostic review: `master_phase3_angel_20261023_03.json` '
                  'supersedes current-source proof with **'+str(proof['python']['passed'])+
                  '/'+str(proof['python']['executed'])+' Python tests PASS**,11/11Node and68 compiled files. '
                  'Valid complete-candle readiness is reported separately from scanner acceptance. '
                  'Current closeout/release use `_02`; all earlier actual receipts/releases remain '
                  'unchanged. No extra private broker call, longer observation or scheduling occurred.\n')
    print(json.dumps(dict(status='WRITTEN', python=proof['python']['passed'], python_seconds=seconds)))


if __name__ == '__main__':
    main()

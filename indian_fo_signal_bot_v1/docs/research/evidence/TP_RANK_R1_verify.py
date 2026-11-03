"""Isolated R1 audit evidence. Does not alter application code or operational data.

Run from the application directory:
python -B docs/research/evidence/TP_RANK_R1_verify.py
Existing output files are never overwritten. Fixtures are authored, not live proof.
"""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from decimal import Decimal, ROUND_HALF_EVEN
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(APP))
from verify_offline import (offline_network, ExecutionResult, case_ids, python_result,
                            source_snapshot, timestamp, run_node_tests)

MODULES = [
    "test_astra_ranking", "test_astra_rank_history", "test_astra_scan_references",
    "test_market_data_contract", "test_phase4_recommendations",
    "test_phase4_evaluation_storage", "test_cash_lineage", "test_h1_paper_conflicts",
    "test_astra_http_safety", "test_track_a_cold_http",
]


class R1IndependentCalculations(unittest.TestCase):
    def test_quality_decimal_reference_cases_and_missingness(self):
        from strategies import compute_setup_quality_score
        # Independent decimal oracle, with exact inputs away from rounding ties.
        cases = [
            ("launch", "1.65", ".15", "1", {"advances": 3, "declines": 1}, True, 70),
            ("no_breadth", "1.65", ".15", "1", None, True, 65),
            ("short_breadth", "1.65", ".15", "1", {"advances": 3, "declines": 1}, False, 55),
            ("extension", "2.5", "2.25", "2", None, True, 85),
            ("only_volume", "2.5", None, None, None, True, 100),
        ]
        for label, r, d, impulse, breadth, bullish, expected in cases:
            with self.subTest(label=label):
                clamp = lambda x: max(Decimal(0), min(Decimal(1), x))
                vals = [clamp((Decimal(r)-Decimal('.8'))/Decimal('1.7')),
                        None, None, None]
                if d is not None:
                    dist = Decimal(d)
                    vals[1] = (Decimal(0) if dist <= Decimal('-.25') or dist >= Decimal('3.25')
                        else (dist+Decimal('.25'))/Decimal('.4') if dist < Decimal('.15')
                        else Decimal(1) if dist <= Decimal('1.25')
                        else 1-(dist-Decimal('1.25'))/2)
                if impulse is not None:
                    vals[2] = clamp(Decimal(impulse)/2)
                if breadth:
                    aligned = breadth['advances' if bullish else 'declines']
                    vals[3] = clamp((Decimal(aligned)/sum(breadth.values())-Decimal('.25'))/Decimal('.5'))
                weights = list(map(Decimal, ['.30', '.25', '.30', '.15']))
                numerator = sum(v*w for v,w in zip(vals, weights) if v is not None)
                denom = sum(w for v,w in zip(vals, weights) if v is not None)
                independent = int((100*numerator/denom).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
                actual, detail = compute_setup_quality_score(rvol=float(r),
                    vwap_dist_atr=None if d is None else float(d),
                    displacement_atr=None if impulse is None else float(impulse),
                    market_breadth=breadth, is_bullish=bullish)
                self.assertEqual(independent, expected)
                self.assertEqual(actual, independent)
                CALCULATIONS.append(dict(case=label, independent_score=independent,
                    implementation_score=actual, effective_weights=detail['effective_weights']))

    def test_actual_rr_long_short_and_lexicographic_order(self):
        from strategies import signal_risk_reward
        from test_completion_engineering import signal_fixture
        from test_astra_ranking import evaluation
        from opportunity_ranking import build_snapshot
        long = signal_fixture(entry_price=100, stop_loss=98, invalidation_level=98,
                              target_1=104, target_2=106)
        short = signal_fixture(entry_price=100, stop_loss=102, invalidation_level=102,
            target_1=96, target_2=94, direction='BEARISH', position_type='SHORT_EQUITY_INTRADAY')
        self.assertEqual(signal_risk_reward(long)['gross_t1_rr'], (104-100)/(100-98))
        self.assertEqual(signal_risk_reward(short)['gross_t1_rr'], (100-96)/(102-100))
        source = evaluation(tcs=90, infy=89)
        source['candidate_evaluations'][0]['risk_reward']['gross_t1_rr'] = 1.01
        source['candidate_evaluations'][1]['risk_reward']['gross_t1_rr'] = 100
        snap = build_snapshot(source, provider='upstox', as_of='2026-10-16T10:00:05+05:30')
        self.assertEqual([r['symbol'] for r in snap['rows']], ['TCS', 'INFY'])
        CALCULATIONS.append(dict(case='quality_dominates_any_positive_rr', order=['TCS','INFY'],
            components=[r['score_components'] for r in snap['rows']], long_rr=2.0, short_rr=2.0))

    def test_relative_strength_is_not_a_rank_factor(self):
        from test_astra_ranking import evaluation
        from opportunity_ranking import build_snapshot
        source = evaluation(tcs=90, infy=80)
        changed = copy.deepcopy(source)
        for index, row in enumerate(changed['candidate_evaluations']):
            row['relative_strength'] = [-100, 100][index]
        kwargs = dict(provider='upstox', as_of='2026-10-16T10:00:05+05:30')
        one, two = build_snapshot(source, **kwargs), build_snapshot(changed, **kwargs)
        self.assertEqual(one['rows'], two['rows'])
        self.assertEqual(one['rank_version'], two['rank_version'])
        self.assertIn('RELATIVE_STRENGTH', one['rows'][0]['missing_components'])

    def test_quality_missing_features_are_renormalized_not_penalized(self):
        from strategies import compute_setup_quality_score
        full, _ = compute_setup_quality_score(rvol=2.5, vwap_dist_atr=-.25, displacement_atr=0)
        partial, _ = compute_setup_quality_score(rvol=2.5)
        self.assertEqual((full, partial), (35, 100))
        with self.assertRaises(ValueError):
            compute_setup_quality_score()
        CALCULATIONS.append(dict(case='missingness_comparability', full_score=full, volume_only_score=partial))


CALCULATIONS = []


def main():
    os.chdir(APP)
    prefix = Path(__file__).with_name('TP_RANK_R1_20261103_02')
    receipt_path = prefix.with_suffix('.json')
    # Reserve before running: no previous evidence is destroyed.
    receipt_path.open('x', encoding='utf-8').close()
    logfile = prefix.with_suffix('.txt')
    before = source_snapshot()
    started = timestamp()
    unraisable = []
    with logfile.open('x', encoding='utf-8') as stream, redirect_stdout(stream), redirect_stderr(stream), ExitStack() as stack:
        offline_network(stack)
        stack.enter_context(patch('sys.unraisablehook', side_effect=lambda e: unraisable.append(type(e.exc_value).__name__)))
        # Existing test_bot imports config while hiding .env and replacing all
        # literal getenv defaults. It never reads private configuration values.
        import test_bot
        suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(R1IndependentCalculations))
        expected = list(case_ids(suite))
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=ExecutionResult).run(suite)
        python = python_result(result, expected)
    checks = []
    for stem in ('test_terminal_opportunities', 'test_terminal_clock'):
        checks.append(run_node_tests(['node', '--test', '--test-reporter=tap', stem+'.js'],
            prefix.with_name(prefix.name+'_'+stem+'.txt')))
    after = source_snapshot()
    status = ('PASS' if python['exit_code'] == 0 and before == after and not unraisable
              and all(c['exit_code'] == 0 for c in checks) else 'FAIL')
    data = dict(kind='ISOLATED_R1_AUDIT_VERIFICATION', status=status,
        exit_code=0 if status=='PASS' else 1, started_at=started, finished_at=timestamp(),
        base_commit=subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
        command=[sys.executable,'-B','docs/research/evidence/TP_RANK_R1_verify.py'],
        python=python, modules=MODULES, checks=checks, calculations=CALCULATIONS,
        source_before=before, source_after=after, source_unchanged=before==after,
        unraisable_errors=unraisable, runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        python_log_sha256=hashlib.sha256(logfile.read_bytes()).hexdigest(),
        scope='OFFLINE_FIXTURES_ONLY_NO_EMPIRICAL_OR_LIVE_ACCEPTANCE')
    receipt_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(json.dumps(dict(status=status, python_tests=python['executed'], passed=python['passed'],
        failures=python['failures'], errors=python['errors'], skipped=python['skipped'],
        node_checks=checks, source_unchanged=before==after), indent=2))
    raise SystemExit(data['exit_code'])


if __name__ == '__main__':
    main()

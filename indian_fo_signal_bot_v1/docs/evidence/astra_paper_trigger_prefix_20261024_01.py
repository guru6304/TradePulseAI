"""Preserved pre-fix reproduction. Synthetic isolated fixture; no live evidence."""
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import test_bot
from test_phase5b_forward import TestPhase5BForwardPaper

with patch.dict(os.environ, test_bot._test_config_defaults):
    case = TestPhase5BForwardPaper()
    case.setUp()
    try:
        candidate, summary, bar, result = case._consume(open=98, high=99, low=96, close=98)
        report = result["report"]
        evidence = dict(
            fixture_scope="SYNTHETIC_TEST_ONLY_NO_LIVE_OR_EMPIRICAL_CLAIM",
            defect="LONG_FILLED_WITHOUT_REACHING_ENTRY_THRESHOLD",
            original_entry_threshold=candidate.entry_price,
            observed_bar=bar,
            actual_decision=report["candidate_decisions"][0]["status"],
            actual_fill=report["positions"][0]["raw_entry_price"],
            positions=report["accounting"]["open_positions"],
            expected_for_trigger_policy="NO_POSITION",
            reproduction_confirmed=(bar["high"] < candidate.entry_price and report["accounting"]["open_positions"] == 1),
            source_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                           for name in ("forward_paper.py", "paper_portfolio.py")},
        )
        print(json.dumps(evidence, indent=2, sort_keys=True))
    finally:
        case.doCleanups()

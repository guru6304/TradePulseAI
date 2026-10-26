"""Retain source locators and an explicitly synthetic pure ranking demonstration."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from opportunity_ranking import build_snapshot, current_view, digest


def emit(name, value):
    with (APP / "docs/evidence" / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def source(run, watermark, tcs, infy):
    rows = []
    for symbol, quality in (("TCS", tcs), ("INFY", infy)):
        rows.append(dict(candidate_id=run + symbol, symbol=symbol, strategy_id="strat_4_orb_filtered",
            status="QUALIFIED", ranking=dict(qualified=True), explanation=dict(setup_quality=quality),
            risk_reward=dict(allowed=True, gross_t1_rr=2.0), source_reference=dict(run_id=run,
                provider="upstox", data_mode="SIMULATED", candle_timestamps=[watermark],
                candle_digest=digest([symbol, watermark, quality]), instrument_identity=dict(provider="upstox",
                    symbol=symbol, identifier="SYNTHETIC_" + symbol, exchange="NSE", instrument_type="EQ", is_index=False))))
    return dict(run_id=run, actionable=False, data_mode="SIMULATED", candidate_evaluations=rows)


def main():
    names = ("scanner_engine.py", "strategies.py", "strategy_evidence.py", "opportunity_ranking.py",
        "paper_portfolio.py", "forward_paper.py", "candle_lineage.py", "historical_study.py",
        "server.py", "option_execution.py", "storage.py")
    records = {}
    for name in names:
        content = (APP / name).read_bytes()
        tree = ast.parse(content)
        items = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                items.append(dict(symbol=node.name, start=node.lineno, end=node.end_lineno))
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        items.append(dict(symbol=node.name + "." + method.name, start=method.lineno, end=method.end_lineno))
        records[name] = dict(sha256=hashlib.sha256(content).hexdigest(), symbols=items)
    emit("astra_code_locations_20261025_01.json", dict(kind="STATIC_SOURCE_LOCATORS_NOT_EXECUTION",
        recorded_at=datetime.now(timezone.utc).isoformat(), files=records))
    first_input = source("synthetic-r1", "2026-10-16 09:55:00", 90, 80)
    second_input = source("synthetic-r2", "2026-10-16 10:05:00", 85, 95)
    first = build_snapshot(first_input, provider="upstox", as_of="2026-10-16T10:00:05+05:30")
    second = build_snapshot(second_input, provider="upstox", as_of="2026-10-16T10:10:05+05:30", previous=first)
    emit("astra_rank_demo_20261025_01.json", dict(kind="EXECUTED_SYNTHETIC_PURE_FUNCTION_DEMO",
        scope="NO_SCANNER_CONSUMER_PERSISTENCE_LIVE_OR_EMPIRICAL_ACCEPTANCE", provider_requests=0,
        source_sha256=records["opportunity_ranking.py"]["sha256"], inputs=[first_input, second_input],
        snapshots=[first, second], stale_read=current_view(second, "2026-10-16T10:11:01+05:30")))
    print(json.dumps(dict(status="WRITTEN", files=2, scope="STATIC_LOCATORS_AND_SYNTHETIC_DEMO")))


if __name__ == "__main__":
    main()

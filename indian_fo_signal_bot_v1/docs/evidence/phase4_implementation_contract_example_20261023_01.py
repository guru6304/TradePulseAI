"""Execute a labeled offline application-contract example, never a market receipt.

Uses only the independent deterministic fixture and in-memory SQLite. It does
not execute unittest cases or add to their totals. All outputs are new exclusive
evidence artifacts; an existing stage is never overwritten.
"""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import json
from pathlib import Path
import sys
import traceback
import warnings


APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import offline_network, source_snapshot, timestamp


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value, reason):
    if not value:
        raise AssertionError(reason)


def selected_summary(summary):
    fields = ("run_id", "scan_status", "total_signals", "persisted_signals", "duplicate_signals",
              "data_mode", "is_simulated", "actionable", "empty_reason", "ranking_policy",
              "ranking_scope", "evaluation_schema_version", "strategy_evaluations",
              "candidate_evaluations", "signals", "input_lineage", "candle_freshness")
    return {key: summary[key] for key in fields if key in summary}


def main():
    script = Path(__file__).resolve()
    artifact = script.with_suffix(".json")
    log = script.with_suffix(".txt")
    started_at = timestamp()
    before = source_snapshot(APP)
    payload = dict(schema_version="tradepulse.offline-contract-example.v1",
        evidence_scope="OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE", operational_acceptance=False,
        historical_research_acceptance=False, profitability_claim=False,
        purpose="Executed application-contract illustration; not an additional unittest result",
        status="RUNNING", exit_code=None, started_at=started_at,
        command=[sys.executable, "-B", "-W", "error::ResourceWarning",
                 script.relative_to(APP).as_posix()],
        script=script.relative_to(APP).as_posix(), script_sha256=sha256(script),
        source_before=before, cleanup=[], unraisable_errors=[])
    with artifact.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
    try:
        with (log.open("x", encoding="utf-8") as stream,
              redirect_stdout(stream), redirect_stderr(stream),
              ExitStack() as stack):
            offline_network(stack)
            stack.enter_context(warnings.catch_warnings())
            warnings.simplefilter("error", ResourceWarning)
            prior_hook = sys.unraisablehook
            sys.unraisablehook = lambda error: payload["unraisable_errors"].append(type(error.exc_value).__name__)
            stack.callback(setattr, sys, "unraisablehook", prior_hook)
            import test_bot  # established bootstrap forbids loading operator credentials
            from test_phase4_recommendations import TestPhase4IndependentRecommendations
            from server import DashboardRequestHandler

            def scenario(label):
                case = TestPhase4IndependentRecommendations()
                def cleanup():
                    complete = case.doCleanups()
                    payload["cleanup"].append(dict(case=label, completed=bool(complete)))
                    require(complete, "Fixture cleanup failed")
                stack.callback(cleanup)
                case.setUp()
                engine, feed = case.engine()
                require(engine.config.database_url == ":memory:", "Example requires memory-only storage")
                require(engine.config.telegram_dry_run and not engine.config.enable_background_scheduler,
                        "Example requires dry-run and disabled scheduler")
                return engine, feed

            engine, feed = scenario("qualified_and_repeated")
            summary = engine.run_single_scan()
            require(summary["scan_status"] == "COMPLETED" and summary["total_signals"] == 1,
                    "Existing order-block fixture must produce exactly one qualified candidate")
            candidate = summary["candidate_evaluations"][0]
            require(candidate["status"] == "QUALIFIED" and candidate["actionable"] is False,
                    "A qualified fixture candidate never authorizes an order")
            require(summary["signals"][0]["strategy_id"] == "strat_1_order_block",
                    "Example must use the actual existing order-block evaluator")
            retained = engine.store.load_cash_scan(summary["run_id"])
            require(retained["result"]["candidate_evaluations"] == summary["candidate_evaluations"],
                    "Retained candidate explanation mismatch")

            handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
            handler.engine, handler.paper_portfolio = engine, None
            handler.evidence_scope = "OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE"
            signal_code, signal_payload = handler._handle_signals({})
            scan_code, scan_payload = handler._handle_scans({})
            require(signal_code == scan_code == 200, "Existing read handlers must return reconciled results")
            item = signal_payload["items"][0]
            evaluation = scan_payload["items"][0]["evaluation"]
            require(item["candidate_evaluation"] == candidate, "Signal-history candidate mismatch")
            require(evaluation["candidate_evaluations"] == summary["candidate_evaluations"],
                    "Scan-history candidate mismatch")
            require(evaluation["strategy_evaluations"] == summary["strategy_evaluations"],
                    "Scan-history strategy mismatch")
            require(item["actionable"] is False and item["recommendation_status"] == "CANDIDATE_ONLY",
                    "Stored fixture output must remain candidate-only")
            payload["qualified_scan"] = selected_summary(summary)
            payload["existing_route_handlers"] = dict(
                evidence_scope="OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE", operational_acceptance=False,
                signals_status=signal_code, signal_history_item=item,
                scans_status=scan_code, scan_history_evaluation=evaluation,
                signal_candidate_equals_scan_candidate=True,
                scan_evaluation_equals_committed_strategy_and_candidate_lists=True)
            repeated = engine.run_single_scan()
            require(repeated["idempotent_replay"] and repeated["signals"] == [],
                    "Repeat must not emit another candidate signal")
            require(repeated["candidate_evaluations"] == summary["candidate_evaluations"],
                    "Repeat must preserve the original candidate explanation")
            require(engine.store.query_signals()["total_count"] == engine.store.query_scan_runs()["total_count"] == 1,
                    "Repeat must preserve exactly one signal and scan")
            payload["idempotent_repeat"] = dict(
                idempotent_replay=True, emitted_signals=repeated["signals"],
                total_signals=repeated["total_signals"], same_candidate_evaluations=True,
                same_strategy_evaluations=(repeated["strategy_evaluations"] == summary["strategy_evaluations"]),
                stored_signal_count=1, stored_scan_count=1,
                recovery_scope=repeated["recovery_scope"], candle_freshness=repeated["candle_freshness"])

            empty_engine, empty_feed = scenario("insufficient_warmup")
            empty_feed.rows = empty_feed.rows[-21:]
            empty = empty_engine.run_single_scan()
            require(empty["scan_status"] == "COMPLETED_EMPTY" and empty["total_signals"] == 0,
                    "Insufficient completed history must be a true empty result")
            require(empty["candidate_evaluations"] == [] and empty_engine.store.query_signals()["total_count"] == 0,
                    "Warm-up example cannot store or rank a candidate")
            by_strategy = {row["strategy_id"]: row for row in empty["strategy_evaluations"]}
            for strategy in ("strat_1_order_block", "strat_5_supertrend_pullback"):
                require(by_strategy[strategy]["status"] == "UNAVAILABLE"
                        and "INSUFFICIENT_COMPLETED_CANDLES" in by_strategy[strategy]["reason_codes"],
                        "Missing history needs a precise unavailable explanation")
            payload["insufficient_warmup_scan"] = selected_summary(empty)
            payload["safety"] = dict(database="MEMORY_ONLY", execution_mode="PAPER_ONLY",
                telegram_dry_run=True, scheduler_enabled=False, provider_requests=False,
                orders_or_account_mutations=False, external_messages=False,
                routes="EXISTING_HANDLERS_NO_LISTENING_SOCKET",
                nested_live_mode_note="LIVE labels exercise the existing validation contract with explicit offline fixtures")
            print("Executed qualified, repeated, route-reconciled and insufficient-warmup examples.")
        require(not payload["unraisable_errors"], "Unraisable error recorded")
        require(payload["cleanup"] and all(row["completed"] for row in payload["cleanup"]), "Cleanup incomplete")
        payload.update(status="PASS", exit_code=0)
    except Exception as error:
        payload.update(status="FAIL", exit_code=1, failure_type=type(error).__name__)
        if log.exists():
            with log.open("a", encoding="utf-8") as stream:
                traceback.print_exception(error, file=stream)
    payload.update(completed_at=timestamp(), source_after=source_snapshot(APP),
                   log=log.relative_to(APP).as_posix(), log_sha256=sha256(log) if log.exists() else None)
    payload["source_unchanged"] = payload["source_before"] == payload["source_after"]
    if not payload["source_unchanged"]:
        payload.update(status="FAIL", exit_code=1, failure_type="SOURCE_CHANGED_DURING_EXAMPLE")
    artifact.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(dict(status=payload["status"], exit_code=payload["exit_code"],
        artifact=artifact.relative_to(APP).as_posix(), artifact_sha256=sha256(artifact),
        script_sha256=payload["script_sha256"], source_unchanged=payload["source_unchanged"],
        evidence_scope=payload["evidence_scope"], operational_acceptance=False)))
    return payload["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

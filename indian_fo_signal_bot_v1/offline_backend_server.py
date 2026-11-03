"""Disposable Offline Backend Server for Real Browser Acceptance (U2-B).

Serves canonical API endpoints using DashboardRequestHandler from server.py,
with verified offline fixtures (no live broker, no operational DB mutation,
zero external network calls, zero order generation).
"""
import sys
import os
import threading
from unittest.mock import Mock, patch
from contextlib import ExitStack

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)
os.chdir(CURRENT_DIR)

import server
from verify_offline import offline_network

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

guards = ExitStack()
offline_network(guards)
guards.enter_context(patch("candle_lineage.annotate_signals", side_effect=lambda store, items, account_id=None: None))
guards.enter_context(patch.object(server, "configure_server_runtime", side_effect=AssertionError("Loopback fixture reached forbidden production runtime configuration")))

engine = Mock(spec=[
    "config", "store", "get_broker_status", "run_single_scan", "_now_ist", "last_scan_summary", "paper_portfolio",
])
engine._now_ist.return_value = "2026-11-03T10:00:00+05:30"
engine.last_scan_summary = {
    "run_id": "run-20261103-0915",
    "scan_status": "COMPLETED",
    "started_at_ist": "2026-11-03T09:15:00+05:30",
    "completed_at_ist": "2026-11-03T09:15:05+05:30",
    "duration_ms": 5000,
    "total_signals": 3,
    "persistence_status": "COMMITTED",
}
engine.config = Mock()
engine.config.active_broker = "paper_sim"
engine.config.equity_watchlist = [{"symbol": "RELIANCE"}, {"symbol": "TCS"}, {"symbol": "INFY"}]
engine.config.to_safe_dict.return_value = {
    "mode": "DISPOSABLE_BROWSER_ACCEPTANCE",
    "trading_allowed": False,
    "execution_mode": "SIMULATED",
    "broker": "paper_sim",
}

engine.get_broker_status.return_value = {
    "active_broker": "paper_sim",
    "broker_name": "Paper Simulation Engine",
    "connection_state": "SIMULATED",
    "is_simulated": True,
    "data_mode": "SIMULATED",
    "connectivity_verified": True,
    "last_verified_at_ist": "2026-11-03T09:15:00+05:30",
    "last_candle_timestamp_ist": "2026-11-03T09:15:00+05:30",
    "candle_freshness": {"status": "CURRENT"},
    "live_signals_allowed": False,
    "error_category": "NONE",
    "stream": {"status": "LIVE"},
}

store = Mock()
store.check_health.return_value = {"status": "ok"}
store.pending_cash_scans.return_value = []
store.list_notification_outbox.return_value = {"counts": {}}
store.query_oi_snapshots.return_value = {"items": [], "total_count": 0, "limit": 10, "offset": 0}
store.list_scans.return_value = {"items": [], "total_count": 0, "limit": 10, "offset": 0}
store.query_scan_runs.return_value = {"items": [], "total_count": 0, "limit": 20, "offset": 0}
store.query_backtest_runs.return_value = {"items": [], "total_count": 0, "limit": 10, "offset": 0}
store.query_historical_datasets.return_value = {"items": [], "total_count": 0, "limit": 10, "offset": 0}

# Create 25 synthetic qualified ranking candidates to test pagination and prior rank
dummy_sha = "c" * 64
scope = {
    "provider": "paper_sim",
    "data_mode": "SIMULATED",
    "segment": "NSE_EQUITY_INTRADAY",
    "profile_digest": dummy_sha,
}

candidates_info = [
    ("RELIANCE", 2885, 1, 3, "SCORE_COMPONENT_CHANGED", 92, 2.34, "strat_1_order_block", "LONG"),
    ("TCS", 11536, 2, None, "NEWLY_QUALIFIED", 88, 1.95, "strat_2_vwap_pullback", "LONG"),
    ("INFY", 1594, 3, 2, "RELATIVE_ORDER_CHANGED", 85, 1.80, "strat_4_orb_filtered", "SHORT"),
]
for i in range(4, 26):
    candidates_info.append((
        f"SYM{i}", 2000 + i, i, i - 1 if i % 2 == 0 else None,
        "UNCHANGED_PRIORITY" if i % 2 == 0 else "NEWLY_QUALIFIED",
        max(60, 95 - i), round(max(1.1, 2.5 - (i * 0.05)), 2),
        "strat_1_order_block" if i % 2 == 0 else "strat_2_vwap_pullback",
        "LONG" if i % 3 != 0 else "SHORT",
    ))

ranking_rows = []
for sym, ident, rk, prior, rsn, qual, rr, strat, dirn in candidates_info:
    ranking_rows.append({
        "opportunity_key": f"opp-{sym.lower()}-{ident}",
        "candidate_id": f"cand-{sym.lower()}-{ident}",
        "symbol": sym,
        "strategy_id": strat,
        "position_type": "LONG_EQUITY_INTRADAY" if dirn == "LONG" else "SHORT_EQUITY_INTRADAY",
        "direction": dirn,
        "source_data_watermark": "2026-11-03T09:15:00+05:30",
        "source_digest": dummy_sha,
        "priority_scope": "QUALIFIED_SCANNER_CANDIDATE_ONLY",
        "instrument_identity": {
            "provider": "paper_sim",
            "identifier": str(ident),
            "symbol": sym,
            "exchange": "NSE",
            "segment": "NSE_EQUITY_INTRADAY",
            "instrument_type": "EQ",
            "is_index": False,
        },
        "score_components": {
            "rule_quality": qual,
            "actual_target1_rr": rr,
        },
        "component_versions": {
            "rule_quality": "EXISTING_EVALUATOR_V1",
            "actual_target1_rr": "PRICE_LEVEL_GEOMETRY_V1",
        },
        "missing_components": ["RELATIVE_STRENGTH", "SECTOR", "REGIME", "LIQUIDITY_DEPTH", "OBSERVED_SPREAD", "NET_EXECUTABLE_REWARD", "EMPIRICAL_EDGE"],
        "rank": rk,
        "previous_rank": prior,
        "rank_change_reason": rsn,
        "component_changes": {},
        "actionable": False,
    })

snapshot_meta = {
    "policy": "CASH_QUALITY_ACTUAL_RR_DIRECTION_ONE_SYMBOL_V2",
    "rank_version": dummy_sha,
    "previous_rank_version": "b" * 64,
    "valid_until": "2026-11-03T10:30:00+05:30",
    "evidence_scope": "LOCAL_OFFLINE_FIXTURE",
    "run_id": "run-20261103-0915",
    "work_id": "work-20261103-0915",
    "reference": "2026-11-03T09:15:00+05:30",
    "scope": scope,
    "previous_snapshot": {
        "run_id": "run-20261103-0910",
        "work_id": "work-20261103-0910",
        "rank_version": "b" * 64,
        "previous_rank_version": None,
        "as_of": "2026-11-03T09:10:00+05:30",
        "actionable": False,
    },
    "source_authenticity": "NOT_ESTABLISHED",
    "source_data_watermarks": ["2026-11-03T09:15:00+05:30"],
    "source_data_watermark_count": 1,
    "exclusions": [],
    "exclusion_count": 0,
    "removals": [],
    "removal_count": 0,
    "metadata_preview_limit": 100,
    "exclusions_truncated": False,
    "removals_truncated": False,
    "source_data_watermarks_truncated": False,
}

def custom_read_current(store_inst, config_inst, read_clock, run_id=None, limit=20, offset=0):
    page_rows = ranking_rows[offset:offset + limit]
    return {
        "status": "CURRENT_CANDIDATE_PRIORITY",
        "actionable": False,
        "scope": scope,
        "as_of": read_clock,
        "current_rows": page_rows,
        "historical_rows": page_rows,
        "pagination": {
            "offset": offset,
            "limit": limit,
            "total": len(ranking_rows),
        },
        "snapshot": snapshot_meta,
    }

# Patch rank_history.read_current
guards.enter_context(patch("rank_history.read_current", side_effect=custom_read_current))

store.query_signals.return_value = {
    "total_count": 1,
    "limit": 50,
    "offset": 0,
    "items": [{
        "id": 1,
        "dedup_key": "cand-reliance-2885",
        "symbol": "RELIANCE",
        "segment": "NSE_EQUITY_INTRADAY",
        "strategy_id": "strat_1_order_block",
        "strategy_name": "Order Block / BOS / FVG",
        "direction": "LONG",
        "position_type": "LONG_EQUITY_INTRADAY",
        "entry_price": 2845.5,
        "entry_zone_low": 2820.0,
        "entry_zone_high": 2845.5,
        "stop_loss": 2800.0,
        "invalidation_level": 2795.0,
        "target_1": 2900.0,
        "target_2": 2950.0,
        "timestamp": "2026-11-03T09:15:00+05:30",
        "actionable": False,
        "instrument_identity": {
            "provider": "paper_sim",
            "identifier": "2885",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "segment": "NSE_EQUITY_INTRADAY",
            "instrument_type": "EQ",
            "is_index": False,
        },
        "paper_decision": {
            "status": "REJECTED",
            "reason_code": "CONFLICTING_OPEN_POSITION",
            "position_id": "pos-opp-991",
            "account_id": "paper_sim_default",
            "candidate_id": "cand-reliance-2885",
            "trigger_contract": "SIMULATED_REJECTION_ONLY",
            "trigger_timestamp_ist": "2026-11-03T09:15:01+05:30",
        },
        "recommendation_status": "PAPER_REJECTED",
    }],
}

store.query_paper_accounts.return_value = {
    "status": "ok",
    "execution_mode": "SIMULATED",
    "accounts": [{
        "account_id": "paper_sim_default",
        "config_hash": "a" * 64,
        "created_at_ist": "2026-11-03T09:00:00+05:30",
        "execution_mode": "SIMULATED",
    }],
    "next_cursor": None,
    "through_sequence": 1,
    "truncated": False,
}

store.get_paper_portfolio_report.return_value = {
    "status": "OK",
    "account_id": "paper_sim_default",
    "run_id": "run-20261103-0915",
    "config_hash": "a" * 64,
    "provider": "paper_sim",
    "source_data_mode": "SIMULATED",
    "execution_mode": "SIMULATED",
    "fill_policy": "NEXT_BAR_OPEN",
    "as_of_ist": "2026-11-03T10:00:00+05:30",
    "reconciliation": {"status": "OK", "errors": []},
    "accounting": {
        "starting_capital_inr": 1000000,
        "realized_net_pnl_inr": 12500,
        "unrealized_net_pnl_inr": 3200,
        "equity_inr": 1015700,
        "reserved_capital_inr": 200000,
        "available_capital_inr": 815700,
        "gross_exposure_inr": 200000,
        "fees_paid_inr": 120,
        "slippage_paid_inr": 80,
        "open_positions": 1,
        "closed_positions": 2,
    },
    "positions": [{
        "position_id": "pos-reliance-01",
        "symbol": "RELIANCE",
        "direction": "LONG",
        "quantity": 70,
        "entry_price": 2840.0,
        "current_price": 2845.5,
        "unrealized_pnl_inr": 385.0,
        "status": "OPEN",
    }],
    "events": [],
    "candidate_decisions": [],
    "total_positions": 1,
    "total_events": 2,
    "total_candidate_decisions": 3,
    "previews_truncated": {
        "positions": False,
        "events": False,
        "candidate_decisions": False,
    },
}

store.load_cash_scan.return_value = {
    "run_id": "run-20261103-0915",
    "status": "COMMITTED",
    "snapshot": {
        "work_id": "work-20261103-0915",
        "version": "v1",
        "reference": "2026-11-03T09:15:00+05:30",
        "code_digest": dummy_sha,
        "profile_digest": dummy_sha,
        "batches": [{
            "batch_id": "batch-reliance-001",
            "validation": {},
            "retrieved_at": "2026-11-03T09:15:05+05:30",
            "source_observation_at": None,
            "content": {
                "identity": {
                    "provider": "paper_sim",
                    "identifier": "2885",
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "segment": "NSE_EQUITY_INTRADAY",
                    "instrument_type": "EQ",
                    "is_index": False,
                },
                "candles": [
                    {"timestamp": "2026-11-03T09:00:00+05:30", "open": 2830, "high": 2842, "low": 2825, "close": 2838, "volume": 12500, "interval_min": 5, "is_complete": True},
                    {"timestamp": "2026-11-03T09:05:00+05:30", "open": 2838, "high": 2845, "low": 2832, "close": 2840, "volume": 15000, "interval_min": 5, "is_complete": True},
                    {"timestamp": "2026-11-03T09:10:00+05:30", "open": 2840, "high": 2850, "low": 2836, "close": 2844, "volume": 18000, "interval_min": 5, "is_complete": True},
                    {"timestamp": "2026-11-03T09:15:00+05:30", "open": 2844, "high": 2852, "low": 2841, "close": 2845.5, "volume": 24000, "interval_min": 5, "is_complete": True},
                ],
            },
        }],
    },
}

engine.store = store

scheduler = Mock(spec=["get_status"])
scheduler.get_status.return_value = {
    "running": True,
    "enabled_in_config": True,
    "session_open": True,
    "session_state": "OPEN",
    "session_start_ist": "09:15",
    "session_end_ist": "15:30",
    "scan_interval_seconds": 300,
    "cycles_executed": 4,
    "configured_holidays": [],
}

paper_mock = Mock()
paper_mock.config.account_id = "paper_sim_default"
engine.paper_portfolio = paper_mock

def ensure_initialized(handler):
    type(handler).engine = engine
    type(handler).scheduler = scheduler
    type(handler).paper_portfolio = paper_mock

handler = type("AcceptanceTestHandler", (server.DashboardRequestHandler,), {
    "engine": None,
    "scheduler": None,
    "paper_portfolio": paper_mock,
    "_ensure_initialized": ensure_initialized,
    "log_message": lambda *args: None,
})

httpd = server.create_http_server("127.0.0.1", port, handler)
print(f"READY {httpd.server_port}", flush=True)

try:
    httpd.serve_forever()
finally:
    guards.close()

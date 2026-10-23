import json
import logging
import os
import threading
import urllib.parse
import ipaddress
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

from config import BotConfig, ConfigValidationError
from brokers import BrokerDataError
from scanner_engine import IntradayBotEngine, MarketScanScheduler
from storage import PersistenceError, PersistenceValidationError

logger = logging.getLogger("tradepulse.api")

_SERVER_INIT_LOCK = threading.Lock()
PROJECT_ROOT = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_WEB_DIR = os.path.realpath(os.path.join(PROJECT_ROOT, "public"))

# Configure standard-library ThreadingHTTPServer for concurrent browser Promise.all() bursts
ThreadingHTTPServer.daemon_threads = True
ThreadingHTTPServer.allow_reuse_address = True
ThreadingHTTPServer.request_queue_size = 64


class TradePulseThreadingHTTPServer(ThreadingHTTPServer):
    """
    Multi-threaded HTTP server based on Python's standard-library `ThreadingHTTPServer`.
    - Spawns daemon worker threads per request so concurrent browser `Promise.all()` calls
      (`/api/health`, `/api/config`, `/api/signals`, `/api/scans`, `/api/oi-snapshots`, `/api/oi-baselines`)
      never block behind one another or behind an active `/api/scan` request.
    - Expands the TCP listen backlog (`request_queue_size = 64`) so simultaneous connections
      from Chrome/Edge on Windows never hit `WSAECONNREFUSED` (`Failed to fetch`).
    """
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


APPROVED_PUBLIC_CONTENT_TYPES: Dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _parse_int_param(
    query_params: Dict[str, list],
    name: str,
    default: int,
    min_val: int,
    max_val: int,
) -> int:
    raw_list = query_params.get(name)
    if not raw_list or raw_list[0] == "":
        return default
    try:
        val = int(raw_list[0])
    except ValueError as exc:
        raise ValueError(f"Query parameter '{name}' must be an integer, got {raw_list[0]!r}.") from exc
    if val < min_val or val > max_val:
        raise ValueError(f"Query parameter '{name}' must be between {min_val} and {max_val}, got {val}.")
    return val


def _get_str_param(query_params: Dict[str, list], name: str) -> Optional[str]:
    raw_list = query_params.get(name)
    if not raw_list or not raw_list[0].strip():
        return None
    return raw_list[0].strip()


class DashboardRequestHandler(BaseHTTPRequestHandler):
    """
    Phase 1D/1E/1F/2B Secure HTTP API & Locked-Down Public Dashboard Handler:
    - Inherits from `BaseHTTPRequestHandler` (NEVER `SimpleHTTPRequestHandler`) so unrestricted
      project-directory file serving is completely eliminated.
    - Never serves `.env`, Python source files (`.py`), SQLite database files (`.db`, `.sqlite`),
      configuration files, markdown reports, or path-traversal targets.
    - Only serves explicitly approved static assets located inside `<project_root>/public/`
      (such as `public/index.html`) when the resolved realpath is strictly inside `public/`
      with an approved static asset extension and no dotfiles. Otherwise returns a safe JSON 404.
    - Exposes documented API endpoints:
      * GET  /api/health       (and /api/v1/health)
      * GET  /api/scan         (and /api/v1/scan)
      * POST /api/scan         (and /api/v1/scan)
      * GET  /api/signals      (and /api/v1/signals)
      * GET  /api/scans        (and /api/v1/scans)
      * GET  /api/oi-snapshots (and /api/v1/oi-snapshots)
      * GET  /api/oi-baselines (and /api/v1/oi-baselines)
      * GET  /api/config       (and /api/v1/config)
    """
    engine: Optional[IntradayBotEngine] = None
    scheduler: Optional[MarketScanScheduler] = None
    paper_portfolio = None  # Explicit operator/test injection, never created by a GET.
    evidence_scope = None

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def _ensure_initialized(self) -> None:
        if self.engine is not None and self.scheduler is not None:
            return
        configure_server_runtime()

    def _send_json(self, status_code: int, payload: Dict[str, Any], send_body: bool = True) -> None:
        if self.evidence_scope:
            payload = dict(payload, evidence_scope=self.evidence_scope)
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
            self.end_headers()
            if send_body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("Client disconnected before JSON response completed.")

    def _try_serve_approved_public_asset(self, raw_path: str, send_body: bool = True) -> bool:
        """
        Serves an explicitly approved static file from `<project_root>/public/` ONLY if:
        1. `<project_root>/public/` exists as a real directory.
        2. The URL-decoded path contains no null bytes, no backslashes, no '..' segments,
           and no dotfile segments (e.g., '.env', '.git').
        3. The file's realpath is strictly inside `<project_root>/public/` and has an
           allowlisted public extension (`.html`, `.css`, `.js`, `.svg`, `.png`, `.ico`).
        Returns False for all other paths so the caller emits a safe 404 JSON response.
        """
        if not os.path.isdir(PUBLIC_WEB_DIR):
            return False

        unquoted = urllib.parse.unquote(raw_path or "")
        if "\x00" in unquoted or "\\" in unquoted:
            return False

        rel_route = "index.html" if unquoted in ("", "/") else unquoted.lstrip("/")
        if rel_route.startswith("public/"):
            rel_route = rel_route[len("public/"):]
        if not rel_route:
            rel_route = "index.html"

        segments = [seg for seg in rel_route.split("/") if seg]
        if not segments:
            return False
        for seg in segments:
            if seg in (".", "..") or seg.startswith("."):
                return False

        _, ext = os.path.splitext(segments[-1])
        content_type = APPROVED_PUBLIC_CONTENT_TYPES.get(ext.lower())
        if content_type is None:
            return False

        candidate = os.path.realpath(os.path.join(PUBLIC_WEB_DIR, *segments))
        try:
            if os.path.commonpath([PUBLIC_WEB_DIR, candidate]) != PUBLIC_WEB_DIR:
                return False
        except ValueError:
            return False

        if not os.path.isfile(candidate):
            return False

        try:
            with open(candidate, "rb") as f:
                data = f.read()
        except OSError:
            return False

        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if send_body:
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("Client disconnected before static asset transfer completed.")
        return True

    def _handle_health(self) -> Tuple[int, Dict[str, Any]]:
        assert self.engine is not None and self.scheduler is not None
        broker_info = self.engine.get_broker_status()
        sched_info = self.scheduler.get_status()
        db_info: Dict[str, Any]
        http_code = 200

        if self.engine.store is not None:
            try:
                db_info = self.engine.store.check_health()
                if db_info.get("status") not in ("ok", "OK", "HEALTHY"):
                    http_code = 503
            except Exception:
                db_info = {"status": "ERROR", "reason_code": "STORAGE_HEALTH_UNAVAILABLE"}
                http_code = 503
        else:
            required = bool(getattr(self.engine.config, "enable_persistence", False))
            db_info = {"status": "ERROR" if required else "DISABLED"}
            if required:
                http_code = 503

        last_scan = None
        if self.engine.last_scan_summary is not None:
            s = self.engine.last_scan_summary
            last_scan = {
                "run_id": s.get("run_id"),
                "scan_status": s.get("scan_status"),
                "started_at_ist": s.get("started_at_ist"),
                "completed_at_ist": s.get("completed_at_ist"),
                "duration_ms": s.get("duration_ms"),
                "total_signals": s.get("total_signals"),
                "persistence_status": s.get("persistence_status"),
                "empty_reason": s.get("empty_reason"),
                "reason_code": s.get("reason_code"),
                "input_lineage": s.get("input_lineage"),
            }

        operations = dict(scope="LOCAL_OPERATIONAL_OBSERVATIONS", alerts=[], real_delivery_enabled=False)
        if self.engine.store is not None and http_code == 200:
            try:
                pending = self.engine.store.pending_cash_scans(limit=200)
                outbox = self.engine.store.list_notification_outbox(limit=1)
                operations.update(pending_cash_preview_count=len(pending), pending_cash_preview_limit=200,
                                  notification_counts=outbox["counts"])
                if pending:
                    operations["alerts"].append("PENDING_CASH_RECOVERY_REQUIRED")
                if any(outbox["counts"].get(state, 0) for state in ("PENDING", "RETRY", "DEAD")):
                    operations["alerts"].append("NOTIFICATION_PREVIEW_REQUIRES_ATTENTION")
                if self.paper_portfolio:
                    report = self.engine.store.get_paper_portfolio_report(self.paper_portfolio.config.account_id,
                                                                        as_of=self.engine._now_ist())
                    operations["paper_reconciliation"] = report.get("reconciliation", {}).get("status", "UNKNOWN")
                    if operations["paper_reconciliation"] != "OK":
                        operations["alerts"].append("PAPER_RECONCILIATION_REQUIRED")
                        http_code = 503
            except Exception:
                operations["alerts"].append("OPERATIONAL_STORAGE_REQUIRES_INSPECTION")
                http_code = 503
        if last_scan and last_scan.get("scan_status") == "FAILED":
            operations["alerts"].append("LAST_SCAN_FAILED")
        if broker_info.get("candle_freshness", {}).get("status") == "STALE":
            operations["alerts"].append("STALE_PROVIDER_CANDLES")
        if broker_info.get("error_category") not in (None, "NONE", "SIMULATED"):
            operations["alerts"].append("PROVIDER_REQUIRES_ATTENTION")
        stream = broker_info.get("stream")
        if stream and stream.get("status") not in ("NOT_STARTED", "LIVE"):
            operations["alerts"].append("STREAM_" + str(stream.get("status", "UNAVAILABLE")))
        overall_status = "ok" if (http_code == 200 and broker_info["connection_state"] != "INVALID_CONFIG"
                                  and not operations["alerts"]) else "degraded"
        from readiness_policy import live_acceptance
        symbols = [str(m["symbol"]).upper() for m in self.engine.config.equity_watchlist]
        clock = getattr(self.engine, "clock", None)
        now = clock() if callable(clock) else None
        acceptance = {s: live_acceptance(self.engine.config, self.engine.store,
                                         self.engine.config.active_broker, s, now) for s in symbols}
        return http_code, {
            "status": overall_status,
            "broker": broker_info,
            "database": db_info,
            "scheduler": sched_info,
            "last_scan": last_scan,
            "paper_account_id": self.paper_portfolio.config.account_id if self.paper_portfolio else None,
            "operations": operations,
            "live_acceptance": {"accepted": bool(symbols) and all(r["accepted"] for r in acceptance.values()),
                                "by_symbol": acceptance},
        }

    def _handle_scan(self) -> Tuple[int, Dict[str, Any]]:
        assert self.engine is not None
        try:
            data = (self.engine.run_single_scan(paper_portfolio=self.paper_portfolio) if self.paper_portfolio
                    else self.engine.run_single_scan())
            if data.get("scan_status") == "SKIPPED_OVERLAP":
                return 409, data
            return 200, data
        except ConfigValidationError as exc:
            logger.error("Scan rejected due to invalid configuration: %s", exc)
            return 400, {
                "status": "error",
                "error_type": "ConfigValidationError",
                "message": str(exc),
            }
        except BrokerDataError as exc:
            logger.error("Scan failed due to BrokerDataError: %s", exc)
            return 502, {
                "status": "error",
                "scan_status": "FAILED",
                "error_type": "BrokerDataError",
                "message": str(exc),
                "is_simulated": False,
                "data_mode": "LIVE",
                "freshness": getattr(exc, "freshness", None),
                "identity_rejection": getattr(exc, "rejection", None),
                "reason_code": getattr(exc, "rejection", getattr(exc, "freshness", {})).get("reason_code", "PROVIDER_ERROR"),
            }
        except (PersistenceError, PersistenceValidationError):
            return 503, {"status": "error", "scan_status": "FAILED", "reason_code": "PERSISTENCE_REQUIRES_RECOVERY",
                         "message": "Required persistence failed; inspect retained pending work.", "total_signals": 0}
        except Exception as exc:
            logger.error("Unexpected internal error during scan: %s", exc)
            return 500, {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": "Internal server error during scan execution.",
            }

    def _handle_signals(self, query_params: Dict[str, list]) -> Tuple[int, Dict[str, Any]]:
        assert self.engine is not None
        if self.engine.store is None:
            return 503, {
                "status": "error",
                "error_type": "PersistenceDisabledError",
                "message": "Signal persistence is currently disabled.",
            }
        try:
            limit = _parse_int_param(query_params, "limit", default=50, min_val=1, max_val=200)
            offset = _parse_int_param(query_params, "offset", default=0, min_val=0, max_val=100000)
            res = self.engine.store.query_signals(
                limit=limit,
                offset=offset,
                symbol=_get_str_param(query_params, "symbol"),
                segment=_get_str_param(query_params, "segment"),
                strategy_id=_get_str_param(query_params, "strategy_id"),
                direction=_get_str_param(query_params, "direction"),
                data_mode=_get_str_param(query_params, "data_mode"),
                provider=_get_str_param(query_params, "provider"),
                state_context=_get_str_param(query_params, "state_context"),
                start_time=_get_str_param(query_params, "start_time"),
                end_time=_get_str_param(query_params, "end_time"),
            )
            from candle_lineage import annotate_signals
            try:
                if self.paper_portfolio:
                    paper = self.engine.store.get_paper_portfolio_report(self.paper_portfolio.config.account_id,
                                                                        as_of=self.engine._now_ist())
                    if paper.get("reconciliation", {}).get("status") not in (None, "OK"):
                        raise PersistenceValidationError("PAPER_RECONCILIATION_REQUIRED")
                annotate_signals(self.engine.store, res["items"],
                                 self.paper_portfolio.config.account_id if self.paper_portfolio else None)
            except Exception:
                return 503, {"status": "RECONCILIATION_REQUIRED", "message": "Stored signal lineage requires inspection."}
            if self.evidence_scope:
                for item in res["items"]:
                    item["evidence_scope"] = self.evidence_scope
            return 200, {"status": "ok", **res}
        except PersistenceValidationError:
            return 503, {"status": "RECONCILIATION_REQUIRED", "message": "Stored signal lineage requires inspection."}
        except ValueError as exc:
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": str(exc),
            }
        except PersistenceError as exc:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": str(exc),
            }

    def _handle_scans(self, query_params: Dict[str, list]) -> Tuple[int, Dict[str, Any]]:
        assert self.engine is not None
        if self.engine.store is None:
            return 503, {
                "status": "error",
                "error_type": "PersistenceDisabledError",
                "message": "Scan-run persistence is currently disabled.",
            }
        try:
            limit = _parse_int_param(query_params, "limit", default=20, min_val=1, max_val=200)
            offset = _parse_int_param(query_params, "offset", default=0, min_val=0, max_val=100000)
            status_filter = _get_str_param(query_params, "status")
            res = self.engine.store.query_scan_runs(limit=limit, offset=offset, status=status_filter)
            return 200, {"status": "ok", **res}
        except ValueError as exc:
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": str(exc),
            }
        except PersistenceError as exc:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": str(exc),
            }

    def _handle_cash_lineage(self, query, *, candles=False):
        """Inspect immutable accepted inputs; never acquire, resume or mutate."""
        if self.engine.store is None:
            return 503, {"status": "error", "message": "Required storage unavailable."}
        try:
            allowed = {"run_id", "batch_id", "limit", "offset"} if candles else {"run_id"}
            if set(query)-allowed or any(len(v) != 1 for v in query.values()):
                raise ValueError()
            run_id = _get_str_param(query, "run_id")
            if not run_id or len(run_id) > 160:
                raise ValueError()
            from candle_lineage import public_summary
            work = self.engine.store.load_cash_scan(run_id)
            if not candles:
                return 200, public_summary(work)
            batch = next((b for b in work["snapshot"]["batches"] if b["batch_id"] == _get_str_param(query,"batch_id")), None)
            if batch is None:
                return 404, {"status": "NOT_FOUND"}
            limit = _parse_int_param(query, "limit", 100, 1, 200)
            offset = _parse_int_param(query, "offset", 0, 0, 25000)
            rows = batch["content"]["candles"]
            return 200, dict(status="ok", run_id=run_id, batch_id=batch["batch_id"],
                             total_count=len(rows), limit=limit, offset=offset, items=rows[offset:offset+limit])
        except PersistenceValidationError as exc:
            return (404 if str(exc)=="LINEAGE_SCAN_NOT_FOUND" else 503), {
                "status": "RECONCILIATION_REQUIRED", "message": "Retained cash input is unavailable or inconsistent."}
        except ValueError:
            return 400, {"status": "error", "message": "Invalid cash-lineage query."}
        except Exception:
            return 503, {"status": "error", "message": "Cash lineage storage unavailable."}

    def _handle_oi_snapshots(self, query_params: Dict[str, list]) -> Tuple[int, Dict[str, Any]]:
        assert self.engine is not None
        if self.engine.store is None:
            return 503, {
                "status": "error",
                "error_type": "PersistenceDisabledError",
                "message": "OI snapshot persistence is currently disabled.",
            }
        try:
            limit = _parse_int_param(query_params, "limit", default=20, min_val=1, max_val=100)
            offset = _parse_int_param(query_params, "offset", default=0, min_val=0, max_val=100000)
            res = self.engine.store.query_oi_snapshots(
                index_symbol=_get_str_param(query_params, "index_symbol"),
                expiry=_get_str_param(query_params, "expiry"),
                data_mode=_get_str_param(query_params, "data_mode"),
                limit=limit,
                offset=offset,
            )
            return 200, {"status": "ok", **res}
        except ValueError as exc:
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": str(exc),
            }
        except PersistenceError as exc:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": str(exc),
            }

    def _handle_oi_baselines(self, query_params: Dict[str, list]) -> Tuple[int, Dict[str, Any]]:
        assert self.engine is not None
        if self.engine.store is None:
            return 503, {
                "status": "error",
                "error_type": "PersistenceDisabledError",
                "message": "OI baseline persistence is currently disabled.",
            }
        try:
            limit = _parse_int_param(query_params, "limit", default=100, min_val=1, max_val=500)
            offset = _parse_int_param(query_params, "offset", default=0, min_val=0, max_val=100000)
            res = self.engine.store.query_oi_baselines(
                index_symbol=_get_str_param(query_params, "index_symbol"),
                expiry=_get_str_param(query_params, "expiry"),
                session_date=_get_str_param(query_params, "session_date"),
                data_mode=_get_str_param(query_params, "data_mode"),
                baseline_kind=_get_str_param(query_params, "baseline_kind"),
                limit=limit,
                offset=offset,
            )
            return 200, {"status": "ok", **res}
        except ValueError as exc:
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": str(exc),
            }
        except PersistenceError as exc:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": str(exc),
            }

    @staticmethod
    def _get_query_param(
        query_params: Dict[str, Any], key: str, default: Optional[str] = None
    ) -> Optional[str]:
        vals = query_params.get(key)
        if not vals:
            return default
        return vals[0]

    def _handle_historical_datasets(self, query_params: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        engine = self.engine
        assert engine is not None
        if engine.store is None:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": "Database persistence is disabled.",
            }
        try:
            limit = int(self._get_query_param(query_params, "limit", "50") or "50")
            offset = int(self._get_query_param(query_params, "offset", "0") or "0")
            symbol = self._get_query_param(query_params, "symbol")
            data_mode = self._get_query_param(query_params, "data_mode")
            provider = self._get_query_param(query_params, "provider")
            quality_status = self._get_query_param(query_params, "quality_status")
            res = engine.store.query_historical_datasets(
                symbol=symbol,
                data_mode=data_mode,
                provider=provider,
                quality_status=quality_status,
                limit=limit,
                offset=offset,
            )
            return 200, {"status": "ok", **res}
        except ValueError as exc:
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": str(exc),
            }
        except PersistenceError as exc:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": str(exc),
            }

    def _handle_historical_readiness(self, query_params: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        from historical_data import evaluate_phase3a_backtest_readiness

        engine = self.engine
        assert engine is not None
        data_mode = (self._get_query_param(query_params, "data_mode", "LIVE") or "LIVE").strip().upper()
        if data_mode not in ("LIVE", "SIMULATED"):
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": "data_mode must be 'LIVE' or 'SIMULATED'.",
            }
        readiness = evaluate_phase3a_backtest_readiness(
            config=engine.config,
            store=engine.store,
            broker_status=engine.get_broker_status(),
            target_data_mode=data_mode,
            provider=self._get_query_param(query_params, "provider", None),
            symbol=self._get_query_param(query_params, "symbol", None),
            strategy_id=self._get_query_param(query_params, "strategy_id", "strat_1_order_block"),
            execution_scope=self._get_query_param(query_params, "execution_scope", None),
            start_date=self._get_query_param(query_params, "evaluation_start_date", None),
            end_date=self._get_query_param(query_params, "evaluation_end_date", None),
            now=engine.clock() if callable(getattr(engine, "clock", None)) else None,
        )
        return 200, {"status": "ok", **readiness}

    def _handle_backtest_eligibility(self, query_params: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        from backtest_engine import (
            BACKTEST_ENGINE_VERSION,
            STRATEGY_BACKTEST_ELIGIBILITY,
        )
        from historical_data import evaluate_phase3a_backtest_readiness

        engine = self.engine
        assert engine is not None
        data_mode = (self._get_query_param(query_params, "data_mode", "LIVE") or "LIVE").strip().upper()
        if data_mode not in ("LIVE", "SIMULATED"):
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": "data_mode must be 'LIVE' or 'SIMULATED'.",
            }
        readiness = evaluate_phase3a_backtest_readiness(
            config=engine.config,
            store=engine.store,
            broker_status=engine.get_broker_status(),
            target_data_mode=data_mode,
            provider=self._get_query_param(query_params, "provider", None),
            symbol=self._get_query_param(query_params, "symbol", "RELIANCE"),
            strategy_id=self._get_query_param(query_params, "strategy_id", "strat_1_order_block"),
            execution_scope=self._get_query_param(query_params, "execution_scope", None),
            start_date=self._get_query_param(query_params, "evaluation_start_date", None),
            end_date=self._get_query_param(query_params, "evaluation_end_date", None),
            now=engine.clock() if callable(getattr(engine, "clock", None)) else None,
        )
        return 200, {
            "status": "ok",
            "engine_version": BACKTEST_ENGINE_VERSION,
            "implementation_status": "IMPLEMENTED_VERIFIED",
            "data_acceptance_status": readiness["execution_gate"]["reason_code"],
            "readiness": readiness,
            "strategies": STRATEGY_BACKTEST_ELIGIBILITY,
        }

    def _handle_backtest_runs(self, query_params: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
        engine = self.engine
        assert engine is not None
        if engine.store is None:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": "Database persistence is disabled.",
            }
        try:
            limit = _parse_int_param(query_params, "limit", default=50, min_val=1, max_val=200)
            offset = _parse_int_param(query_params, "offset", default=0, min_val=0, max_val=100000)
            res = engine.store.query_backtest_runs(
                strategy_id=_get_str_param(query_params, "strategy_id"),
                symbol=_get_str_param(query_params, "symbol"),
                data_mode=_get_str_param(query_params, "data_mode"),
                period_type=_get_str_param(query_params, "period_type"),
                limit=limit,
                offset=offset,
            )
            return 200, {"status": "ok", **res}
        except ValueError as exc:
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": str(exc),
            }
        except PersistenceError as exc:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": str(exc),
            }

    def _handle_backtest_run_detail(self, run_id: str) -> Tuple[int, Dict[str, Any]]:
        engine = self.engine
        assert engine is not None
        if engine.store is None:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": "Database persistence is disabled.",
            }
        try:
            detail = engine.store.get_backtest_run_detail(run_id)
            if detail is None:
                return 404, {
                    "status": "error",
                    "error_type": "NotFoundError",
                    "message": f"Backtest run '{run_id}' not found.",
                }
            return 200, {"status": "ok", "backtest_run": detail}
        except ValueError as exc:
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": str(exc),
            }
        except PersistenceError as exc:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": str(exc),
            }

    def _handle_post_backtest(self) -> Tuple[int, Dict[str, Any]]:
        from backtest_engine import (
            BacktestConfig,
            BacktestEligibilityError,
            BacktestReadinessError,
            BacktestValidationError,
            DeterministicBacktestEngine,
            IndianCostModel,
        )

        engine = self.engine
        assert engine is not None
        try:
            content_len = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            content_len = 0
        if content_len <= 0 or content_len > 10 * 1024 * 1024:
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": "POST /api/backtest requires a valid JSON request body.",
            }
        try:
            raw_body = self.rfile.read(content_len).decode("utf-8")
            body = json.loads(raw_body)
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object.")
        except Exception as exc:
            return 400, {
                "status": "error",
                "error_type": "ValidationError",
                "message": f"Invalid JSON request body: {exc}",
            }

        try:
            strategy_id = str(body.get("strategy_id") or "").strip()
            symbol = str(body.get("symbol") or "").strip().upper()
            if not strategy_id or not symbol:
                raise BacktestValidationError("Both 'strategy_id' and 'symbol' are required.")

            data_mode = str(body.get("data_mode") or "SIMULATED").strip().upper()
            cost_dict = body.get("cost_model") if isinstance(body.get("cost_model"), dict) else {}
            for values, names in (
                (body, ("starting_capital_inr", "risk_per_trade_pct", "max_daily_loss_inr",
                        "daily_profit_target_inr", "slippage_bps_per_leg", "max_concurrent_positions")),
                (cost_dict, ("brokerage_per_order_inr", "slippage_bps_per_leg", "other_cost_per_trade_inr")),
            ):
                if any(isinstance(values.get(name), bool) for name in names):
                    raise BacktestValidationError("Risk, capital, costs and quantities cannot be booleans.")
            cost_model = IndianCostModel(
                brokerage_per_order_inr=float(cost_dict.get("brokerage_per_order_inr", 20.0)),
                slippage_bps_per_leg=float(cost_dict.get("slippage_bps_per_leg", body.get("slippage_bps_per_leg", 5.0))),
                other_cost_per_trade_inr=float(cost_dict.get("other_cost_per_trade_inr", 0.0)),
            )
            bt_cfg = BacktestConfig(
                starting_capital_inr=float(body.get("starting_capital_inr", engine.config.account_capital_inr or 100000.0)),
                risk_per_trade_pct=float(body.get("risk_per_trade_pct", engine.config.max_risk_per_trade_pct or 1.0)),
                max_daily_loss_inr=(
                    float(body["max_daily_loss_inr"])
                    if "max_daily_loss_inr" in body and body["max_daily_loss_inr"] is not None
                    else float(engine.config.max_daily_loss_inr or 2000.0)
                ),
                daily_profit_target_inr=(
                    float(body["daily_profit_target_inr"])
                    if "daily_profit_target_inr" in body and body["daily_profit_target_inr"] is not None
                    else float(engine.config.daily_profit_target_inr or 4000.0)
                ),
                max_concurrent_positions=body.get("max_concurrent_positions", 1),
                target_mode=str(body.get("target_mode") or "TARGET_1").strip().upper(),
                instrument_type=str(body.get("instrument_type") or ("INDEX_SPOT" if symbol in ("NIFTY", "BANKNIFTY") else "EQ")).strip().upper(),
                historical_lot_size=body.get("historical_lot_size"),
                historical_instrument_identity=body.get("historical_instrument_identity"),
                historical_instrument_archive_id=body.get("historical_instrument_archive_id"),
                period_type=str(body.get("period_type") or "FULL").strip().upper(),
                evaluation_start_date=body.get("evaluation_start_date"),
                evaluation_end_date=body.get("evaluation_end_date"),
                execution_scope=body.get("execution_scope"),
                cost_model=cost_model,
            )
            bt_engine = DeterministicBacktestEngine(
                bot_config=engine.config,
                store=engine.store,
                broker_status=engine.get_broker_status(),
                clock=getattr(engine, "clock", None),
            )
            res = bt_engine.run_backtest(
                strategy_id=strategy_id,
                symbol=symbol,
                candles=body.get("candles"),
                segment=body.get("segment"),
                exchange=str(body.get("exchange") or "NSE"),
                provider=body.get("provider"),
                instrument_token=str(body.get("instrument_token") or "2885"),
                interval_min=int(body.get("interval_min", 5)),
                data_mode=data_mode,
                backtest_config=bt_cfg,
                option_execution_request=body.get("option_execution_request"),
                persist_run=bool(body.get("persist_run", True)),
            )
            return 200, {"status": "ok", **res}
        except (BacktestValidationError, ValueError) as exc:
            return 400, {
                "status": "error",
                "error_type": "BacktestValidationError",
                "message": str(exc),
            }
        except (BacktestEligibilityError, BacktestReadinessError) as exc:
            payload = {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            if exc.details:
                payload["rejection"] = exc.details
            return 422, payload
        except PersistenceError as exc:
            return 503, {
                "status": "error",
                "error_type": "PersistenceError",
                "message": str(exc),
            }

    def _handle_paper_portfolio(self, query_params, *, accounts=False, ledger=False, session=False):
        """Read existing simulated accounts only; never scan, mark, fill or create."""
        assert self.engine is not None
        if self.engine.store is None:
            return 503, {"status": "error", "message": "Database persistence is disabled."}
        try:
            allowed = {"limit", "cursor"} if accounts else {"account_id", "session_date"} if session else {"account_id", "collection", "limit", "cursor"} if ledger else {"account_id"}
            if set(query_params) - allowed or any(len(v) != 1 for v in query_params.values()):
                raise ValueError()
            if accounts:
                raw_limit = _get_str_param(query_params, "limit") or "100"
                if not raw_limit.isascii() or not raw_limit.isdecimal() or len(raw_limit)>3:
                    raise ValueError()
                return 200, self.engine.store.query_paper_accounts(limit=int(raw_limit),
                    cursor=_get_str_param(query_params, "cursor"))
            account_id = _get_str_param(query_params, "account_id")
            if not account_id or len(account_id) > 128:
                raise ValueError()
            if session:
                session_date = _get_str_param(query_params, "session_date")
                if not session_date:
                    raise ValueError()
                report = self.engine.store.get_paper_session_report(account_id,session_date,as_of=self.engine._now_ist())
            elif ledger:
                page_limit = _get_str_param(query_params, "limit") or "100"
                if not page_limit.isascii() or not page_limit.isdecimal() or len(page_limit) > 3:
                    raise ValueError()
                report = self.engine.store.query_paper_ledger(account_id,
                    collection=_get_str_param(query_params, "collection") or "events", limit=int(page_limit),
                    cursor=_get_str_param(query_params, "cursor"))
            else:
                report = self.engine.store.get_paper_portfolio_report(account_id, as_of=self.engine._now_ist())
            return (404 if report["status"] == "NOT_CONFIGURED" else 200), report
        except ValueError as exc:
            if getattr(exc, "reason_code", "") == "MALFORMED_OR_OVERSIZED_PAPER_RECORD":
                return 503, {"status": "RECONCILIATION_REQUIRED", "message": "Paper ledger requires inspection."}
            return 400, {"status": "error", "message": "Invalid paper-report query."}
        except Exception:
            return 503, {"status": "error", "message": "Paper portfolio report is unavailable."}

    def _handle_contract_inspection(self, query_params, *, resolve=False):
        """Inspect retained local declarations; no broker/master download or activation."""
        assert self.engine is not None
        if self.engine.store is None:
            return 503, {"status": "error", "message": "Database persistence is disabled."}
        try:
            allowed = ({"master_id", "provider", "instrument_type", "as_of", "identifier",
                        "underlying", "expiry", "strike", "option_type"} if resolve else {"provider"})
            if (set(query_params) - allowed or any(len(v) != 1 for v in query_params.values())
                    or any(len(v[0]) > 256 for v in query_params.values())):
                raise ValueError()
            if not resolve:
                candidates = self.engine.store.list_contract_master_candidates(_get_str_param(query_params, "provider"))
                return 200, {"status": "ok", "eligible": False, "historical_replay_allowed": False,
                             "masters": [{key: item[key] for key in
                                          ("master_id", "status", "eligible", "record_count", "normalized_sha256")}
                                         for item in candidates]}
            required = ("master_id", "provider", "instrument_type", "as_of")
            if any(not _get_str_param(query_params, key) for key in required):
                raise ValueError()
            request = {key: values[0] for key, values in query_params.items() if key != "master_id"}
            if "strike" in request:
                request["strike"] = float(request["strike"])
            report = self.engine.store.inspect_contract_resolution(query_params["master_id"][0], **request)
            return 200, report
        except ValueError:
            return 400, {"status": "error", "eligible": False, "message": "Invalid contract-inspection query or declaration."}
        except Exception:
            return 503, {"status": "error", "eligible": False, "message": "Contract inspection is unavailable."}

    def _handle_config(self) -> Tuple[int, Dict[str, Any]]:
        assert self.engine is not None and self.scheduler is not None
        return 200, {
            "status": "ok",
            "config": self.engine.config.to_safe_dict(),
            "broker_status": self.engine.get_broker_status(),
            "scheduler": self.scheduler.get_status(),
        }

    def _handle_operational_read(self, query, *, history=False):
        """Bounded stored facts only; no acquisition, preview dispatch or replay."""
        if self.engine.store is None:
            return 503, {"status": "error", "reason_code": "REQUIRED_STORAGE_UNAVAILABLE"}
        try:
            allowed = ({"symbol", "interval_min", "data_mode", "provider", "start_time_ist", "end_time_ist",
                        "decision_time_ist", "cursor", "limit"} if history else {"limit", "status"})
            if (set(query)-allowed or any(len(values)!=1 for values in query.values())
                    or any(len(values[0])>4096 for values in query.values())):
                raise ValueError()
            limit = _parse_int_param(query, "limit", 100, 1, 200 if not history else 10000)
            if not history:
                return 200, self.engine.store.list_notification_outbox(limit=limit, status=_get_str_param(query,"status"))
            symbol = _get_str_param(query, "symbol")
            if not symbol:
                raise ValueError()
            options = {key: values[0] for key, values in query.items() if key not in ("symbol", "interval_min", "limit")}
            options["interval_min"] = _parse_int_param(query,"interval_min",5,1,1440)
            return 200, self.engine.store.query_historical_candle_page(symbol, limit=limit, **options)
        except PersistenceValidationError:
            return 503, {"status": "RECONCILIATION_REQUIRED", "reason_code": "OPERATIONAL_RECORD_REQUIRES_INSPECTION"}
        except (ValueError, TypeError):
            return 400, {"status": "error", "reason_code": "INVALID_OPERATIONAL_QUERY"}
        except Exception:
            return 503, {"status": "error", "reason_code": "OPERATIONAL_STORAGE_UNAVAILABLE"}

    def _dispatch_get_or_head(self, send_body: bool = True) -> None:
        if not self._allow_local_request():
            return
        self._ensure_initialized()
        parsed = urllib.parse.urlparse(self.path)
        raw_path = parsed.path or "/"
        route = raw_path.rstrip("/") or "/"
        query_params = urllib.parse.parse_qs(parsed.query)

        if route in ("/api/notification-outbox", "/api/v1/notification-outbox",
                     "/api/historical-candle-pages", "/api/v1/historical-candle-pages"):
            code, payload = self._handle_operational_read(query_params, history=route.endswith("historical-candle-pages"))
            self._send_json(code, payload, send_body=send_body)
            return

        if route in ("/api/scan-lineage", "/api/v1/scan-lineage", "/api/cash-candles", "/api/v1/cash-candles"):
            code, payload = self._handle_cash_lineage(query_params, candles=route.endswith("cash-candles"))
            self._send_json(code, payload, send_body=send_body)
            return

        if route in ("/api/paper-accounts", "/api/v1/paper-accounts", "/api/paper-portfolio", "/api/v1/paper-portfolio",
                     "/api/paper-ledger", "/api/v1/paper-ledger", "/api/paper-session", "/api/v1/paper-session"):
            code, payload = self._handle_paper_portfolio(query_params, accounts=route.endswith("paper-accounts"),
                                                       ledger=route.endswith("paper-ledger"),session=route.endswith("paper-session"))
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/contract-masters", "/api/v1/contract-masters", "/api/contract-resolution", "/api/v1/contract-resolution"):
            code, payload = self._handle_contract_inspection(query_params, resolve=route.endswith("contract-resolution"))
            self._send_json(code, payload, send_body=send_body)
            return

        if route in ("/api/health", "/api/v1/health"):
            code, payload = self._handle_health()
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/scan", "/api/v1/scan"):
            code, payload = self._handle_scan()
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/signals", "/api/v1/signals"):
            code, payload = self._handle_signals(query_params)
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/scans", "/api/v1/scans"):
            code, payload = self._handle_scans(query_params)
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/oi-snapshots", "/api/v1/oi-snapshots"):
            code, payload = self._handle_oi_snapshots(query_params)
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/oi-baselines", "/api/v1/oi-baselines"):
            code, payload = self._handle_oi_baselines(query_params)
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/historical-datasets", "/api/v1/historical-datasets"):
            code, payload = self._handle_historical_datasets(query_params)
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/historical-readiness", "/api/v1/historical-readiness"):
            code, payload = self._handle_historical_readiness(query_params)
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/backtest-eligibility", "/api/v1/backtest-eligibility"):
            code, payload = self._handle_backtest_eligibility(query_params)
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/backtest-runs", "/api/v1/backtest-runs"):
            code, payload = self._handle_backtest_runs(query_params)
            self._send_json(code, payload, send_body=send_body)
            return
        if route.startswith("/api/backtest-runs/") or route.startswith("/api/v1/backtest-runs/"):
            run_id_part = route.rsplit("/", 1)[-1]
            code, payload = self._handle_backtest_run_detail(run_id_part)
            self._send_json(code, payload, send_body=send_body)
            return
        if route in ("/api/config", "/api/v1/config"):
            code, payload = self._handle_config()
            self._send_json(code, payload, send_body=send_body)
            return
        if route.startswith("/api/") or route == "/api":
            self._send_json(
                404,
                {
                    "status": "error",
                    "error_type": "NotFoundError",
                    "message": f"Unknown API endpoint: {route}",
                },
                send_body=send_body,
            )
            return

        if self._try_serve_approved_public_asset(raw_path, send_body=send_body):
            return

        self._send_json(
            404,
            {
                "status": "error",
                "error_type": "NotFoundError",
                "message": "Resource not found.",
            },
            send_body=send_body,
        )

    def do_GET(self) -> None:
        self._dispatch_get_or_head(send_body=True)

    def do_HEAD(self) -> None:
        self._dispatch_get_or_head(send_body=False)

    def do_OPTIONS(self) -> None:
        if not self._allow_local_request():
            return
        parsed = urllib.parse.urlparse(self.path)
        route = (parsed.path or "/").rstrip("/") or "/"
        if route.startswith("/api/") or route == "/api":
            try:
                self.send_response(204)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
                self.send_header("Content-Length", "0")
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self._send_json(404, {
            "status": "error",
            "error_type": "NotFoundError",
            "message": "Resource not found.",
        })

    def do_POST(self) -> None:
        if not self._allow_local_request():
            return
        self._ensure_initialized()
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        if route in ("/api/scan", "/api/v1/scan"):
            code, payload = self._handle_scan()
            self._send_json(code, payload)
            return
        if route in ("/api/backtest", "/api/v1/backtest"):
            code, payload = self._handle_post_backtest()
            self._send_json(code, payload)
            return
        self._send_json(405, {
            "status": "error",
            "error_type": "MethodNotAllowedError",
            "message": f"POST is not supported on {route}. Live order execution is strictly disabled.",
        })

    def _allow_local_request(self):
        """Same-origin browser/loopback CLI only; no public API authorization."""
        try:
            hosts = self.headers.get_all("Host") or []
            if len(hosts)!=1:
                raise ValueError()
            host = urllib.parse.urlsplit("http://"+hosts[0])
            local = host.hostname=="localhost" or ipaddress.ip_address(host.hostname).is_loopback
            if (not local or host.username is not None or host.password is not None
                    or host.path or host.query or host.fragment or (host.port or 80)!=self.server.server_address[1]
                    or not ipaddress.ip_address(self.client_address[0]).is_loopback
                    or self.headers.get("Sec-Fetch-Site")=="cross-site"
                    or self.headers.get("Origin") not in (None, "http://"+hosts[0])):
                raise ValueError()
            return True
        except (ValueError, TypeError):
            self._send_json(403, {"status": "error", "reason_code": "LOCAL_SAME_ORIGIN_REQUIRED",
                                  "message": "Open the dashboard from its loopback server address."})
            return False


def configure_server_runtime(
    config: Optional[BotConfig] = None,
    start_scheduler: Optional[bool] = None,
    clock: Optional[Any] = None,
    broker_scanner: Optional[Any] = None,
) -> Tuple[IntradayBotEngine, MarketScanScheduler]:
    """
    Thread-safe, idempotent initializer for `DashboardRequestHandler.engine` and
    `DashboardRequestHandler.scheduler`.
    """
    with _SERVER_INIT_LOCK:
        if config is not None or DashboardRequestHandler.engine is None:
            if DashboardRequestHandler.scheduler is not None:
                DashboardRequestHandler.scheduler.stop()
            if DashboardRequestHandler.engine is not None:
                try:
                    DashboardRequestHandler.engine.close()
                except Exception:
                    pass
            resolved_cfg = config or BotConfig(
                database_url=os.getenv("DATABASE_URL", "sqlite:///tradepulse_phase1d.db")
            )
            if start_scheduler is not None:
                resolved_cfg.enable_background_scheduler = bool(start_scheduler)
            DashboardRequestHandler.engine = IntradayBotEngine(
                resolved_cfg,
                clock=clock,
                broker_scanner=broker_scanner,
            )
            DashboardRequestHandler.scheduler = MarketScanScheduler(
                DashboardRequestHandler.engine,
                clock=clock,
            )
        else:
            if DashboardRequestHandler.scheduler is None:
                DashboardRequestHandler.scheduler = MarketScanScheduler(
                    DashboardRequestHandler.engine,
                    clock=clock,
                )
            if start_scheduler is not None:
                DashboardRequestHandler.engine.config.enable_background_scheduler = bool(start_scheduler)

        engine = DashboardRequestHandler.engine
        scheduler = DashboardRequestHandler.scheduler
        should_run = (
            bool(start_scheduler)
            if start_scheduler is not None
            else bool(engine.config.enable_background_scheduler)
        )
        if should_run:
            scheduler.start()
        else:
            scheduler.stop()
        return engine, scheduler


def create_http_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    handler_cls: type = DashboardRequestHandler,
) -> ThreadingHTTPServer:
    """
    Factory returning a configured `ThreadingHTTPServer` instance for production and tests.
    """
    return TradePulseThreadingHTTPServer((host, port), handler_cls)


def run_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    start_scheduler: Optional[bool] = None,
    config: Optional[BotConfig] = None,
) -> None:
    os.chdir(PROJECT_ROOT)
    configure_server_runtime(config=config, start_scheduler=start_scheduler)
    server = ThreadingHTTPServer((host, port), DashboardRequestHandler)
    print(f"TradePulse & OrderBlock Server (Phase 2C) running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if DashboardRequestHandler.scheduler is not None:
            DashboardRequestHandler.scheduler.stop()
        server.server_close()


if __name__ == "__main__":
    host_env = os.getenv("SERVER_HOST", "127.0.0.1")
    port_env = int(os.getenv("SERVER_PORT", "8080"))
    sched_env = os.getenv("ENABLE_BACKGROUND_SCHEDULER", "false").strip().lower() in ("true", "1", "yes")
    run_server(host=host_env, port=port_env, start_scheduler=sched_env)

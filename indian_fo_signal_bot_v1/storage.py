from instrument_identity import IdentityValidationError, validate_signal_identity
import json
import logging
import math
import os
import atexit
import sqlite3
import threading
import time
import weakref
import csv
from contextlib import contextmanager
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from strategies import (
    IST,
    TradeSignal,
    format_ist_timestamp,
    parse_ist_timestamp,
    validate_option_chain_for_strategy,
    normalize_state_scope,
    signal_state_identity,
)

logger = logging.getLogger("tradepulse.storage")


class PersistenceError(RuntimeError):
    """Raised when a database initialization, read, or write operation fails."""


class PersistenceValidationError(ValueError):
    """Raised when a signal, OI snapshot, or OI baseline record fails validation prior to database persistence."""


def resolve_sqlite_path(database_url: str) -> str:
    """
    Resolves a configured DATABASE_URL into a valid sqlite3 path or ':memory:'.
    Supported formats:
    - ':memory:' or 'sqlite:///:memory:'
    - 'sqlite:///relative/or/absolute/path.db'
    - Plain file path ending in '.db' or '.sqlite' or '.sqlite3'
    Raises ValueError if the scheme is unsupported or empty.
    """
    if not isinstance(database_url, str) or not database_url.strip():
        raise ValueError("DATABASE_URL must be a non-empty string.")
    raw = database_url.strip()
    if raw in (":memory:", "sqlite:///:memory:", "sqlite://"):
        return ":memory:"
    if raw.startswith("sqlite:///"):
        path = raw[len("sqlite:///"):]
        if not path.strip():
            raise ValueError(f"Invalid SQLite DATABASE_URL with empty path: {database_url!r}")
        return path.strip()
    if "://" in raw:
        scheme = raw.split("://", 1)[0].lower()
        raise ValueError(
            f"Unsupported DATABASE_URL scheme '{scheme}://'. Phase 1D/2B uses standard-library SQLite "
            f"('sqlite:///tradepulse_phase1d.db' or ':memory:') by default; external database drivers "
            f"(e.g., PostgreSQL psycopg/SQLAlchemy) require installing external packages."
        )
    return raw


def _coerce_to_date(val: Any) -> date:
    if isinstance(val, datetime):
        return parse_ist_timestamp(val).date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        s = val.strip()
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return datetime.strptime(s, "%Y-%m-%d").date()
        return parse_ist_timestamp(s).date()
    raise ValueError(f"Cannot parse session date from {val!r}.")


def is_nse_trading_day(day_val: Any, configured_holidays: Optional[List[str]] = None) -> bool:
    """
    Returns True if `day_val` is a weekday (Mon-Fri) and not in `configured_holidays` (YYYY-MM-DD).
    """
    d = _coerce_to_date(day_val)
    if d.weekday() >= 5:
        return False
    holiday_set = {str(h).strip() for h in (configured_holidays or []) if str(h).strip()}
    return d.strftime("%Y-%m-%d") not in holiday_set


def resolve_effective_trading_session_date(
    ref_date_or_dt: Any,
    configured_holidays: Optional[List[str]] = None,
) -> date:
    """
    Resolves `ref_date_or_dt` to itself if it is an NSE trading day, or rolls backward
    across weekends and `configured_holidays` to the most recent NSE trading session date.
    """
    cursor = _coerce_to_date(ref_date_or_dt)
    for _ in range(366):
        if is_nse_trading_day(cursor, configured_holidays):
            return cursor
        cursor -= timedelta(days=1)
    return cursor


def resolve_prior_trading_session_date(
    current_session_date: Any,
    configured_holidays: Optional[List[str]] = None,
) -> date:
    """
    Returns the immediately preceding NSE trading session date strictly before
    the effective trading session date of `current_session_date`, skipping weekends
    and `configured_holidays`.
    """
    eff_curr = resolve_effective_trading_session_date(current_session_date, configured_holidays)
    cursor = eff_curr - timedelta(days=1)
    for _ in range(366):
        if is_nse_trading_day(cursor, configured_holidays):
            return cursor
        cursor -= timedelta(days=1)
    return cursor


def count_trading_sessions_between(
    earlier_date: Any,
    later_date: Any,
    configured_holidays: Optional[List[str]] = None,
) -> int:
    """
    Counts the number of NSE trading sessions strictly after `earlier_date` up to and
    including the effective trading session of `later_date`.
    Returns 1 when `earlier_date` is the immediately preceding trading session before `later_date`
    (even across weekends or configured exchange holidays).
    """
    d_early = _coerce_to_date(earlier_date)
    d_late = resolve_effective_trading_session_date(later_date, configured_holidays)
    if d_early >= d_late:
        return 0
    count = 0
    cursor = d_early + timedelta(days=1)
    while cursor <= d_late:
        if is_nse_trading_day(cursor, configured_holidays):
            count += 1
        cursor += timedelta(days=1)
    return count


def compute_signal_dedup_key(sig: Any, broker: str = "") -> str:
    """Versioned provider/mode/context/instrument/setup/direction/candle identity."""
    try:
        return signal_state_identity(sig, broker)[0]
    except ValueError as exc:
        raise PersistenceValidationError(str(exc)) from exc


NSE_CLOSING_WINDOW_START = dt_time(15, 25, 0)


def is_closing_session_timestamp(obs_ts_or_dt: Any) -> bool:
    """
    Returns True if `obs_ts_or_dt` (in Asia/Kolkata) is at or after 15:25:00 IST
    (the final 5-minute closing bar window 15:25-15:30 IST or post-market EOD).
    Arbitrary mid-session intraday snapshots (< 15:25:00 IST) return False.
    """
    dt_val = parse_ist_timestamp(obs_ts_or_dt)
    t_val = dt_val.timetz().replace(tzinfo=None)
    return t_val >= NSE_CLOSING_WINDOW_START


def compute_oi_baseline_dedup_key(
    index_symbol: str,
    expiry: str,
    strike: int,
    option_type: str,
    session_date: str,
    data_mode: str,
) -> str:
    """
    Computes the canonical deterministic unique key for an `oi_baselines` row:
    `{INDEX_SYMBOL}:{EXPIRY}:{STRIKE}:{OPTION_TYPE}:{SESSION_DATE}:{DATA_MODE}`
    """
    return (
        f"{str(index_symbol).strip().upper()}:"
        f"{str(expiry).strip()}:"
        f"{int(strike)}:"
        f"{str(option_type).strip().upper()}:"
        f"{str(session_date).strip()}:"
        f"{str(data_mode).strip().upper()}"
    )


_ACTIVE_SQLITE_STORES: "weakref.WeakSet[SQLitePersistenceStore]" = weakref.WeakSet()


def _close_all_active_sqlite_stores() -> None:
    for store in list(_ACTIVE_SQLITE_STORES):
        try:
            store.close()
        except Exception:
            pass


atexit.register(_close_all_active_sqlite_stores)


class SQLitePersistenceStore:
    """
    Lightweight, zero-dependency, thread-safe SQLite persistence store for TradePulse AI:
    - Persists generated signals with deterministic deduplication (`signals` table).
    - Persists scan-run lifecycle metadata and status (`scan_runs` table).
    - Persists validated option-chain / open-interest snapshots and computes rolling
      intraday OI diffs against the previous valid snapshot (`oi_snapshots` table).
    - Persists strike-level prior-session and session-closing open interest baselines
      (`oi_baselines` table) with strict `LIVE` vs `SIMULATED` isolation, CE/PE pairing
      validation, holiday/weekend-aware session age checks, and idempotent updates.
    - Persists mitigated Order Block zones across restarts (`mitigated_order_blocks` table).
    - Thread-safe under concurrent `ThreadingHTTPServer` requests:
      * File-backed SQLite databases use connection-per-operation with WAL mode,
        `timeout=30.0`, `PRAGMA busy_timeout=30000`, and a reentrant lock (`self._db_lock`).
      * In-memory (`:memory:`) databases serialize access to the single in-memory connection
        using `self._db_lock` so concurrent threads never share an unguarded connection or
        collide on transactions/cursors.
    - Uses parameterized SQL queries everywhere and surfaces any database error explicitly.
    """

    def __init__(self, database_url: str = "sqlite:///tradepulse_phase1d.db"):
        self.database_url = database_url
        self.db_path = resolve_sqlite_path(database_url)
        self._db_lock = threading.RLock()
        self._memory_conn: Optional[sqlite3.Connection] = None
        self._closed: bool = False
        _ACTIVE_SQLITE_STORES.add(self)
        self.initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        try:
            if self.db_path == ":memory:":
                if self._memory_conn is None:
                    conn = sqlite3.connect(
                        ":memory:",
                        timeout=30.0,
                        check_same_thread=False,
                    )
                    try:
                        conn.row_factory = sqlite3.Row
                        conn.execute("PRAGMA foreign_keys=ON;")
                    except Exception:
                        conn.close()
                        raise
                    self._memory_conn = conn
                    self._closed = False
                return self._memory_conn

            parent_dir = os.path.dirname(os.path.abspath(self.db_path))
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            try:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA busy_timeout=30000;")
                conn.execute("PRAGMA foreign_keys=ON;")
            except Exception:
                conn.close()
                raise
            return conn
        except Exception as exc:
            logger.error("Database connection failed for %s: %s", self.db_path, type(exc).__name__)
            raise PersistenceError(f"Failed to connect to SQLite database ({type(exc).__name__}): {exc}") from exc

    def _close_if_file(self, conn: Optional[sqlite3.Connection]) -> None:
        if conn is not None and self.db_path != ":memory:":
            try:
                conn.close()
            except Exception:
                pass

    def close(self) -> None:
        """
        Deterministically closes any persistent in-memory SQLite connection so that
        Python 3.11/3.12/3.13 garbage collection never emits sqlite3 ResourceWarnings.
        Safe and idempotent to call multiple times.
        """
        with self._db_lock:
            if self._memory_conn is not None:
                try:
                    self._memory_conn.close()
                except Exception:
                    pass
                self._memory_conn = None
            self._closed = True

    def __enter__(self) -> "SQLitePersistenceStore":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def initialize_schema(self) -> None:
        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    if self.db_path != ":memory:":
                        # WAL initialization can return SQLITE_BUSY immediately when
                        # another process is enabling it, despite busy_timeout.
                        deadline = time.monotonic() + 30.0
                        while True:
                            try:
                                conn.execute("PRAGMA journal_mode=WAL;")
                                break
                            except sqlite3.OperationalError as exc:
                                if (getattr(exc, "sqlite_errorcode", None) not in
                                        (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                                        or time.monotonic() >= deadline):
                                    raise
                                time.sleep(0.01)
                    conn.execute("PRAGMA foreign_keys=ON;")
                    # Serialize additive migrations across independent store instances.
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS scan_runs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            run_id TEXT NOT NULL UNIQUE,
                            started_at_ist TEXT NOT NULL,
                            completed_at_ist TEXT,
                            duration_ms REAL,
                            status TEXT NOT NULL,
                            broker TEXT NOT NULL,
                            data_mode TEXT NOT NULL,
                            is_simulated INTEGER NOT NULL,
                            total_signals INTEGER NOT NULL DEFAULT 0,
                            persisted_signals INTEGER NOT NULL DEFAULT 0,
                            duplicate_signals INTEGER NOT NULL DEFAULT 0,
                            oi_snapshots_saved INTEGER NOT NULL DEFAULT 0,
                            market_breadth_json TEXT,
                            error_type TEXT,
                            error_message TEXT
                        );
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_scan_runs_started ON scan_runs(started_at_ist DESC, id DESC);"
                    )

                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS signals (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            dedup_key TEXT NOT NULL UNIQUE,
                            scan_run_id TEXT,
                            symbol TEXT NOT NULL,
                            segment TEXT NOT NULL,
                            strategy_id TEXT NOT NULL,
                            strategy_name TEXT NOT NULL,
                            direction TEXT NOT NULL,
                            position_type TEXT NOT NULL,
                            instrument_label TEXT NOT NULL,
                            entry_price REAL NOT NULL,
                            entry_zone_low REAL NOT NULL,
                            entry_zone_high REAL NOT NULL,
                            stop_loss REAL NOT NULL,
                            invalidation_level REAL NOT NULL,
                            target_1 REAL NOT NULL,
                            target_2 REAL NOT NULL,
                            risk_reward TEXT NOT NULL,
                            confidence_pct INTEGER NOT NULL,
                            quality_score INTEGER NOT NULL,
                            score_breakdown_json TEXT NOT NULL,
                            win_rate_benchmark TEXT NOT NULL,
                            position_qty INTEGER NOT NULL,
                            capital_risk_inr REAL NOT NULL,
                            est_charges_inr REAL NOT NULL,
                            rationale TEXT NOT NULL,
                            candle_timestamp TEXT NOT NULL,
                            is_simulated INTEGER NOT NULL,
                            data_mode TEXT NOT NULL,
                            broker TEXT NOT NULL,
                            created_at_ist TEXT NOT NULL
                        );
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(candle_timestamp DESC, id DESC);"
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_signals_lookup ON signals(symbol, segment, strategy_id, data_mode);"
                    )
                    # Additive migration: retain legacy keys and all original values.
                    # Unknown source/context must never suppress a scoped scanner signal.
                    signal_cols = {r[1] for r in conn.execute("PRAGMA table_info(signals)")}
                    for column, definition in (
                        ("provider", "TEXT NOT NULL DEFAULT 'unknown'"),
                        ("state_context", "TEXT NOT NULL DEFAULT 'LEGACY_UNSCOPED'"),
                        ("interval_min", "INTEGER NOT NULL DEFAULT 0"),
                        ("instrument_identity_json", "TEXT NOT NULL DEFAULT '{}'"),
                    ):
                        if column not in signal_cols:
                            conn.execute(f"ALTER TABLE signals ADD COLUMN {column} {definition}")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_state_scope "
                                 "ON signals(provider, data_mode, state_context, candle_timestamp)")

                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS oi_snapshots (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            dedup_key TEXT NOT NULL UNIQUE,
                            scan_run_id TEXT,
                            index_symbol TEXT NOT NULL,
                            expiry TEXT NOT NULL,
                            snapshot_timestamp TEXT NOT NULL,
                            spot REAL NOT NULL,
                            atm_strike INTEGER NOT NULL,
                            pcr REAL NOT NULL,
                            total_ce_oi INTEGER NOT NULL,
                            total_pe_oi INTEGER NOT NULL,
                            oi_change_measure TEXT NOT NULL,
                            strikes_json TEXT NOT NULL,
                            previous_snapshot_id INTEGER,
                            intraday_oi_diff_json TEXT,
                            is_simulated INTEGER NOT NULL,
                            data_mode TEXT NOT NULL,
                            broker TEXT NOT NULL,
                            created_at_ist TEXT NOT NULL
                        );
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_oi_snapshots_lookup "
                        "ON oi_snapshots(index_symbol, expiry, data_mode, snapshot_timestamp DESC, id DESC);"
                    )

                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS oi_baselines (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            dedup_key TEXT NOT NULL UNIQUE,
                            index_symbol TEXT NOT NULL,
                            expiry TEXT NOT NULL,
                            strike INTEGER NOT NULL,
                            option_type TEXT NOT NULL,
                            open_interest INTEGER NOT NULL,
                            source TEXT NOT NULL,
                            baseline_kind TEXT NOT NULL DEFAULT 'CLOSING_BASELINE',
                            observation_timestamp TEXT NOT NULL,
                            session_date TEXT NOT NULL,
                            data_mode TEXT NOT NULL,
                            is_simulated INTEGER NOT NULL,
                            created_at_ist TEXT NOT NULL,
                            updated_at_ist TEXT NOT NULL,
                            UNIQUE(index_symbol, expiry, strike, option_type, session_date, data_mode)
                        );
                        """
                    )
                    existing_cols = {
                        str(r[1]).lower()
                        for r in conn.execute("PRAGMA table_info(oi_baselines);").fetchall()
                    }
                    if "baseline_kind" not in existing_cols:
                        conn.execute(
                            "ALTER TABLE oi_baselines ADD COLUMN baseline_kind TEXT NOT NULL DEFAULT 'CLOSING_BASELINE';"
                        )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_oi_baselines_lookup "
                        "ON oi_baselines(index_symbol, expiry, data_mode, session_date DESC, strike ASC, option_type ASC);"
                    )

                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS mitigated_order_blocks (
                            zone_key TEXT PRIMARY KEY,
                            symbol TEXT NOT NULL,
                            direction TEXT NOT NULL,
                            ob_timestamp TEXT NOT NULL,
                            mitigated_at_ist TEXT NOT NULL,
                            data_mode TEXT NOT NULL
                        );
                        """
                    )

                    # Keep the old globally keyed table intact as legacy history.
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS scoped_mitigated_order_blocks (
                            provider TEXT NOT NULL, data_mode TEXT NOT NULL,
                            state_context TEXT NOT NULL, segment TEXT NOT NULL,
                            interval_min INTEGER NOT NULL, zone_key TEXT NOT NULL,
                            mitigated_at_ist TEXT NOT NULL,
                            PRIMARY KEY(provider, data_mode, state_context, segment, interval_min, zone_key)
                        )
                    """)

                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS historical_datasets (
                            dataset_id TEXT PRIMARY KEY,
                            symbol TEXT NOT NULL,
                            segment TEXT NOT NULL,
                            exchange TEXT NOT NULL,
                            provider TEXT NOT NULL,
                            instrument_token TEXT NOT NULL,
                            interval_min INTEGER NOT NULL,
                            from_timestamp_ist TEXT NOT NULL,
                            to_timestamp_ist TEXT NOT NULL,
                            retrieved_at_ist TEXT NOT NULL,
                            source_timestamp_ist TEXT,
                            data_mode TEXT NOT NULL,
                            is_simulated INTEGER NOT NULL,
                            transformations_json TEXT NOT NULL,
                            quality_status TEXT NOT NULL,
                            bars_count INTEGER NOT NULL,
                            completed_bars_count INTEGER NOT NULL,
                            sessions_count INTEGER NOT NULL,
                            missing_bars_count INTEGER NOT NULL,
                            missing_timestamps_json TEXT NOT NULL,
                            zero_volume_bars_count INTEGER NOT NULL DEFAULT 0,
                            duplicate_bars_coalesced INTEGER NOT NULL DEFAULT 0,
                            sha256_checksum TEXT NOT NULL,
                            created_at_ist TEXT NOT NULL,
                            updated_at_ist TEXT NOT NULL
                        );
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_historical_datasets_lookup "
                        "ON historical_datasets(symbol, interval_min, data_mode, provider, to_timestamp_ist DESC);"
                    )

                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS historical_candles (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            dedup_key TEXT NOT NULL UNIQUE,
                            dataset_id TEXT NOT NULL,
                            symbol TEXT NOT NULL,
                            segment TEXT NOT NULL,
                            exchange TEXT NOT NULL,
                            provider TEXT NOT NULL,
                            instrument_token TEXT NOT NULL,
                            interval_min INTEGER NOT NULL,
                            candle_timestamp TEXT NOT NULL,
                            session_date TEXT NOT NULL,
                            open REAL NOT NULL,
                            high REAL NOT NULL,
                            low REAL NOT NULL,
                            close REAL NOT NULL,
                            volume REAL NOT NULL,
                            open_interest INTEGER NOT NULL DEFAULT 0,
                            is_complete INTEGER NOT NULL DEFAULT 1,
                            source_timestamp_ist TEXT,
                            retrieved_at_ist TEXT NOT NULL,
                            data_mode TEXT NOT NULL,
                            is_simulated INTEGER NOT NULL,
                            transformations_json TEXT NOT NULL,
                            created_at_ist TEXT NOT NULL,
                            updated_at_ist TEXT NOT NULL,
                            UNIQUE(symbol, interval_min, candle_timestamp, data_mode, provider)
                        );
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_historical_candles_lookup "
                        "ON historical_candles(symbol, interval_min, data_mode, provider, candle_timestamp ASC);"
                    )

                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS backtest_runs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            run_id TEXT NOT NULL UNIQUE,
                            strategy_id TEXT NOT NULL,
                            strategy_name TEXT NOT NULL,
                            strategy_version TEXT NOT NULL,
                            symbol TEXT NOT NULL,
                            segment TEXT NOT NULL,
                            exchange TEXT NOT NULL,
                            interval_min INTEGER NOT NULL,
                            dataset_id TEXT NOT NULL,
                            dataset_checksum TEXT NOT NULL,
                            provider TEXT NOT NULL,
                            data_mode TEXT NOT NULL,
                            is_simulated INTEGER NOT NULL,
                            run_label TEXT NOT NULL,
                            implementation_status TEXT NOT NULL,
                            data_acceptance_status TEXT NOT NULL,
                            period_type TEXT NOT NULL,
                            from_timestamp_ist TEXT NOT NULL,
                            to_timestamp_ist TEXT NOT NULL,
                            starting_capital_inr REAL NOT NULL,
                            ending_capital_inr REAL NOT NULL,
                            risk_per_trade_pct REAL NOT NULL,
                            max_daily_loss_inr REAL,
                            daily_profit_target_inr REAL,
                            total_trades INTEGER NOT NULL,
                            winning_trades INTEGER NOT NULL,
                            losing_trades INTEGER NOT NULL,
                            breakeven_trades INTEGER NOT NULL,
                            win_rate_pct REAL NOT NULL,
                            gross_pnl_inr REAL NOT NULL,
                            total_charges_inr REAL NOT NULL,
                            total_slippage_inr REAL NOT NULL,
                            total_costs_inr REAL NOT NULL,
                            net_pnl_inr REAL NOT NULL,
                            return_on_capital_pct REAL NOT NULL,
                            profit_factor REAL,
                            profit_factor_status TEXT NOT NULL,
                            max_drawdown_inr REAL NOT NULL,
                            max_drawdown_pct REAL NOT NULL,
                            expectancy_per_trade_inr REAL NOT NULL,
                            average_r_multiple REAL NOT NULL,
                            missing_bars_count INTEGER NOT NULL,
                            rejected_signals_count INTEGER NOT NULL,
                            assumptions_json TEXT NOT NULL,
                            metrics_json TEXT NOT NULL,
                            created_at_ist TEXT NOT NULL
                        );
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_backtest_runs_lookup "
                        "ON backtest_runs(created_at_ist DESC, id DESC);"
                    )

                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS backtest_trades (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            run_id TEXT NOT NULL,
                            trade_index INTEGER NOT NULL,
                            strategy_id TEXT NOT NULL,
                            strategy_version TEXT NOT NULL,
                            symbol TEXT NOT NULL,
                            segment TEXT NOT NULL,
                            exchange TEXT NOT NULL,
                            direction TEXT NOT NULL,
                            position_side TEXT NOT NULL,
                            signal_timestamp TEXT NOT NULL,
                            entry_timestamp TEXT NOT NULL,
                            exit_timestamp TEXT NOT NULL,
                            session_date TEXT NOT NULL,
                            raw_entry_price REAL NOT NULL,
                            entry_price REAL NOT NULL,
                            raw_exit_price REAL NOT NULL,
                            exit_price REAL NOT NULL,
                            quantity INTEGER NOT NULL,
                            stop_loss REAL NOT NULL,
                            target_price REAL NOT NULL,
                            target_1 REAL NOT NULL,
                            target_2 REAL NOT NULL,
                            exit_reason TEXT NOT NULL,
                            same_candle_collision INTEGER NOT NULL DEFAULT 0,
                            holding_bars INTEGER NOT NULL,
                            holding_minutes REAL NOT NULL,
                            gross_pnl_inr REAL NOT NULL,
                            charges_inr REAL NOT NULL,
                            slippage_inr REAL NOT NULL,
                            total_costs_inr REAL NOT NULL,
                            net_pnl_inr REAL NOT NULL,
                            risk_amount_inr REAL NOT NULL,
                            realized_r_multiple REAL NOT NULL,
                            dataset_id TEXT NOT NULL,
                            dataset_checksum TEXT NOT NULL,
                            data_mode TEXT NOT NULL,
                            is_simulated INTEGER NOT NULL,
                            provider TEXT NOT NULL,
                            cost_breakdown_json TEXT NOT NULL,
                            signal_metadata_json TEXT NOT NULL,
                            UNIQUE(run_id, trade_index)
                        );
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_backtest_trades_run "
                        "ON backtest_trades(run_id, trade_index ASC);"
                    )
                    # Immutable archive evidence; no existing row is reclassified or replaced.
                    conn.execute("""CREATE TABLE IF NOT EXISTS instrument_master_archives (
                        archive_id TEXT PRIMARY KEY, provider TEXT NOT NULL, status TEXT NOT NULL,
                        original_bytes BLOB NOT NULL, candidate_json TEXT NOT NULL
                    )""")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_instrument_archives_provider "
                                 "ON instrument_master_archives(provider, status)")
                    # Separate immutable assessments; retain original archive rows and old results verbatim.
                    conn.execute("""CREATE TABLE IF NOT EXISTS instrument_source_assessments (
                        archive_id TEXT NOT NULL REFERENCES instrument_master_archives(archive_id),
                        policy_version TEXT NOT NULL, assessment_json TEXT NOT NULL,
                        PRIMARY KEY(archive_id, policy_version)
                    )""")
                    # Additive migration: old databases start with no acceptance evidence.
                    conn.execute("""CREATE TABLE IF NOT EXISTS live_acceptance_evidence (
                        provider TEXT NOT NULL, symbol TEXT NOT NULL,
                        evidence_json TEXT NOT NULL, PRIMARY KEY(provider, symbol)
                    );""")
                    # Forward paper accounting is order-free and isolated from signal/replay rows.
                    conn.execute("""CREATE TABLE IF NOT EXISTS paper_accounts (
                        account_id TEXT PRIMARY KEY, config_hash TEXT NOT NULL,
                        config_json TEXT NOT NULL, created_at_ist TEXT NOT NULL
                    )""")
                    conn.execute("""CREATE TABLE IF NOT EXISTS paper_positions (
                        position_id TEXT PRIMARY KEY,
                        account_id TEXT NOT NULL REFERENCES paper_accounts(account_id),
                        entry_key TEXT NOT NULL, payload_json TEXT NOT NULL,
                        UNIQUE(account_id, entry_key)
                    )""")
                    conn.execute("""CREATE TABLE IF NOT EXISTS paper_events (
                        event_id TEXT PRIMARY KEY,
                        account_id TEXT NOT NULL REFERENCES paper_accounts(account_id),
                        event_key TEXT NOT NULL, kind TEXT NOT NULL,
                        position_id TEXT REFERENCES paper_positions(position_id),
                        payload_json TEXT NOT NULL, UNIQUE(account_id, event_key)
                    )""")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_events_account "
                                 "ON paper_events(account_id, event_id)")
                    # Local normalized declarations are NOT an accepted current master.
                    conn.execute("""CREATE TABLE IF NOT EXISTS contract_master_candidates (
                        master_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                        original_bytes BLOB NOT NULL, candidate_json TEXT NOT NULL
                    )""")
            except Exception as exc:
                logger.error("Schema initialization failed: %s", exc)
                raise PersistenceError(f"Failed to initialize SQLite schema: {exc}") from exc
            finally:
                self._close_if_file(conn)

    @contextmanager
    def paper_transaction(self, write=True):
        """One existing-store transaction; serialize reservations across processes.

        Read contexts enforce SQLite query_only, including for shared :memory:
        connections. Exceptions roll back all position/event mutations together.
        """
        if type(write) is not bool:
            raise PersistenceValidationError("Transaction write mode must be boolean.")
        with self._db_lock:
            conn = self._get_connection()
            previous_query_only = None
            try:
                if conn.in_transaction:
                    raise PersistenceError("Nested paper transactions are unsupported.")
                if not write:
                    previous_query_only = conn.execute("PRAGMA query_only").fetchone()[0]
                    conn.execute("PRAGMA query_only=ON")
                conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                try:
                    yield conn
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise
            finally:
                try:
                    if previous_query_only is not None:
                        conn.execute("PRAGMA query_only=" + str(int(previous_query_only)))
                finally:
                    self._close_if_file(conn)

    def list_paper_accounts(self):
        """Existing-account inventory only; does not configure or operate accounts."""
        with self.paper_transaction(write=False) as conn:
            rows = conn.execute("SELECT account_id, config_hash, created_at_ist "
                                "FROM paper_accounts ORDER BY account_id").fetchall()
        return [dict(row, execution_mode="SIMULATED") for row in rows]

    def get_paper_portfolio_report(self, account_id, as_of=None):
        from paper_portfolio import PaperPortfolio
        return PaperPortfolio.report_existing(self, account_id, as_of=as_of)

    def ingest_contract_master_bytes(self, raw_bytes, *, provider, source_reference,
                                     source_version, captured_at=None):
        """Retain a normalized local declaration; never grant execution eligibility."""
        from instrument_identity import prepare_contract_master
        candidate = prepare_contract_master(raw_bytes, provider=provider,
            source_reference=source_reference, source_version=source_version, captured_at=captured_at)
        payload = dict(candidate)
        original = payload.pop("original_bytes")
        with self.paper_transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO contract_master_candidates VALUES (?, ?, ?, ?)",
                         (candidate["master_id"], provider, original,
                          json.dumps(payload, sort_keys=True, allow_nan=False)))
        return self.get_contract_master_candidate(candidate["master_id"])

    def get_contract_master_candidate(self, master_id, *, include_original=False):
        """Reparse retained bytes and bind metadata on every inspection/resolution."""
        from instrument_identity import prepare_contract_master, reject
        with self.paper_transaction(write=False) as conn:
            row = conn.execute("SELECT * FROM contract_master_candidates WHERE master_id=?",
                               (master_id,)).fetchone()
        if row is None:
            reject("CONTRACT_MASTER_NOT_FOUND", "Local contract-master candidate was not found.")
        try:
            stored = json.loads(row["candidate_json"])
            meta = stored["metadata"]
            parsed = prepare_contract_master(bytes(row["original_bytes"]), provider=row["provider"],
                source_reference=meta["source_reference"], source_version=meta["source_version"],
                captured_at=meta["captured_at"])
            original = parsed.pop("original_bytes")
            if parsed != stored or parsed["master_id"] != row["master_id"]:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            reject("CONTRACT_MASTER_INTEGRITY_FAILURE", "Stored contract declaration and retained bytes disagree.")
        if include_original:
            parsed["original_bytes"] = original
        return parsed

    def list_contract_master_candidates(self, provider=None):
        from instrument_identity import PROVIDERS, reject
        if provider is not None and provider not in PROVIDERS:
            reject("UNSUPPORTED_PROVIDER", "Contract-master provider is unsupported.")
        with self.paper_transaction(write=False) as conn:
            rows = conn.execute("SELECT master_id FROM contract_master_candidates "
                                "WHERE (? IS NULL OR provider=?) ORDER BY master_id", (provider, provider)).fetchall()
        return [self.get_contract_master_candidate(row["master_id"]) for row in rows]

    def inspect_contract_resolution(self, master_id, **request):
        from instrument_identity import resolve_contract_identity
        return resolve_contract_identity(self.get_contract_master_candidate(master_id, include_original=True), **request)

    def ingest_instrument_master_bytes(self, raw_bytes, provider, original_filename, source_reference, **metadata):
        """Atomically retain accepted, incomplete and rejected candidates without replacing evidence."""
        from instrument_archive import prepare_archive
        if "ingested_at" in metadata:
            raise IdentityValidationError("INGESTION_TIME_IS_LOCAL", "Ingestion time is calculated locally; supply capture/publication claims separately.")
        candidate = prepare_archive(raw_bytes, provider, original_filename, source_reference, **metadata)
        payload = json.dumps(candidate, sort_keys=True, allow_nan=False)
        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("INSERT OR IGNORE INTO instrument_master_archives VALUES (?, ?, ?, ?, ?)",
                                 (candidate["archive_id"], provider, candidate["status"], raw_bytes, payload))
                # The first ingestion timestamp is retained on idempotent retries.
                return self.get_instrument_master_archive(candidate["archive_id"])
            finally:
                self._close_if_file(conn)

    def ingest_instrument_master_file(self, path, provider, source_reference, *, import_root=".", **metadata):
        """Read a regular local JSON file under an explicit root. Never write to its filename."""
        from pathlib import Path
        from instrument_archive import MAX_ARCHIVE_BYTES
        from instrument_identity import reject
        supplied = Path(path)
        if (".." in supplied.parts or str(path).startswith(("//", "\\\\"))
                or str(import_root).startswith(("//", "\\\\"))):
            reject("UNSAFE_ARCHIVE_PATH", "Traversal and network archive paths are unsupported.")
        root = Path(import_root).resolve(strict=True)
        target = supplied if supplied.is_absolute() else root / supplied
        if target.is_symlink() or not target.resolve(strict=True).is_relative_to(root):
            reject("UNSAFE_ARCHIVE_PATH", "Archive must be a regular file inside the import root.")
        target = target.resolve(strict=True)
        if not target.is_file() or target.stat().st_size > MAX_ARCHIVE_BYTES:
            reject("INVALID_ARCHIVE_SIZE", "Archive must be a regular file of at most 64 MiB.")
        with target.open("rb") as stream:
            raw_bytes = stream.read(MAX_ARCHIVE_BYTES + 1)
        return self.ingest_instrument_master_bytes(raw_bytes, provider, target.name, source_reference,
                                                   input_kind="LOCAL_FILE", **metadata)

    def get_instrument_master_archive(self, archive_id, *, include_original=False):
        """Revalidate original bytes and normalized evidence on every read; no mutable trust cache."""
        from instrument_archive import prepare_archive
        from instrument_identity import reject
        with self._db_lock:
            conn = self._get_connection()
            try:
                row = conn.execute("SELECT * FROM instrument_master_archives WHERE archive_id=?", (archive_id,)).fetchone()
            finally:
                self._close_if_file(conn)
        if row is None:
            reject("ARCHIVE_NOT_FOUND", "Instrument-master archive was not found.")
        try:
            candidate = json.loads(row["candidate_json"])
            m = candidate["metadata"]
            verified = prepare_archive(bytes(row["original_bytes"]), row["provider"], m["original_filename"],
                m["source_reference"], captured_at=m["captured_at"], publisher_published_at=m["publisher_published_at"],
                source_url=m["source_url"], ingested_at=candidate["ingested_at"], input_kind=m["input_kind"])
            if verified != candidate or row["archive_id"] != verified["archive_id"] or row["status"] != verified["status"]:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            reject("ARCHIVE_INTEGRITY_FAILURE", "Stored original bytes, provenance or normalized content disagree.")
        if include_original:
            candidate["original_bytes"] = bytes(row["original_bytes"])
        return candidate

    def list_instrument_master_archives(self, provider=None):
        """Return summaries; original bytes are accessible only through explicit local retrieval."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                if provider is None:
                    rows = conn.execute("SELECT archive_id FROM instrument_master_archives ORDER BY archive_id").fetchall()
                else:
                    rows = conn.execute("SELECT archive_id FROM instrument_master_archives WHERE provider=? ORDER BY archive_id",
                                        (provider,)).fetchall()
            finally:
                self._close_if_file(conn)
        return [self.get_instrument_master_archive(row[0]) for row in rows]

    def qualify_instrument_master_archive(self, archive_id):
        """Persist a versioned evidence assessment; never import a submitter's trust verdict."""
        from source_qualification import assess_source_evidence
        from instrument_identity import reject
        archive = self.get_instrument_master_archive(archive_id, include_original=True)
        assessment = assess_source_evidence(archive, archive.pop("original_bytes"))
        payload = json.dumps(assessment, sort_keys=True, allow_nan=False)
        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("INSERT OR IGNORE INTO instrument_source_assessments VALUES (?, ?, ?)",
                                 (archive_id, assessment["policy_version"], payload))
                    previous = conn.execute("SELECT assessment_json FROM instrument_source_assessments "
                        "WHERE archive_id=? AND policy_version=?", (archive_id, assessment["policy_version"])).fetchone()
                    if previous[0] != payload:
                        reject("SOURCE_ASSESSMENT_INTEGRITY_FAILURE", "Stored assessment disagrees with current evidence/policy; a saved verdict cannot grant trust.")
            finally:
                self._close_if_file(conn)
        return assessment

    def inspect_archived_instrument_identity(self, provider, symbol, identifier, exchange, instrument_type,
                                             first_date, last_date, lot_size=None, archive_id=None):
        """Metadata inspection only; a resolved declaration never authorizes LIVE replay."""
        from instrument_archive import resolve_archive_declarations
        identity = resolve_archive_declarations(self.list_instrument_master_archives(provider), provider, symbol, identifier,
                                                exchange, instrument_type, first_date, last_date, lot_size, archive_id)
        identity["source_qualification"] = self.qualify_instrument_master_archive(identity["archive_id"])
        identity["live_historical_eligible"] = identity["source_qualification"]["historical_eligibility"]["allowed"]
        return identity

    def resolve_archived_instrument_identity(self, provider, symbol, identifier, exchange, instrument_type,
                                             first_date, last_date, lot_size=None, archive_id=None):
        from instrument_archive import resolve_archives
        archives = self.list_instrument_master_archives(provider)
        for archive in archives:
            archive["source_qualification"] = self.qualify_instrument_master_archive(archive["archive_id"])
            archive["original_bytes"] = self.get_instrument_master_archive(archive["archive_id"], include_original=True)["original_bytes"]
        return resolve_archives(archives, provider, symbol, identifier,
                                exchange, instrument_type, first_date, last_date, lot_size, archive_id)

    def _save_live_acceptance_evidence(self, provider: str, symbol: str, evidence: Dict[str, Any]) -> None:
        """Internal diagnostic writer. Local DB writers are inside the trust boundary."""
        payload = json.dumps(evidence, sort_keys=True, allow_nan=False)
        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("INSERT OR REPLACE INTO live_acceptance_evidence VALUES (?, ?, ?)",
                                 (provider, symbol, payload))
            finally:
                self._close_if_file(conn)

    def load_live_acceptance_evidence(self, provider: str, symbol: str) -> Optional[Dict[str, Any]]:
        with self._db_lock:
            conn = self._get_connection()
            try:
                row = conn.execute("SELECT evidence_json FROM live_acceptance_evidence WHERE provider=? AND symbol=?",
                                   (provider, symbol)).fetchone()
                return json.loads(row[0]) if row else None
            finally:
                self._close_if_file(conn)

    def _revoke_live_acceptance_evidence(self, provider: str, symbol: str) -> None:
        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM live_acceptance_evidence WHERE provider=? AND symbol=?", (provider, symbol))
            finally:
                self._close_if_file(conn)

    def check_health(self) -> Dict[str, Any]:
        """Verifies database connectivity and returns table row counts."""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                sig_count = cur.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
                scan_count = cur.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0]
                oi_count = cur.execute("SELECT COUNT(*) FROM oi_snapshots").fetchone()[0]
                oi_base_count = cur.execute("SELECT COUNT(*) FROM oi_baselines").fetchone()[0]
                oi_closing_count = cur.execute(
                    "SELECT COUNT(*) FROM oi_baselines WHERE baseline_kind = 'CLOSING_BASELINE'"
                ).fetchone()[0]
                oi_intraday_obs_count = cur.execute(
                    "SELECT COUNT(*) FROM oi_baselines WHERE baseline_kind = 'INTRADAY_OBSERVATION'"
                ).fetchone()[0]
                oi_live_closing_count = cur.execute(
                    "SELECT COUNT(*) FROM oi_baselines WHERE data_mode = 'LIVE' AND baseline_kind = 'CLOSING_BASELINE'"
                ).fetchone()[0]
                ob_count = cur.execute("SELECT COUNT(*) FROM mitigated_order_blocks").fetchone()[0]
                ob_count += cur.execute("SELECT COUNT(*) FROM scoped_mitigated_order_blocks").fetchone()[0]
                hist_ds_count = cur.execute("SELECT COUNT(*) FROM historical_datasets").fetchone()[0]
                hist_candles_count = cur.execute("SELECT COUNT(*) FROM historical_candles").fetchone()[0]
                hist_live_candles_count = cur.execute(
                    "SELECT COUNT(*) FROM historical_candles WHERE data_mode = 'LIVE'"
                ).fetchone()[0]
                bt_runs_count = cur.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
                bt_trades_count = cur.execute("SELECT COUNT(*) FROM backtest_trades").fetchone()[0]
                return {
                    "status": "OK",
                    "database_path": self.db_path,
                    "signals_count": int(sig_count),
                    "scan_runs_count": int(scan_count),
                    "oi_snapshots_count": int(oi_count),
                    "oi_baselines_count": int(oi_base_count),
                    "oi_closing_baselines_count": int(oi_closing_count),
                    "oi_intraday_observations_count": int(oi_intraday_obs_count),
                    "oi_live_closing_baselines_count": int(oi_live_closing_count),
                    "mitigated_order_blocks_count": int(ob_count),
                    "historical_datasets_count": int(hist_ds_count),
                    "historical_candles_count": int(hist_candles_count),
                    "historical_live_candles_count": int(hist_live_candles_count),
                    "backtest_runs_count": int(bt_runs_count),
                    "backtest_trades_count": int(bt_trades_count),
                }
            except Exception as exc:
                logger.error("Database health check failed: %s", exc)
                raise PersistenceError(f"Database health check failed: {exc}") from exc
            finally:
                self._close_if_file(conn)

    # ------------------------------------------------------------------------
    # Persistent OI Baseline Lifecycle (Phase 2B & Phase 2C Provenance Hardening)
    # ------------------------------------------------------------------------
    def _validate_single_baseline_record(
        self,
        rec: Dict[str, Any],
        ref_now_ist: datetime,
        configured_holidays: Optional[List[str]] = None,
        require_closing_evidence: bool = False,
        auto_classify_by_timestamp: bool = False,
    ) -> Dict[str, Any]:
        if not isinstance(rec, dict):
            raise PersistenceValidationError("OI baseline record must be a dictionary.")

        idx_sym = str(rec.get("index_symbol") or rec.get("index") or "").strip().upper()
        if idx_sym not in ("NIFTY", "BANKNIFTY"):
            raise PersistenceValidationError(
                f"Invalid OI baseline index_symbol {idx_sym!r}. Expected 'NIFTY' or 'BANKNIFTY'."
            )

        expiry = str(rec.get("expiry") or "").strip()
        if not expiry:
            raise PersistenceValidationError("OI baseline record is missing required 'expiry' (YYYY-MM-DD).")
        try:
            exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        except ValueError as exc:
            raise PersistenceValidationError(f"Invalid OI baseline expiry {expiry!r}. Expected YYYY-MM-DD.") from exc

        raw_strike = rec.get("strike")
        if raw_strike is None or isinstance(raw_strike, bool):
            raise PersistenceValidationError("OI baseline record is missing a valid 'strike'.")
        try:
            strike_flt = float(raw_strike)
        except (TypeError, ValueError) as exc:
            raise PersistenceValidationError(f"Invalid non-numeric strike {raw_strike!r}.") from exc
        if not math.isfinite(strike_flt) or strike_flt <= 0 or abs(strike_flt - round(strike_flt)) > 1e-4:
            raise PersistenceValidationError(f"OI baseline strike must be a positive integer, got {raw_strike!r}.")
        strike_int = int(round(strike_flt))
        step = 50 if idx_sym == "NIFTY" else 100
        if strike_int % step != 0:
            raise PersistenceValidationError(
                f"OI baseline strike {strike_int} for {idx_sym} is not aligned to strike step {step}."
            )

        opt_type = str(rec.get("option_type") or rec.get("side") or "").strip().upper()
        if opt_type not in ("CE", "PE"):
            raise PersistenceValidationError(
                f"Invalid OI baseline option_type {opt_type!r}. Expected 'CE' or 'PE'."
            )

        raw_oi = rec.get("open_interest")
        if raw_oi is None or isinstance(raw_oi, bool):
            raise PersistenceValidationError(
                f"OI baseline record for {idx_sym} {expiry} {strike_int} {opt_type} has missing/null open_interest."
            )
        try:
            oi_flt = float(raw_oi)
        except (TypeError, ValueError) as exc:
            raise PersistenceValidationError(f"OI baseline open_interest must be numeric, got {raw_oi!r}.") from exc
        if not math.isfinite(oi_flt) or oi_flt < 0 or abs(oi_flt - round(oi_flt)) > 1e-4:
            raise PersistenceValidationError(
                f"OI baseline open_interest must be a non-negative integer, got {raw_oi!r}."
            )
        oi_int = int(round(oi_flt))

        source = str(rec.get("source") or "").strip()
        if not source:
            raise PersistenceValidationError("OI baseline record is missing required 'source' provenance.")

        raw_obs_ts = rec.get("observation_timestamp")
        if raw_obs_ts is None or (isinstance(raw_obs_ts, str) and not raw_obs_ts.strip()):
            raise PersistenceValidationError("OI baseline record is missing required 'observation_timestamp'.")
        try:
            obs_dt = parse_ist_timestamp(raw_obs_ts)
        except ValueError as exc:
            raise PersistenceValidationError(f"Invalid OI baseline observation_timestamp: {exc}") from exc

        # Reject future-dated baseline observations (allowing up to 60s minor clock skew)
        if obs_dt > ref_now_ist + timedelta(seconds=60):
            raise PersistenceValidationError(
                f"OI baseline observation_timestamp {format_ist_timestamp(obs_dt)} is in the future "
                f"relative to current IST clock {format_ist_timestamp(ref_now_ist)}."
            )
        obs_ts_str = format_ist_timestamp(obs_dt)
        obs_date_str = obs_dt.strftime("%Y-%m-%d")

        raw_session_date = str(rec.get("session_date") or "").strip()
        if raw_session_date:
            try:
                sess_date = datetime.strptime(raw_session_date, "%Y-%m-%d").date()
            except ValueError as exc:
                raise PersistenceValidationError(
                    f"Invalid OI baseline session_date {raw_session_date!r}. Expected YYYY-MM-DD."
                ) from exc
            if raw_session_date != obs_date_str:
                raise PersistenceValidationError(
                    f"OI baseline session_date {raw_session_date} does not match observation_timestamp date {obs_date_str}."
                )
        else:
            sess_date = obs_dt.date()
            raw_session_date = obs_date_str

        if sess_date.weekday() >= 5:
            raise PersistenceValidationError(
                f"OI baseline session_date {raw_session_date} falls on a weekend (non-trading day)."
            )
        holiday_set = {str(h).strip() for h in (configured_holidays or []) if str(h).strip()}
        if raw_session_date in holiday_set:
            raise PersistenceValidationError(
                f"OI baseline session_date {raw_session_date} is a configured NSE market holiday."
            )
        if exp_date < sess_date:
            raise PersistenceValidationError(
                f"OI baseline expiry {expiry} is earlier than session_date {raw_session_date} (expired contract)."
            )

        raw_mode = str(rec.get("data_mode") or "").strip().upper()
        if raw_mode not in ("LIVE", "SIMULATED"):
            raise PersistenceValidationError(
                f"Invalid OI baseline data_mode {raw_mode!r}. Expected 'LIVE' or 'SIMULATED'."
            )
        if "is_simulated" in rec and rec["is_simulated"] is not None:
            is_sim_flag = bool(rec["is_simulated"])
            if (is_sim_flag and raw_mode != "SIMULATED") or (not is_sim_flag and raw_mode != "LIVE"):
                raise PersistenceValidationError(
                    f"OI baseline provenance mismatch: data_mode={raw_mode!r} conflicts with is_simulated={is_sim_flag}."
                )
        else:
            is_sim_flag = raw_mode == "SIMULATED"

        src_low = source.lower()
        if raw_mode == "LIVE" and ("sim" in src_low or "paper" in src_low or "mock" in src_low):
            raise PersistenceValidationError(
                f"Cannot persist simulated source '{source}' with data_mode='LIVE'."
            )
        if raw_mode == "SIMULATED" and "live" in src_low:
            raise PersistenceValidationError(
                f"Cannot persist live source '{source}' with data_mode='SIMULATED'."
            )

        # Phase 2C Provenance Rule: Distinguish CLOSING_BASELINE vs INTRADAY_OBSERVATION
        is_closing_time = is_closing_session_timestamp(obs_dt)
        is_intraday_source = "intraday" in src_low
        explicit_kind = str(rec.get("baseline_kind") or "").strip().upper()

        if explicit_kind and explicit_kind not in ("CLOSING_BASELINE", "INTRADAY_OBSERVATION"):
            raise PersistenceValidationError(
                f"Invalid baseline_kind {explicit_kind!r}. Expected 'CLOSING_BASELINE' or 'INTRADAY_OBSERVATION'."
            )

        if explicit_kind == "CLOSING_BASELINE" and is_intraday_source:
            raise PersistenceValidationError(
                f"Cannot promote intraday source '{source}' (@ {obs_ts_str}) to CLOSING_BASELINE."
            )

        if require_closing_evidence:
            if is_intraday_source or not is_closing_time:
                raise PersistenceValidationError(
                    f"Cannot promote arbitrary intraday OI observation at {obs_ts_str} (< 15:25:00 IST session close) "
                    f"from source '{source}' to a prior-session CLOSING_BASELINE without session-close evidence."
                )
            baseline_kind = "CLOSING_BASELINE"
        elif explicit_kind:
            if explicit_kind == "CLOSING_BASELINE" and auto_classify_by_timestamp and not is_closing_time:
                raise PersistenceValidationError(
                    f"Cannot label mid-session observation at {obs_ts_str} (< 15:25:00 IST) as CLOSING_BASELINE."
                )
            baseline_kind = explicit_kind
        elif is_intraday_source:
            baseline_kind = "INTRADAY_OBSERVATION"
        elif auto_classify_by_timestamp:
            baseline_kind = "CLOSING_BASELINE" if is_closing_time else "INTRADAY_OBSERVATION"
        else:
            baseline_kind = "CLOSING_BASELINE"

        dedup_key = compute_oi_baseline_dedup_key(
            index_symbol=idx_sym,
            expiry=expiry,
            strike=strike_int,
            option_type=opt_type,
            session_date=raw_session_date,
            data_mode=raw_mode,
        )
        return {
            "dedup_key": dedup_key,
            "index_symbol": idx_sym,
            "expiry": expiry,
            "strike": strike_int,
            "option_type": opt_type,
            "open_interest": oi_int,
            "source": source,
            "baseline_kind": baseline_kind,
            "observation_timestamp": obs_ts_str,
            "session_date": raw_session_date,
            "data_mode": raw_mode,
            "is_simulated": 1 if is_sim_flag else 0,
        }

    def save_oi_baseline_records(
        self,
        records: List[Dict[str, Any]],
        now_ist: Optional[Any] = None,
        configured_holidays: Optional[List[str]] = None,
        allow_newer_intraday_update: bool = True,
        require_closing_evidence: bool = False,
        auto_classify_by_timestamp: bool = False,
    ) -> Dict[str, Any]:
        """
        Validates and persists a batch of strike-level OI baseline records in a single
        atomic SQLite transaction (`oi_baselines` table).
        - Idempotent when identical records are re-submitted (`unchanged_count`).
        - Updates existing same-session record when `allow_newer_intraday_update=True` and
          the incoming record has a strictly newer `observation_timestamp` (`updated_count`),
          EXCEPT an `INTRADAY_OBSERVATION` record may NEVER overwrite or downgrade an
          existing `CLOSING_BASELINE` record.
        - Rejects conflicting duplicate records (same dedup_key + same or older timestamp
          with different `open_interest`) by raising `PersistenceValidationError` and
          rolling back the entire transaction.
        """
        if not isinstance(records, list) or not records:
            raise PersistenceValidationError("save_oi_baseline_records requires a non-empty list of records.")

        ref_now = parse_ist_timestamp(now_ist or datetime.now(IST))
        now_str = format_ist_timestamp(ref_now)

        validated_by_key: Dict[str, Dict[str, Any]] = {}
        for rec in records:
            norm = self._validate_single_baseline_record(
                rec,
                ref_now_ist=ref_now,
                configured_holidays=configured_holidays,
                require_closing_evidence=require_closing_evidence,
                auto_classify_by_timestamp=auto_classify_by_timestamp,
            )
            dk = norm["dedup_key"]
            if dk in validated_by_key:
                prev = validated_by_key[dk]
                if (
                    prev["open_interest"] == norm["open_interest"]
                    and prev["observation_timestamp"] == norm["observation_timestamp"]
                    and prev["baseline_kind"] == norm["baseline_kind"]
                ):
                    continue
                raise PersistenceValidationError(
                    f"Batch contains conflicting duplicate OI baseline records for key {dk} "
                    f"(OI {prev['open_interest']} @ {prev['observation_timestamp']} [{prev['baseline_kind']}] vs "
                    f"OI {norm['open_interest']} @ {norm['observation_timestamp']} [{norm['baseline_kind']}])."
                )
            validated_by_key[dk] = norm

        inserted = 0
        updated = 0
        unchanged = 0

        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    for dk, norm in validated_by_key.items():
                        existing = conn.execute(
                            """
                            SELECT id, open_interest, observation_timestamp, source, baseline_kind
                            FROM oi_baselines
                            WHERE dedup_key = ?
                            """,
                            (dk,),
                        ).fetchone()

                        if existing is None:
                            conn.execute(
                                """
                                INSERT INTO oi_baselines (
                                    dedup_key, index_symbol, expiry, strike, option_type,
                                    open_interest, source, baseline_kind, observation_timestamp, session_date,
                                    data_mode, is_simulated, created_at_ist, updated_at_ist
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    norm["dedup_key"],
                                    norm["index_symbol"],
                                    norm["expiry"],
                                    norm["strike"],
                                    norm["option_type"],
                                    norm["open_interest"],
                                    norm["source"],
                                    norm["baseline_kind"],
                                    norm["observation_timestamp"],
                                    norm["session_date"],
                                    norm["data_mode"],
                                    norm["is_simulated"],
                                    now_str,
                                    now_str,
                                ),
                            )
                            inserted += 1
                        else:
                            ex_oi = int(existing["open_interest"])
                            ex_ts = str(existing["observation_timestamp"])
                            ex_kind = str(existing["baseline_kind"] or "CLOSING_BASELINE").upper()
                            new_oi = int(norm["open_interest"])
                            new_ts = str(norm["observation_timestamp"])
                            new_kind = str(norm["baseline_kind"]).upper()

                            # Never allow an INTRADAY_OBSERVATION to downgrade an existing CLOSING_BASELINE
                            if ex_kind == "CLOSING_BASELINE" and new_kind == "INTRADAY_OBSERVATION":
                                raise PersistenceValidationError(
                                    f"Cannot overwrite verified CLOSING_BASELINE for {dk} (@ {ex_ts}) "
                                    f"with an INTRADAY_OBSERVATION (@ {new_ts})."
                                )

                            if ex_oi == new_oi and new_ts <= ex_ts and ex_kind == new_kind:
                                unchanged += 1
                            elif allow_newer_intraday_update and (
                                new_ts > ex_ts
                                or (ex_kind == "INTRADAY_OBSERVATION" and new_kind == "CLOSING_BASELINE")
                            ):
                                if ex_oi == new_oi and ex_kind == new_kind:
                                    conn.execute(
                                        """
                                        UPDATE oi_baselines
                                        SET observation_timestamp = ?, source = ?, updated_at_ist = ?
                                        WHERE dedup_key = ?
                                        """,
                                        (new_ts, norm["source"], now_str, dk),
                                    )
                                    unchanged += 1
                                else:
                                    conn.execute(
                                        """
                                        UPDATE oi_baselines
                                        SET open_interest = ?, observation_timestamp = ?, source = ?, baseline_kind = ?, updated_at_ist = ?
                                        WHERE dedup_key = ?
                                        """,
                                        (new_oi, new_ts, norm["source"], new_kind, now_str, dk),
                                    )
                                    updated += 1
                            else:
                                raise PersistenceValidationError(
                                    f"Conflicting OI baseline record for {dk}: existing OI={ex_oi} "
                                    f"(@ {ex_ts} [{ex_kind}]) conflicts with incoming OI={new_oi} (@ {new_ts} [{new_kind}])."
                                )
                return {
                    "inserted_count": inserted,
                    "updated_count": updated,
                    "unchanged_count": unchanged,
                    "total_processed": len(validated_by_key),
                }
            except (PersistenceValidationError, PersistenceError):
                raise
            except Exception as exc:
                logger.error("Failed to save OI baseline records: %s", exc)
                raise PersistenceError(f"Failed to save OI baseline records: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def save_paired_strike_baselines(
        self,
        index_symbol: str,
        expiry: str,
        baseline_by_strike: Dict[int, Dict[str, Any]],
        session_date: str,
        observation_timestamp: Any,
        source: str = "angelone_live_quote",
        data_mode: str = "LIVE",
        now_ist: Optional[Any] = None,
        configured_holidays: Optional[List[str]] = None,
        allow_newer_intraday_update: bool = True,
        baseline_kind: Optional[str] = None,
        require_closing_evidence: bool = False,
        auto_classify_by_timestamp: bool = False,
    ) -> Dict[str, Any]:
        """
        Persists a dictionary of paired CE/PE strike open interest values
        (`{strike: {"ce_prev_oi": int, "pe_prev_oi": int}}` or `{strike: {"ce_oi": int, "pe_oi": int}}`)
        into `oi_baselines` atomically. Rejects incomplete CE/PE pairs.
        """
        if not isinstance(baseline_by_strike, dict) or not baseline_by_strike:
            raise PersistenceValidationError("baseline_by_strike must be a non-empty dictionary.")

        records: List[Dict[str, Any]] = []
        for k, leg_dict in sorted(baseline_by_strike.items(), key=lambda item: float(item[0])):
            if not isinstance(leg_dict, dict):
                raise PersistenceValidationError(f"Strike {k} baseline entry must be a dict.")
            ce_val = leg_dict.get("ce_prev_oi") if "ce_prev_oi" in leg_dict else leg_dict.get("ce_oi")
            pe_val = leg_dict.get("pe_prev_oi") if "pe_prev_oi" in leg_dict else leg_dict.get("pe_oi")
            if ce_val is None or pe_val is None or isinstance(ce_val, bool) or isinstance(pe_val, bool):
                raise PersistenceValidationError(
                    f"Incomplete CE/PE baseline pair for strike {k}: both CE and PE open interest are required."
                )
            rec_ce: Dict[str, Any] = {
                "index_symbol": index_symbol,
                "expiry": expiry,
                "strike": k,
                "option_type": "CE",
                "open_interest": ce_val,
                "source": source,
                "observation_timestamp": observation_timestamp,
                "session_date": session_date,
                "data_mode": data_mode,
            }
            rec_pe: Dict[str, Any] = {
                "index_symbol": index_symbol,
                "expiry": expiry,
                "strike": k,
                "option_type": "PE",
                "open_interest": pe_val,
                "source": source,
                "observation_timestamp": observation_timestamp,
                "session_date": session_date,
                "data_mode": data_mode,
            }
            if baseline_kind:
                rec_ce["baseline_kind"] = baseline_kind
                rec_pe["baseline_kind"] = baseline_kind
            records.append(rec_ce)
            records.append(rec_pe)

        return self.save_oi_baseline_records(
            records=records,
            now_ist=now_ist,
            configured_holidays=configured_holidays,
            allow_newer_intraday_update=allow_newer_intraday_update,
            require_closing_evidence=require_closing_evidence,
            auto_classify_by_timestamp=auto_classify_by_timestamp,
        )

    def import_prior_oi_baseline_file(
        self,
        file_path: str,
        default_index_symbol: Optional[str] = None,
        default_expiry: Optional[str] = None,
        default_session_date: Optional[str] = None,
        source: str = "external_verified_closing_import",
        data_mode: str = "LIVE",
        now_ist: Optional[Any] = None,
        configured_holidays: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Documented, validated external import workflow for prior-session closing OI baselines:
        Supports JSON (either a list of row objects or a `{"index_symbol", "expiry", "session_date",
        "observation_timestamp", "strikes": {"24800": {"ce_prev_oi": ..., "pe_prev_oi": ...}}}` object)
        and CSV files.
        - Validates that every imported session_date is strictly prior to the current trading session (`< curr_session_date`).
        - Validates that observation timestamps represent session close (`>= 15:25:00 IST`); rejects arbitrary mid-day timestamps.
        - Enforces complete CE/PE pairing for every `(index_symbol, expiry, session_date, strike)`.
        - Enforces `LIVE` vs `SIMULATED` provenance isolation.
        """
        if not isinstance(file_path, str) or not file_path.strip() or not os.path.isfile(file_path.strip()):
            raise PersistenceValidationError(f"OI baseline import file not found: {file_path!r}")

        clean_path = file_path.strip()
        ref_now = parse_ist_timestamp(now_ist or datetime.now(IST))
        curr_session = resolve_effective_trading_session_date(ref_now, configured_holidays)
        curr_session_str = curr_session.strftime("%Y-%m-%d")

        raw_records: List[Dict[str, Any]] = []
        _, ext = os.path.splitext(clean_path.lower())

        try:
            if ext == ".csv":
                with open(clean_path, "r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if not isinstance(row, dict):
                            continue
                        idx_sym = (row.get("index_symbol") or row.get("index") or default_index_symbol or "").strip().upper()
                        exp_str = (row.get("expiry") or default_expiry or "").strip()
                        sess_str = (row.get("session_date") or default_session_date or "").strip()
                        obs_ts = (row.get("observation_timestamp") or (f"{sess_str} 15:30:00" if sess_str else "")).strip()
                        row_src = (row.get("source") or source).strip()
                        row_dm = (row.get("data_mode") or data_mode).strip().upper()
                        strike_val = row.get("strike")
                        ce_col = row.get("ce_prev_oi") if row.get("ce_prev_oi") not in (None, "") else row.get("ce_oi")
                        pe_col = row.get("pe_prev_oi") if row.get("pe_prev_oi") not in (None, "") else row.get("pe_oi")
                        if ce_col not in (None, "") and pe_col not in (None, ""):
                            raw_records.append({
                                "index_symbol": idx_sym,
                                "expiry": exp_str,
                                "strike": strike_val,
                                "option_type": "CE",
                                "open_interest": ce_col,
                                "session_date": sess_str,
                                "observation_timestamp": obs_ts,
                                "source": row_src,
                                "data_mode": row_dm,
                                "baseline_kind": "CLOSING_BASELINE",
                            })
                            raw_records.append({
                                "index_symbol": idx_sym,
                                "expiry": exp_str,
                                "strike": strike_val,
                                "option_type": "PE",
                                "open_interest": pe_col,
                                "session_date": sess_str,
                                "observation_timestamp": obs_ts,
                                "source": row_src,
                                "data_mode": row_dm,
                                "baseline_kind": "CLOSING_BASELINE",
                            })
                        else:
                            raw_records.append({
                                "index_symbol": idx_sym,
                                "expiry": exp_str,
                                "strike": strike_val,
                                "option_type": row.get("option_type") or row.get("side"),
                                "open_interest": row.get("open_interest") if row.get("open_interest") is not None else row.get("oi"),
                                "session_date": sess_str,
                                "observation_timestamp": obs_ts,
                                "source": row_src,
                                "data_mode": row_dm,
                                "baseline_kind": "CLOSING_BASELINE",
                            })
            else:
                with open(clean_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict) and isinstance(payload.get("strikes"), dict):
                    idx_sym = str(payload.get("index_symbol") or payload.get("index") or default_index_symbol or "").strip().upper()
                    exp_str = str(payload.get("expiry") or default_expiry or "").strip()
                    sess_str = str(payload.get("session_date") or default_session_date or "").strip()
                    obs_ts = str(payload.get("observation_timestamp") or (f"{sess_str} 15:30:00" if sess_str else "")).strip()
                    obj_src = str(payload.get("source") or source).strip()
                    obj_dm = str(payload.get("data_mode") or data_mode).strip().upper()
                    for k_str, legs in payload["strikes"].items():
                        if not isinstance(legs, dict):
                            raise PersistenceValidationError(f"Strike {k_str} entry in import file must be a JSON object.")
                        ce_v = legs.get("ce_prev_oi") if "ce_prev_oi" in legs else legs.get("ce_oi")
                        pe_v = legs.get("pe_prev_oi") if "pe_prev_oi" in legs else legs.get("pe_oi")
                        raw_records.append({
                            "index_symbol": idx_sym,
                            "expiry": exp_str,
                            "strike": k_str,
                            "option_type": "CE",
                            "open_interest": ce_v,
                            "session_date": sess_str,
                            "observation_timestamp": obs_ts,
                            "source": obj_src,
                            "data_mode": obj_dm,
                            "baseline_kind": "CLOSING_BASELINE",
                        })
                        raw_records.append({
                            "index_symbol": idx_sym,
                            "expiry": exp_str,
                            "strike": k_str,
                            "option_type": "PE",
                            "open_interest": pe_v,
                            "session_date": sess_str,
                            "observation_timestamp": obs_ts,
                            "source": obj_src,
                            "data_mode": obj_dm,
                            "baseline_kind": "CLOSING_BASELINE",
                        })
                elif isinstance(payload, list):
                    for item in payload:
                        if not isinstance(item, dict):
                            raise PersistenceValidationError("Each item in baseline JSON array must be an object.")
                        sess_str = str(item.get("session_date") or default_session_date or "").strip()
                        raw_records.append({
                            "index_symbol": item.get("index_symbol") or item.get("index") or default_index_symbol,
                            "expiry": item.get("expiry") or default_expiry,
                            "strike": item.get("strike"),
                            "option_type": item.get("option_type") or item.get("side"),
                            "open_interest": item.get("open_interest") if "open_interest" in item else item.get("oi"),
                            "session_date": sess_str,
                            "observation_timestamp": item.get("observation_timestamp") or (f"{sess_str} 15:30:00" if sess_str else None),
                            "source": item.get("source") or source,
                            "data_mode": item.get("data_mode") or data_mode,
                            "baseline_kind": item.get("baseline_kind") or "CLOSING_BASELINE",
                        })
                else:
                    raise PersistenceValidationError("Unsupported JSON baseline structure. Expected a list of records or a paired 'strikes' object.")
        except PersistenceValidationError:
            raise
        except Exception as exc:
            raise PersistenceValidationError(f"Failed to parse OI baseline import file {os.path.basename(clean_path)}: {exc}") from exc

        if not raw_records:
            raise PersistenceValidationError("OI baseline import file contains 0 records.")

        # Validate every record with `require_closing_evidence=True` and verify complete CE/PE pairing + prior session_date
        pair_tracker: Dict[Tuple[str, str, str, int], Set[str]] = {}
        for rec in raw_records:
            norm = self._validate_single_baseline_record(
                rec,
                ref_now_ist=ref_now,
                configured_holidays=configured_holidays,
                require_closing_evidence=True,
            )
            if norm["session_date"] >= curr_session_str:
                raise PersistenceValidationError(
                    f"Imported prior-session baseline session_date ({norm['session_date']}) must be strictly earlier "
                    f"than current trading session ({curr_session_str})."
                )
            pair_key = (norm["index_symbol"], norm["expiry"], norm["session_date"], norm["strike"])
            pair_tracker.setdefault(pair_key, set()).add(norm["option_type"])

        incomplete_pairs = [
            f"{sym} {exp} {sess} strike {stk}"
            for (sym, exp, sess, stk), sides in sorted(pair_tracker.items())
            if sides != {"CE", "PE"}
        ]
        if incomplete_pairs:
            raise PersistenceValidationError(
                f"OI baseline import rejected due to incomplete CE/PE strike pairs: {', '.join(incomplete_pairs)}."
            )

        res = self.save_oi_baseline_records(
            records=raw_records,
            now_ist=ref_now,
            configured_holidays=configured_holidays,
            allow_newer_intraday_update=True,
            require_closing_evidence=True,
        )
        res["status"] = "IMPORTED"
        res["baseline_kind"] = "CLOSING_BASELINE"
        res["imported_file"] = os.path.basename(clean_path)
        res["paired_strikes_imported"] = len(pair_tracker)
        res["paired_strikes_count"] = len(pair_tracker)
        return res

    def load_prior_session_oi_baseline(
        self,
        index_symbol: str,
        expiry: str,
        current_session_date: Optional[Any] = None,
        data_mode: str = "LIVE",
        configured_holidays: Optional[List[str]] = None,
        max_sessions_age: int = 1,
        required_strikes: Optional[List[int]] = None,
        now_ist: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Loads and validates the prior trading session's closing OI baseline (`ce_prev_oi`, `pe_prev_oi`)
        for `(index_symbol, expiry, data_mode)`:
        - Strictly isolates `LIVE` and `SIMULATED` data modes.
        - Requires `session_date < current_session_date` so same-session intraday OI observations
          are NEVER substituted for previous-session closing OI.
        - Requires `baseline_kind == 'CLOSING_BASELINE'`: arbitrary mid-day `INTRADAY_OBSERVATION`
          records from a prior day are never promoted to a closing baseline!
        - Validates contract expiry (`expiry >= current_session_date`).
        - Validates session freshness across weekends and `configured_holidays` (`sessions_age <= max_sessions_age`).
        - Validates complete CE/PE pairs on every strike and rejects future-dated observations.
        - Never fabricates previous OI or backfills missing values with zero.
        """
        sym = str(index_symbol or "").strip().upper()
        if sym not in ("NIFTY", "BANKNIFTY"):
            raise ValueError(f"Unsupported index_symbol {index_symbol!r}. Expected 'NIFTY' or 'BANKNIFTY'.")

        exp_str = str(expiry or "").strip()
        try:
            datetime.strptime(exp_str, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Invalid expiry {expiry!r}. Expected YYYY-MM-DD.") from exc

        dm = str(data_mode or "").strip().upper()
        if dm not in ("LIVE", "SIMULATED"):
            raise ValueError(f"Invalid data_mode {data_mode!r}. Expected 'LIVE' or 'SIMULATED'.")

        if isinstance(max_sessions_age, bool) or not isinstance(max_sessions_age, int) or max_sessions_age < 1:
            raise ValueError("max_sessions_age must be an integer >= 1.")

        ref_now = parse_ist_timestamp(now_ist or datetime.now(IST))
        if current_session_date is not None:
            curr_date = resolve_effective_trading_session_date(current_session_date, configured_holidays)
        else:
            curr_date = resolve_effective_trading_session_date(ref_now, configured_holidays)

        curr_date_str = curr_date.strftime("%Y-%m-%d")
        expected_prior_date = resolve_prior_trading_session_date(curr_date, configured_holidays)
        expected_prior_str = expected_prior_date.strftime("%Y-%m-%d")

        if exp_str < curr_date_str:
            return {
                "status": "EXPIRED_CONTRACT",
                "usable": False,
                "index_symbol": sym,
                "expiry": exp_str,
                "data_mode": dm,
                "current_session_date": curr_date_str,
                "expected_prior_session_date": expected_prior_str,
                "baseline_session_date": None,
                "sessions_age": None,
                "paired_strikes_count": 0,
                "strikes": {},
                "reason": f"Option expiry {exp_str} has already expired prior to session {curr_date_str}.",
            }

        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                all_prior_rows = cur.execute(
                    """
                    SELECT strike, option_type, open_interest, source, baseline_kind, observation_timestamp, session_date
                    FROM oi_baselines
                    WHERE index_symbol = ? AND expiry = ? AND data_mode = ? AND session_date < ?
                    ORDER BY session_date DESC, strike ASC, option_type ASC
                    """,
                    (sym, exp_str, dm, curr_date_str),
                ).fetchall()

                rows = [
                    r for r in all_prior_rows
                    if str(r["baseline_kind"] or "CLOSING_BASELINE").upper() == "CLOSING_BASELINE"
                ]

                if not rows:
                    if all_prior_rows:
                        intraday_sess = str(all_prior_rows[0]["session_date"])
                        intraday_ts = str(all_prior_rows[0]["observation_timestamp"])
                        intraday_src = str(all_prior_rows[0]["source"])
                        return {
                            "status": "NO_PRIOR_BASELINE",
                            "sub_status": "INTRADAY_OBSERVATION_ONLY",
                            "usable": False,
                            "index_symbol": sym,
                            "expiry": exp_str,
                            "data_mode": dm,
                            "current_session_date": curr_date_str,
                            "expected_prior_session_date": expected_prior_str,
                            "baseline_session_date": intraday_sess,
                            "sessions_age": None,
                            "intraday_only_records_present": len(all_prior_rows),
                            "paired_strikes_count": 0,
                            "strikes": {},
                            "reason": (
                                f"No verified prior-session CLOSING_BASELINE found for {sym} {exp_str} ({dm}); "
                                f"only mid-session intraday OI observations ({len(all_prior_rows)} rows @ {intraday_ts} "
                                f"from {intraday_src}) exist on {intraday_sess}. Arbitrary intraday observations cannot "
                                f"be promoted to a session-closing baseline."
                            ),
                        }

                    # Check if a prior-session closing baseline exists for a different expiry on the same index & data_mode
                    other_exp = cur.execute(
                        """
                        SELECT expiry, session_date
                        FROM oi_baselines
                        WHERE index_symbol = ? AND data_mode = ? AND session_date < ? AND expiry != ?
                          AND baseline_kind = 'CLOSING_BASELINE'
                        ORDER BY session_date DESC
                        LIMIT 1
                        """,
                        (sym, dm, curr_date_str, exp_str),
                    ).fetchone()
                    if other_exp is not None:
                        return {
                            "status": "EXPIRY_MISMATCH",
                            "usable": False,
                            "index_symbol": sym,
                            "expiry": exp_str,
                            "mismatched_baseline_expiry": str(other_exp["expiry"]),
                            "data_mode": dm,
                            "current_session_date": curr_date_str,
                            "expected_prior_session_date": expected_prior_str,
                            "baseline_session_date": str(other_exp["session_date"]),
                            "sessions_age": None,
                            "paired_strikes_count": 0,
                            "strikes": {},
                            "reason": (
                                f"No prior-session OI baseline found for {sym} expiry {exp_str} ({dm}); "
                                f"persisted baseline exists only for mismatched expiry {other_exp['expiry']}."
                            ),
                        }

                    same_day_count = cur.execute(
                        """
                        SELECT COUNT(*) FROM oi_baselines
                        WHERE index_symbol = ? AND expiry = ? AND data_mode = ? AND session_date = ?
                        """,
                        (sym, exp_str, dm, curr_date_str),
                    ).fetchone()[0]
                    if same_day_count > 0:
                        reason_msg = (
                            f"No prior-session OI baseline (< {curr_date_str}) found for {sym} {exp_str} ({dm}). "
                            f"Same-session observations ({same_day_count} rows on {curr_date_str}) cannot be substituted "
                            f"for previous-session closing OI."
                        )
                    else:
                        reason_msg = (
                            f"No persisted prior-session OI baseline found for {sym} {exp_str} ({dm}) "
                            f"prior to session {curr_date_str} (expected {expected_prior_str})."
                        )
                    return {
                        "status": "NO_PRIOR_BASELINE",
                        "usable": False,
                        "index_symbol": sym,
                        "expiry": exp_str,
                        "data_mode": dm,
                        "current_session_date": curr_date_str,
                        "expected_prior_session_date": expected_prior_str,
                        "baseline_session_date": None,
                        "sessions_age": None,
                        "same_session_records_present": int(same_day_count),
                        "paired_strikes_count": 0,
                        "strikes": {},
                        "reason": reason_msg,
                    }

                latest_session_str = str(rows[0]["session_date"])
                session_rows = [r for r in rows if str(r["session_date"]) == latest_session_str]

                # Validate timestamp freshness / non-future observation timestamps
                max_obs_ts = ""
                latest_source = ""
                for r in session_rows:
                    obs_ts = str(r["observation_timestamp"])
                    obs_dt = parse_ist_timestamp(obs_ts)
                    if obs_dt > ref_now + timedelta(seconds=60):
                        return {
                            "status": "FUTURE_TIMESTAMP_INVALID",
                            "usable": False,
                            "index_symbol": sym,
                            "expiry": exp_str,
                            "data_mode": dm,
                            "current_session_date": curr_date_str,
                            "expected_prior_session_date": expected_prior_str,
                            "baseline_session_date": latest_session_str,
                            "sessions_age": None,
                            "paired_strikes_count": 0,
                            "strikes": {},
                            "reason": (
                                f"Baseline observation_timestamp {obs_ts} for {sym} {exp_str} is in the future "
                                f"relative to current clock {format_ist_timestamp(ref_now)}."
                            ),
                        }
                    if obs_ts >= max_obs_ts:
                        max_obs_ts = obs_ts
                        latest_source = str(r["source"])

                sessions_age = count_trading_sessions_between(
                    latest_session_str,
                    curr_date,
                    configured_holidays=configured_holidays,
                )
                if sessions_age > max_sessions_age:
                    return {
                        "status": "STALE_BASELINE",
                        "usable": False,
                        "index_symbol": sym,
                        "expiry": exp_str,
                        "data_mode": dm,
                        "current_session_date": curr_date_str,
                        "expected_prior_session_date": expected_prior_str,
                        "baseline_session_date": latest_session_str,
                        "sessions_age": sessions_age,
                        "max_sessions_age": max_sessions_age,
                        "paired_strikes_count": 0,
                        "strikes": {},
                        "reason": (
                            f"Persisted OI baseline for {sym} {exp_str} from {latest_session_str} is stale "
                            f"({sessions_age} trading sessions old; max allowed is {max_sessions_age}, "
                            f"expected {expected_prior_str})."
                        ),
                    }

                by_strike: Dict[int, Dict[str, int]] = {}
                for r in session_rows:
                    k_int = int(r["strike"])
                    side = str(r["option_type"]).strip().upper()
                    oi_val = int(r["open_interest"])
                    if oi_val < 0 or side not in ("CE", "PE"):
                        return {
                            "status": "CORRUPT_BASELINE",
                            "usable": False,
                            "index_symbol": sym,
                            "expiry": exp_str,
                            "data_mode": dm,
                            "current_session_date": curr_date_str,
                            "expected_prior_session_date": expected_prior_str,
                            "baseline_session_date": latest_session_str,
                            "sessions_age": sessions_age,
                            "paired_strikes_count": 0,
                            "strikes": {},
                            "reason": f"Corrupt OI baseline row for strike {k_int} ({side}).",
                        }
                    by_strike.setdefault(k_int, {})[side] = oi_val

                unpaired_strikes = sorted(
                    k for k, legs in by_strike.items() if "CE" not in legs or "PE" not in legs
                )
                if unpaired_strikes:
                    return {
                        "status": "INCOMPLETE_CE_PE_PAIRS",
                        "usable": False,
                        "index_symbol": sym,
                        "expiry": exp_str,
                        "data_mode": dm,
                        "current_session_date": curr_date_str,
                        "expected_prior_session_date": expected_prior_str,
                        "baseline_session_date": latest_session_str,
                        "sessions_age": sessions_age,
                        "unpaired_strikes": unpaired_strikes,
                        "paired_strikes_count": 0,
                        "strikes": {},
                        "reason": (
                            f"OI baseline for {sym} {exp_str} on {latest_session_str} has incomplete CE/PE pairs "
                            f"at strikes: {unpaired_strikes}."
                        ),
                    }

                paired_map: Dict[int, Dict[str, int]] = {
                    k: {"ce_prev_oi": legs["CE"], "pe_prev_oi": legs["PE"]}
                    for k, legs in sorted(by_strike.items())
                }

                if required_strikes:
                    missing_req = sorted(int(k) for k in required_strikes if int(k) not in paired_map)
                    if missing_req:
                        return {
                            "status": "INCOMPLETE_CE_PE_PAIRS",
                            "usable": False,
                            "index_symbol": sym,
                            "expiry": exp_str,
                            "data_mode": dm,
                            "current_session_date": curr_date_str,
                            "expected_prior_session_date": expected_prior_str,
                            "baseline_session_date": latest_session_str,
                            "sessions_age": sessions_age,
                            "missing_strikes": missing_req,
                            "paired_strikes_count": len(paired_map),
                            "strikes": {},
                            "reason": (
                                f"OI baseline for {sym} {exp_str} on {latest_session_str} is missing required "
                                f"paired strikes: {missing_req}."
                            ),
                        }

                return {
                    "status": "READY",
                    "usable": True,
                    "index_symbol": sym,
                    "expiry": exp_str,
                    "data_mode": dm,
                    "current_session_date": curr_date_str,
                    "expected_prior_session_date": expected_prior_str,
                    "baseline_session_date": latest_session_str,
                    "sessions_age": sessions_age,
                    "source": latest_source,
                    "baseline_kind": "CLOSING_BASELINE",
                    "observation_timestamp": max_obs_ts,
                    "paired_strikes_count": len(paired_map),
                    "strikes": paired_map,
                    "reason": (
                        f"Verified prior-session OI baseline loaded from session {latest_session_str} "
                        f"({len(paired_map)} paired CE/PE strikes, observed @ {max_obs_ts} IST)."
                    ),
                }
            except Exception as exc:
                logger.error("Failed to load prior-session OI baseline for %s %s: %s", sym, exp_str, exc)
                raise PersistenceError(f"Failed to load prior-session OI baseline: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def query_oi_baselines(
        self,
        index_symbol: Optional[str] = None,
        expiry: Optional[str] = None,
        session_date: Optional[str] = None,
        data_mode: Optional[str] = None,
        baseline_kind: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ValueError("limit must be an integer between 1 and 500.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

        clauses: List[str] = []
        params: List[Any] = []
        if index_symbol:
            sym = index_symbol.strip().upper()
            if sym not in ("NIFTY", "BANKNIFTY"):
                raise ValueError(f"Invalid index_symbol '{index_symbol}'. Expected 'NIFTY' or 'BANKNIFTY'.")
            clauses.append("index_symbol = ?")
            params.append(sym)
        if expiry:
            exp_str = expiry.strip()
            try:
                datetime.strptime(exp_str, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"Invalid expiry filter '{expiry}'. Expected YYYY-MM-DD.") from exc
            clauses.append("expiry = ?")
            params.append(exp_str)
        if session_date:
            sess_str = session_date.strip()
            try:
                datetime.strptime(sess_str, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"Invalid session_date filter '{session_date}'. Expected YYYY-MM-DD.") from exc
            clauses.append("session_date = ?")
            params.append(sess_str)
        if data_mode:
            dm = data_mode.strip().upper()
            if dm not in ("LIVE", "SIMULATED"):
                raise ValueError(f"Invalid data_mode '{data_mode}'. Expected 'LIVE' or 'SIMULATED'.")
            clauses.append("data_mode = ?")
            params.append(dm)
        if baseline_kind:
            bk = baseline_kind.strip().upper()
            if bk not in ("CLOSING_BASELINE", "INTRADAY_OBSERVATION"):
                raise ValueError(
                    f"Invalid baseline_kind '{baseline_kind}'. Expected 'CLOSING_BASELINE' or 'INTRADAY_OBSERVATION'."
                )
            clauses.append("baseline_kind = ?")
            params.append(bk)

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                total_count = cur.execute(f"SELECT COUNT(*) FROM oi_baselines {where_sql}", params).fetchone()[0]
                rows = cur.execute(
                    f"""
                    SELECT * FROM oi_baselines
                    {where_sql}
                    ORDER BY session_date DESC, index_symbol ASC, expiry ASC, strike ASC, option_type ASC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset],
                ).fetchall()

                items = []
                for r in rows:
                    items.append({
                        "id": int(r["id"]),
                        "dedup_key": r["dedup_key"],
                        "index_symbol": r["index_symbol"],
                        "expiry": r["expiry"],
                        "strike": int(r["strike"]),
                        "option_type": r["option_type"],
                        "open_interest": int(r["open_interest"]),
                        "source": r["source"],
                        "baseline_kind": r["baseline_kind"] if "baseline_kind" in r.keys() else "CLOSING_BASELINE",
                        "observation_timestamp": r["observation_timestamp"],
                        "session_date": r["session_date"],
                        "data_mode": r["data_mode"],
                        "is_simulated": bool(r["is_simulated"]),
                        "created_at_ist": r["created_at_ist"],
                        "updated_at_ist": r["updated_at_ist"],
                    })
                return {
                    "total_count": int(total_count),
                    "limit": limit,
                    "offset": offset,
                    "items": items,
                }
            except Exception as exc:
                logger.error("Failed to query OI baselines: %s", exc)
                raise PersistenceError(f"Failed to query OI baselines: {exc}") from exc
            finally:
                self._close_if_file(conn)

    # ------------------------------------------------------------------------
    # Order Block Mitigation Persistence
    # ------------------------------------------------------------------------
    @staticmethod
    def _zone_scope(provider, data_mode, state_context, segment, interval_min):
        scope = normalize_state_scope(provider, data_mode, state_context)
        if scope[0] == "unknown" or scope[2] in ("UNKNOWN", "LEGACY_UNSCOPED"):
            raise PersistenceValidationError("Zone operations require explicit provenance.")
        segment = str(segment).strip().upper()
        if segment not in ("NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"):
            raise PersistenceValidationError("Zone operations require an explicit segment.")
        if isinstance(interval_min, bool) or not isinstance(interval_min, int) or interval_min <= 0:
            raise PersistenceValidationError("Zone interval_min must be a positive integer.")
        return (*scope, segment, interval_min)

    def load_mitigated_order_blocks(
        self, *, provider: str, data_mode: str, state_context: str,
        segment: str, interval_min: int,
    ) -> Set[str]:
        scope = self._zone_scope(provider, data_mode, state_context, segment, interval_min)
        with self._db_lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT zone_key FROM scoped_mitigated_order_blocks WHERE "
                    "provider=? AND data_mode=? AND state_context=? AND segment=? AND interval_min=?",
                    scope,
                ).fetchall()
                return {str(r["zone_key"]) for r in rows}
            except Exception as exc:
                raise PersistenceError(f"Failed to load mitigated order blocks: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def save_mitigated_order_blocks(
        self, zone_keys: Set[str], *, provider: str, data_mode: str,
        state_context: str, segment: str, interval_min: int, now_ist: Optional[Any] = None,
    ) -> int:
        scope = self._zone_scope(provider, data_mode, state_context, segment, interval_min)
        ts_str = format_ist_timestamp(now_ist or datetime.now(IST))
        # Validate the existing strategy key shape without changing strategy thresholds.
        for key in zone_keys:
            parts = str(key).split(":", 3)
            if len(parts) != 4 or not parts[0] or parts[1] != "OB" or parts[2] not in ("BULL", "BEAR"):
                raise PersistenceValidationError("Invalid Order Block zone key.")
            parse_ist_timestamp(parts[3])
        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    inserted = 0
                    for key in sorted(zone_keys):
                        cur = conn.execute(
                            "INSERT OR IGNORE INTO scoped_mitigated_order_blocks "
                            "(provider,data_mode,state_context,segment,interval_min,zone_key,mitigated_at_ist) "
                            "VALUES (?,?,?,?,?,?,?)", (*scope, key, ts_str),
                        )
                        inserted += int(cur.rowcount > 0)
                return inserted
            except Exception as exc:
                raise PersistenceError(f"Failed to save mitigated order blocks: {exc}") from exc
            finally:
                self._close_if_file(conn)

    # ------------------------------------------------------------------------
    # Signal Persistence & Querying
    # ------------------------------------------------------------------------
    def save_signal(
        self,
        sig: TradeSignal,
        broker: str,
        scan_run_id: Optional[str] = None,
        now_ist: Optional[Any] = None,
    ) -> Tuple[bool, str]:
        """
        Persists a validated TradeSignal to SQLite.
        Returns `(was_inserted: bool, dedup_key: str)`.
        If a signal with the same `dedup_key` already exists, returns `(False, dedup_key)`
        without overwriting or duplicating the historical record.
        """
        if not isinstance(sig, TradeSignal):
            raise PersistenceValidationError("save_signal requires a TradeSignal instance.")

        for num_name, num_val in (
            ("entry_price", sig.entry_price),
            ("entry_zone_low", sig.entry_zone_low),
            ("entry_zone_high", sig.entry_zone_high),
            ("stop_loss", sig.stop_loss),
            ("invalidation_level", sig.invalidation_level),
            ("target_1", sig.target_1),
            ("target_2", sig.target_2),
            ("capital_risk_inr", sig.capital_risk_inr),
            ("est_charges_inr", sig.est_charges_inr),
        ):
            if isinstance(num_val, bool) or not math.isfinite(float(num_val)):
                raise PersistenceValidationError(f"Signal field '{num_name}' must be a finite number.")
        if float(sig.entry_price) <= 0 or float(sig.stop_loss) <= 0:
            raise PersistenceValidationError("Signal entry_price and stop_loss must be positive.")
        if isinstance(sig.position_qty, bool) or not isinstance(sig.position_qty, int) or sig.position_qty <= 0:
            raise PersistenceValidationError("Signal position_qty must be a positive integer.")

        try:
            validate_signal_identity(sig.to_dict())
        except IdentityValidationError as exc:
            raise PersistenceValidationError(f"{exc.rejection['reason_code']}: {exc}") from exc
        dedup_key = compute_signal_dedup_key(sig, broker)
        _, (provider, data_mode, state_context) = signal_state_identity(sig, broker)
        candle_ts = format_ist_timestamp(sig.timestamp)
        created_ts = format_ist_timestamp(now_ist or datetime.now(IST))
        is_sim = data_mode == "SIMULATED"

        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO signals (
                            dedup_key, scan_run_id, symbol, segment, strategy_id, strategy_name,
                            direction, position_type, instrument_label, entry_price, entry_zone_low,
                            entry_zone_high, stop_loss, invalidation_level, target_1, target_2,
                            risk_reward, confidence_pct, quality_score, score_breakdown_json,
                            win_rate_benchmark, position_qty, capital_risk_inr, est_charges_inr,
                            rationale, candle_timestamp, is_simulated, data_mode, broker, created_at_ist,
                            provider, state_context, interval_min, instrument_identity_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            dedup_key,
                            scan_run_id,
                            sig.symbol.strip().upper(),
                            sig.segment.strip().upper(),
                            sig.strategy_id.strip(),
                            sig.strategy_name.strip(),
                            sig.direction.strip(),
                            sig.position_type.strip(),
                            sig.instrument_label.strip(),
                            round(float(sig.entry_price), 2),
                            round(float(sig.entry_zone_low), 2),
                            round(float(sig.entry_zone_high), 2),
                            round(float(sig.stop_loss), 2),
                            round(float(sig.invalidation_level), 2),
                            round(float(sig.target_1), 2),
                            round(float(sig.target_2), 2),
                            str(sig.risk_reward),
                            int(sig.confidence_pct),
                            int(sig.quality_score),
                            json.dumps(sig.score_breakdown or {}, sort_keys=True),
                            str(sig.win_rate_benchmark),
                            int(sig.position_qty),
                            round(float(sig.capital_risk_inr), 2),
                            round(float(sig.est_charges_inr), 2),
                            str(sig.rationale),
                            candle_ts,
                            1 if is_sim else 0,
                            data_mode,
                            str(broker),
                            created_ts,
                            provider, state_context, sig.interval_min,
                            json.dumps(sig.instrument_identity, sort_keys=True, allow_nan=False),
                        ),
                    )
                    was_inserted = cur.rowcount > 0
                    if was_inserted:
                        logger.info("Persisted signal %s (quality=%d, mode=%s)", dedup_key, sig.quality_score, data_mode)
                    else:
                        logger.info("Skipped duplicate signal %s", dedup_key)
                    return was_inserted, dedup_key
            except Exception as exc:
                logger.error("Failed to persist signal %s: %s", dedup_key, exc)
                raise PersistenceError(f"Failed to persist signal {dedup_key}: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def query_signals(
        self,
        limit: int = 50,
        offset: int = 0,
        symbol: Optional[str] = None,
        segment: Optional[str] = None,
        strategy_id: Optional[str] = None,
        direction: Optional[str] = None,
        data_mode: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        provider: Optional[str] = None,
        state_context: Optional[str] = None,
        interval_min: Optional[int] = None,
    ) -> Dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 200:
            raise ValueError("limit must be an integer between 1 and 200.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

        clauses: List[str] = []
        params: List[Any] = []

        if symbol:
            sym = symbol.strip().upper()
            clauses.append("symbol = ?")
            params.append(sym)
        if segment:
            seg = segment.strip().upper()
            if seg not in ("NSE_EQUITY_INTRADAY", "NSE_FO_INDEX"):
                raise ValueError(f"Invalid segment filter: {segment!r}")
            clauses.append("segment = ?")
            params.append(seg)
        if strategy_id:
            clauses.append("strategy_id = ?")
            params.append(strategy_id.strip())
        if direction:
            dir_up = direction.strip().upper()
            if dir_up in ("BULLISH", "BEARISH"):
                clauses.append("direction LIKE ?")
                params.append(f"{dir_up}%")
            else:
                clauses.append("UPPER(direction) = ?")
                params.append(dir_up)
        if data_mode:
            dm = data_mode.strip().upper()
            if dm not in ("LIVE", "SIMULATED"):
                raise ValueError(f"Invalid data_mode filter: {data_mode!r}. Expected 'LIVE' or 'SIMULATED'.")
            clauses.append("data_mode = ?")
            params.append(dm)
        if provider:
            clauses.append("provider = ?")
            source = str(provider).strip().lower()
            params.append({"sim": "paper_sim", "simulated": "paper_sim"}.get(source, source))
        if state_context:
            clauses.append("state_context = ?")
            params.append(str(state_context).strip().upper())
        if interval_min is not None:
            if isinstance(interval_min, bool) or not isinstance(interval_min, int) or interval_min <= 0:
                raise ValueError("interval_min must be a positive integer.")
            clauses.append("interval_min = ?")
            params.append(interval_min)
        if start_time:
            norm_start = format_ist_timestamp(start_time)
            clauses.append("candle_timestamp >= ?")
            params.append(norm_start)
        if end_time:
            norm_end = format_ist_timestamp(end_time)
            clauses.append("candle_timestamp <= ?")
            params.append(norm_end)

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                total_count = cur.execute(f"SELECT COUNT(*) FROM signals {where_sql}", params).fetchone()[0]
                rows = cur.execute(
                    f"""
                    SELECT * FROM signals
                    {where_sql}
                    ORDER BY candle_timestamp DESC, id DESC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset],
                ).fetchall()

                items = []
                for r in rows:
                    items.append({
                        "id": int(r["id"]),
                        "dedup_key": r["dedup_key"],
                        "scan_run_id": r["scan_run_id"],
                        "symbol": r["symbol"],
                        "segment": r["segment"],
                        "strategy_id": r["strategy_id"],
                        "strategy_name": r["strategy_name"],
                        "direction": r["direction"],
                        "position_type": r["position_type"],
                        "instrument_label": r["instrument_label"],
                        "entry_price": float(r["entry_price"]),
                        "entry_zone_low": float(r["entry_zone_low"]),
                        "entry_zone_high": float(r["entry_zone_high"]),
                        "stop_loss": float(r["stop_loss"]),
                        "invalidation_level": float(r["invalidation_level"]),
                        "target_1": float(r["target_1"]),
                        "target_2": float(r["target_2"]),
                        "risk_reward": r["risk_reward"],
                        "confidence_pct": int(r["confidence_pct"]),
                        "quality_score": int(r["quality_score"]),
                        "score_breakdown": json.loads(r["score_breakdown_json"] or "{}"),
                        "win_rate_benchmark": r["win_rate_benchmark"],
                        "position_qty": int(r["position_qty"]),
                        "capital_risk_inr": float(r["capital_risk_inr"]),
                        "est_charges_inr": float(r["est_charges_inr"]),
                        "rationale": r["rationale"],
                        "timestamp": r["candle_timestamp"],
                        "is_simulated": bool(r["is_simulated"]),
                        "data_mode": r["data_mode"],
                        "broker": r["broker"],
                        "provider": r["provider"],
                        "state_context": r["state_context"],
                        "interval_min": r["interval_min"],
                        "instrument_identity": json.loads(r["instrument_identity_json"] or "{}"),
                        "created_at_ist": r["created_at_ist"],
                    })
                return {
                    "total_count": int(total_count),
                    "limit": limit,
                    "offset": offset,
                    "items": items,
                }
            except Exception as exc:
                logger.error("Failed to query signals: %s", exc)
                raise PersistenceError(f"Failed to query signals: {exc}") from exc
            finally:
                self._close_if_file(conn)

    # ------------------------------------------------------------------------
    # OI Snapshot Persistence, Previous-Snapshot Selection & Intraday Diffing
    # ------------------------------------------------------------------------
    def save_oi_snapshot(
        self,
        option_chain: Dict[str, Any],
        snapshot_timestamp: Any,
        broker: str,
        scan_run_id: Optional[str] = None,
        max_snapshot_age_minutes: int = 60,
        now_ist: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Validates and persists an option-chain / open-interest snapshot.
        - Never fabricates missing fields; validates via `validate_option_chain_for_strategy()`
          plus explicit `index`, `expiry`, `spot`, `total_ce_oi`, and `total_pe_oi` checks.
        - Selects the most recent valid previous snapshot matching `(index_symbol, expiry, data_mode)`
          from the same trading session day (`snapshot_timestamp < current_ts`) within
          `max_snapshot_age_minutes` to compute rolling intraday OI deltas (`intraday_oi_diff`).
        - Distinguishes `LIVE` vs `SIMULATED` snapshots strictly.
        """
        if not isinstance(option_chain, dict) or not option_chain:
            raise PersistenceValidationError("option_chain must be a non-empty dictionary.")

        idx_sym = str(option_chain.get("index") or "").strip().upper()
        if idx_sym not in ("NIFTY", "BANKNIFTY"):
            raise PersistenceValidationError(f"Unsupported option_chain index symbol: {idx_sym!r}")

        expiry = str(option_chain.get("expiry") or "").strip()
        if not expiry:
            raise PersistenceValidationError("option_chain is missing required 'expiry' (YYYY-MM-DD).")
        try:
            datetime.strptime(expiry, "%Y-%m-%d")
        except ValueError as exc:
            raise PersistenceValidationError(f"Invalid option_chain expiry format: {expiry!r}") from exc

        if "spot" not in option_chain or option_chain["spot"] is None or isinstance(option_chain["spot"], bool):
            raise PersistenceValidationError("option_chain is missing required 'spot' price.")
        try:
            spot_val = float(option_chain["spot"])
        except (TypeError, ValueError) as exc:
            raise PersistenceValidationError("option_chain 'spot' must be numeric.") from exc
        if not math.isfinite(spot_val) or spot_val <= 0:
            raise PersistenceValidationError(f"Invalid option_chain spot price: {spot_val}")

        # Validate ATM strike, PCR, and strike-level fields
        try:
            atm_int, pcr_val, _ = validate_option_chain_for_strategy(option_chain)
        except LookupError as exc:
            raise PersistenceValidationError(str(exc)) from exc

        # Validate every strike row in strikes list
        strikes = option_chain["strikes"]
        normalized_strikes: List[Dict[str, Any]] = []
        calc_total_ce = 0
        calc_total_pe = 0
        for i, s_row in enumerate(strikes):
            for req_k in ("strike", "ce_ltp", "pe_ltp", "ce_oi", "pe_oi", "ce_oi_change", "pe_oi_change"):
                if req_k not in s_row or s_row[req_k] is None or isinstance(s_row[req_k], bool):
                    raise PersistenceValidationError(f"Strike row {i} missing required field '{req_k}'.")
            try:
                k_int = int(round(float(s_row["strike"])))
                ce_ltp = float(s_row["ce_ltp"])
                pe_ltp = float(s_row["pe_ltp"])
                ce_oi = int(round(float(s_row["ce_oi"])))
                pe_oi = int(round(float(s_row["pe_oi"])))
                ce_chg = int(round(float(s_row["ce_oi_change"])))
                pe_chg = int(round(float(s_row["pe_oi_change"])))
            except (TypeError, ValueError) as exc:
                raise PersistenceValidationError(f"Strike row {i} has non-numeric field.") from exc
            if not (math.isfinite(ce_ltp) and math.isfinite(pe_ltp)) or ce_ltp <= 0 or pe_ltp <= 0:
                raise PersistenceValidationError(f"Strike row {i} has non-positive option LTP.")
            if ce_oi < 0 or pe_oi < 0:
                raise PersistenceValidationError(f"Strike row {i} has negative open interest.")
            calc_total_ce += ce_oi
            calc_total_pe += pe_oi
            normalized_strikes.append({
                "strike": k_int,
                "ce_ltp": round(ce_ltp, 2),
                "ce_oi": ce_oi,
                "ce_oi_change": ce_chg,
                "ce_iv": round(float(s_row.get("ce_iv", 0.0) or 0.0), 2),
                "pe_ltp": round(pe_ltp, 2),
                "pe_oi": pe_oi,
                "pe_oi_change": pe_chg,
                "pe_iv": round(float(s_row.get("pe_iv", 0.0) or 0.0), 2),
            })

        total_ce_oi = int(option_chain.get("total_ce_oi") or calc_total_ce)
        total_pe_oi = int(option_chain.get("total_pe_oi") or calc_total_pe)
        if total_ce_oi <= 0 or total_pe_oi < 0:
            raise PersistenceValidationError("option_chain total_ce_oi must be positive.")

        snap_dt = parse_ist_timestamp(snapshot_timestamp)
        snap_ts_str = format_ist_timestamp(snap_dt)
        created_ts = format_ist_timestamp(now_ist or datetime.now(IST))
        is_sim = bool(
            option_chain.get("is_simulated", False)
            or str(option_chain.get("data_mode", "")).upper() == "SIMULATED"
            or "SIMULATED" in str(broker).upper()
        )
        data_mode = "SIMULATED" if is_sim else "LIVE"
        oi_measure = str(option_chain.get("oi_change_measure") or "net_change_from_previous_day_close")
        dedup_key = f"{idx_sym}:{expiry}:{snap_ts_str}:{data_mode}"

        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    existing = conn.execute(
                        "SELECT id FROM oi_snapshots WHERE dedup_key = ?",
                        (dedup_key,),
                    ).fetchone()
                    if existing is not None:
                        return {
                            "inserted": False,
                            "duplicate": True,
                            "snapshot_id": int(existing["id"]),
                            "dedup_key": dedup_key,
                            "data_mode": data_mode,
                        }

                    # Select the most recent prior valid snapshot for the same index, expiry, and data_mode
                    prev_row = conn.execute(
                        """
                        SELECT id, snapshot_timestamp, total_ce_oi, total_pe_oi, pcr, strikes_json
                        FROM oi_snapshots
                        WHERE index_symbol = ? AND expiry = ? AND data_mode = ? AND snapshot_timestamp < ?
                        ORDER BY snapshot_timestamp DESC, id DESC
                        LIMIT 1
                        """,
                        (idx_sym, expiry, data_mode, snap_ts_str),
                    ).fetchone()

                    prev_id: Optional[int] = None
                    intraday_diff: Dict[str, Any] = {
                        "comparison_status": "NO_PRIOR_SNAPSHOT",
                        "previous_snapshot_timestamp": None,
                        "elapsed_minutes": None,
                        "total_ce_oi_delta": None,
                        "total_pe_oi_delta": None,
                        "pcr_delta": None,
                        "atm_ce_oi_delta": None,
                        "atm_pe_oi_delta": None,
                    }

                    if prev_row is not None:
                        prev_dt = parse_ist_timestamp(prev_row["snapshot_timestamp"])
                        elapsed_min = (snap_dt - prev_dt).total_seconds() / 60.0
                        same_session = prev_dt.date() == snap_dt.date()
                        if same_session and 0 < elapsed_min <= max_snapshot_age_minutes:
                            prev_id = int(prev_row["id"])
                            prev_strikes = {
                                int(s["strike"]): s
                                for s in json.loads(prev_row["strikes_json"] or "[]")
                            }
                            curr_atm_row = next((s for s in normalized_strikes if s["strike"] == atm_int), None)
                            prev_atm_row = prev_strikes.get(atm_int)
                            intraday_diff = {
                                "comparison_status": "VALID_INTRADAY_DIFF",
                                "previous_snapshot_timestamp": prev_row["snapshot_timestamp"],
                                "elapsed_minutes": round(elapsed_min, 2),
                                "total_ce_oi_delta": total_ce_oi - int(prev_row["total_ce_oi"]),
                                "total_pe_oi_delta": total_pe_oi - int(prev_row["total_pe_oi"]),
                                "pcr_delta": round(pcr_val - float(prev_row["pcr"]), 4),
                                "atm_ce_oi_delta": (
                                    int(curr_atm_row["ce_oi"]) - int(prev_atm_row["ce_oi"])
                                    if curr_atm_row and prev_atm_row else None
                                ),
                                "atm_pe_oi_delta": (
                                    int(curr_atm_row["pe_oi"]) - int(prev_atm_row["pe_oi"])
                                    if curr_atm_row and prev_atm_row else None
                                ),
                            }
                        else:
                            intraday_diff = {
                                "comparison_status": "STALE_PRIOR_SNAPSHOT",
                                "previous_snapshot_timestamp": prev_row["snapshot_timestamp"],
                                "elapsed_minutes": round(elapsed_min, 2),
                                "total_ce_oi_delta": None,
                                "total_pe_oi_delta": None,
                                "pcr_delta": None,
                                "atm_ce_oi_delta": None,
                                "atm_pe_oi_delta": None,
                            }

                    cur = conn.execute(
                        """
                        INSERT INTO oi_snapshots (
                            dedup_key, scan_run_id, index_symbol, expiry, snapshot_timestamp,
                            spot, atm_strike, pcr, total_ce_oi, total_pe_oi, oi_change_measure,
                            strikes_json, previous_snapshot_id, intraday_oi_diff_json,
                            is_simulated, data_mode, broker, created_at_ist
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            dedup_key,
                            scan_run_id,
                            idx_sym,
                            expiry,
                            snap_ts_str,
                            round(spot_val, 2),
                            atm_int,
                            round(pcr_val, 2),
                            total_ce_oi,
                            total_pe_oi,
                            oi_measure,
                            json.dumps(normalized_strikes),
                            prev_id,
                            json.dumps(intraday_diff, sort_keys=True),
                            1 if is_sim else 0,
                            data_mode,
                            str(broker),
                            created_ts,
                        ),
                    )
                    return {
                        "inserted": True,
                        "duplicate": False,
                        "snapshot_id": int(cur.lastrowid),
                        "dedup_key": dedup_key,
                        "data_mode": data_mode,
                        "intraday_oi_diff": intraday_diff,
                    }
            except (PersistenceValidationError, PersistenceError):
                raise
            except Exception as exc:
                logger.error("Failed to persist OI snapshot %s: %s", dedup_key, exc)
                raise PersistenceError(f"Failed to persist OI snapshot {dedup_key}: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def query_oi_snapshots(
        self,
        index_symbol: Optional[str] = None,
        expiry: Optional[str] = None,
        data_mode: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError("limit must be an integer between 1 and 100.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

        clauses: List[str] = []
        params: List[Any] = []
        if index_symbol:
            sym = index_symbol.strip().upper()
            if sym not in ("NIFTY", "BANKNIFTY"):
                raise ValueError(f"Invalid index_symbol '{index_symbol}'. Expected 'NIFTY' or 'BANKNIFTY'.")
            clauses.append("index_symbol = ?")
            params.append(sym)
        if expiry:
            exp_str = expiry.strip()
            try:
                datetime.strptime(exp_str, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"Invalid expiry filter '{expiry}'. Expected YYYY-MM-DD.") from exc
            clauses.append("expiry = ?")
            params.append(exp_str)
        if data_mode:
            dm = data_mode.strip().upper()
            if dm not in ("LIVE", "SIMULATED"):
                raise ValueError(f"Invalid data_mode '{data_mode}'. Expected 'LIVE' or 'SIMULATED'.")
            clauses.append("data_mode = ?")
            params.append(dm)

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                total_count = cur.execute(f"SELECT COUNT(*) FROM oi_snapshots {where_sql}", params).fetchone()[0]
                rows = cur.execute(
                    f"""
                    SELECT * FROM oi_snapshots
                    {where_sql}
                    ORDER BY snapshot_timestamp DESC, id DESC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset],
                ).fetchall()

                items = []
                for r in rows:
                    items.append({
                        "id": int(r["id"]),
                        "dedup_key": r["dedup_key"],
                        "scan_run_id": r["scan_run_id"],
                        "index_symbol": r["index_symbol"],
                        "expiry": r["expiry"],
                        "snapshot_timestamp": r["snapshot_timestamp"],
                        "spot": float(r["spot"]),
                        "atm_strike": int(r["atm_strike"]),
                        "pcr": float(r["pcr"]),
                        "total_ce_oi": int(r["total_ce_oi"]),
                        "total_pe_oi": int(r["total_pe_oi"]),
                        "oi_change_measure": r["oi_change_measure"],
                        "strikes": json.loads(r["strikes_json"] or "[]"),
                        "previous_snapshot_id": r["previous_snapshot_id"],
                        "intraday_oi_diff": json.loads(r["intraday_oi_diff_json"] or "{}"),
                        "is_simulated": bool(r["is_simulated"]),
                        "data_mode": r["data_mode"],
                        "broker": r["broker"],
                        "created_at_ist": r["created_at_ist"],
                    })
                return {
                    "total_count": int(total_count),
                    "limit": limit,
                    "offset": offset,
                    "items": items,
                }
            except Exception as exc:
                logger.error("Failed to query OI snapshots: %s", exc)
                raise PersistenceError(f"Failed to query OI snapshots: {exc}") from exc
            finally:
                self._close_if_file(conn)

    # ------------------------------------------------------------------------
    # Scan-Run Lifecycle Persistence & Querying
    # ------------------------------------------------------------------------
    def record_scan_run(
        self,
        run_id: str,
        started_at_ist: str,
        completed_at_ist: Optional[str],
        duration_ms: Optional[float],
        status: str,
        broker: str,
        data_mode: str,
        is_simulated: bool,
        total_signals: int = 0,
        persisted_signals: int = 0,
        duplicate_signals: int = 0,
        oi_snapshots_saved: int = 0,
        market_breadth: Optional[Dict[str, Any]] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> int:
        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute(
                        """
                        INSERT OR REPLACE INTO scan_runs (
                            run_id, started_at_ist, completed_at_ist, duration_ms, status,
                            broker, data_mode, is_simulated, total_signals, persisted_signals,
                            duplicate_signals, oi_snapshots_saved, market_breadth_json,
                            error_type, error_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(run_id),
                            str(started_at_ist),
                            completed_at_ist,
                            round(float(duration_ms), 2) if duration_ms is not None else None,
                            str(status),
                            str(broker),
                            str(data_mode),
                            1 if is_simulated else 0,
                            int(total_signals),
                            int(persisted_signals),
                            int(duplicate_signals),
                            int(oi_snapshots_saved),
                            json.dumps(market_breadth) if market_breadth is not None else None,
                            error_type,
                            error_message,
                        ),
                    )
                    return int(cur.lastrowid)
            except Exception as exc:
                logger.error("Failed to record scan run %s: %s", run_id, exc)
                raise PersistenceError(f"Failed to record scan run {run_id}: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def query_scan_runs(
        self,
        limit: int = 20,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 200:
            raise ValueError("limit must be an integer between 1 and 200.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("UPPER(status) = ?")
            params.append(status.strip().upper())

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                total_count = cur.execute(f"SELECT COUNT(*) FROM scan_runs {where_sql}", params).fetchone()[0]
                rows = cur.execute(
                    f"""
                    SELECT * FROM scan_runs
                    {where_sql}
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset],
                ).fetchall()

                items = []
                for r in rows:
                    items.append({
                        "id": int(r["id"]),
                        "run_id": r["run_id"],
                        "started_at_ist": r["started_at_ist"],
                        "completed_at_ist": r["completed_at_ist"],
                        "duration_ms": float(r["duration_ms"]) if r["duration_ms"] is not None else None,
                        "status": r["status"],
                        "broker": r["broker"],
                        "data_mode": r["data_mode"],
                        "is_simulated": bool(r["is_simulated"]),
                        "total_signals": int(r["total_signals"]),
                        "persisted_signals": int(r["persisted_signals"]),
                        "duplicate_signals": int(r["duplicate_signals"]),
                        "oi_snapshots_saved": int(r["oi_snapshots_saved"]),
                        "market_breadth": json.loads(r["market_breadth_json"]) if r["market_breadth_json"] else None,
                        "error_type": r["error_type"],
                        "error_message": r["error_message"],
                    })
                return {
                    "total_count": int(total_count),
                    "limit": limit,
                    "offset": offset,
                    "items": items,
                }
            except Exception as exc:
                logger.error("Failed to query scan runs: %s", exc)
                raise PersistenceError(f"Failed to query scan runs: {exc}") from exc
            finally:
                self._close_if_file(conn)


    # ------------------------------------------------------------------------
    # Phase 3A: Historical Market Data Quality, Provenance & Resumable Storage
    # ------------------------------------------------------------------------
    def save_historical_candle_dataset(
        self,
        candles: List[Dict[str, Any]],
        symbol: str,
        segment: Optional[str] = None,
        exchange: Optional[str] = None,
        provider: str = "angelone",
        instrument_token: str = "UNKNOWN",
        interval_min: int = 5,
        data_mode: str = "LIVE",
        retrieved_at_ist: Optional[Any] = None,
        reference_time_ist: Optional[Any] = None,
        configured_holidays: Optional[List[str]] = None,
        session_start_ist: str = "09:15",
        session_end_ist: str = "15:30",
        allow_identical_duplicates: bool = True,
        sort_chronologically: bool = True,
        reject_forming_candles: bool = True,
        filter_forming_candles: bool = False,
        require_complete_sessions: bool = False,
        initial_transformations: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Validates a batch of historical OHLCV candles via `validate_and_prepare_historical_dataset`
        and persists both the dataset provenance manifest (`historical_datasets`) and individual
        bars (`historical_candles`) in a single atomic SQLite transaction:
        - Resumable & Idempotent: Re-submitting existing timestamps with identical OHLCV values
          is a clean no-op (`unchanged_count`), while new non-overlapping bars are inserted
          (`inserted_count`).
        - Conflict Rejection: If any incoming bar has the same `(symbol, interval_min,
          candle_timestamp, data_mode, provider)` as an already-stored row in SQLite but
          differs in OHLCV or OI values, raises `PersistenceValidationError` and rolls back
          the entire transaction.
        """
        from historical_data import (
            HistoricalDataValidationError,
            validate_and_prepare_historical_dataset,
        )

        sym_clean = str(symbol or "").strip().upper()
        resolved_seg = segment or ("NSE_FO_INDEX" if sym_clean in ("NIFTY", "BANKNIFTY") else "NSE_EQUITY_INTRADAY")
        resolved_exch = exchange or "NSE"

        try:
            prepared = validate_and_prepare_historical_dataset(
                candles=candles,
                symbol=sym_clean,
                segment=resolved_seg,
                exchange=resolved_exch,
                provider=provider,
                instrument_token=instrument_token,
                interval_min=interval_min,
                data_mode=data_mode,
                retrieved_at_ist=retrieved_at_ist,
                reference_time_ist=reference_time_ist,
                configured_holidays=configured_holidays,
                session_start_ist=session_start_ist,
                session_end_ist=session_end_ist,
                allow_identical_duplicates=allow_identical_duplicates,
                sort_chronologically=sort_chronologically,
                reject_forming_candles=reject_forming_candles,
                filter_forming_candles=filter_forming_candles,
                require_complete_sessions=require_complete_sessions,
                initial_transformations=initial_transformations,
            )
        except HistoricalDataValidationError as exc:
            raise PersistenceValidationError(str(exc)) from exc

        manifest = prepared["manifest"]
        norm_bars = prepared["candles"]
        now_str = format_ist_timestamp(retrieved_at_ist or datetime.now(IST))

        inserted_count = 0
        unchanged_count = 0

        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.cursor()
                    for bar in norm_bars:
                        existing = cur.execute(
                            """
                            SELECT id, open, high, low, close, volume, open_interest, data_mode, is_simulated
                            FROM historical_candles
                            WHERE dedup_key = ?
                            """,
                            (bar["dedup_key"],),
                        ).fetchone()

                        if existing is not None:
                            same_vals = (
                                abs(float(existing["open"]) - float(bar["open"])) <= 1e-6
                                and abs(float(existing["high"]) - float(bar["high"])) <= 1e-6
                                and abs(float(existing["low"]) - float(bar["low"])) <= 1e-6
                                and abs(float(existing["close"]) - float(bar["close"])) <= 1e-6
                                and abs(float(existing["volume"]) - float(bar["volume"])) <= 1e-4
                                and int(existing["open_interest"]) == int(bar["open_interest"])
                            )
                            if not same_vals:
                                raise PersistenceValidationError(
                                    f"Conflicting historical candle already stored for {bar['dedup_key']}: "
                                    f"stored=({existing['open']}, {existing['high']}, {existing['low']}, {existing['close']}, vol={existing['volume']}) "
                                    f"vs incoming=({bar['open']}, {bar['high']}, {bar['low']}, {bar['close']}, vol={bar['volume']})."
                                )
                            unchanged_count += 1
                            continue

                        cur.execute(
                            """
                            INSERT INTO historical_candles (
                                dedup_key, dataset_id, symbol, segment, exchange, provider,
                                instrument_token, interval_min, candle_timestamp, session_date,
                                open, high, low, close, volume, open_interest, is_complete,
                                source_timestamp_ist, retrieved_at_ist, data_mode, is_simulated,
                                transformations_json, created_at_ist, updated_at_ist
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                bar["dedup_key"],
                                manifest["dataset_id"],
                                bar["symbol"],
                                bar["segment"],
                                bar["exchange"],
                                bar["provider"],
                                bar["instrument_token"],
                                int(bar["interval_min"]),
                                bar["timestamp"],
                                bar["session_date"],
                                float(bar["open"]),
                                float(bar["high"]),
                                float(bar["low"]),
                                float(bar["close"]),
                                float(bar["volume"]),
                                int(bar["open_interest"]),
                                1 if bar["is_complete"] else 0,
                                bar["source_timestamp_ist"],
                                bar["retrieved_at_ist"],
                                bar["data_mode"],
                                1 if bar["is_simulated"] else 0,
                                json.dumps(bar["transformations"]),
                                now_str,
                                now_str,
                            ),
                        )
                        inserted_count += 1

                    cur.execute(
                        """
                        INSERT INTO historical_datasets (
                            dataset_id, symbol, segment, exchange, provider, instrument_token,
                            interval_min, from_timestamp_ist, to_timestamp_ist, retrieved_at_ist,
                            source_timestamp_ist, data_mode, is_simulated, transformations_json,
                            quality_status, bars_count, completed_bars_count, sessions_count,
                            missing_bars_count, missing_timestamps_json, zero_volume_bars_count,
                            duplicate_bars_coalesced, sha256_checksum, created_at_ist, updated_at_ist
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(dataset_id) DO UPDATE SET
                            retrieved_at_ist = excluded.retrieved_at_ist,
                            updated_at_ist = excluded.updated_at_ist
                        """,
                        (
                            manifest["dataset_id"],
                            manifest["symbol"],
                            manifest["segment"],
                            manifest["exchange"],
                            manifest["provider"],
                            manifest["instrument_token"],
                            int(manifest["interval_min"]),
                            manifest["from_timestamp_ist"],
                            manifest["to_timestamp_ist"],
                            manifest["retrieved_at_ist"],
                            manifest["source_timestamp_ist"],
                            manifest["data_mode"],
                            1 if manifest["is_simulated"] else 0,
                            json.dumps(manifest["transformations"]),
                            manifest["quality_status"],
                            int(manifest["bars_count"]),
                            int(manifest["completed_bars_count"]),
                            int(manifest["sessions_count"]),
                            int(manifest["missing_bars_count"]),
                            json.dumps(manifest["missing_timestamps"]),
                            int(manifest["zero_volume_bars_count"]),
                            int(manifest["duplicate_bars_coalesced"]),
                            manifest["sha256_checksum"],
                            now_str,
                            now_str,
                        ),
                    )
                return {
                    "status": "SAVED",
                    "dataset_id": manifest["dataset_id"],
                    "inserted_count": inserted_count,
                    "unchanged_count": unchanged_count,
                    "total_validated_bars": len(norm_bars),
                    "manifest": manifest,
                }
            except PersistenceValidationError:
                raise
            except Exception as exc:
                logger.error("Failed to save historical candle dataset: %s", exc)
                raise PersistenceError(f"Failed to save historical candle dataset: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def import_historical_candles_file(
        self,
        file_path: str,
        default_symbol: str = "RELIANCE",
        default_segment: Optional[str] = None,
        default_exchange: str = "NSE",
        default_provider: str = "angelone",
        default_instrument_token: str = "2885",
        interval_min: int = 5,
        data_mode: str = "LIVE",
        retrieved_at_ist: Optional[Any] = None,
        reference_time_ist: Optional[Any] = None,
        configured_holidays: Optional[List[str]] = None,
        require_complete_sessions: bool = False,
    ) -> Dict[str, Any]:
        """
        Resumable, idempotent historical dataset import workflow supporting JSON and CSV files:
        - JSON may be either `{"symbol", "provider", "instrument_token", "data_mode", "candles": [...]}`
          or a list of candle objects `[...]`.
        - CSV must include headers `timestamp,open,high,low,close,volume` (and optional
          `symbol,open_interest,source_timestamp,data_mode`).
        """
        if not isinstance(file_path, str) or not file_path.strip() or not os.path.isfile(file_path.strip()):
            raise PersistenceValidationError(f"Historical candle import file not found: {file_path!r}")

        clean_path = file_path.strip()
        _, ext = os.path.splitext(clean_path.lower())

        sym = str(default_symbol or "RELIANCE").strip().upper()
        seg = default_segment
        exch = str(default_exchange or "NSE").strip().upper()
        prov = str(default_provider or "angelone").strip().lower()
        tok = str(default_instrument_token or "UNKNOWN").strip()
        intv = int(interval_min)
        dm = str(data_mode or "LIVE").strip().upper()
        ret_ts = retrieved_at_ist
        ref_ts = reference_time_ist
        raw_bars: List[Dict[str, Any]] = []

        try:
            if ext == ".csv":
                with open(clean_path, "r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if not isinstance(row, dict):
                            continue
                        bar_item: Dict[str, Any] = {
                            "timestamp": row.get("timestamp") or row.get("candle_timestamp"),
                            "open": row.get("open"),
                            "high": row.get("high"),
                            "low": row.get("low"),
                            "close": row.get("close"),
                            "volume": row.get("volume"),
                        }
                        if row.get("open_interest") not in (None, ""):
                            bar_item["open_interest"] = row.get("open_interest")
                        if row.get("symbol") not in (None, ""):
                            bar_item["symbol"] = row.get("symbol")
                        if row.get("data_mode") not in (None, ""):
                            bar_item["data_mode"] = row.get("data_mode")
                        if row.get("is_complete") not in (None, ""):
                            bar_item["is_complete"] = str(row["is_complete"]).strip().lower() not in ("false", "0", "no")
                        raw_bars.append(bar_item)
            else:
                with open(clean_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict):
                    sym = str(payload.get("symbol") or sym).strip().upper()
                    seg = payload.get("segment") or seg
                    exch = str(payload.get("exchange") or exch).strip().upper()
                    prov = str(payload.get("provider") or prov).strip().lower()
                    tok = str(payload.get("instrument_token") or tok).strip()
                    intv = int(payload.get("interval_min") or intv)
                    dm = str(payload.get("data_mode") or dm).strip().upper()
                    ret_ts = payload.get("retrieved_at_ist") or ret_ts
                    ref_ts = payload.get("reference_time_ist") or ref_ts
                    candles_val = payload.get("candles") if "candles" in payload else payload.get("bars")
                    if not isinstance(candles_val, list):
                        raise PersistenceValidationError("JSON historical dataset object must contain a 'candles' list.")
                    raw_bars = candles_val
                elif isinstance(payload, list):
                    raw_bars = payload
                else:
                    raise PersistenceValidationError("Unsupported JSON structure for historical candle import.")
        except PersistenceValidationError:
            raise
        except Exception as exc:
            raise PersistenceValidationError(
                f"Failed to parse historical candle file {os.path.basename(clean_path)}: {exc}"
            ) from exc

        res = self.save_historical_candle_dataset(
            candles=raw_bars,
            symbol=sym,
            segment=seg,
            exchange=exch,
            provider=prov,
            instrument_token=tok,
            interval_min=intv,
            data_mode=dm,
            retrieved_at_ist=ret_ts,
            reference_time_ist=ref_ts,
            configured_holidays=configured_holidays,
            require_complete_sessions=require_complete_sessions,
            initial_transformations=[f"imported_from_{ext.lstrip('.') or 'file'}"],
        )
        res["imported_file"] = os.path.basename(clean_path)
        return res

    def get_historical_ingestion_watermark(
        self,
        symbol: str,
        interval_min: int = 5,
        data_mode: str = "LIVE",
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Returns the resumable ingestion watermark (earliest/latest stored `candle_timestamp`,
        stored bar count, and stored session dates) for `(symbol, interval_min, data_mode)`
        so interrupted multi-session historical downloads or imports can resume cleanly.
        """
        sym = str(symbol or "").strip().upper()
        dm = str(data_mode or "LIVE").strip().upper()
        intv = int(interval_min)

        clauses = ["symbol = ?", "interval_min = ?", "data_mode = ?"]
        params: List[Any] = [sym, intv, dm]
        if provider:
            clauses.append("provider = ?")
            params.append(str(provider).strip().lower())
        where_sql = "WHERE " + " AND ".join(clauses)

        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                row = cur.execute(
                    f"""
                    SELECT COUNT(*) AS cnt,
                           MIN(candle_timestamp) AS min_ts,
                           MAX(candle_timestamp) AS max_ts,
                           COUNT(DISTINCT session_date) AS sess_cnt
                    FROM historical_candles
                    {where_sql}
                    """,
                    params,
                ).fetchone()
                sess_rows = cur.execute(
                    f"SELECT DISTINCT session_date FROM historical_candles {where_sql} ORDER BY session_date ASC",
                    params,
                ).fetchall()
                return {
                    "symbol": sym,
                    "interval_min": intv,
                    "data_mode": dm,
                    "provider": provider.strip().lower() if provider else None,
                    "stored_bars_count": int(row["cnt"] or 0),
                    "earliest_timestamp_ist": row["min_ts"],
                    "latest_timestamp_ist": row["max_ts"],
                    "stored_sessions_count": int(row["sess_cnt"] or 0),
                    "stored_session_dates": [r["session_date"] for r in sess_rows],
                }
            except Exception as exc:
                raise PersistenceError(f"Failed to query historical ingestion watermark: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def query_historical_datasets(
        self,
        symbol: Optional[str] = None,
        data_mode: Optional[str] = None,
        provider: Optional[str] = None,
        quality_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 200:
            raise ValueError("limit must be an integer between 1 and 200.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

        clauses: List[str] = []
        params: List[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.strip().upper())
        if data_mode:
            dm = data_mode.strip().upper()
            if dm not in ("LIVE", "SIMULATED"):
                raise ValueError("data_mode must be 'LIVE' or 'SIMULATED'.")
            clauses.append("data_mode = ?")
            params.append(dm)
        if provider:
            clauses.append("provider = ?")
            params.append(provider.strip().lower())
        if quality_status:
            clauses.append("quality_status = ?")
            params.append(quality_status.strip().upper())

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                total_count = cur.execute(
                    f"SELECT COUNT(*) FROM historical_datasets {where_sql}", params
                ).fetchone()[0]
                rows = cur.execute(
                    f"""
                    SELECT * FROM historical_datasets
                    {where_sql}
                    ORDER BY to_timestamp_ist DESC, updated_at_ist DESC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset],
                ).fetchall()

                items = []
                for r in rows:
                    items.append({
                        "dataset_id": r["dataset_id"],
                        "symbol": r["symbol"],
                        "segment": r["segment"],
                        "exchange": r["exchange"],
                        "provider": r["provider"],
                        "instrument_token": r["instrument_token"],
                        "interval_min": int(r["interval_min"]),
                        "from_timestamp_ist": r["from_timestamp_ist"],
                        "to_timestamp_ist": r["to_timestamp_ist"],
                        "retrieved_at_ist": r["retrieved_at_ist"],
                        "source_timestamp_ist": r["source_timestamp_ist"],
                        "data_mode": r["data_mode"],
                        "is_simulated": bool(r["is_simulated"]),
                        "transformations": json.loads(r["transformations_json"] or "[]"),
                        "quality_status": r["quality_status"],
                        "bars_count": int(r["bars_count"]),
                        "completed_bars_count": int(r["completed_bars_count"]),
                        "sessions_count": int(r["sessions_count"]),
                        "missing_bars_count": int(r["missing_bars_count"]),
                        "missing_timestamps": json.loads(r["missing_timestamps_json"] or "[]"),
                        "zero_volume_bars_count": int(r["zero_volume_bars_count"]),
                        "duplicate_bars_coalesced": int(r["duplicate_bars_coalesced"]),
                        "sha256_checksum": r["sha256_checksum"],
                        "created_at_ist": r["created_at_ist"],
                        "updated_at_ist": r["updated_at_ist"],
                    })
                return {
                    "total_count": int(total_count),
                    "limit": limit,
                    "offset": offset,
                    "items": items,
                }
            except Exception as exc:
                logger.error("Failed to query historical datasets: %s", exc)
                raise PersistenceError(f"Failed to query historical datasets: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def query_historical_candles(
        self,
        symbol: str,
        interval_min: int = 5,
        data_mode: str = "LIVE",
        provider: Optional[str] = None,
        start_time_ist: Optional[str] = None,
        end_time_ist: Optional[str] = None,
        decision_time_ist: Optional[Any] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Queries persisted historical OHLCV bars for `symbol` with strict `data_mode` isolation
        (`LIVE` vs `SIMULATED` can never be mixed in a single query).
        When `decision_time_ist` is supplied, enforces point-in-time look-ahead prevention
        so only completed bars where `bar_start + interval_min <= decision_time_ist` are returned.
        """
        sym = str(symbol or "").strip().upper()
        if not sym:
            raise ValueError("symbol is required to query historical candles.")
        dm = str(data_mode or "LIVE").strip().upper()
        if dm not in ("LIVE", "SIMULATED"):
            raise ValueError("data_mode must be strictly 'LIVE' or 'SIMULATED'.")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 10000:
            raise ValueError("limit must be an integer between 1 and 10000.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

        clauses = ["symbol = ?", "interval_min = ?", "data_mode = ?"]
        params: List[Any] = [sym, int(interval_min), dm]

        if provider:
            clauses.append("provider = ?")
            params.append(str(provider).strip().lower())
        if start_time_ist:
            clauses.append("candle_timestamp >= ?")
            params.append(format_ist_timestamp(start_time_ist))
        if end_time_ist:
            clauses.append("candle_timestamp <= ?")
            params.append(format_ist_timestamp(end_time_ist))
        if decision_time_ist is not None:
            dec_dt = parse_ist_timestamp(decision_time_ist)
            max_bar_start_dt = dec_dt - timedelta(minutes=int(interval_min))
            clauses.append("candle_timestamp <= ?")
            params.append(format_ist_timestamp(max_bar_start_dt))
            clauses.append("is_complete = 1")

        where_sql = "WHERE " + " AND ".join(clauses)
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                total_count = cur.execute(
                    f"SELECT COUNT(*) FROM historical_candles {where_sql}", params
                ).fetchone()[0]
                rows = cur.execute(
                    f"""
                    SELECT * FROM historical_candles
                    {where_sql}
                    ORDER BY candle_timestamp ASC, id ASC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset],
                ).fetchall()

                items = []
                for r in rows:
                    items.append({
                        "id": int(r["id"]),
                        "dedup_key": r["dedup_key"],
                        "dataset_id": r["dataset_id"],
                        "symbol": r["symbol"],
                        "segment": r["segment"],
                        "exchange": r["exchange"],
                        "provider": r["provider"],
                        "instrument_token": r["instrument_token"],
                        "interval_min": int(r["interval_min"]),
                        "timestamp": r["candle_timestamp"],
                        "session_date": r["session_date"],
                        "open": float(r["open"]),
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                        "volume": float(r["volume"]),
                        "open_interest": int(r["open_interest"]),
                        "is_complete": bool(r["is_complete"]),
                        "source_timestamp_ist": r["source_timestamp_ist"],
                        "retrieved_at_ist": r["retrieved_at_ist"],
                        "data_mode": r["data_mode"],
                        "is_simulated": bool(r["is_simulated"]),
                        "transformations": json.loads(r["transformations_json"] or "[]"),
                    })
                return {
                    "total_count": int(total_count),
                    "limit": limit,
                    "offset": offset,
                    "data_mode": dm,
                    "items": items,
                }
            except Exception as exc:
                logger.error("Failed to query historical candles: %s", exc)
                raise PersistenceError(f"Failed to query historical candles: {exc}") from exc
            finally:
                self._close_if_file(conn)

    # ------------------------------------------------------------------------
    # Phase 3B Backtest Run & Trade Ledger Persistence
    # ------------------------------------------------------------------------
    def save_backtest_run(
        self,
        run_summary: Dict[str, Any],
        trades: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Persists a completed backtest run summary (`backtest_runs`) and its full trade ledger
        (`backtest_trades`) atomically inside a single SQLite transaction.
        Idempotent on `run_id`: re-saving an identical `run_id` updates metadata and replaces
        its trade rows deterministically.
        """
        if not isinstance(run_summary, dict) or not run_summary.get("run_id"):
            raise PersistenceValidationError("run_summary must be a dict with a non-empty 'run_id'.")
        if not isinstance(trades, list):
            raise PersistenceValidationError("trades must be a list of trade dicts.")
        for trade in trades:
            quantity = trade.get("quantity") if isinstance(trade, dict) else None
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                raise PersistenceValidationError("Trade quantity must be a positive integer; fractional lots are not coerced.")

        run_id = str(run_summary["run_id"]).strip()
        dm = str(run_summary.get("data_mode") or "SIMULATED").strip().upper()
        if dm not in ("LIVE", "SIMULATED"):
            raise PersistenceValidationError(f"Invalid backtest data_mode: {dm!r}")

        created_at = str(run_summary.get("created_at_ist") or format_ist_timestamp(datetime.now(IST)))
        metrics = run_summary.get("metrics") or {}

        with self._db_lock:
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO backtest_runs (
                            run_id, strategy_id, strategy_name, strategy_version,
                            symbol, segment, exchange, interval_min,
                            dataset_id, dataset_checksum, provider, data_mode, is_simulated,
                            run_label, implementation_status, data_acceptance_status,
                            period_type, from_timestamp_ist, to_timestamp_ist,
                            starting_capital_inr, ending_capital_inr, risk_per_trade_pct,
                            max_daily_loss_inr, daily_profit_target_inr,
                            total_trades, winning_trades, losing_trades, breakeven_trades,
                            win_rate_pct, gross_pnl_inr, total_charges_inr, total_slippage_inr,
                            total_costs_inr, net_pnl_inr, return_on_capital_pct,
                            profit_factor, profit_factor_status,
                            max_drawdown_inr, max_drawdown_pct,
                            expectancy_per_trade_inr, average_r_multiple,
                            missing_bars_count, rejected_signals_count,
                            assumptions_json, metrics_json, created_at_ist
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        ON CONFLICT(run_id) DO UPDATE SET
                            metrics_json = excluded.metrics_json,
                            assumptions_json = excluded.assumptions_json,
                            created_at_ist = excluded.created_at_ist
                        """,
                        (
                            run_id,
                            str(run_summary["strategy_id"]),
                            str(run_summary.get("strategy_name") or run_summary["strategy_id"]),
                            str(run_summary.get("strategy_version") or "phase_3b_v1"),
                            str(run_summary["symbol"]),
                            str(run_summary["segment"]),
                            str(run_summary.get("exchange") or "NSE"),
                            int(run_summary.get("interval_min") or 5),
                            str(run_summary["dataset_id"]),
                            str(run_summary["dataset_checksum"]),
                            str(run_summary["provider"]),
                            dm,
                            1 if dm == "SIMULATED" else 0,
                            str(run_summary.get("run_label") or dm),
                            str(run_summary.get("implementation_status") or "IMPLEMENTED_VERIFIED"),
                            str(run_summary.get("data_acceptance_status") or "UNVERIFIED"),
                            str(run_summary.get("period_type") or "FULL"),
                            str(run_summary["from_timestamp_ist"]),
                            str(run_summary["to_timestamp_ist"]),
                            float(run_summary["starting_capital_inr"]),
                            float(run_summary["ending_capital_inr"]),
                            float(run_summary["risk_per_trade_pct"]),
                            float(run_summary["max_daily_loss_inr"]) if run_summary.get("max_daily_loss_inr") is not None else None,
                            float(run_summary["daily_profit_target_inr"]) if run_summary.get("daily_profit_target_inr") is not None else None,
                            int(metrics.get("total_trades", len(trades))),
                            int(metrics.get("winning_trades", 0)),
                            int(metrics.get("losing_trades", 0)),
                            int(metrics.get("breakeven_trades", 0)),
                            float(metrics.get("win_rate_pct", 0.0)),
                            float(metrics.get("gross_pnl_inr", 0.0)),
                            float(metrics.get("total_charges_inr", 0.0)),
                            float(metrics.get("total_slippage_inr", 0.0)),
                            float(metrics.get("total_costs_inr", 0.0)),
                            float(metrics.get("net_pnl_inr", 0.0)),
                            float(metrics.get("return_on_starting_capital_pct", 0.0)),
                            float(metrics["profit_factor"]) if metrics.get("profit_factor") is not None else None,
                            str(metrics.get("profit_factor_status") or "NO_TRADES"),
                            float(metrics.get("max_drawdown_inr", 0.0)),
                            float(metrics.get("max_drawdown_pct", 0.0)),
                            float(metrics.get("expectancy_per_trade_inr", 0.0)),
                            float(metrics.get("average_r_multiple", 0.0)),
                            int(metrics.get("missing_bars_count", 0)),
                            int(metrics.get("rejected_signals_count", 0)),
                            json.dumps(run_summary.get("assumptions") or {}, sort_keys=True),
                            json.dumps(metrics, sort_keys=True),
                            created_at,
                        ),
                    )

                    cur.execute("DELETE FROM backtest_trades WHERE run_id = ?", (run_id,))
                    for idx, t in enumerate(trades, start=1):
                        cur.execute(
                            """
                            INSERT INTO backtest_trades (
                                run_id, trade_index, strategy_id, strategy_version,
                                symbol, segment, exchange, direction, position_side,
                                signal_timestamp, entry_timestamp, exit_timestamp, session_date,
                                raw_entry_price, entry_price, raw_exit_price, exit_price,
                                quantity, stop_loss, target_price, target_1, target_2,
                                exit_reason, same_candle_collision, holding_bars, holding_minutes,
                                gross_pnl_inr, charges_inr, slippage_inr, total_costs_inr, net_pnl_inr,
                                risk_amount_inr, realized_r_multiple,
                                dataset_id, dataset_checksum, data_mode, is_simulated, provider,
                                cost_breakdown_json, signal_metadata_json
                            ) VALUES (
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                            )
                            """,
                            (
                                run_id,
                                int(t.get("trade_index", idx)),
                                str(t["strategy_id"]),
                                str(t.get("strategy_version") or "phase_3b_v1"),
                                str(t["symbol"]),
                                str(t["segment"]),
                                str(t.get("exchange") or "NSE"),
                                str(t["direction"]),
                                str(t["position_side"]),
                                str(t["signal_timestamp"]),
                                str(t["entry_timestamp"]),
                                str(t["exit_timestamp"]),
                                str(t["session_date"]),
                                float(t.get("raw_entry_price", t["entry_price"])),
                                float(t["entry_price"]),
                                float(t.get("raw_exit_price", t["exit_price"])),
                                float(t["exit_price"]),
                                int(t["quantity"]),
                                float(t["stop_loss"]),
                                float(t["target_price"]),
                                float(t.get("target_1", t["target_price"])),
                                float(t.get("target_2", t["target_price"])),
                                str(t["exit_reason"]),
                                1 if t.get("same_candle_collision") else 0,
                                int(t.get("holding_bars", 1)),
                                float(t.get("holding_minutes", 5.0)),
                                float(t["gross_pnl_inr"]),
                                float(t["charges_inr"]),
                                float(t["slippage_inr"]),
                                float(t["total_costs_inr"]),
                                float(t["net_pnl_inr"]),
                                float(t["risk_amount_inr"]),
                                float(t["realized_r_multiple"]),
                                str(t["dataset_id"]),
                                str(t["dataset_checksum"]),
                                str(t["data_mode"]),
                                1 if t.get("is_simulated") else 0,
                                str(t["provider"]),
                                json.dumps(t.get("cost_breakdown") or {}, sort_keys=True),
                                json.dumps(t.get("signal_metadata") or {}, sort_keys=True),
                            ),
                        )
                return {
                    "status": "SAVED",
                    "run_id": run_id,
                    "trades_saved": len(trades),
                    "data_mode": dm,
                }
            except PersistenceValidationError:
                raise
            except Exception as exc:
                logger.error("Failed to save backtest run %s: %s", run_id, exc)
                raise PersistenceError(f"Failed to save backtest run: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def query_backtest_runs(
        self,
        strategy_id: Optional[str] = None,
        symbol: Optional[str] = None,
        data_mode: Optional[str] = None,
        period_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 200:
            raise ValueError("limit must be an integer between 1 and 200.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

        clauses: List[str] = []
        params: List[Any] = []
        if strategy_id:
            clauses.append("strategy_id = ?")
            params.append(strategy_id.strip())
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.strip().upper())
        if data_mode:
            dm = data_mode.strip().upper()
            if dm not in ("LIVE", "SIMULATED"):
                raise ValueError("data_mode must be 'LIVE' or 'SIMULATED'.")
            clauses.append("data_mode = ?")
            params.append(dm)
        if period_type:
            clauses.append("period_type = ?")
            params.append(period_type.strip().upper())

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                total_count = cur.execute(
                    f"SELECT COUNT(*) FROM backtest_runs {where_sql}", params
                ).fetchone()[0]
                rows = cur.execute(
                    f"""
                    SELECT * FROM backtest_runs
                    {where_sql}
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset],
                ).fetchall()
                items = []
                for r in rows:
                    items.append({
                        "run_id": r["run_id"],
                        "strategy_id": r["strategy_id"],
                        "strategy_name": r["strategy_name"],
                        "strategy_version": r["strategy_version"],
                        "symbol": r["symbol"],
                        "segment": r["segment"],
                        "exchange": r["exchange"],
                        "interval_min": int(r["interval_min"]),
                        "dataset_id": r["dataset_id"],
                        "dataset_checksum": r["dataset_checksum"],
                        "provider": r["provider"],
                        "data_mode": r["data_mode"],
                        "is_simulated": bool(r["is_simulated"]),
                        "run_label": r["run_label"],
                        "implementation_status": r["implementation_status"],
                        "data_acceptance_status": r["data_acceptance_status"],
                        "period_type": r["period_type"],
                        "from_timestamp_ist": r["from_timestamp_ist"],
                        "to_timestamp_ist": r["to_timestamp_ist"],
                        "starting_capital_inr": float(r["starting_capital_inr"]),
                        "ending_capital_inr": float(r["ending_capital_inr"]),
                        "risk_per_trade_pct": float(r["risk_per_trade_pct"]),
                        "max_daily_loss_inr": float(r["max_daily_loss_inr"]) if r["max_daily_loss_inr"] is not None else None,
                        "daily_profit_target_inr": float(r["daily_profit_target_inr"]) if r["daily_profit_target_inr"] is not None else None,
                        "total_trades": int(r["total_trades"]),
                        "winning_trades": int(r["winning_trades"]),
                        "losing_trades": int(r["losing_trades"]),
                        "breakeven_trades": int(r["breakeven_trades"]),
                        "win_rate_pct": float(r["win_rate_pct"]),
                        "gross_pnl_inr": float(r["gross_pnl_inr"]),
                        "total_charges_inr": float(r["total_charges_inr"]),
                        "total_slippage_inr": float(r["total_slippage_inr"]),
                        "total_costs_inr": float(r["total_costs_inr"]),
                        "net_pnl_inr": float(r["net_pnl_inr"]),
                        "return_on_capital_pct": float(r["return_on_capital_pct"]),
                        "profit_factor": float(r["profit_factor"]) if r["profit_factor"] is not None else None,
                        "profit_factor_status": r["profit_factor_status"],
                        "max_drawdown_inr": float(r["max_drawdown_inr"]),
                        "max_drawdown_pct": float(r["max_drawdown_pct"]),
                        "expectancy_per_trade_inr": float(r["expectancy_per_trade_inr"]),
                        "average_r_multiple": float(r["average_r_multiple"]),
                        "missing_bars_count": int(r["missing_bars_count"]),
                        "rejected_signals_count": int(r["rejected_signals_count"]),
                        "assumptions": json.loads(r["assumptions_json"] or "{}"),
                        "metrics": json.loads(r["metrics_json"] or "{}"),
                        "created_at_ist": r["created_at_ist"],
                    })
                return {
                    "total_count": int(total_count),
                    "limit": limit,
                    "offset": offset,
                    "items": items,
                }
            except Exception as exc:
                logger.error("Failed to query backtest runs: %s", exc)
                raise PersistenceError(f"Failed to query backtest runs: {exc}") from exc
            finally:
                self._close_if_file(conn)

    def get_backtest_run_detail(self, run_id: str) -> Optional[Dict[str, Any]]:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string.")
        clean_id = run_id.strip()
        with self._db_lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                r = cur.execute(
                    "SELECT * FROM backtest_runs WHERE run_id = ?", (clean_id,)
                ).fetchone()
                if r is None:
                    return None
                t_rows = cur.execute(
                    "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY trade_index ASC",
                    (clean_id,),
                ).fetchall()
                trades = []
                for tr in t_rows:
                    trades.append({
                        "trade_index": int(tr["trade_index"]),
                        "strategy_id": tr["strategy_id"],
                        "strategy_version": tr["strategy_version"],
                        "symbol": tr["symbol"],
                        "segment": tr["segment"],
                        "exchange": tr["exchange"],
                        "direction": tr["direction"],
                        "position_side": tr["position_side"],
                        "signal_timestamp": tr["signal_timestamp"],
                        "entry_timestamp": tr["entry_timestamp"],
                        "exit_timestamp": tr["exit_timestamp"],
                        "session_date": tr["session_date"],
                        "raw_entry_price": float(tr["raw_entry_price"]),
                        "entry_price": float(tr["entry_price"]),
                        "raw_exit_price": float(tr["raw_exit_price"]),
                        "exit_price": float(tr["exit_price"]),
                        "quantity": int(tr["quantity"]),
                        "stop_loss": float(tr["stop_loss"]),
                        "target_price": float(tr["target_price"]),
                        "target_1": float(tr["target_1"]),
                        "target_2": float(tr["target_2"]),
                        "exit_reason": tr["exit_reason"],
                        "same_candle_collision": bool(tr["same_candle_collision"]),
                        "holding_bars": int(tr["holding_bars"]),
                        "holding_minutes": float(tr["holding_minutes"]),
                        "gross_pnl_inr": float(tr["gross_pnl_inr"]),
                        "charges_inr": float(tr["charges_inr"]),
                        "slippage_inr": float(tr["slippage_inr"]),
                        "total_costs_inr": float(tr["total_costs_inr"]),
                        "net_pnl_inr": float(tr["net_pnl_inr"]),
                        "risk_amount_inr": float(tr["risk_amount_inr"]),
                        "realized_r_multiple": float(tr["realized_r_multiple"]),
                        "dataset_id": tr["dataset_id"],
                        "dataset_checksum": tr["dataset_checksum"],
                        "data_mode": tr["data_mode"],
                        "is_simulated": bool(tr["is_simulated"]),
                        "provider": tr["provider"],
                        "cost_breakdown": json.loads(tr["cost_breakdown_json"] or "{}"),
                        "signal_metadata": json.loads(tr["signal_metadata_json"] or "{}"),
                    })
                return {
                    "run_id": r["run_id"],
                    "strategy_id": r["strategy_id"],
                    "strategy_name": r["strategy_name"],
                    "strategy_version": r["strategy_version"],
                    "symbol": r["symbol"],
                    "segment": r["segment"],
                    "exchange": r["exchange"],
                    "interval_min": int(r["interval_min"]),
                    "dataset_id": r["dataset_id"],
                    "dataset_checksum": r["dataset_checksum"],
                    "provider": r["provider"],
                    "data_mode": r["data_mode"],
                    "is_simulated": bool(r["is_simulated"]),
                    "run_label": r["run_label"],
                    "implementation_status": r["implementation_status"],
                    "data_acceptance_status": r["data_acceptance_status"],
                    "period_type": r["period_type"],
                    "from_timestamp_ist": r["from_timestamp_ist"],
                    "to_timestamp_ist": r["to_timestamp_ist"],
                    "starting_capital_inr": float(r["starting_capital_inr"]),
                    "ending_capital_inr": float(r["ending_capital_inr"]),
                    "risk_per_trade_pct": float(r["risk_per_trade_pct"]),
                    "max_daily_loss_inr": float(r["max_daily_loss_inr"]) if r["max_daily_loss_inr"] is not None else None,
                    "daily_profit_target_inr": float(r["daily_profit_target_inr"]) if r["daily_profit_target_inr"] is not None else None,
                    "assumptions": json.loads(r["assumptions_json"] or "{}"),
                    "metrics": json.loads(r["metrics_json"] or "{}"),
                    "trades": trades,
                    "created_at_ist": r["created_at_ist"],
                }
            except Exception as exc:
                logger.error("Failed to fetch backtest run detail %s: %s", clean_id, exc)
                raise PersistenceError(f"Failed to fetch backtest run detail: {exc}") from exc
            finally:
                self._close_if_file(conn)


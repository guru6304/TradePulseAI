import base64
import binascii
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from typing import List, Dict, Optional, Any


class ConfigValidationError(ValueError):
    """Raised when BotConfig contains invalid or unsafe configuration parameters."""

    def __init__(self, message, *, reason_code="CONFIGURATION_INVALID", line_number=None):
        super().__init__(message)
        self.reason_code = reason_code
        self.line_number = line_number


def _is_placeholder_value(val: Optional[str]) -> bool:
    if not val or not str(val).strip():
        return True
    lower = str(val).strip().lower()
    return (
        lower.startswith("your_")
        or "placeholder" in lower
        or "example" in lower
        or "your_telegram_bot_token" in lower
    )


def _is_valid_base32_secret(val: Optional[str]) -> bool:
    if _is_placeholder_value(val):
        return False
    clean = str(val).strip().replace(" ", "").upper()
    if not clean:
        return False
    padding = (8 - len(clean) % 8) % 8
    try:
        decoded = base64.b32decode(clean + "=" * padding, casefold=True)
        return len(decoded) > 0
    except (binascii.Error, ValueError):
        return False


def _parse_hhmm(val: str, field_name: str) -> dt_time:
    if not isinstance(val, str) or ":" not in val.strip():
        raise ConfigValidationError(f"Invalid {field_name}. Expected 'HH:MM' in 24-hour IST format.")
    try:
        dt = datetime.strptime(val.strip(), "%H:%M")
        return dt_time(dt.hour, dt.minute)
    except ValueError:
        raise ConfigValidationError(f"Invalid {field_name}. Expected 'HH:MM' in 24-hour IST format.") from None


def _load_dotenv(filepath: Optional[str] = None) -> None:
    """Load the module's project .env, or the caller's explicit path, atomically.

    Missing files remain optional; selected live credentials are required by validate.
    Explicit relative paths retain their caller-relative meaning. Process values and
    the first occurrence of a duplicate key keep their established precedence.
    """
    path = filepath if filepath is not None else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    pending = {}
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8-sig") as stream:
            for number, line in enumerate(stream, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, separator, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or "\x00" in value:
                    code = ("DOTENV_ASSIGNMENT_MISSING_EQUALS" if not separator else
                            "DOTENV_KEY_INVALID" if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) else "DOTENV_NUL_BYTE")
                    raise ConfigValidationError(f"Malformed configuration assignment at line {number}.",
                        reason_code=code, line_number=number)
                if value.startswith(("'", '"')):
                    if len(value) < 2 or value[-1] != value[0]:
                        raise ConfigValidationError(f"Unterminated configuration quote at line {number}.",
                            reason_code="DOTENV_QUOTE_UNTERMINATED", line_number=number)
                    value = value[1:-1]
                pending.setdefault(key, value)
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ConfigValidationError):
            raise
        raise ConfigValidationError("Project configuration file could not be read safely.") from None
    for key, value in pending.items():
        os.environ.setdefault(key, value)


def _config_number(value: str, name: str, kind):
    try:
        return kind(value)
    except (ValueError, TypeError, OverflowError):
        raise ConfigValidationError(f"{name} must be a valid {kind.__name__} setting.") from None


def _config_bool(value: str, name: str) -> bool:
    text = value.strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise ConfigValidationError(f"{name} must be a boolean setting.")


_load_dotenv()


@dataclass
class BotConfig:
    active_broker: Optional[str] = None

    # Angel One SmartAPI (Read-Only Market Data Integration)
    angel_api_key: Optional[str] = None
    angel_client_code: Optional[str] = None
    angel_pin: Optional[str] = None
    angel_totp_secret: Optional[str] = None
    angel_scrip_master_path: Optional[str] = None
    angel_scrip_master_max_age_hours: Optional[float] = None
    angel_baseline_max_sessions_age: Optional[int] = None
    angel_request_timeout_seconds: Optional[float] = None
    angel_min_request_interval_seconds: Optional[float] = None

    # DhanHQ API v2
    dhan_client_id: Optional[str] = None
    dhan_access_token: Optional[str] = None
    # Explicit bounded streaming scope; configuring it never starts a connection.
    dhan_feed_instruments: Optional[List[Dict[str, Any]]] = None

    # Upstox API v2
    upstox_api_key: Optional[str] = None
    upstox_access_token: Optional[str] = None

    # Telegram Bot
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_dry_run: Optional[bool] = None

    # Gemini / Antigravity API Key
    gemini_api_key: Optional[str] = None

    # Risk & Capital Management
    account_capital_inr: Optional[float] = None
    max_risk_per_trade_pct: Optional[float] = None
    max_daily_loss_inr: Optional[float] = None
    daily_profit_target_inr: Optional[float] = None
    max_concurrent_positions: Optional[int] = None
    scan_interval_seconds: Optional[int] = None
    # Live candle age is measured from close: interval + publication-delay allowance.
    live_candle_max_delay_seconds: Optional[float] = None
    live_candle_future_skew_seconds: Optional[float] = None

    # Market Session, Scheduler & Persistence (Phase 1D / 2B)
    session_start_ist: Optional[str] = None
    session_end_ist: Optional[str] = None
    configured_holidays: Optional[List[str]] = None
    database_url: Optional[str] = None
    enable_persistence: Optional[bool] = None
    enable_background_scheduler: Optional[bool] = None

    # Core Target Universe:
    # 1) F&O Indices: Strictly NIFTY 50 & BANK NIFTY
    fo_indices: Dict[str, Dict] = field(default_factory=lambda: {
        "NIFTY": {
            "name": "NIFTY 50",
            "lot_size": 75,
            "strike_step": 50,
            "angel_token": "99926000",
            "dhan_security_id": "13",
            "upstox_key": "NSE_INDEX|Nifty 50",
        },
        "BANKNIFTY": {
            "name": "BANK NIFTY",
            "lot_size": 30,
            "strike_step": 100,
            "angel_token": "99926009",
            "dhan_security_id": "25",
            "upstox_key": "NSE_INDEX|Nifty Bank",
        },
    })

    # 2) Intraday Equity Cash/F&O Liquid Stocks (NSE)
    equity_watchlist: List[Dict[str, str]] = field(default_factory=lambda: [
        {"symbol": "RELIANCE", "sector": "Energy", "angel_token": "2885", "dhan_id": "2885", "upstox_key": "NSE_EQ|INE002A01018"},
        {"symbol": "HDFCBANK", "sector": "Banking", "angel_token": "1333", "dhan_id": "1333", "upstox_key": "NSE_EQ|INE040A01034"},
        {"symbol": "ICICIBANK", "sector": "Banking", "angel_token": "4963", "dhan_id": "4963", "upstox_key": "NSE_EQ|INE090A01021"},
        {"symbol": "INFY", "sector": "IT", "angel_token": "1594", "dhan_id": "1594", "upstox_key": "NSE_EQ|INE009A01021"},
        {"symbol": "TCS", "sector": "IT", "angel_token": "11536", "dhan_id": "11536", "upstox_key": "NSE_EQ|INE467B01029"},
        {"symbol": "SBIN", "sector": "PSU Bank", "angel_token": "3045", "dhan_id": "3045", "upstox_key": "NSE_EQ|INE062A01020"},
        {"symbol": "BAJFINANCE", "sector": "NBFC", "angel_token": "317", "dhan_id": "317", "upstox_key": "NSE_EQ|INE296A01024"},
        {"symbol": "LT", "sector": "Infra", "angel_token": "11483", "dhan_id": "11483", "upstox_key": "NSE_EQ|INE018A01030"},
        {"symbol": "TATAMOTORS", "sector": "Auto", "angel_token": "3456", "dhan_id": "3456", "upstox_key": "NSE_EQ|INE155A01022"},
        {"symbol": "AXISBANK", "sector": "Banking", "angel_token": "5900", "dhan_id": "5900", "upstox_key": "NSE_EQ|INE238A01034"},
        {"symbol": "M&M", "sector": "Auto", "angel_token": "2031", "dhan_id": "2031", "upstox_key": "NSE_EQ|INE101A01026"},
        {"symbol": "BHARTIARTL", "sector": "Telecom", "angel_token": "10604", "dhan_id": "10604", "upstox_key": "NSE_EQ|INE397D01024"},
        {"symbol": "TRENT", "sector": "Retail", "angel_token": "1964", "dhan_id": "1964", "upstox_key": "NSE_EQ|INE849A01020"},
        {"symbol": "HAL", "sector": "Defence", "angel_token": "2303", "dhan_id": "2303", "upstox_key": "NSE_EQ|INE066F01020"},
        {"symbol": "TATASTEEL", "sector": "Metals", "angel_token": "3499", "dhan_id": "3499", "upstox_key": "NSE_EQ|INE081A01020"},
    ])

    def __post_init__(self) -> None:
        if self.active_broker is None:
            self.active_broker = os.getenv("ACTIVE_BROKER", "paper_sim")
        if self.angel_api_key is None:
            self.angel_api_key = os.getenv("ANGEL_API_KEY", "")
        if self.angel_client_code is None:
            self.angel_client_code = os.getenv("ANGEL_CLIENT_CODE", "")
        if self.angel_pin is None:
            self.angel_pin = os.getenv("ANGEL_PIN", "")
        if self.angel_totp_secret is None:
            self.angel_totp_secret = os.getenv("ANGEL_TOTP_SECRET", "")
        if self.angel_scrip_master_path is None:
            self.angel_scrip_master_path = os.getenv("ANGEL_SCRIP_MASTER_PATH", "")
        if self.angel_scrip_master_max_age_hours is None:
            self.angel_scrip_master_max_age_hours = _config_number(os.getenv("ANGEL_SCRIP_MASTER_MAX_AGE_HOURS", "24.0"), "ANGEL_SCRIP_MASTER_MAX_AGE_HOURS", float)
        if self.angel_baseline_max_sessions_age is None:
            self.angel_baseline_max_sessions_age = _config_number(os.getenv("ANGEL_BASELINE_MAX_SESSIONS_AGE", "1"), "ANGEL_BASELINE_MAX_SESSIONS_AGE", int)
        if self.angel_request_timeout_seconds is None:
            self.angel_request_timeout_seconds = _config_number(os.getenv("ANGEL_REQUEST_TIMEOUT_SECONDS", "8.0"), "ANGEL_REQUEST_TIMEOUT_SECONDS", float)
        if self.angel_min_request_interval_seconds is None:
            self.angel_min_request_interval_seconds = _config_number(os.getenv("ANGEL_MIN_REQUEST_INTERVAL_SECONDS", "0.4"), "ANGEL_MIN_REQUEST_INTERVAL_SECONDS", float)
        if self.dhan_client_id is None:
            self.dhan_client_id = os.getenv("DHAN_CLIENT_ID", "")
        if self.dhan_access_token is None:
            self.dhan_access_token = os.getenv("DHAN_ACCESS_TOKEN", "")
        if self.dhan_feed_instruments is None:
            try:
                self.dhan_feed_instruments = json.loads(os.getenv("DHAN_FEED_INSTRUMENTS_JSON", "[]"))
            except (ValueError, TypeError):
                raise ConfigValidationError("DHAN_FEED_INSTRUMENTS_JSON must be a JSON instrument list.") from None
        if self.upstox_api_key is None:
            self.upstox_api_key = os.getenv("UPSTOX_API_KEY", "")
        if self.upstox_access_token is None:
            self.upstox_access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
        if self.telegram_bot_token is None:
            self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if self.telegram_chat_id is None:
            self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if self.telegram_dry_run is None:
            self.telegram_dry_run = _config_bool(os.getenv("TELEGRAM_DRY_RUN", "true"), "TELEGRAM_DRY_RUN")
        if self.gemini_api_key is None:
            self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        if self.account_capital_inr is None:
            self.account_capital_inr = _config_number(os.getenv("ACCOUNT_CAPITAL_INR", "150000"), "ACCOUNT_CAPITAL_INR", float)
        if self.max_risk_per_trade_pct is None:
            self.max_risk_per_trade_pct = _config_number(os.getenv("MAX_RISK_PER_TRADE_PCT", "1.0"), "MAX_RISK_PER_TRADE_PCT", float)
        if self.max_daily_loss_inr is None:
            self.max_daily_loss_inr = _config_number(os.getenv("MAX_DAILY_LOSS_INR", "2000"), "MAX_DAILY_LOSS_INR", float)
        if self.daily_profit_target_inr is None:
            self.daily_profit_target_inr = _config_number(os.getenv("DAILY_PROFIT_TARGET_INR", "4000"), "DAILY_PROFIT_TARGET_INR", float)
        if self.max_concurrent_positions is None:
            self.max_concurrent_positions = _config_number(os.getenv("MAX_CONCURRENT_POSITIONS", "1"), "MAX_CONCURRENT_POSITIONS", int)
        if self.scan_interval_seconds is None:
            self.scan_interval_seconds = _config_number(os.getenv("SCAN_INTERVAL_SECONDS", "60"), "SCAN_INTERVAL_SECONDS", int)
        if self.live_candle_max_delay_seconds is None:
            self.live_candle_max_delay_seconds = _config_number(os.getenv("LIVE_CANDLE_MAX_DELAY_SECONDS", "60"), "LIVE_CANDLE_MAX_DELAY_SECONDS", float)
        if self.live_candle_future_skew_seconds is None:
            self.live_candle_future_skew_seconds = _config_number(os.getenv("LIVE_CANDLE_FUTURE_SKEW_SECONDS", "5"), "LIVE_CANDLE_FUTURE_SKEW_SECONDS", float)
        if self.session_start_ist is None:
            self.session_start_ist = os.getenv("SESSION_START_IST", "09:15")
        if self.session_end_ist is None:
            self.session_end_ist = os.getenv("SESSION_END_IST", "15:30")
        if self.configured_holidays is None:
            raw_holidays = os.getenv("NSE_HOLIDAYS", "")
            self.configured_holidays = [h.strip() for h in raw_holidays.split(",") if h.strip()]
        if self.database_url is None:
            self.database_url = os.getenv("DATABASE_URL", ":memory:")
        if self.enable_persistence is None:
            self.enable_persistence = _config_bool(os.getenv("ENABLE_PERSISTENCE", "true"), "ENABLE_PERSISTENCE")
        if self.enable_background_scheduler is None:
            self.enable_background_scheduler = (
                _config_bool(os.getenv("ENABLE_BACKGROUND_SCHEDULER", "false"), "ENABLE_BACKGROUND_SCHEDULER")
            )

    def is_broker_credentials_configured(self, broker_key: Optional[str] = None) -> bool:
        key = (broker_key or self.active_broker or "").strip().lower()
        if key in ("paper_sim", "simulated", "sim"):
            return True
        if key == "angelone":
            return (
                not any(
                    _is_placeholder_value(v)
                    for v in (self.angel_api_key, self.angel_client_code, self.angel_pin, self.angel_totp_secret)
                )
                and _is_valid_base32_secret(self.angel_totp_secret)
            )
        if key == "dhan":
            return not any(_is_placeholder_value(v) for v in (self.dhan_client_id, self.dhan_access_token))
        if key == "upstox":
            return not _is_placeholder_value(self.upstox_access_token)
        return False

    def validate(self, require_live_credentials: bool = False) -> None:
        """
        Validates configuration values and raises ConfigValidationError on invalid settings.
        Never invents credentials or silently switches a failed live configuration to simulation.
        """
        valid_brokers = ("angelone", "dhan", "upstox", "paper_sim", "simulated", "sim")
        bkey = str(self.active_broker or "").strip().lower()
        if bkey not in valid_brokers:
            raise ConfigValidationError(
                f"Invalid active_broker. Expected one of: {', '.join(valid_brokers)}."
            )

        if not isinstance(self.dhan_feed_instruments, list) or len(self.dhan_feed_instruments) > 50:
            raise ConfigValidationError("Dhan streaming requires an explicit list of at most 50 instruments.")
        seen = set()
        from instrument_identity import spot_identity, IdentityValidationError
        for meta in self.dhan_feed_instruments:
            try:
                identity = spot_identity(meta, "dhan")
            except (IdentityValidationError, TypeError, ValueError):
                raise ConfigValidationError("Dhan streaming instrument mapping is unsupported or conflicting.") from None
            key = (identity["exchange"], identity["identifier"])
            if key in seen:
                raise ConfigValidationError("Dhan streaming instruments must be unique.")
            seen.add(key)

        if isinstance(self.account_capital_inr, bool) or not isinstance(self.account_capital_inr, (int, float)):
            raise ConfigValidationError("account_capital_inr must be a positive number.")
        if not math.isfinite(float(self.account_capital_inr)) or float(self.account_capital_inr) <= 0:
            raise ConfigValidationError("account_capital_inr must be finite and > 0.")

        if isinstance(self.max_risk_per_trade_pct, bool) or not isinstance(self.max_risk_per_trade_pct, (int, float)):
            raise ConfigValidationError("max_risk_per_trade_pct must be a number in (0, 100].")
        if not math.isfinite(float(self.max_risk_per_trade_pct)) or not (0.0 < float(self.max_risk_per_trade_pct) <= 100.0):
            raise ConfigValidationError(
                "max_risk_per_trade_pct must be finite and between 0 and 100."
            )

        if self.max_daily_loss_inr is not None:
            if isinstance(self.max_daily_loss_inr, bool) or not isinstance(self.max_daily_loss_inr, (int, float)) or not math.isfinite(float(self.max_daily_loss_inr)) or float(self.max_daily_loss_inr) <= 0:
                raise ConfigValidationError(
                    "max_daily_loss_inr must be a positive finite number."
                )

        if self.daily_profit_target_inr is not None:
            if isinstance(self.daily_profit_target_inr, bool) or not isinstance(self.daily_profit_target_inr, (int, float)) or not math.isfinite(float(self.daily_profit_target_inr)) or float(self.daily_profit_target_inr) <= 0:
                raise ConfigValidationError(
                    "daily_profit_target_inr must be a positive finite number."
                )

        if self.max_concurrent_positions is not None:
            if isinstance(self.max_concurrent_positions, bool) or not isinstance(self.max_concurrent_positions, int) or int(self.max_concurrent_positions) < 1:
                raise ConfigValidationError(
                    "max_concurrent_positions must be an integer >= 1."
                )

        if isinstance(self.scan_interval_seconds, bool) or not isinstance(self.scan_interval_seconds, int) or self.scan_interval_seconds < 5:
            raise ConfigValidationError(
                "scan_interval_seconds must be an integer >= 5."
            )

        for name in ("enable_background_scheduler", "telegram_dry_run", "enable_persistence"):
            if not isinstance(getattr(self, name), bool):
                raise ConfigValidationError(f"{name} must be a boolean.")

        if self.angel_request_timeout_seconds is not None:
            if isinstance(self.angel_request_timeout_seconds, bool) or not isinstance(self.angel_request_timeout_seconds, (int, float)) or not math.isfinite(self.angel_request_timeout_seconds) or float(self.angel_request_timeout_seconds) <= 0:
                raise ConfigValidationError("angel_request_timeout_seconds must be a positive number.")

        if self.angel_min_request_interval_seconds is not None:
            if isinstance(self.angel_min_request_interval_seconds, bool) or not isinstance(self.angel_min_request_interval_seconds, (int, float)) or not math.isfinite(self.angel_min_request_interval_seconds) or float(self.angel_min_request_interval_seconds) < 0:
                raise ConfigValidationError("angel_min_request_interval_seconds must be a non-negative number.")

        if self.angel_scrip_master_max_age_hours is not None:
            if isinstance(self.angel_scrip_master_max_age_hours, bool) or not isinstance(self.angel_scrip_master_max_age_hours, (int, float)) or not math.isfinite(self.angel_scrip_master_max_age_hours) or float(self.angel_scrip_master_max_age_hours) <= 0:
                raise ConfigValidationError("angel_scrip_master_max_age_hours must be a positive number.")

        if self.angel_baseline_max_sessions_age is not None:
            if isinstance(self.angel_baseline_max_sessions_age, bool) or not isinstance(self.angel_baseline_max_sessions_age, int) or int(self.angel_baseline_max_sessions_age) < 1:
                raise ConfigValidationError("angel_baseline_max_sessions_age must be an integer >= 1.")

        for name in ("live_candle_max_delay_seconds", "live_candle_future_skew_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ConfigValidationError(f"{name} must be finite and non-negative.")
        t_start = _parse_hhmm(str(self.session_start_ist or ""), "session_start_ist")
        t_end = _parse_hhmm(str(self.session_end_ist or ""), "session_end_ist")
        if t_start >= t_end:
            raise ConfigValidationError(
                "session_start_ist must be strictly earlier than session_end_ist."
            )

        for h_str in (self.configured_holidays or []):
            try:
                datetime.strptime(str(h_str).strip(), "%Y-%m-%d")
            except ValueError:
                raise ConfigValidationError("Invalid holiday date in configured_holidays. Expected YYYY-MM-DD.") from None

        if self.enable_persistence:
            from storage import resolve_sqlite_path
            try:
                resolve_sqlite_path(str(self.database_url or ""))
            except ValueError:
                raise ConfigValidationError("Invalid DATABASE_URL; a supported SQLite path is required.") from None

        if require_live_credentials and bkey in ("angelone", "dhan", "upstox"):
            if bkey == "angelone":
                missing_fields = [
                    env_name
                    for env_name, val in (
                        ("ANGEL_API_KEY", self.angel_api_key),
                        ("ANGEL_CLIENT_CODE", self.angel_client_code),
                        ("ANGEL_PIN", self.angel_pin),
                        ("ANGEL_TOTP_SECRET", self.angel_totp_secret),
                    )
                    if _is_placeholder_value(val)
                ]
                if missing_fields:
                    raise ConfigValidationError(
                        f"Active live broker 'angelone' is missing required credentials: {', '.join(missing_fields)}."
                    )
                if not _is_valid_base32_secret(self.angel_totp_secret):
                    raise ConfigValidationError(
                        "Active live broker 'angelone' has an invalid Base32 ANGEL_TOTP_SECRET."
                    )
            elif not self.is_broker_credentials_configured(bkey):
                raise ConfigValidationError(
                    f"Active live broker '{bkey}' is missing required credentials or uses placeholder values."
                )

    def to_safe_dict(self) -> Dict[str, Any]:
        """
        Returns a sanitized configuration dictionary safe for API exposure and logging.
        Never includes API keys, PINs, TOTP seeds, access tokens, or Telegram bot tokens.
        """
        bkey = (self.active_broker or "").strip().lower()
        is_sim = bkey in ("paper_sim", "simulated", "sim")
        scrip_path = str(self.angel_scrip_master_path or "").strip()
        return {
            "active_broker": self.active_broker,
            "data_mode": "SIMULATED" if is_sim else "LIVE",
            "is_simulated": is_sim,
            "account_capital_inr": float(self.account_capital_inr or 0.0),
            "max_risk_per_trade_pct": float(self.max_risk_per_trade_pct or 0.0),
            "max_daily_loss_inr": float(self.max_daily_loss_inr or 0.0),
            "daily_profit_target_inr": float(self.daily_profit_target_inr or 0.0),
            "max_concurrent_positions": int(self.max_concurrent_positions or 1),
            "scan_interval_seconds": int(self.scan_interval_seconds or 60),
            "live_candle_max_delay_seconds": self.live_candle_max_delay_seconds,
            "live_candle_future_skew_seconds": self.live_candle_future_skew_seconds,
            "session_start_ist": self.session_start_ist,
            "session_end_ist": self.session_end_ist,
            "configured_holidays": list(self.configured_holidays or []),
            "enable_persistence": bool(self.enable_persistence),
            "enable_background_scheduler": bool(self.enable_background_scheduler),
            "telegram_dry_run": bool(self.telegram_dry_run),
            "brokers_configured": {
                "angelone": self.is_broker_credentials_configured("angelone"),
                "dhan": self.is_broker_credentials_configured("dhan"),
                "upstox": self.is_broker_credentials_configured("upstox"),
                "paper_sim": True,
            },
            "dhan_feed_instrument_count": len(self.dhan_feed_instruments or []),
            "angel_scrip_master_configured": bool(scrip_path and os.path.isfile(scrip_path)),
            "angel_scrip_master_max_age_hours": float(self.angel_scrip_master_max_age_hours or 24.0),
            "angel_baseline_max_sessions_age": int(self.angel_baseline_max_sessions_age or 1),
            "telegram_configured": not (
                _is_placeholder_value(self.telegram_bot_token) or _is_placeholder_value(self.telegram_chat_id)
            ),
            "fo_indices": [
                {"symbol": k, "name": v.get("name"), "lot_size": v.get("lot_size"), "strike_step": v.get("strike_step")}
                for k, v in (self.fo_indices or {}).items()
            ],
            "equity_watchlist_count": len(self.equity_watchlist or []),
            "equity_watchlist_symbols": [item.get("symbol") for item in (self.equity_watchlist or [])],
        }

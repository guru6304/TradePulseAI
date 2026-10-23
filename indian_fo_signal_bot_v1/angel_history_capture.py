"""One read-only completed-session Angel history capture; never research authority.

The caller owns preflight and initial authentication. No login, refresh, retries,
redirects, orders or automatic scheduling exist here. Original response bytes and
derived candidate bars are separate files beneath the private local research root.
Authenticated HTTPS is retained as acquisition evidence, never a detached publisher
signature or a rights approval. Transport injection always produces SIMULATED data.
"""
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import ssl
import urllib.error
import urllib.request

from historical_data import validate_and_prepare_historical_dataset
from instrument_identity import bind_candles, check_echo
from strategies import IST

VERSION = "angel-history-capture-v1"
ENDPOINT = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
MAX_BYTES = 8 * 1024 * 1024


class HistoryCaptureError(ValueError):
    """Stable error code only; private request/response contents never enter errors."""


def _reject(code):
    raise HistoryCaptureError(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _aware(value):
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        _reject("AWARE_SOURCE_TIMESTAMP_REQUIRED")
    return stamp.astimezone(IST)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _secure_open(request, timeout):
    opener = urllib.request.build_opener(_NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    return opener.open(request, timeout=timeout)


def _private_root(root, fixture):
    root = Path(root).resolve()
    if not fixture:
        base = Path(__file__).resolve().parent / ".local"
        if (base.is_symlink() or getattr(base, "is_junction", lambda: False)()
                or not root.is_relative_to(base) or root == base):
            _reject("PRIVATE_LOCAL_RESEARCH_ROOT_REQUIRED")
    return root


def _normalise(raw, identity, day, received, config, fixture):
    from historical_study import strict_json
    envelope = strict_json(raw.decode("utf-8-sig"))
    if not isinstance(envelope, dict) or envelope.get("status") is not True:
        _reject("ANGEL_HISTORICAL_PROVIDER_REJECTED")
    check_echo(envelope, identity)
    rows = envelope.get("data")
    if not isinstance(rows, list) or not rows or len(rows) > 75:
        _reject("ANGEL_HISTORICAL_EMPTY_OR_OUT_OF_SCOPE_ROWS")
    bars = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 6:
            _reject("ANGEL_HISTORICAL_ROW_SCHEMA_INVALID")
        stamp = _aware(row[0])
        if stamp.date() != day or stamp + timedelta(minutes=5) > received:
            _reject("ANGEL_HISTORICAL_ROW_OUTSIDE_COMPLETED_WINDOW")
        bars.append(dict(timestamp=stamp.isoformat(), open=row[1], high=row[2], low=row[3], close=row[4], volume=row[5],
            is_complete=True, data_mode="SIMULATED" if fixture else "LIVE", is_simulated=fixture))
    if not fixture:
        bars = bind_candles(bars, identity, envelope)
    prepared = validate_and_prepare_historical_dataset(bars, identity["symbol"], "NSE_EQUITY_INTRADAY", "NSE",
        "fixture_angelone" if fixture else "angelone", identity["identifier"], interval_min=5,
        data_mode="SIMULATED" if fixture else "LIVE", reference_time_ist=received, retrieved_at_ist=received,
        configured_holidays=config.configured_holidays, allow_identical_duplicates=False, sort_chronologically=False,
        reject_forming_candles=True, session_start_ist="09:15", session_end_ist="15:30")
    return prepared


def capture_one_history(adapter, symbol_meta, session_date, private_root, stage, *,
                        transport=None, allow_live_request=False):
    """Capture exactly one session through an already-authenticated Angel adapter.

    ``transport(request, timeout=...)`` is an OFFLINE fixture seam. Passing it can
    never produce LIVE-classified output. A real call requires explicit
    ``allow_live_request=True`` after the caller's offline tests and preflight.
    Return only public-safe metadata. Original bytes and normalized candidates
    remain private; callers may publish the returned receipt, never raw files.
    """
    from brokers import AngelOneSmartAPIAdapter
    if not isinstance(adapter, AngelOneSmartAPIAdapter):
        _reject("EXPLICIT_ANGEL_ADAPTER_REQUIRED")
    cfg = adapter.config
    # active_broker on this explicitly read-only adapter may name its data
    # provider. The caller's execution configuration remains independently paper.
    if (cfg.active_broker not in ("paper_sim", "angelone") or cfg.telegram_dry_run is not True
            or cfg.enable_background_scheduler is not False):
        _reject("PAPER_DRY_RUN_DISABLED_SCHEDULER_REQUIRED")
    if not adapter.jwt_token:
        _reject("EXISTING_ANGEL_AUTHENTICATION_REQUIRED")
    fixture = transport is not None
    if not fixture and allow_live_request is not True:
        _reject("EXPLICIT_BOUNDED_HISTORY_AUTHORIZATION_REQUIRED")
    if not isinstance(stage, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", stage):
        _reject("UNSAFE_CAPTURE_STAGE")
    reference = _aware(adapter.clock())
    try:
        day = date.fromisoformat(session_date) if isinstance(session_date, str) else session_date
        if not isinstance(day, date) or isinstance(day, datetime):
            raise ValueError()
        end = datetime.combine(day, time(15, 30), IST)
    except (ValueError, TypeError):
        _reject("EXPLICIT_COMPLETED_SESSION_DATE_REQUIRED")
    if (day.weekday() >= 5 or day.isoformat() in cfg.configured_holidays or end > reference
            or cfg.session_start_ist != "09:15" or cfg.session_end_ist != "15:30"):
        _reject("EXPLICIT_COMPLETED_STANDARD_NSE_SESSION_REQUIRED")
    resolved = adapter.resolve_instrument(symbol_meta)
    identity = resolved["instrument_identity"]
    current = adapter._scrip_master_equities.get(identity["symbol"])
    if (identity["provider"] != "angelone" or identity["exchange"] != "NSE" or identity["instrument_type"] != "EQ"
            or not current or str(current.get("angel_token")) != identity["identifier"]
            or not adapter._scrip_master_meta.get("source_revision")):
        _reject("CURRENT_MASTER_CASH_MAPPING_REQUIRED")
    root = _private_root(private_root, fixture)
    root.mkdir(parents=True, exist_ok=True)
    folder = root / stage
    # Exclusive reservation precedes the request: reusing a stage cannot repeat it.
    folder.mkdir(exist_ok=False)
    payload = dict(exchange="NSE", symboltoken=identity["identifier"], interval="FIVE_MINUTE",
        fromdate=day.isoformat() + " 09:15", todate=day.isoformat() + " 15:25")
    request_raw = _json(payload)
    (folder / "request.json").write_bytes(request_raw)
    receipt = dict(schema_version=VERSION, provider="angelone", endpoint=ENDPOINT, method="POST", request=payload,
        request_sha256=_sha(request_raw), request_started_at=reference.isoformat(), session_date=day.isoformat(),
        symbol=identity["symbol"], identifier=identity["identifier"], exchange="NSE", interval_min=5,
        expected_session_bars=75, current_mapping_revision=adapter._scrip_master_meta["source_revision"],
        historical_identity_authority="NOT_ESTABLISHED", capture_class="SYNTHETIC_TRANSPORT_FIXTURE" if fixture else "AUTHENTICATED_HTTPS_API_CANDIDATE",
        candidate_only=True, research_eligible=False, publisher_signature="NOT_SUPPLIED", rights_approval="NOT_ESTABLISHED",
        historical_study_status="BLOCKED", phase3_websocket_acceptance=False, http_status=None,
        response_sha256=None, original_response_complete=False, response_bytes=0, normalization_status="NOT_ATTEMPTED",
        normalized_bar_count=0, quality_status="NOT_ASSESSED", missing_bars_count=None, provider_cause="NOT_ESTABLISHED",
        network_requests=0 if fixture else 1, transport_calls=1, retries=0, redirects_followed=0,
        authentication_calls=0, token_refresh_calls=0, order_calls=0, stage=stage)
    receipt["execution_scope"] = "READ_ONLY_DATA_CAPTURE_NO_EXECUTION"
    request = urllib.request.Request(ENDPOINT, data=request_raw, headers=adapter._headers(include_auth=True), method="POST")
    body, response, complete = None, None, False
    try:
        try:
            response = (transport or _secure_open)(request, timeout=8.0)
        except urllib.error.HTTPError as exc:
            response = exc
        status = getattr(response, "status", None) or getattr(response, "code", None)
        if type(status) is not int:
            status = response.getcode()
        receipt["http_status"] = status
        headers = getattr(response, "headers", {}) or {}
        receipt["content_type"] = str(headers.get("Content-Type", "")).split(";", 1)[0].lower()
        if receipt["content_type"] not in ("application/json", "text/json", "text/html", "text/plain"):
            receipt["content_type"] = "UNKNOWN"
        try:
            server_date = parsedate_to_datetime(headers.get("Date", ""))
            receipt["provider_http_date_utc"] = server_date.astimezone(timezone.utc).isoformat() if server_date.tzinfo else None
        except (TypeError, ValueError, OverflowError):
            receipt["provider_http_date_utc"] = None
        body = response.read(MAX_BYTES + 1)
        if not isinstance(body, bytes):
            _reject("ANGEL_HISTORICAL_RESPONSE_BYTES_REQUIRED")
        complete = len(body) <= MAX_BYTES
        receipt.update(response_sha256=_sha(body), response_bytes=len(body), original_response_complete=complete)
        (folder / ("response.bin" if complete else "response_prefix.bin")).write_bytes(body)
        # No raw headers, server text, cookies, account fields or error bodies are
        # copied into the returned/public receipt. Hash original private bytes.
        receipt["response_received_at"] = _aware(adapter.clock()).isoformat()
        if not complete:
            receipt["normalization_status"] = "RESPONSE_RESOURCE_LIMIT"
        elif status != 200:
            receipt["normalization_status"] = "HTTP_REQUEST_REJECTED"
            receipt["blocker_code"] = "ANGEL_HISTORICAL_CANDLE_REQUEST_REJECTED"
        else:
            try:
                prepared = _normalise(body, identity, day, _aware(adapter.clock()), cfg, fixture)
                raw_normalized = _json(dict(schema_version="tradepulse.cash-observations.v1", candles=prepared["candles"]))
                (folder / "normalized_candidate.json").write_bytes(raw_normalized)
                quality = prepared["manifest"]
                receipt.update(normalization_status="VALIDATED_CANDIDATE_ONLY", normalized_bar_count=quality["bars_count"],
                    normalized_sha256=_sha(raw_normalized), quality_status=quality["quality_status"],
                    missing_bars_count=quality["missing_bars_count"], missing_timestamps=quality["missing_timestamps"],
                    duplicate_bars_coalesced=quality["duplicate_bars_coalesced"], filtered_forming_count=quality["filtered_forming_count"],
                    dataset_checksum=quality["sha256_checksum"], coverage_start=quality["from_timestamp_ist"],
                    coverage_end=quality["to_timestamp_ist"], data_mode="SIMULATED" if fixture else "LIVE")
            except (ValueError, KeyError, TypeError, UnicodeError):
                receipt["normalization_status"] = "SOURCE_SCHEMA_IDENTITY_OR_QUALITY_REJECTED"
    except Exception as exc:
        # Do not retain exception strings: transport failures may echo headers.
        receipt["normalization_status"] = "TRANSPORT_OR_CAPTURE_FAILURE"
        receipt["error_type"] = type(exc).__name__
        receipt["blocker_code"] = "ANGEL_PROVIDER_UNAVAILABLE"
    finally:
        if response is not None:
            try:
                response.close()
                receipt["response_closed"] = True
            except Exception:
                receipt["response_closed"] = False
                receipt["normalization_status"] = "RESPONSE_CLOSE_FAILED"
    receipt["completed_at"] = _aware(adapter.clock()).isoformat()
    receipt["private_files"] = [name.name for name in sorted(folder.iterdir()) if name.is_file()]
    (folder / "capture_receipt.json").write_bytes(_json(receipt))
    return receipt

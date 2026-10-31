"""Bounded, transport-free inspection of option snapshots, never execution inputs.

Endpoint schemas are separate: no REST quantity/Greek scaling or source clock is
inferred from another endpoint. Retained master declarations establish structural
identity only. Even synthetic mechanics outputs remain non-actionable.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException
import hashlib
import json
import math
import re

from instrument_identity import IdentityValidationError, prepare_contract_master, validate_contract_identity

UPSTOX_V2_CHAIN = "upstox.v2.option_chain"
UPSTOX_V3_GREEKS = "upstox.v3.option_greeks"
ANGEL_GREEKS = "angelone.v1.option_greeks"
PARSER_VERSION = "option-capture-inspection-v1"
MAX_BYTES = 2 * 1024 * 1024
MAX_OBSERVATIONS = 100
IST = timezone(timedelta(hours=5, minutes=30))
PROVENANCE = ("SYNTHETIC_FIXTURE", "UNVERIFIED_CAPTURE")
FIELDS = ("ltp", "volume", "oi", "previous_oi", "previous_close", "bid_price",
          "bid_qty", "ask_price", "ask_qty", "ltq", "delta", "gamma", "theta", "vega", "iv", "pop")
COUNTS = {"volume", "oi", "previous_oi", "bid_qty", "ask_qty", "ltq"}
SIGNED = {"delta", "gamma", "theta", "vega", "pop"}
MONTHS = {v: i for i, v in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


class ObservationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise ObservationError(code)


def _text(value, code="INVALID_TEXT"):
    if not isinstance(value, str) or not value or len(value) > 512 or value != value.strip():
        _fail(code)
    return value


def _time(value):
    # datetime.fromisoformat also accepts dates and arbitrary separators; this
    # boundary deliberately admits only explicit ISO timestamps with an offset.
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-5][0-9]:[0-5][0-9]"
            r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])", value):
        _fail("INVALID_OFFSET_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        parsed.astimezone(IST)  # Reject calendar overflow before downstream date comparisons.
        return parsed
    except (ValueError, OverflowError):
        _fail("INVALID_OFFSET_TIMESTAMP")


def _day(value, angel=False):
    try:
        if angel:
            if not isinstance(value, str) or not re.fullmatch(r"\d{2}[A-Z]{3}\d{4}", value):
                raise ValueError()
            return date(int(value[5:]), MONTHS[value[2:5]], int(value[:2])).isoformat()
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError()
        return date.fromisoformat(value).isoformat()
    except (ValueError, KeyError):
        _fail("INVALID_EXACT_DATE")


def _number(value, *, count=False, signed=False, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _fail("INVALID_NUMERIC_VALUE")
    if isinstance(value, str) and (len(value) > 64 or not re.fullmatch(
            r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value)):
        _fail("INVALID_NUMERIC_VALUE")
    try:
        numeric = Decimal(str(value))
        if (not numeric.is_finite() or (not signed and numeric < 0)
                or (positive and numeric <= 0) or numeric > 2**53 - 1 or numeric < -(2**53 - 1)
                or (count and numeric != numeric.to_integral_value())):
            _fail("INVALID_NUMERIC_VALUE")
        parsed = int(numeric) if count else float(numeric)
        if not math.isfinite(parsed) or (positive and parsed <= 0) or (numeric != 0 and parsed == 0):
            _fail("INVALID_NUMERIC_VALUE")
        return parsed
    except (DecimalException, OverflowError, ValueError) as exc:
        if isinstance(exc, ObservationError):
            raise
        _fail("INVALID_NUMERIC_VALUE")


def _strict_json(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        _fail("INVALID_CAPTURE_SIZE")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail("DUPLICATE_JSON_FIELD")
            result[key] = value
        return result
    def exact_float(token):
        # json.loads' default float conversion loses nonzero underflow and may
        # round a fractional count into an integer before field validation. Keep
        # only literals representable without changing their canonical decimal
        # value; original bytes remain available for any future interpretation.
        parsed = _number(token, signed=True)
        if Decimal(token) != Decimal(str(parsed)):
            _fail("JSON_NUMBER_PRECISION_LOSS")
        return parsed
    try:
        text = raw.decode("utf-8")
        data = json.loads(text, object_pairs_hook=unique, parse_float=exact_float,
                          parse_constant=lambda _: _fail("NONFINITE_JSON"))
        _json_shape(data)
        # Nonfinite overflow (1e999) is not routed through parse_constant.
        json.dumps(data, allow_nan=False)
        return text, data
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, ObservationError):
            raise
        _fail("INVALID_CAPTURE_JSON")


def _object(value):
    if not isinstance(value, dict):
        _fail("INVALID_RESPONSE_OBJECT")
    return value


def _json_shape(value):
    """Limit metadata work and forbid key coercion in source fingerprints."""
    count, characters = 0, 0
    def visit(item, depth=0):
        nonlocal count, characters
        count += 1
        if count > 20000 or depth > 32:
            _fail("DECLARATION_TOO_LARGE")
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    _fail("INVALID_DECLARATION_JSON")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            characters += len(item)
            if len(item) > 65536 or characters > MAX_BYTES:
                _fail("DECLARATION_TOO_LARGE")
        elif type(item) not in (int, float, bool, type(None)):
            _fail("INVALID_DECLARATION_JSON")
    visit(value)


def _master(master, provider, received):
    if not isinstance(master, dict) or not isinstance(master.get("original_bytes"), bytes):
        _fail("INVALID_MASTER_INTEGRITY")
    if len(master["original_bytes"]) > MAX_BYTES:
        _fail("MASTER_TOO_LARGE")
    try:
        meta = master["metadata"]
        rebuilt = prepare_contract_master(master["original_bytes"], provider=meta["provider"],
            source_reference=meta["source_reference"], source_version=meta["source_version"],
            captured_at=meta["captured_at"], parser_version=meta["parser_version"])
        if rebuilt != master or meta["provider"] != provider:
            _fail("INVALID_MASTER_INTEGRITY")
    except (KeyError, TypeError, IdentityValidationError, RecursionError):
        _fail("INVALID_MASTER_INTEGRITY")
    if rebuilt["status"] != "BLOCKED_UNQUALIFIED_MASTER":
        _fail("DATED_NORMALIZED_MASTER_REQUIRED")
    if meta["captured_at"] is None:
        _fail("MASTER_CAPTURE_TIME_REQUIRED")
    if _time(meta["captured_at"]) > received:
        _fail("MASTER_NOT_AVAILABLE_AT_CAPTURE")
    return rebuilt


def _identity(master, day, *, identifier=None, underlying=None, expiry=None, strike=None, side=None):
    # prepare_contract_master already validates exact identities, unique terms,
    # provider-specific identifiers and underlying coverage against original bytes.
    # This bounded batch lookup applies the resolver's date/status checks once per
    # selected record without rebuilding the same original bytes for each leg.
    matches = [r for r in master["records"] if r["instrument_type"] in ("OPTIDX", "OPTSTK")
               and all(v is None or r.get(k) == v for k, v in
                       (("identifier", identifier), ("underlying", underlying), ("expiry", expiry),
                        ("strike", strike), ("option_type", side)))]
    if len(matches) != 1:
        _fail("EXACT_UNIQUE_OPTION_REQUIRED")
    identity = matches[0]
    if (identity["expiry"] < day or not identity["valid_from"] <= day <= identity["valid_to"]
            or identity["contract_status"] != "ACTIVE"):
        _fail("OPTION_NOT_EFFECTIVE")
    spots = [r for r in master["records"] if r["identifier"] == identity["underlying_identifier"]
             and r["symbol"] == identity["underlying"]
             and r["instrument_type"] == ("INDEX_SPOT" if identity["instrument_type"] == "OPTIDX" else "EQ")]
    if len(spots) != 1 or spots[0]["contract_status"] != "ACTIVE":
        _fail("UNDERLYING_NOT_EFFECTIVE")
    return deepcopy(identity), deepcopy(spots[0])


def _fields(sources):
    result = {}
    for field in FIELDS:
        mapping = sources.get(field)
        obj, key, path = mapping if mapping else ({}, field, None)
        present = key in obj
        raw = obj.get(key)
        result[field] = dict(presence="ABSENT" if not present else "NULL" if raw is None else "OBSERVED",
            raw_value=raw, numeric_value=None if raw is None else _number(raw, count=field in COUNTS, signed=field in SIGNED),
            raw_path=path, normalized_value=None, unit_status="UNAVAILABLE_UNIT_CONTRACT")
    bid, ask = (result[f]["numeric_value"] for f in ("bid_price", "ask_price"))
    if bid is not None and ask is not None and bid > 0 and ask > 0 and bid > ask:
        _fail("CROSSED_TOP_OF_BOOK")
    return result


def _maps(obj, mapping, path):
    return {field: (obj, native, path + [native]) for field, native in mapping.items()}


def parse_option_capture(raw_bytes, *, endpoint, request, master, received_at, available_at,
                         decision_at, provenance):
    """Inspect three documented response shapes; no adapter, trust or fill activation.

    Local received/available times and master capture time are caller declarations.
    They constrain look-ahead in these mechanics but do not prove provider clocks.
    A native master without exact dated declarations cannot resolve this interface.
    """
    if endpoint not in (UPSTOX_V2_CHAIN, UPSTOX_V3_GREEKS, ANGEL_GREEKS):
        _fail("UNSUPPORTED_ENDPOINT")
    if provenance not in PROVENANCE:
        _fail("EXPLICIT_PROVENANCE_REQUIRED")
    received, available, decision = map(_time, (received_at, available_at, decision_at))
    if not received <= available <= decision:
        _fail("AVAILABILITY_AFTER_CUTOFF")
    provider = "angelone" if endpoint == ANGEL_GREEKS else "upstox"
    retained = _master(master, provider, received)
    raw_text, payload = _strict_json(raw_bytes)
    payload, request = _object(payload), _object(request)
    if endpoint == ANGEL_GREEKS:
        if payload.get("status") is not True or payload.get("errorcode") not in (None, ""):
            _fail("PROVIDER_RESPONSE_FAILED")
    elif payload.get("status") != "success":
        _fail("PROVIDER_RESPONSE_FAILED")
    day = received.astimezone(IST).date().isoformat()
    observations, seen = [], set()
    requested = []

    def append(identity, spot, path, sources):
        token = identity["identifier"]
        if token in seen:
            _fail("DUPLICATE_OPTION")
        seen.add(token)
        if len(seen) > MAX_OBSERVATIONS:
            _fail("TOO_MANY_OBSERVATIONS")
        observations.append(dict(identity=identity, underlying_identity=spot, locator=path,
            fields=_fields(sources), source_time=None, source_time_status="UNAVAILABLE_SOURCE_TIME",
            eligible=False, actionable=False, historical_replay_allowed=False))

    if endpoint == UPSTOX_V3_GREEKS:
        if set(request) != {"instrument_keys"}:
            _fail("INVALID_REQUEST_SCOPE")
        requested = request["instrument_keys"]
        if (not isinstance(requested, list) or not 1 <= len(requested) <= 50
                or any(not isinstance(k, str) for k in requested) or len(set(requested)) != len(requested)):
            _fail("INVALID_REQUEST_SCOPE")
        # Validate missing responses' requested identities too; partial data cannot
        # hide an invalid requested contract behind a valid returned token.
        identities = {key: _identity(retained, day, identifier=key) for key in requested}
        rows = _object(payload.get("data"))
        if len(rows) > 50:
            _fail("TOO_MANY_OBSERVATIONS")
        for label, row in rows.items():
            row = _object(row)
            token = row.get("instrument_token")
            if not isinstance(token, str) or token not in identities:
                _fail("UNREQUESTED_OPTION")
            mapping = {f: f for f in ("ltq", "volume", "oi", "iv", "vega", "gamma", "theta", "delta")}
            mapping.update(ltp="last_price", previous_close="cp")
            append(*identities[token], ["data", label], _maps(row, mapping, ["data", label]))
    else:
        rows = payload.get("data")
        if not isinstance(rows, list) or len(rows) > MAX_OBSERVATIONS:
            _fail("INVALID_RESPONSE_ROWS")
        if endpoint == UPSTOX_V2_CHAIN:
            if set(request) != {"underlying_key", "expiry_date"}:
                _fail("INVALID_REQUEST_SCOPE")
            underlying_key = _text(request["underlying_key"])
            expiry = _day(request["expiry_date"])
            spots = [r for r in retained["records"] if r["identifier"] == underlying_key and r["instrument_type"] in ("EQ", "INDEX_SPOT")]
            if len(spots) != 1 or spots[0]["contract_status"] != "ACTIVE" or not spots[0]["valid_from"] <= day <= spots[0]["valid_to"] or expiry < day:
                _fail("INVALID_REQUEST_SCOPE")
            for i, row in enumerate(rows):
                row = _object(row)
                if row.get("underlying_key") != underlying_key or _day(row.get("expiry")) != expiry:
                    _fail("CHAIN_SCOPE_MISMATCH")
                strike = _number(row.get("strike_price"), positive=True)
                if "underlying_spot_price" in row:
                    _number(row["underlying_spot_price"], positive=True)
                if not any(k in row for k in ("call_options", "put_options")):
                    _fail("MISSING_OPTION_LEGS")
                for key, side in (("call_options", "CE"), ("put_options", "PE")):
                    if key not in row:
                        continue
                    leg = _object(row[key])
                    identity, spot = _identity(retained, day, identifier=_text(leg.get("instrument_key")),
                        underlying=spots[0]["symbol"], expiry=expiry, strike=strike, side=side)
                    path = ["data", i, key]
                    market = _object(leg.get("market_data", {}))
                    greeks = _object(leg.get("option_greeks", {}))
                    mapping = {f: f for f in ("ltp", "volume", "oi", "bid_price", "bid_qty", "ask_price", "ask_qty")}
                    mapping.update(previous_oi="prev_oi", previous_close="close_price")
                    sources = _maps(market, mapping, path + ["market_data"])
                    sources.update(_maps(greeks, {f: f for f in ("delta", "gamma", "theta", "vega", "iv", "pop")}, path + ["option_greeks"]))
                    append(identity, spot, path, sources)
        else:
            if set(request) != {"name", "expirydate"}:
                _fail("INVALID_REQUEST_SCOPE")
            name, expiry = _text(request["name"]), _day(request["expirydate"], angel=True)
            if not any(r["symbol"] == name and r["instrument_type"] in ("EQ", "INDEX_SPOT")
                       and r["contract_status"] == "ACTIVE" and r["valid_from"] <= day <= r["valid_to"]
                       for r in retained["records"]) or expiry < day:
                _fail("INVALID_REQUEST_SCOPE")
            for i, row in enumerate(rows):
                row = _object(row)
                if row.get("name") != name or _day(row.get("expiry"), angel=True) != expiry:
                    _fail("GREEKS_SCOPE_MISMATCH")
                side = row.get("optionType")
                if side not in ("CE", "PE"):
                    _fail("INVALID_OPTION_SIDE")
                identity, spot = _identity(retained, day, underlying=name, expiry=expiry,
                    strike=_number(row.get("strikePrice"), positive=True), side=side)
                mapping = {f: f for f in ("delta", "gamma", "theta", "vega")}
                mapping.update(iv="impliedVolatility", volume="tradeVolume")
                append(identity, spot, ["data", i], _maps(row, mapping, ["data", i]))
    observations.sort(key=lambda r: r["identity"]["identifier"])
    return dict(schema_version="tradepulse.option-capture.v1", parser_version=PARSER_VERSION,
        status="STRUCTURALLY_VALID_UNQUALIFIED", provider=provider, endpoint=endpoint,
        request=deepcopy(request), provenance=provenance, data_mode="SIMULATED" if provenance == "SYNTHETIC_FIXTURE" else "LIVE",
        raw_text=raw_text, raw_sha256=hashlib.sha256(raw_bytes).hexdigest(), raw_size_bytes=len(raw_bytes),
        master_id=retained["master_id"], master_sha256=retained["metadata"]["original_sha256"],
        master_metadata=deepcopy(retained["metadata"]), received_at=received_at, available_at=available_at,
        decision_at=decision_at, observations=observations, missing_identifiers=sorted(set(requested) - seen),
        capabilities={"source_time": "UNAVAILABLE", "normalized_units": "UNAVAILABLE",
                      "dated_prior_close_oi": "UNAVAILABLE", "executable_depth": "UNAVAILABLE",
                      "publisher_authority": "NOT_ESTABLISHED", "replay_dataset": "NOT_ESTABLISHED"},
        eligible=False, actionable=False, historical_replay_allowed=False)


def inspect_depth(bids, asks, *, quantity_unit=None, requested_units=None, provenance="UNVERIFIED_CAPTURE"):
    """Check displayed levels. Coverage is synthetic declared-unit arithmetic only."""
    if provenance not in PROVENANCE or quantity_unit not in (None, "UNKNOWN", "CONTRACTS", "UNDERLYING_UNITS"):
        _fail("INVALID_DEPTH_DECLARATION")
    parsed = []
    for levels, descending in ((bids, True), (asks, False)):
        if not isinstance(levels, list) or not 1 <= len(levels) <= 30:
            _fail("INVALID_DEPTH_LEVELS")
        side = []
        for row in levels:
            if not isinstance(row, dict) or set(row) != {"price", "quantity"}:
                _fail("INVALID_DEPTH_LEVEL")
            price, quantity = _number(row["price"], positive=True), _number(row["quantity"], count=True)
            if side and (price >= side[-1]["price"] if descending else price <= side[-1]["price"]):
                _fail("UNSORTED_DEPTH")
            side.append(dict(price=price, quantity=quantity))
        parsed.append(side)
    if parsed[0][0]["price"] > parsed[1][0]["price"]:
        _fail("CROSSED_TOP_OF_BOOK")
    size = None if requested_units is None else _number(requested_units, count=True, positive=True)
    coverage = None
    if provenance == "SYNTHETIC_FIXTURE" and quantity_unit == "UNDERLYING_UNITS" and size is not None:
        coverage = {name: sum(r["quantity"] for r in rows) >= size for name, rows in zip(("bid", "ask"), parsed)}
    return dict(bids=parsed[0], asks=parsed[1], raw_bids=deepcopy(bids), raw_asks=deepcopy(asks),
        quantity_unit=quantity_unit, requested_units=size, coverage=coverage,
        status="SYNTHETIC_MECHANICS_ONLY" if coverage is not None else "UNAVAILABLE_UNIT_OR_SOURCE_CONTRACT",
        provenance=provenance, eligible=False, actionable=False, executable_depth=False)


def _digest(value):
    try:
        _json_shape(value)
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded) > MAX_BYTES:
            _fail("DECLARATION_TOO_LARGE")
        return hashlib.sha256(encoded).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ObservationError):
            raise
        _fail("INVALID_DECLARATION_JSON")


def _policy_seconds(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 86400:
        _fail("INVALID_FRESHNESS_POLICY")
    return value


def _oi_observation(row, decision):
    row = _object(row)
    identity = _object(row.get("identity"))
    try:
        validate_contract_identity(identity, provider=identity.get("provider"))
    except IdentityValidationError:
        _fail("INVALID_OI_IDENTITY")
    revision = identity.get("source_revision")
    if (identity.get("instrument_type") not in ("OPTIDX", "OPTSTK")
            or not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision)):
        _fail("INVALID_OI_IDENTITY")
    if row.get("provenance") not in PROVENANCE:
        _fail("EXPLICIT_PROVENANCE_REQUIRED")
    _text(row.get("source_reference"))
    if row.get("quantity_unit") not in (None, "UNKNOWN", "CONTRACTS", "UNDERLYING_UNITS"):
        _fail("INVALID_OI_UNIT")
    value = _number(row.get("value"), count=True)
    observed, available = _time(row.get("observed_at")), _time(row.get("available_at"))
    day = _day(row.get("session_date"))
    local = observed.astimezone(IST)
    minute = local.hour * 60 + local.minute + local.second / 60 + local.microsecond / 60000000
    if (local.date().isoformat() != day or local.weekday() > 4 or not 555 <= minute <= 930
            or not observed <= available <= decision):
        _fail("INVALID_OI_CLOCK")
    if (not identity["valid_from"] <= day <= identity["valid_to"] or identity["expiry"] < day
            or identity.get("contract_status") != "ACTIVE"):
        _fail("OI_CONTRACT_NOT_EFFECTIVE")
    return value, observed, _digest(row)


def compare_oi(current, baseline, *, decision_at, max_age_seconds, max_alignment_seconds):
    """Declared-clock OI mechanics; genuine prior-close authority stays unavailable.

    PRIOR_CLOSE requires an explicit preceding session declaration and exact15:30
    IST observation. Only synthetic fixtures can yield arithmetic. The session
    declaration is not a verified trading calendar, and quantity units are never
    inferred from a master lot size or an endpoint's raw prev_oi field.
    """
    decision = _time(decision_at)
    age, alignment = _policy_seconds(max_age_seconds), _policy_seconds(max_alignment_seconds)
    current_value, current_time, current_hash = _oi_observation(current, decision)
    baseline_value, baseline_time, baseline_hash = _oi_observation(baseline, decision)
    if current.get("kind") != "CURRENT" or baseline.get("kind") not in ("PRIOR_CLOSE", "INTRADAY", "UNKNOWN"):
        _fail("INVALID_OI_BASELINE_KIND")
    if current["identity"] != baseline["identity"]:
        _fail("OI_CONTRACT_MISMATCH")
    if current.get("quantity_unit") != baseline.get("quantity_unit"):
        _fail("OI_UNIT_MISMATCH")
    if not baseline_time < current_time or (decision - current_time).total_seconds() > age:
        _fail("STALE_OR_UNORDERED_OI")
    kind = baseline["kind"]
    if kind == "INTRADAY" and (current["session_date"] != baseline["session_date"]
                              or (current_time - baseline_time).total_seconds() > alignment):
        _fail("MISALIGNED_INTRADAY_OI")
    if kind == "PRIOR_CLOSE":
        prior_day = _day(current.get("prior_session_date"))
        close = baseline_time.astimezone(IST)
        if (prior_day != baseline["session_date"] or prior_day >= current["session_date"]
                or (close.hour, close.minute, close.second, close.microsecond) != (15, 30, 0, 0)):
            _fail("INVALID_PRIOR_CLOSE_DECLARATION")
    status, delta = "UNAVAILABLE_BASELINE_SEMANTICS", None
    if kind != "UNKNOWN":
        if current.get("quantity_unit") in (None, "UNKNOWN"):
            status = "UNAVAILABLE_UNIT_CONTRACT"
        elif current["provenance"] != "SYNTHETIC_FIXTURE" or baseline["provenance"] != "SYNTHETIC_FIXTURE":
            status = "UNQUALIFIED_SOURCE"
        else:
            status, delta = "SYNTHETIC_MECHANICS_ONLY", current_value - baseline_value
    return dict(schema_version="tradepulse.oi-comparison.v1", status=status, delta=delta,
        current=deepcopy(current), baseline=deepcopy(baseline),
        input_sha256s={"current": current_hash, "baseline": baseline_hash},
        decision_at=decision_at, max_age_seconds=age, max_alignment_seconds=alignment,
        prior_close_authority="NOT_ESTABLISHED", eligible=False, actionable=False, historical_replay_allowed=False)

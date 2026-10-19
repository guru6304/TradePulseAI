"""Local identity consistency policy; mappings are not a broker-acceptance claim.

The checked-in BotConfig defaults are a pinned application reference, not a dated
historical master. Runtime configuration cannot redefine those mappings. Current
Angel master records may add equities/contracts, but cannot contradict the pins.
Archived-master checks trust supplied local research inputs; their digest detects
corruption, not publisher authenticity. No network, expiry-calendar or lot inference.
"""
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, TypedDict

from config import BotConfig


REFERENCE_SOURCE = "CHECKED_IN_BOTCONFIG_REFERENCE_V1"
INDICES = BotConfig.__dataclass_fields__["fo_indices"].default_factory()
EQUITIES = {r["symbol"]: r for r in BotConfig.__dataclass_fields__["equity_watchlist"].default_factory()}
PROVIDERS = ("angelone", "dhan", "upstox")
ALIASES = {"NIFTY 50": "NIFTY", "BANK NIFTY": "BANKNIFTY", "NIFTY BANK": "BANKNIFTY"}


class IdentityValidationError(ValueError):
    def __init__(self, code, reason):
        self.rejection = {"reason_code": code, "reason": reason}
        super().__init__(reason)


def reject(code, reason):
    raise IdentityValidationError(code, reason)


def digest(records):
    try:
        encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError):
        reject("INVALID_IDENTITY_PROVENANCE", "Identity provenance must contain finite JSON values.")
    return hashlib.sha256(encoded).hexdigest()


def canonical_symbol(value):
    if not isinstance(value, str) or not value.strip():
        reject("MISSING_SYMBOL", "Instrument symbol is required.")
    symbol = value.strip().upper()
    symbol = ALIASES.get(symbol, symbol)
    if symbol.endswith("-EQ"):
        symbol = symbol[:-3]
        if symbol in INDICES:
            reject("IDENTITY_MISMATCH", "An index cannot use an equity trading-symbol suffix.")
    return symbol


def positive_integer(value, field):
    try:
        number = Decimal(str(value))
        if isinstance(value, bool) or not number.is_finite() or number <= 0 or number != number.to_integral_value():
            raise ValueError()
        return int(number)
    except (ValueError, TypeError, InvalidOperation):
        reject("INVALID_CONTRACT_QUANTITY", f"{field} must be an explicit positive integer.")


def spot_identity(meta, provider, master=None):
    if not isinstance(meta, dict):
        reject("MISSING_IDENTITY", "Instrument metadata must be an object.")
    provider = str(provider).strip().lower()
    if provider not in PROVIDERS:
        reject("UNSUPPORTED_PROVIDER", "No trusted live mapping exists for this provider.")
    symbol = canonical_symbol(meta.get("symbol"))
    is_index = symbol in INDICES
    pinned = INDICES.get(symbol) if is_index else EQUITIES.get(symbol)
    extra = (master or {}).get(symbol)
    source = REFERENCE_SOURCE
    if pinned is None:
        if provider != "angelone" or not extra:
            reject("UNKNOWN_INSTRUMENT", "Symbol has no trusted provider-specific mapping.")
        pinned, source = extra, "LOADED_ANGEL_MASTER"
    field = {"angelone": "angel_token", "dhan": "dhan_security_id" if is_index else "dhan_id",
             "upstox": "upstox_key"}[provider]
    expected = str(pinned.get(field) or "").strip()
    if not expected or str(meta.get(field) or "").strip() != expected:
        reject("IDENTIFIER_MISMATCH", f"{symbol} {provider} identifier disagrees with its trusted mapping.")
    references = dict(EQUITIES, **INDICES)
    for known_symbol, known in references.items():
        known_field = "dhan_security_id" if provider == "dhan" and known_symbol in INDICES else "dhan_id" if provider == "dhan" else field
        if known_symbol != symbol and str(known.get(known_field)) == expected:
            reject("AMBIGUOUS_IDENTITY", "Identifier is already assigned to another pinned instrument.")
    for key in ("trading_symbol", "tradingSymbol"):
        if key in meta and canonical_symbol(meta[key]) != symbol:
            reject("IDENTITY_MISMATCH", "Trading symbol conflicts with the canonical instrument.")
    if extra and str(extra.get("angel_token")) != str(pinned.get("angel_token")):
        reject("AMBIGUOUS_IDENTITY", "Loaded master conflicts with the pinned symbol/token mapping.")
    expected_segment = "NSE_FO_INDEX" if is_index else "NSE_EQUITY_INTRADAY"
    expected_wire = "IDX_I" if is_index else "NSE_EQ"
    expected_type = "INDEX_SPOT" if is_index else "EQ"
    for key, allowed in (("exchange", ("NSE",)), ("segment", (expected_segment,)),
                         ("exchange_segment", (expected_wire,)),
                         ("instrument_type", (expected_type,)),
                         ("instrument", ("INDEX",) if is_index else ("EQUITY", "EQ"))):
        if key in meta and str(meta[key]).strip().upper() not in allowed:
            reject("SEGMENT_MISMATCH", f"{symbol} has conflicting {key} metadata.")
    if "is_index" in meta and (not isinstance(meta["is_index"], bool) or meta["is_index"] != is_index):
        reject("IDENTITY_MISMATCH", "Index/equity classification conflicts with the trusted mapping.")
    if "multiplier" in meta and (isinstance(meta["multiplier"], bool) or meta["multiplier"] != 1):
        reject("UNSUPPORTED_MULTIPLIER", "Only unit-multiplier instruments are supported.")
    for key in ("lot_size", "lotsize"):
        if key in meta:
            lot = positive_integer(meta[key], key)
            if not is_index and lot != 1:
                reject("INVALID_CONTRACT_QUANTITY", "Cash equities require unit share quantities.")
    identity = dict(provider=provider, symbol=symbol, identifier=expected, exchange="NSE", segment=expected_segment,
                instrument_type=expected_type, is_index=is_index, source=source,
                source_revision=digest(pinned), historical_validity="NOT_ESTABLISHED")
    if source == "LOADED_ANGEL_MASTER":
        identity["master_record"] = dict(pinned)
    return identity


def check_echo(payload, identity):
    """Check all identity fields actually echoed; bare OHLCV remains request-bound."""
    if not isinstance(payload, dict):
        return False
    if identity.get("provider") in PROVIDERS:
        if (("is_simulated" in payload and payload["is_simulated"] is not False)
                or ("data_mode" in payload and payload["data_mode"] != "LIVE")):
            reject("INVALID_PROVENANCE", "Response explicitly identifies non-live or invalid data provenance.")
    # Provider metadata may be echoed on the envelope or its data object.
    seen = check_echo(payload["data"], identity) if isinstance(payload.get("data"), dict) else False
    values = {"symbol": identity["symbol"], "tradingSymbol": identity["symbol"],
              "trading_symbol": identity["symbol"], "tradingsymbol": identity["symbol"],
              "exchange": identity["exchange"], "provider": identity["provider"],
              "instrument_token": identity["identifier"], "symbol_token": identity["identifier"],
              "symbolToken": identity["identifier"],
              "symboltoken": identity["identifier"], "securityId": identity["identifier"],
              "instrument_key": identity["identifier"], "identifier": identity["identifier"]}
    for key, expected in values.items():
        if key not in payload:
            continue
        seen = True
        actual = payload[key]
        if key in ("symbol", "tradingSymbol", "trading_symbol", "tradingsymbol"):
            actual = canonical_symbol(actual)
        elif key in ("exchange",):
            actual = str(actual).strip().upper()
        else:
            actual = str(actual).strip()
        if actual != expected:
            reject("RESPONSE_IDENTITY_MISMATCH", f"Response {key} does not match the requested instrument.")
    wire = "NSE_FNO" if identity["instrument_type"] == "OPTIDX" else "IDX_I" if identity["is_index"] else "NSE_EQ"
    for key in ("exchangeSegment", "exchange_segment"):
        if key in payload and str(payload[key]).upper() != wire:
            reject("RESPONSE_IDENTITY_MISMATCH", "Response exchange segment conflicts with the request.")
    return seen


def bind_candles(candles, identity, envelope=None):
    if not isinstance(candles, list) or not all(isinstance(c, dict) for c in candles):
        reject("INVALID_RESPONSE_IDENTITY", "Candle response must contain instrument-bound candle objects.")
    candles = [dict(c) for c in candles]
    echo = check_echo(envelope, identity)
    if isinstance(envelope, dict) and isinstance(envelope.get("data"), dict):
        echo = check_echo(envelope["data"], identity) or echo
    for bar in candles:
        echo = check_echo(bar, identity) or echo
        previous = bar.get("instrument_identity")
        if previous and not isinstance(previous, dict):
            reject("INVALID_RESPONSE_IDENTITY", "Candle instrument identity must be an object.")
        if previous:
            for key in ("provider", "symbol", "identifier", "exchange", "segment", "instrument_type"):
                if previous.get(key) != identity[key]:
                    reject("RESPONSE_IDENTITY_MISMATCH", "Candle identity conflicts with the validated request.")
        binding = "ECHO_CHECKED" if echo or (previous and previous.get("response_binding") == "ECHO_CHECKED") else "REQUEST_BOUND_NO_ECHO"
        bar["instrument_identity"] = dict(identity, response_binding=binding)
    return candles


def option_contract(record, underlying, expiry, strike, side, provider, as_of):
    """Validate an explicit local master contract; never derive a missing token or lot."""
    if not isinstance(record, dict):
        reject("INCOMPLETE_CONTRACT", "Option master record must be an object.")
    try:
        expiry = date.fromisoformat(expiry).isoformat()
        date.fromisoformat(str(as_of)[:10])
    except (ValueError, TypeError):
        reject("INCOMPLETE_CONTRACT", "Option expiry and operation date must be explicit ISO dates.")
    if (side not in ("CE", "PE") or isinstance(strike, bool) or not isinstance(strike, (int, float))
            or not Decimal(str(strike)).is_finite() or strike <= 0):
        reject("CONTRACT_IDENTITY_MISMATCH", "Option side and strike are invalid.")
    expected = dict(underlying=canonical_symbol(underlying), expiry=expiry, strike=strike, option_type=side,
                    provider=provider, exchange="NFO", instrument_type="OPTIDX")
    for key, value in expected.items():
        if record.get(key) != value:
            reject("CONTRACT_IDENTITY_MISMATCH", f"Option contract {key} conflicts with the selected leg.")
    if expiry < str(as_of)[:10]:
        reject("EXPIRED_CONTRACT", "Option contract expired before the requested operation.")
    if provider != "angelone" or canonical_symbol(underlying) not in INDICES:
        reject("UNSUPPORTED_CONTRACT", "Only master-resolved Angel index options are supported for live proposals.")
    if (not isinstance(record.get("identifier"), str) or not record["identifier"].isdigit()
            or record.get("source") != "LOADED_ANGEL_MASTER" or not record.get("source_revision")):
        reject("INCOMPLETE_CONTRACT", "Option token and master provenance are required.")
    lot = positive_integer(record.get("lot_size"), "lot_size")
    if record.get("multiplier") != 1 or isinstance(record.get("multiplier"), bool):
        reject("UNSUPPORTED_MULTIPLIER", "Option contract requires an explicit supported multiplier.")
    return dict(record, lot_size=lot)


def dated_identity(archive, symbol, provider, identifier, exchange, instrument_type, first_date, last_date, lot_size=None):
    """Consistency of date-appropriate local archive evidence, not authenticity proof."""
    if not isinstance(archive, dict) or archive.get("source") != "ARCHIVED_PROVIDER_MASTER":
        reject("HISTORICAL_IDENTITY_UNVERIFIED", "Date-appropriate archived instrument-master evidence is required.")
    records = archive.get("records")
    if (not isinstance(records, list) or not all(isinstance(r, dict) for r in records)
            or not isinstance(archive.get("source_reference"), str) or not archive["source_reference"].strip()
            or archive.get("sha256") != digest(records)):
        reject("HISTORICAL_IDENTITY_UNVERIFIED", "Historical master reference/digest is missing or inconsistent.")
    matching = []
    for record in records:
        if (record.get("provider") != provider or record.get("symbol") != symbol
                or record.get("identifier") != identifier):
            continue
        try:
            start, end = date.fromisoformat(record["valid_from"]), date.fromisoformat(record["valid_to"])
        except (KeyError, ValueError, TypeError):
            reject("HISTORICAL_IDENTITY_UNVERIFIED", "Historical identity requires explicit validity dates.")
        if end < start:
            reject("HISTORICAL_IDENTITY_UNVERIFIED", "Historical validity dates are reversed.")
        if start <= date.fromisoformat(last_date) and end >= date.fromisoformat(first_date):
            matching.append(record)
    if len(matching) != 1:
        reject("HISTORICAL_IDENTITY_UNVERIFIED", "Historical identity is missing, ambiguous or outside its effective dates.")
    record = matching[0]
    if record["valid_from"] > first_date or record["valid_to"] < last_date:
        reject("HISTORICAL_IDENTITY_UNVERIFIED", "One unambiguous archived contract must cover the full dataset.")
    for key, expected in (("identifier", identifier), ("exchange", exchange), ("instrument_type", instrument_type)):
        if record.get(key) != expected:
            reject("HISTORICAL_IDENTITY_MISMATCH", f"Historical {key} conflicts with the requested dataset.")
    if record.get("multiplier") != 1 or isinstance(record.get("multiplier"), bool):
        reject("UNSUPPORTED_MULTIPLIER", "Historical contract multiplier is missing or unsupported.")
    expected_segment = "NSE_FO_INDEX" if instrument_type == "FUTIDX" else "NSE_EQUITY_INTRADAY"
    if "segment" in record and record["segment"] != expected_segment:
        reject("HISTORICAL_IDENTITY_MISMATCH", "Archived exchange segment conflicts with the contract type.")
    if instrument_type == "FUTIDX":
        try:
            date.fromisoformat(record.get("expiry"))
        except (ValueError, TypeError):
            reject("HISTORICAL_CONTRACT_MISMATCH", "Futures expiry must be an explicit ISO date.")
        if (record.get("underlying") != symbol or record.get("exchange") != "NFO"
                or not record.get("expiry") or record["expiry"] < last_date):
            reject("HISTORICAL_CONTRACT_MISMATCH", "Futures underlying, expiry and NFO identity must cover the evaluation dates.")
        if positive_integer(record.get("lot_size"), "historical lot_size") != lot_size:
            reject("HISTORICAL_CONTRACT_MISMATCH", "Historical lot size conflicts with the archived contract.")
        if identifier in {str(m.get(k)) for m in INDICES.values() for k in ("angel_token", "dhan_security_id", "upstox_key")}:
            reject("HISTORICAL_CONTRACT_MISMATCH", "An index-spot identifier cannot identify an executable future.")
    elif instrument_type != "EQ" or record.get("exchange") != "NSE" or symbol in INDICES:
        reject("UNSUPPORTED_HISTORICAL_INSTRUMENT", "Only dated NSE equities and explicit index futures are supported.")
    if instrument_type == "EQ" and "lot_size" in record and positive_integer(record["lot_size"], "lot_size") != 1:
        reject("INVALID_CONTRACT_QUANTITY", "Archived NSE equities require unit share quantities.")
    return dict(record, segment=expected_segment, source="ARCHIVED_PROVIDER_MASTER", source_reference=archive["source_reference"],
                source_revision=archive["sha256"], historical_validity="ARCHIVE_CONSISTENCY_CHECKED")


def validate_signal_identity(data):
    """Reject conflicting supplied signal identity; require it for new live scanner records."""
    data = dict(data, provider=str(data.get("provider") or "").strip().lower(),
                data_mode="SIMULATED" if data.get("is_simulated") else str(data.get("data_mode") or "").strip().upper(),
                state_context=str(data.get("state_context") or "").strip().upper())
    identity = data.get("instrument_identity") or {}
    required = data.get("data_mode") == "LIVE" and data.get("state_context") == "SCANNER"
    if required and data.get("symbol") != canonical_symbol(data.get("symbol")):
        reject("NONCANONICAL_CONFIGURATION", "Live signal symbols must be canonical before state/persistence lookup.")
    if not identity:
        if required:
            reject("MISSING_IDENTITY", "Live scanner signals require validated instrument metadata.")
        return
    if not isinstance(identity, dict):
        reject("MISSING_IDENTITY", "Signal identity must be an object.")
    if (identity.get("provider") != data.get("provider") or identity.get("segment") != data.get("segment")
            or (identity.get("underlying") or identity.get("symbol")) != data.get("symbol")):
        reject("IDENTITY_MISMATCH", "Signal scope conflicts with its instrument identity.")
    if identity.get("instrument_type") == "EQ":
        field = {"angelone": "angel_token", "dhan": "dhan_id", "upstox": "upstox_key"}.get(identity.get("provider"))
        if not field:
            reject("UNSUPPORTED_PROVIDER", "Signal provider has no supported cash mapping.")
        master = None
        if identity.get("source") == "LOADED_ANGEL_MASTER":
            record = identity.get("master_record")
            if not isinstance(record, dict) or digest(record) != identity.get("source_revision"):
                reject("AMBIGUOUS_IDENTITY", "Serialized master record disagrees with its provenance digest.")
            master = {data["symbol"]: record}
        expected = spot_identity(dict(symbol=data["symbol"], **{field: identity.get("identifier")}), identity["provider"], master)
        for key in ("exchange", "instrument_type", "source", "source_revision", "historical_validity"):
            if identity.get(key) != expected[key]:
                reject("IDENTITY_MISMATCH", "Signal identity disagrees with its mapping provenance.")
        if required and (data.get("instrument_label") != f"{data['symbol']} EQ"
                         or data.get("position_type") not in ("LONG_EQUITY_INTRADAY", "SHORT_EQUITY_INTRADAY")):
            reject("IDENTITY_MISMATCH", "Cash signal label/type conflicts with its instrument.")
    elif identity.get("instrument_type") == "OPTIDX":
        option_contract(identity, data["symbol"], identity.get("expiry"), identity.get("strike"),
                        "CE" if data.get("position_type") == "LONG_CALL_OPTION" else "PE",
                        data.get("provider"), data.get("timestamp"))
        if data.get("instrument_label") != identity.get("symbol"):
            reject("IDENTITY_MISMATCH", "Signal option label must identify its exact master contract.")
    elif required:
        reject("UNSUPPORTED_CONTRACT", "Live futures require a contract resolver and contract candles.")


def check_chain_metadata(payload, underlying, expiry, provider, identifier, strike=None, side=None):
    """Validate echoed analytical chain fields without inventing a contract master."""
    if not isinstance(payload, dict):
        return
    for key in ("underlying", "index", "underlying_symbol"):
        if key in payload and canonical_symbol(payload[key]) != underlying:
            reject("RESPONSE_IDENTITY_MISMATCH", "Option-chain underlying conflicts with the request.")
    for key, expected in (("expiry", expiry), ("expiry_date", expiry), ("provider", provider),
                          ("underlying_key", identifier), ("UnderlyingScrip", identifier),
                          ("strike", strike), ("strike_price", strike), ("option_type", side)):
        if key in payload and expected is not None and str(payload[key]) != str(expected):
            # Numeric strike echoes may be encoded with a decimal suffix.
            if key in ("strike", "strike_price"):
                try:
                    if Decimal(str(payload[key])) == Decimal(str(expected)):
                        continue
                except InvalidOperation:
                    pass
            reject("RESPONSE_IDENTITY_MISMATCH", f"Option-chain {key} conflicts with the requested contract.")


# Additive current-contract inspection boundary. Existing live identities and the
# historical archive resolver retain their own stricter, independent policies.
ContractType = Literal["EQ", "INDEX_SPOT", "FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK"]


class ContractIdentity(TypedDict, total=False):
    """The existing identity dictionary, typed for local contract declarations."""
    provider: str
    symbol: str
    identifier: str
    exchange: str
    segment: str
    instrument_type: ContractType
    is_index: bool
    underlying: str
    underlying_identifier: str
    expiry: str
    strike: float
    option_type: Literal["CE", "PE"]
    lot_size: int
    multiplier: int
    price_unit: str
    quantity_unit: str
    valid_from: str
    valid_to: str
    contract_status: str
    source: str
    source_revision: str
    source_version: str
    historical_validity: str


class ContractResolution(TypedDict):
    status: str
    reason: str
    eligible: bool
    historical_replay_allowed: bool
    identity: ContractIdentity | None
    master_id: str | None


CONTRACT_MASTER_SCHEMA = "tradepulse.contract-master.v1"
CONTRACT_MASTER_PARSER_VERSION = "local-contract-master-v1"
MAX_CONTRACT_MASTER_BYTES = 64 * 1024 * 1024
MAX_CONTRACT_MASTER_RECORDS = 100000
_CONTRACT_TYPES = ("EQ", "INDEX_SPOT", "FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK")


def _contract_text(value, field, limit=160):
    if (not isinstance(value, str) or not value or value != value.strip() or len(value) > limit
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        reject("INVALID_CONTRACT_FIELD", f"{field} requires a bounded nonempty string without control characters.")
    return value


def _contract_date(value, field):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (TypeError, ValueError):
        reject("INVALID_CONTRACT_DATE", f"{field} requires YYYY-MM-DD.")
    return value


def _contract_as_of(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            reject("INVALID_CONTRACT_DATE", "The operation datetime requires an explicit timezone.")
        # Reuse the project's exchange timezone without introducing another clock.
        from strategies import IST
        return value.astimezone(IST).date().isoformat()
    return _contract_date(value, "as_of")


def _contract_identifier(value, provider, kind):
    value = _contract_text(value, "identifier")
    if provider in ("angelone", "dhan"):
        if not value.isascii() or not value.isdigit():
            reject("INVALID_CONTRACT_IDENTIFIER", "The provider identifier requires decimal digits.")
    else:
        prefix = "NSE_INDEX" if kind == "INDEX_SPOT" else "NSE_EQ" if kind == "EQ" else "NSE_FO"
        segment, separator, token = value.partition("|")
        if (segment != prefix or not separator or not token or token != token.strip()
                or not token.isascii() or "|" in token
                or any(char in token for char in "/\\?#%")
                or (kind != "INDEX_SPOT" and any(char.isspace() for char in token))
                or (kind not in ("EQ", "INDEX_SPOT") and not token.isdigit())):
            reject("INVALID_CONTRACT_IDENTIFIER", "The provider key conflicts with the declared instrument type.")
    return value


def validate_contract_identity(record, *, provider, as_of=None) -> ContractIdentity:
    """Validate declared facts only; never activate a contract or establish trust.

    This normalized input boundary is not a provider-native master parser. A
    derivative's symbol is its explicit contract label, not its underlying name.
    """
    if provider not in PROVIDERS:
        reject("UNSUPPORTED_PROVIDER", "The contract provider is unsupported.")
    if not isinstance(record, dict):
        reject("INVALID_CONTRACT_RECORD", "A normalized contract record must be an object.")
    if record.get("provider", provider) != provider:
        reject("CONTRACT_PROVIDER_MISMATCH", "The record provider differs from its master.")
    if (record.get("data_mode", "LIVE") != "LIVE"
            or ("is_simulated" in record and record["is_simulated"] is not False)):
        reject("INVALID_PROVENANCE", "Explicit non-live declarations cannot identify accepted live contracts.")
    kind = record.get("instrument_type")
    if kind not in _CONTRACT_TYPES:
        reject("UNSUPPORTED_CONTRACT_TYPE", "The declared instrument type is unsupported.")
    derivative = kind not in ("EQ", "INDEX_SPOT")
    index = kind in ("INDEX_SPOT", "FUTIDX", "OPTIDX")
    exchange = "NFO" if derivative else "NSE"
    segment = "NSE_FO_INDEX" if index else "NSE_FO_STOCK" if derivative else "NSE_EQUITY_INTRADAY"
    if record.get("exchange") != exchange or record.get("segment") != segment:
        reject("CONTRACT_SEGMENT_MISMATCH", "Exchange, segment and instrument type disagree.")
    symbol = _contract_text(record.get("symbol"), "symbol")
    if derivative:
        if symbol != symbol.upper() or not re.fullmatch(r"[A-Z0-9&._-]+", symbol):
            reject("INVALID_CONTRACT_SYMBOL", "An explicit canonical contract label is required.")
    else:
        symbol = canonical_symbol(symbol)
        if (kind == "INDEX_SPOT") != (symbol in INDICES):
            reject("CONTRACT_TYPE_MISMATCH", "Cash and supported index-spot classifications disagree.")
    if "trading_symbol" in record and record["trading_symbol"] != symbol:
        reject("CONTRACT_TYPE_MISMATCH", "The trading label conflicts with the declared contract symbol.")
    if "is_index" in record and (not isinstance(record["is_index"], bool)
                                  or record["is_index"] != (kind == "INDEX_SPOT")):
        reject("CONTRACT_TYPE_MISMATCH", "The index-spot flag conflicts with the instrument type.")
    valid_from = _contract_date(record.get("valid_from"), "valid_from")
    valid_to = _contract_date(record.get("valid_to"), "valid_to")
    if valid_from > valid_to:
        reject("INVALID_CONTRACT_DATE", "Declared validity dates are reversed.")
    price_unit = "INDEX_POINTS" if kind == "INDEX_SPOT" else "INR"
    quantity_unit = "NOT_EXECUTABLE" if kind == "INDEX_SPOT" else "UNDERLYING_UNITS" if derivative else "SHARES"
    if record.get("price_unit") != price_unit or record.get("quantity_unit") != quantity_unit:
        reject("UNSUPPORTED_CONTRACT_UNITS", "Price and quantity units must match the declared instrument type.")
    status = record.get("contract_status", "UNKNOWN")
    if status not in ("ACTIVE", "INACTIVE", "SUSPENDED", "EXPIRED", "UNKNOWN"):
        reject("INVALID_CONTRACT_STATUS", "The declared contract status is unsupported.")
    result: ContractIdentity = dict(provider=provider, symbol=symbol,
        identifier=_contract_identifier(record.get("identifier"), provider, kind),
        exchange=exchange, segment=segment, instrument_type=kind, is_index=kind == "INDEX_SPOT",
        price_unit=price_unit, quantity_unit=quantity_unit, valid_from=valid_from, valid_to=valid_to,
        contract_status=status, source="LOCAL_NORMALIZED_MASTER_DECLARATION", historical_validity="NOT_ESTABLISHED")
    if kind == "INDEX_SPOT":
        if record.get("lot_size") is not None or record.get("multiplier") is not None:
            reject("SPOT_QUANTITY_NOT_APPLICABLE", "Index spot has no executable lot size or quantity multiplier.")
    else:
        lot = positive_integer(record.get("lot_size"), "lot_size")
        if kind == "EQ" and lot != 1:
            reject("INVALID_CONTRACT_QUANTITY", "Cash equities require unit shares.")
        if isinstance(record.get("multiplier"), bool) or record.get("multiplier") != 1:
            reject("UNSUPPORTED_MULTIPLIER", "Only an explicit unit quantity multiplier is supported.")
        result.update(lot_size=lot, multiplier=1)
    if derivative:
        underlying = canonical_symbol(record.get("underlying"))
        if (underlying in INDICES) != index or underlying == symbol:
            reject("CONTRACT_TYPE_MISMATCH", "The derivative label and index/stock underlying disagree.")
        underlying_kind = "INDEX_SPOT" if index else "EQ"
        underlying_identifier = _contract_identifier(record.get("underlying_identifier"), provider, underlying_kind)
        if underlying_identifier == result["identifier"]:
            reject("SPOT_CONTRACT_SUBSTITUTION", "A spot identifier cannot be reused as its derivative contract.")
        if index:
            field = {"angelone": "angel_token", "dhan": "dhan_security_id", "upstox": "upstox_key"}[provider]
            if result["identifier"] in {str(meta[field]) for meta in INDICES.values()}:
                reject("SPOT_CONTRACT_SUBSTITUTION", "A pinned index-spot identifier cannot identify a derivative.")
        expiry = _contract_date(record.get("expiry"), "expiry")
        if expiry < valid_to:
            reject("INVALID_CONTRACT_DATE", "Declared validity cannot extend beyond contract expiry.")
        result.update(underlying=underlying, underlying_identifier=underlying_identifier, expiry=expiry)
        if kind.startswith("OPT"):
            strike = record.get("strike")
            if (isinstance(strike, bool) or not isinstance(strike, (int, float))
                    or not Decimal(str(strike)).is_finite() or strike <= 0
                    or record.get("option_type") not in ("CE", "PE")):
                reject("INVALID_OPTION_CONTRACT", "Options require a finite positive strike and an explicit CE/PE side.")
            result.update(strike=strike, option_type=record["option_type"])
        elif record.get("strike") is not None or record.get("option_type") is not None:
            reject("CONTRACT_TYPE_MISMATCH", "A futures contract cannot carry option strike or side metadata.")
    elif any(record.get(key) is not None for key in ("underlying", "underlying_identifier", "expiry", "strike", "option_type")):
        reject("CONTRACT_TYPE_MISMATCH", "Cash/index spot cannot carry derivative contract terms.")
    if as_of is not None:
        _contract_as_of(as_of)  # Validate the operation date; eligibility remains a resolver decision.
    return result


def prepare_contract_master(raw_bytes, *, provider, source_reference, source_version, captured_at=None):
    """Retain a bounded local normalized declaration; never activate a universe.

    Publisher, version, capture time and effective dates remain supplied claims.
    Malformed bodies are retained as REJECTED candidates, as in archive ingestion.
    """
    if provider not in PROVIDERS:
        reject("UNSUPPORTED_PROVIDER", "The contract-master provider is unsupported.")
    if not isinstance(raw_bytes, bytes) or not raw_bytes or len(raw_bytes) > MAX_CONTRACT_MASTER_BYTES:
        reject("INVALID_CONTRACT_MASTER_SIZE", "A bounded nonempty original byte artifact is required.")
    source_reference = _contract_text(source_reference, "source_reference", 512)
    source_version = _contract_text(source_version, "source_version", 128)
    if captured_at is not None:
        try:
            parsed = datetime.fromisoformat(_contract_text(captured_at, "captured_at", 64))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError()
            captured_at = parsed.isoformat()
        except (TypeError, ValueError):
            reject("INVALID_MASTER_CAPTURE_TIME", "A supplied capture time requires an explicit timezone.")
    metadata = dict(provider=provider, source_reference=source_reference, source_version=source_version,
        captured_at=captured_at, parser_version=CONTRACT_MASTER_PARSER_VERSION,
        original_sha256=hashlib.sha256(raw_bytes).hexdigest(), source_kind="LOCAL_NORMALIZED_DECLARATION",
        publisher_authenticity="NOT_ESTABLISHED", effective_date_evidence="DECLARED_ONLY")
    candidate = dict(schema_version=CONTRACT_MASTER_SCHEMA, metadata=metadata, original_bytes=raw_bytes,
        records=[], normalized_sha256=digest([]), record_count=0, status="REJECTED", validation=None,
        eligible=False, historical_replay_allowed=False)
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                reject("INVALID_CONTRACT_MASTER_SCHEMA", "Duplicate JSON fields are ambiguous.")
            result[key] = value
        return result
    try:
        try:
            payload = json.loads(raw_bytes.decode("utf-8-sig"), object_pairs_hook=unique_fields,
                parse_constant=lambda _: reject("INVALID_CONTRACT_MASTER_SCHEMA", "Nonfinite JSON values are unsupported."))
        except (ValueError, UnicodeError, RecursionError) as exc:
            if isinstance(exc, IdentityValidationError):
                raise
            reject("INVALID_CONTRACT_MASTER_SCHEMA", "A complete normalized UTF-8 JSON artifact is required.")
        if (not isinstance(payload, dict) or payload.get("schema_version") != CONTRACT_MASTER_SCHEMA
                or payload.get("provider") != provider):
            reject("INVALID_CONTRACT_MASTER_SCHEMA", "Schema and provider must match the declared local normalized format.")
        if (payload.get("data_mode", "LIVE") != "LIVE"
                or ("is_simulated" in payload and payload["is_simulated"] is not False)):
            reject("INVALID_PROVENANCE", "A declared synthetic master cannot identify accepted live contracts.")
        rows = payload.get("records")
        if not isinstance(rows, list) or not rows or len(rows) > MAX_CONTRACT_MASTER_RECORDS:
            reject("INVALID_CONTRACT_MASTER_RECORDS", "A bounded nonempty list of normalized records is required.")
        records = [validate_contract_identity(row, provider=provider) for row in rows]
        identifiers, terms = set(), set()
        option_pairs = {}
        for record in records:
            identifier_key = (record["exchange"], record["identifier"])
            if identifier_key in identifiers:
                reject("CONFLICTING_IDENTIFIER", "The artifact repeats or conflicts on a provider/exchange identifier.")
            identifiers.add(identifier_key)
            term_key = (record["instrument_type"], record.get("underlying", record["symbol"]),
                        record.get("expiry"), record.get("strike"), record.get("option_type"))
            if term_key in terms:
                reject("AMBIGUOUS_CONTRACT", "Multiple identifiers or labels claim the same contract terms.")
            terms.add(term_key)
            if record["instrument_type"] in ("OPTIDX", "OPTSTK"):
                pair_key = (record["instrument_type"], record["underlying"], record["expiry"], record["strike"])
                quantity_scope = tuple(record[key] for key in ("underlying_identifier", "lot_size", "multiplier",
                    "price_unit", "quantity_unit", "valid_from", "valid_to"))
                if pair_key in option_pairs and option_pairs[pair_key] != quantity_scope:
                    reject("CONFLICTING_OPTION_PAIR", "Declared call/put pairs require matching quantity and effective-date terms.")
                option_pairs[pair_key] = quantity_scope
        spots = {(record["instrument_type"], record["symbol"], record["identifier"]): record
                 for record in records if record["instrument_type"] in ("EQ", "INDEX_SPOT")}
        for record in records:
            if "underlying" not in record:
                continue
            expected_type = "INDEX_SPOT" if record["instrument_type"].endswith("IDX") else "EQ"
            spot = spots.get((expected_type, record["underlying"], record["underlying_identifier"]))
            if spot is None:
                reject("MISSING_UNDERLYING_IDENTITY", "A derivative requires one matching underlying spot record in the same declaration.")
            if spot["valid_from"] > record["valid_from"] or spot["valid_to"] < record["valid_to"]:
                reject("UNDERLYING_DATE_MISMATCH", "The underlying declaration must cover its derivative validity interval.")
        records.sort(key=lambda record: (record["exchange"], record["identifier"], record["symbol"]))
        for record in records:
            record.update(source_revision=metadata["original_sha256"], source_version=source_version)
        candidate.update(records=records, normalized_sha256=digest(records), record_count=len(records),
                         status="BLOCKED_UNQUALIFIED_MASTER")
    except IdentityValidationError as exc:
        candidate["validation"] = dict(exc.rejection)
    candidate["master_id"] = digest({key: value for key, value in candidate.items() if key != "original_bytes"})
    return candidate


def resolve_contract_identity(master, *, provider, instrument_type, as_of, identifier=None,
                              underlying=None, expiry=None, strike=None, option_type=None,
                              symbol=None) -> ContractResolution:
    """Inspect a unique declared contract, always blocked until an independent verifier exists."""
    def result(status, reason, identity=None):
        master_id = master.get("master_id") if isinstance(master, dict) else None
        return dict(status=status, reason=reason, eligible=False, historical_replay_allowed=False,
                    identity=identity, master_id=master_id if isinstance(master_id, str) and re.fullmatch(r"[a-f0-9]{64}", master_id) else None)
    if provider not in PROVIDERS:
        return result("UNSUPPORTED_PROVIDER", "The requested contract provider is unsupported.")
    if instrument_type not in _CONTRACT_TYPES:
        return result("UNSUPPORTED_CONTRACT_TYPE", "The requested contract type is unsupported.")
    if not isinstance(master, dict):
        return result("MASTER_NOT_AVAILABLE", "No retained local contract-master declaration is available.")
    try:
        metadata = master["metadata"]
        rebuilt = prepare_contract_master(master["original_bytes"], provider=metadata["provider"],
            source_reference=metadata["source_reference"], source_version=metadata["source_version"],
            captured_at=metadata["captured_at"])
        if rebuilt != master:
            return result("INVALID_MASTER_INTEGRITY", "Retained bytes, normalized facts and declaration metadata disagree.")
    except (IdentityValidationError, TypeError, KeyError, RecursionError):
        return result("INVALID_MASTER_INTEGRITY", "Retained bytes or bound declaration metadata could not be revalidated.")
    if metadata["provider"] != provider:
        return result("CONTRACT_PROVIDER_MISMATCH", "The retained declaration belongs to a different provider.")
    if rebuilt["status"] == "REJECTED":
        return result(rebuilt["validation"]["reason_code"], "The retained local declaration failed structural validation.")
    try:
        day = _contract_as_of(as_of)
        if identifier is not None:
            identifier = _contract_identifier(identifier, provider, instrument_type)
        if underlying is not None:
            underlying = canonical_symbol(underlying)
        if symbol is not None:
            symbol = _contract_text(symbol, "symbol")
        if expiry is not None:
            expiry = _contract_date(expiry, "expiry")
        if strike is not None and (isinstance(strike, bool) or not isinstance(strike, (int, float))
                                   or not Decimal(str(strike)).is_finite() or strike <= 0):
            reject("INVALID_OPTION_CONTRACT", "The requested strike must be finite and positive.")
        if option_type is not None and option_type not in ("CE", "PE"):
            reject("INVALID_OPTION_CONTRACT", "The requested option side must be CE or PE.")
        if instrument_type not in ("OPTIDX", "OPTSTK") and (strike is not None or option_type is not None):
            reject("CONTRACT_TYPE_MISMATCH", "A non-option request cannot supply option terms.")
    except IdentityValidationError as exc:
        return result(exc.rejection["reason_code"], exc.rejection["reason"])
    records = [record for record in rebuilt["records"] if record["instrument_type"] == instrument_type
               and all(value is None or record.get(key) == value for key, value in (
                   ("identifier", identifier), ("underlying", underlying), ("expiry", expiry),
                   ("strike", strike), ("option_type", option_type), ("symbol", symbol)))]
    if not records:
        return result("MISSING_CONTRACT", "No declared contract matches all requested identity fields.")
    if len(records) != 1:
        return result("AMBIGUOUS_CONTRACT", "The request must identify one exact declared contract.")
    identity = dict(records[0])
    if identity.get("expiry", day) < day or identity["contract_status"] == "EXPIRED":
        return result("EXPIRED_CONTRACT", "The declared contract has expired for the operation date.", identity)
    if identity["valid_to"] < day:
        return result("STALE_MASTER", "The declaration no longer covers the operation date.", identity)
    if identity["valid_from"] > day:
        return result("CONTRACT_NOT_YET_EFFECTIVE", "The declaration does not yet cover the operation date.", identity)
    if identity["contract_status"] in ("INACTIVE", "SUSPENDED"):
        return result("INACTIVE_CONTRACT", "The supplied declaration does not mark this contract active.", identity)
    return result("BLOCKED_UNQUALIFIED_MASTER",
        "Structural consistency and supplied dates do not establish publisher authenticity or current-contract eligibility.", identity)

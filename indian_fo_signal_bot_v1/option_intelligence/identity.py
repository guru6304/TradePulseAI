"""Exact, declared option identities for isolated offline research.

VERIFIED below means only validation of supplied structure, units and event time.
A caller's ACTIVE label and a master digest do not establish actual listing,
publisher authenticity, data rights or permission to execute a paper entry.
"""
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

from .evidence import CheckError, Evidence, day, digest, number, require, timestamp


IST = ZoneInfo("Asia/Kolkata")
PROVIDERS = ("angelone", "dhan", "upstox")
INDEX_UNDERLYINGS = ("NIFTY", "BANKNIFTY")
STRUCTURAL_REASONS = (
    "SUPPLIED_CONTRACT_FACTS_VALIDATED",
    "SOURCE_AUTHENTICITY_NOT_ESTABLISHED",
    "LISTING_AUTHORITY_NOT_ESTABLISHED",
)


@dataclass(frozen=True)
class ExactOptionContract:
    provider: str
    identifier: str
    symbol: str
    underlying: str
    underlying_identifier: str
    exchange: str
    segment: str
    instrument_type: str
    option_type: str
    expiry: date
    strike: Decimal
    lot_size: int
    tick_size: Decimal
    multiplier: int
    price_unit: str
    quantity_unit: str
    valid_from: date
    valid_to: date
    contract_status: str
    source: str
    source_revision: str
    master_id: str
    master_sha256: str
    source_observed_at: datetime
    received_at: datetime
    available_at: datetime
    source_authenticity: str = "NOT_ESTABLISHED"
    listing_authority: str = "NOT_ESTABLISHED"

    @property
    def contract_id(self):
        # Re-observation clocks do not redefine the same dated contract terms.
        content = {field.name: getattr(self, field.name) for field in fields(self)
                   if field.name not in ("source_observed_at", "received_at", "available_at")}
        for name in ("strike", "tick_size"):
            encoded = format(content[name], "f")
            content[name] = encoded.rstrip("0").rstrip(".") if "." in encoded else encoded
        return "tp-option-contract-v1:" + digest(content)


@dataclass(frozen=True)
class ContractResult:
    contract: ExactOptionContract | None
    evidence: Evidence


@dataclass(frozen=True)
class ExpirySelection:
    expiries: tuple[date, ...]
    evidence: Evidence
    scope: str = "SUPPLIED_CONTRACT_RECORDS_ONLY"
    complete_universe_established: bool = False


REQUIRED_FIELDS = tuple(field.name for field in fields(ExactOptionContract)
                        if field.name not in ("source_authenticity", "listing_authority"))


def _present(raw, name):
    require(name in raw and raw[name] is not None, "UNAVAILABLE", "MISSING_" + name.upper())
    return raw[name]


def _text(raw, name, limit=160):
    value = _present(raw, name)
    require(isinstance(value, str) and bool(value) and value == value.strip()
            and len(value) <= limit and all(32 <= ord(char) != 127 for char in value),
            "INVALID", "INVALID_" + name.upper())
    return value


def _exact_integer(raw, name):
    value = _present(raw, name)
    require(type(value) is int and 0 < value <= 2**53 - 1, "INVALID", "INVALID_" + name.upper())
    return value


def _identifier(value, provider, instrument_type):
    if provider in ("angelone", "dhan"):
        require(value.isascii() and value.isdigit(), "INVALID", "INVALID_PROVIDER_IDENTIFIER")
        return value
    prefix = "NSE_FO" if instrument_type in ("OPTIDX", "OPTSTK") else (
        "NSE_INDEX" if instrument_type == "INDEX_SPOT" else "NSE_EQ")
    scope, separator, token = value.partition("|")
    require(scope == prefix and separator == "|" and bool(token) and token == token.strip()
            and token.isascii() and "|" not in token
            and not any(char in token for char in "/\\?#%"),
            "INVALID", "INVALID_PROVIDER_IDENTIFIER")
    if prefix == "NSE_FO":
        require(token.isdigit(), "INVALID", "INVALID_PROVIDER_IDENTIFIER")
    elif prefix == "NSE_EQ":
        require(bool(re.fullmatch(r"[A-Z0-9]+", token)), "INVALID", "INVALID_PROVIDER_IDENTIFIER")
    return value


def _stock_membership(raw, contract, decision):
    require(raw is not None, "UNAVAILABLE", "POINT_IN_TIME_NIFTY200_MEMBERSHIP_UNAVAILABLE")
    require(isinstance(raw, Mapping), "INVALID", "INVALID_MEMBERSHIP_RECORD")
    for name in ("provider", "underlying", "underlying_identifier", "universe", "source", "source_revision"):
        _text(raw, name)
    for name in ("provider", "underlying", "underlying_identifier"):
        require(raw[name] == getattr(contract, name), "INVALID", "MEMBERSHIP_IDENTITY_MISMATCH")
    require(raw["universe"] == "NIFTY200", "INVALID", "UNSUPPORTED_MEMBERSHIP_UNIVERSE")
    require(_present(raw, "ordinary_equity") is True, "INVALID", "ORDINARY_EQUITY_REQUIRED")
    valid_from, valid_to = day(_present(raw, "valid_from")), day(_present(raw, "valid_to"))
    require(valid_from <= valid_to, "INVALID", "INVALID_MEMBERSHIP_VALIDITY")
    require(valid_from <= decision.astimezone(IST).date() <= valid_to,
            "UNAVAILABLE", "DATED_NIFTY200_MEMBERSHIP_UNAVAILABLE")
    available_at = timestamp(_present(raw, "available_at"))
    require(available_at <= decision, "UNAVAILABLE", "MEMBERSHIP_NOT_YET_AVAILABLE")


def validate_contract(raw, *, decision_at, membership=None):
    """Normalize an explicit declaration; never infer a token/expiry/lot/tick.

    Stock membership is a separately supplied dated mapping, also unverified as
    to publisher authenticity. Unknown trading status is NOT_ESTABLISHED.
    """
    try:
        decision = timestamp(decision_at)
        require(isinstance(raw, Mapping), "INVALID", "INVALID_CONTRACT_RECORD")
        for name in REQUIRED_FIELDS:
            _present(raw, name)
        values = {}
        date_fields = ("expiry", "valid_from", "valid_to")
        clock_fields = ("source_observed_at", "received_at", "available_at")
        numeric_fields = ("strike", "tick_size")
        integer_fields = ("lot_size", "multiplier")
        for name in REQUIRED_FIELDS:
            if name in date_fields:
                values[name] = day(raw[name])
            elif name in clock_fields:
                values[name] = timestamp(raw[name])
            elif name in numeric_fields:
                values[name] = number(raw[name])
                require(values[name] > 0, "INVALID", "INVALID_" + name.upper())
            elif name in integer_fields:
                values[name] = _exact_integer(raw, name)
            else:
                values[name] = _text(raw, name)
        contract = ExactOptionContract(**values)
        require(contract.provider in PROVIDERS, "INVALID", "UNSUPPORTED_PROVIDER")
        require(contract.exchange == "NFO", "INVALID", "OPTION_EXCHANGE_MISMATCH")
        require(contract.instrument_type in ("OPTIDX", "OPTSTK"), "INVALID", "UNSUPPORTED_OPTION_TYPE")
        expected_segment = "NSE_FO_INDEX" if contract.instrument_type == "OPTIDX" else "NSE_FO_STOCK"
        require(contract.segment == expected_segment, "INVALID", "OPTION_SEGMENT_MISMATCH")
        require(contract.option_type in ("CE", "PE"), "INVALID", "INVALID_OPTION_SIDE")
        require(contract.symbol != contract.underlying
                and bool(re.fullmatch(r"[A-Z0-9&._-]+", contract.symbol))
                and bool(re.fullmatch(r"[A-Z0-9&._-]+", contract.underlying)),
                "INVALID", "EXACT_CONTRACT_LABEL_REQUIRED")
        index = contract.instrument_type == "OPTIDX"
        require((contract.underlying in INDEX_UNDERLYINGS) == index,
                "INVALID", "UNDERLYING_TYPE_MISMATCH")
        _identifier(contract.identifier, contract.provider, contract.instrument_type)
        _identifier(contract.underlying_identifier, contract.provider, "INDEX_SPOT" if index else "EQ")
        require(contract.identifier != contract.underlying_identifier,
                "INVALID", "SPOT_CONTRACT_SUBSTITUTION")
        require(contract.price_unit == "INR" and contract.quantity_unit == "UNDERLYING_UNITS"
                and contract.multiplier == 1, "INVALID", "UNSUPPORTED_CONTRACT_UNITS")
        require(contract.valid_from <= contract.valid_to <= contract.expiry,
                "INVALID", "INVALID_CONTRACT_VALIDITY")
        today = decision.astimezone(IST).date()
        require(contract.expiry > today, "INVALID",
                "EXPIRY_DAY_INELIGIBLE" if contract.expiry == today else "EXPIRED_CONTRACT")
        require(contract.valid_from <= today <= contract.valid_to,
                "UNAVAILABLE", "DATED_CONTRACT_UNAVAILABLE")
        require(contract.source_observed_at <= contract.received_at <= contract.available_at,
                "INVALID", "INVALID_CONTRACT_CLOCK_ORDER")
        require(contract.available_at <= decision, "UNAVAILABLE", "CONTRACT_NOT_YET_AVAILABLE")
        require(bool(re.fullmatch(r"[0-9a-f]{64}", contract.master_sha256)),
                "INVALID", "INVALID_MASTER_SHA256")
        require(contract.contract_status in ("ACTIVE", "INACTIVE", "SUSPENDED", "EXPIRED", "UNKNOWN"),
                "INVALID", "INVALID_TRADING_STATUS")
        if not index:
            _stock_membership(membership, contract, decision)
        if contract.contract_status == "UNKNOWN":
            return ContractResult(contract, Evidence("NOT_ESTABLISHED", (
                "TRADING_STATUS_NOT_ESTABLISHED", "SOURCE_AUTHENTICITY_NOT_ESTABLISHED",
                "LISTING_AUTHORITY_NOT_ESTABLISHED")))
        require(contract.contract_status == "ACTIVE", "INVALID", "CONTRACT_NOT_ACTIVE")
        return ContractResult(contract, Evidence("VERIFIED", STRUCTURAL_REASONS))
    except CheckError as error:
        return ContractResult(None, Evidence(error.state, (error.code,)))


def nearest_two_expiries(results, *, decision_at):
    """Select within supplied validated records, never claim a complete master.

    A single provider/underlying/type scope is required. Invalid/unavailable rows
    are counted in evidence rather than converted to fictitious listed records.
    """
    try:
        decision = timestamp(decision_at)
        require(isinstance(results, (tuple, list)), "INVALID", "INVALID_CONTRACT_RESULTS")
        results = tuple(results)
        require(all(isinstance(item, ContractResult) for item in results),
                "INVALID", "INVALID_CONTRACT_RESULTS")
        usable = tuple(item.contract for item in results
                       if item.evidence.state == "VERIFIED" and item.contract is not None
                       and item.contract.contract_status == "ACTIVE"
                       and item.contract.available_at <= decision
                       and item.contract.valid_from <= decision.astimezone(IST).date() <= item.contract.valid_to
                       and item.contract.expiry > decision.astimezone(IST).date())
        require(bool(usable), "UNAVAILABLE", "NO_VALID_SUPPLIED_OPTION_CONTRACTS")
        scope = {(item.provider, item.underlying, item.underlying_identifier, item.instrument_type)
                 for item in usable}
        require(len(scope) == 1, "INVALID", "MIXED_CONTRACT_SELECTION_SCOPE")
        expiries = tuple(sorted({item.expiry for item in usable})[:2])
        reasons = ["NEAREST_WITHIN_SUPPLIED_RECORDS_ONLY", "COMPLETE_LISTING_UNIVERSE_NOT_ESTABLISHED"]
        if len(expiries) < 2:
            reasons.append("FEWER_THAN_TWO_ELIGIBLE_SUPPLIED_EXPIRIES")
        if len(usable) < len(results):
            reasons.append("UNUSABLE_SUPPLIED_RECORDS_EXCLUDED")
        return ExpirySelection(expiries, Evidence("NOT_ESTABLISHED", tuple(reasons), expiries))
    except CheckError as error:
        return ExpirySelection((), Evidence(error.state, (error.code,)))

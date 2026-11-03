"""Prospective Option Apex declaration checks, without trust or entry activation.

No capture/replay adapter is accepted implicitly. A valid declaration is only
mechanical evidence: independent source qualification and the future premium
lifecycle are still unavailable. This module performs no I/O.
"""
from decimal import Decimal

from instrument_identity import resolve_contract_identity, digest
from option_observations import _time, _number, _json_shape, ObservationError, IST

VERSION = "tradepulse.option-prospective-preflight.v1"
IDENTITY_FIELDS = ("provider", "identifier", "symbol", "exchange", "segment",
    "instrument_type", "underlying", "underlying_identifier", "expiry", "strike",
    "option_type", "lot_size", "multiplier", "price_unit", "quantity_unit",
    "valid_from", "valid_to", "contract_status", "source_revision")


def prospective_preflight(declaration=None, *, master=None, decision_at):
    """Validate explicit source-bound declarations; never authorize paper entry.

    Fixed v1 mechanics: <=5s quote age, <=1s bid/ask/depth skew,
    <=2% spread/mid, both displayed sizes >= requested underlying units.
    These conservative limits are safety checks, not contract-fitness scoring.
    """
    def result(status, reason, valid=False):
        return dict(schema_version=VERSION, status=status, reason_code=reason,
            declaration_valid=valid, source_qualified=False,
            prospective_ready=False, forward_entry_allowed=False,
            blockers=[reason, "OPTION_APEX_FORWARD_LIFECYCLE_DISABLED"])

    try:
        decision = _time(decision_at).astimezone(IST)
        if declaration is None:
            return result("UNAVAILABLE", "QUALIFIED_PROSPECTIVE_PREMIUM_REQUIRED")
        if not isinstance(declaration, dict):
            return result("REJECTED", "INVALID_PREFLIGHT_DECLARATION")
        d = declaration
        _json_shape(d)
        required = ("scope", "data_mode", "is_simulated", "identity", "quantity_units",
            "tick_size", "quote_identity_digest", "source_revision", "bid", "ask",
            "bid_size_units", "ask_size_units", "quote_at", "bid_at", "ask_at",
            "liquidity_at", "received_at", "available_at", "quantity_unit", "price_unit")
        for field in required:
            if field not in d or d[field] is None:
                return result("UNAVAILABLE", "MISSING_" + field.upper())
        if d["scope"] != "PROSPECTIVE_PREMIUM" or d["data_mode"] != "LIVE" or d["is_simulated"] is not False:
            return result("REJECTED", "NON_PROSPECTIVE_PREMIUM_EVIDENCE")
        identity = d["identity"]
        if not isinstance(identity, dict):
            return result("REJECTED", "INVALID_OPTION_IDENTITY")
        for field in IDENTITY_FIELDS:
            if field not in identity or identity[field] is None:
                return result("UNAVAILABLE", "MISSING_IDENTITY_" + field.upper())
        if identity["instrument_type"] != "OPTIDX" or identity["underlying"] not in ("NIFTY", "BANKNIFTY"):
            return result("REJECTED", "OPTION_APEX_INDEX_CONTRACT_REQUIRED")
        resolved = resolve_contract_identity(master, provider=identity["provider"], instrument_type="OPTIDX",
            as_of=decision, identifier=identity["identifier"], underlying=identity["underlying"],
            expiry=identity["expiry"], strike=identity["strike"], option_type=identity["option_type"])
        if resolved["status"] != "BLOCKED_UNQUALIFIED_MASTER" or not resolved.get("identity"):
            return result("REJECTED", resolved["status"])
        exact = resolved["identity"]
        if any(type(identity[k]) is not type(exact[k]) or identity[k] != exact[k] for k in IDENTITY_FIELDS):
            return result("REJECTED", "OPTION_IDENTITY_MISMATCH")
        if exact["contract_status"] != "ACTIVE":
            return result("REJECTED", "OPTION_NOT_ACTIVE")
        capture = _time(master["metadata"]["captured_at"])
        if capture > decision or capture.astimezone(IST).date() != decision.date():
            return result("REJECTED", "STALE_OR_FUTURE_MASTER_CAPTURE")
        if d["quote_identity_digest"] != digest(identity) or d["source_revision"] != identity["source_revision"]:
            return result("REJECTED", "QUOTE_IDENTITY_OR_REVISION_MISMATCH")
        if d["quantity_unit"] != "UNDERLYING_UNITS" or d["price_unit"] != "INR":
            return result("REJECTED", "PREMIUM_UNITS_MISMATCH")
        qty = d["quantity_units"]
        if type(qty) is not int or qty <= 0 or qty % identity["lot_size"]:
            return result("REJECTED", "INVALID_OPTION_QUANTITY_UNITS")
        tick, bid, ask = [Decimal(str(_number(d[k], positive=True))) for k in ("tick_size", "bid", "ask")]
        # Tick must be retained in the same master revision, never inferred.
        if exact.get("tick_size") is None:
            return result("UNAVAILABLE", "MASTER_TICK_SIZE_UNAVAILABLE")
        if tick != Decimal(str(exact["tick_size"])) or bid % tick or ask % tick:
            return result("REJECTED", "OPTION_TICK_MISMATCH")
        if ask < bid or (ask-bid)/((ask+bid)/2) > Decimal("0.02"):
            return result("REJECTED", "INVALID_OR_WIDE_PREMIUM_SPREAD")
        for key in ("bid_size_units", "ask_size_units"):
            if type(d[key]) is not int or d[key] < qty:
                return result("REJECTED", "INSUFFICIENT_QUALIFIED_LIQUIDITY")
        quote, bid_at, ask_at, depth, received, available = [_time(d[k]) for k in
            ("quote_at", "bid_at", "ask_at", "liquidity_at", "received_at", "available_at")]
        if not max(quote, bid_at, ask_at, depth) <= received <= available <= decision:
            return result("REJECTED", "PREMIUM_CLOCK_ORDER_INVALID")
        if any(t.astimezone(IST).date() != decision.date() or not 0 <= (decision-t).total_seconds() <= 5
               for t in (quote, bid_at, ask_at, depth)):
            return result("REJECTED", "STALE_PREMIUM_CLOCK")
        if (max(quote, bid_at, ask_at, depth)-min(quote, bid_at, ask_at, depth)).total_seconds() > 1:
            return result("REJECTED", "UNSYNCHRONIZED_PREMIUM_EVIDENCE")
        return result("UNAVAILABLE", "INDEPENDENT_SOURCE_QUALIFICATION_UNAVAILABLE", True)
    except (ObservationError, ValueError, TypeError, KeyError, ArithmeticError, OverflowError, RecursionError):
        return result("REJECTED", "INVALID_PREFLIGHT_EVIDENCE")

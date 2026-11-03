"""Declared-unit, exact-contract optional context; never execution admission.

VERIFIED denotes only checks against supplied inputs. No authenticated source,
listing authority, direction, fill price, implied probability or percentile is
established by these functions. Missing fields remain missing.
"""
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
import math

from .evidence import (CheckError, Evidence, IST, day, digest, json_value, number,
                       require, text, timestamp)
from .identity import ExactOptionContract


FIELDS = ("iv", "delta", "gamma", "vega", "theta", "oi", "oi_change", "volume")
DELTA_UNIT = "PREMIUM_INR_PER_UNDERLYING_INR"
GAMMA_UNIT = "PREMIUM_INR_PER_UNDERLYING_INR_SQUARED"
VEGA_FRACTION_UNIT = "INR_PER_IV_FRACTION"
VEGA_POINT_UNIT = "INR_PER_IV_PERCENTAGE_POINT"
THETA_DAY_UNIT = "INR_PER_CALENDAR_DAY"
THETA_YEAR_UNIT = "INR_PER_YEAR"


def _safe_raw(raw):
    """Retain bounded immutable scalars, explicitly flag unsupported raw data."""
    if raw is None or type(raw) is bool:
        return raw, type(raw).__name__, "RETAINED"
    if type(raw) is str:
        return ((raw, "str", "RETAINED") if len(raw) <= 128
                else (None, "str", "OVERSIZE_NOT_RETAINED"))
    if type(raw) is int:
        return ((raw, "int", "RETAINED") if abs(raw) <= 2**53-1
                else (None, "int", "OUT_OF_BOUNDS_NOT_RETAINED"))
    if type(raw) is float:
        if not math.isfinite(raw):
            return repr(raw), "float", "NONFINITE_REPRESENTATION"
        return raw, "float", "RETAINED"
    if type(raw) is Decimal:
        encoded = str(raw)
        return ((raw, "Decimal", "RETAINED") if len(encoded) <= 128
                else (None, "Decimal", "OVERSIZE_NOT_RETAINED"))
    return None, type(raw).__name__[:64], "UNSUPPORTED_TYPE_NOT_RETAINED"


@dataclass(frozen=True)
class FieldObservation:
    name: str
    presence: str
    raw_value: object
    raw_type: str
    raw_retention: str
    raw_unit: str | None
    value: Decimal | None
    unit: str | None
    evidence: Evidence

    @property
    def state(self):
        return self.evidence.state

    @property
    def reason_codes(self):
        return self.evidence.reason_codes

    def to_dict(self):
        return json_value(self)


@dataclass(frozen=True)
class ContextSnapshot:
    contract_id: str | None
    provider: str | None
    source_revision: str | None
    source_id: str | None
    observed_at: datetime | None
    received_at: datetime | None
    available_at: datetime | None
    decision_at: datetime | None
    common_evidence: Evidence
    fields: tuple[FieldObservation, ...]
    schema_version: str = "tradepulse.option-optional-context.v1"
    source_authenticity: str = "NOT_ESTABLISHED"
    actionable: bool = False

    def field(self, name):
        return next(field for field in self.fields if field.name == name)

    @property
    def iv(self):
        return self.field("iv")

    @property
    def delta(self):
        return self.field("delta")

    @property
    def gamma(self):
        return self.field("gamma")

    @property
    def vega(self):
        return self.field("vega")

    @property
    def theta(self):
        return self.field("theta")

    @property
    def oi(self):
        return self.field("oi")

    @property
    def oi_change(self):
        return self.field("oi_change")

    @property
    def volume(self):
        return self.field("volume")

    def to_dict(self):
        result = json_value(self)
        result["fields"] = {field.name: field.to_dict() for field in self.fields}
        result["qualification_effect"] = "OPTIONAL_CONTEXT_ONLY"
        return result


def _policy(value, code):
    require(value is not None, "NOT_ESTABLISHED", code)
    result = number(value)
    require(0 <= result <= 86400, "INVALID", "INVALID_CONTEXT_FRESHNESS_POLICY")
    return result


def _envelope(record, contract, decision_at, max_age_seconds, *, fresh=True):
    require(record is not None, "UNAVAILABLE", "OPTIONAL_CONTEXT_NOT_SUPPLIED")
    require(isinstance(record, dict), "INVALID", "CONTEXT_RECORD_REQUIRED")
    require(isinstance(contract, ExactOptionContract), "NOT_ESTABLISHED", "EXACT_CONTRACT_NOT_ESTABLISHED")
    decision = timestamp(decision_at)
    age = _policy(max_age_seconds, "CONTEXT_FRESHNESS_POLICY_NOT_ESTABLISHED")
    require(contract.option_type in ("CE", "PE") and type(contract.lot_size) is int
            and contract.lot_size > 0 and contract.price_unit == "INR"
            and contract.quantity_unit == "UNDERLYING_UNITS" and contract.multiplier == 1,
            "INVALID", "INVALID_CONTEXT_CONTRACT_UNITS")
    master_observed, master_received, master_available = map(timestamp,
        (contract.source_observed_at, contract.received_at, contract.available_at))
    require(master_observed <= master_received <= master_available,
            "INVALID", "INVALID_CONTEXT_MASTER_CLOCK_ORDER")
    require(master_available <= decision, "UNAVAILABLE", "CONTEXT_MASTER_NOT_YET_AVAILABLE")
    require(all(type(value) is date for value in
                (contract.valid_from, contract.valid_to, contract.expiry)),
            "INVALID", "INVALID_CONTEXT_CONTRACT_DATES")
    for name, expected in (("contract_id", contract.contract_id), ("provider", contract.provider),
                           ("source_revision", contract.source_revision)):
        require(record.get(name) is not None, "NOT_ESTABLISHED", "CONTEXT_IDENTITY_NOT_ESTABLISHED")
        require(record[name] == expected, "INVALID", "CONTEXT_IDENTITY_MISMATCH")
    text(record.get("source_id"), "CONTEXT_SOURCE_UNAVAILABLE")
    require(record.get("observed_at") is not None, "NOT_ESTABLISHED", "SOURCE_TIME_NOT_ESTABLISHED")
    observed, received, available = (timestamp(record.get(key)) for key in
                                    ("observed_at", "received_at", "available_at"))
    require(observed <= received <= available, "INVALID", "INVALID_CONTEXT_CLOCK_ORDER")
    require(available <= decision, "UNAVAILABLE", "CONTEXT_NOT_YET_AVAILABLE")
    observed_day = observed.astimezone(IST).date()
    require(contract.valid_from <= observed_day <= contract.valid_to and
            observed_day <= contract.expiry, "INVALID", "CONTEXT_CONTRACT_NOT_EFFECTIVE")
    if fresh:
        elapsed = Decimal(str((decision-observed).total_seconds()))
        require(elapsed <= age, "STALE", "OPTIONAL_CONTEXT_STALE")
    return decision, observed, received, available


def _normalized(name, raw, unit, record, contract):
    value = number(raw)
    require(unit is not None, "NOT_ESTABLISHED", "OPTIONAL_UNIT_NOT_ESTABLISHED")
    if name == "iv":
        require(unit in ("FRACTION", "PERCENT"), "INVALID", "INVALID_IV_UNIT")
        require(value > 0, "INVALID", "INVALID_IV_VALUE")
        return (value/100 if unit == "PERCENT" else value), "FRACTION"
    if name == "delta":
        require(unit == DELTA_UNIT, "INVALID", "INVALID_DELTA_UNIT")
        require(-1 <= value <= 1 and (value >= 0 if contract.option_type == "CE" else value <= 0),
                "INVALID", "INVALID_SIGNED_DELTA")
        return value, DELTA_UNIT
    if name == "gamma":
        require(unit == GAMMA_UNIT, "INVALID", "INVALID_GAMMA_UNIT")
        require(value >= 0, "INVALID", "NEGATIVE_GAMMA")
        return value, GAMMA_UNIT
    if name == "vega":
        require(unit in (VEGA_FRACTION_UNIT, VEGA_POINT_UNIT), "INVALID", "INVALID_VEGA_UNIT")
        require(value >= 0, "INVALID", "NEGATIVE_VEGA")
        return (value * 100 if unit == VEGA_POINT_UNIT else value), VEGA_FRACTION_UNIT
    if name == "theta":
        require(unit in (THETA_DAY_UNIT, THETA_YEAR_UNIT), "INVALID", "INVALID_THETA_UNIT")
        if unit == THETA_YEAR_UNIT:
            require(record.get("theta_calendar_basis") == 365 and
                    type(record.get("theta_calendar_basis")) is int,
                    "NOT_ESTABLISHED", "THETA_365_CALENDAR_BASIS_NOT_ESTABLISHED")
            value /= 365
        return value, THETA_DAY_UNIT
    require(name in ("oi", "oi_change", "volume"), "INVALID", "UNSUPPORTED_OPTIONAL_FIELD")
    require(unit in ("CONTRACTS", "UNDERLYING_UNITS"), "INVALID", "INVALID_QUANTITY_UNIT")
    require(value == value.to_integral_value() and (name == "oi_change" or value >= 0),
            "INVALID", "INVALID_OPTION_COUNT")
    if name == "volume":
        window = record.get("volume_window")
        require(isinstance(window, dict), "NOT_ESTABLISHED", "VOLUME_WINDOW_NOT_ESTABLISHED")
        start, end = timestamp(window.get("start_at")), timestamp(window.get("end_at"))
        require(start < end <= timestamp(record.get("observed_at")), "INVALID", "INVALID_VOLUME_WINDOW")
    result = value * contract.lot_size if unit == "CONTRACTS" else value
    require(abs(result) <= 2**53-1, "INVALID", "NORMALIZED_COUNT_OUT_OF_BOUNDS")
    return result, "UNDERLYING_UNITS"


def _inspect(record, contract, *, decision_at, max_age_seconds, fresh):
    clocks = (None, None, None, None)
    try:
        clocks = _envelope(record, contract, decision_at, max_age_seconds, fresh=fresh)
        common = Evidence("VERIFIED", ("SUPPLIED_IDENTITY_CLOCK_CHECKS_ONLY",))
    except CheckError as exc:
        common = Evidence(exc.state, (exc.code,))
    container = record if isinstance(record, dict) else {}
    values, units = container.get("fields", {}), container.get("units", {})
    if not isinstance(values, dict):
        values = {}
        common = Evidence("INVALID", ("OPTIONAL_FIELDS_MAPPING_REQUIRED",))
    if not isinstance(units, dict):
        units = {}
        common = Evidence("INVALID", ("OPTIONAL_UNITS_MAPPING_REQUIRED",))
    observations = []
    for name in FIELDS:
        presence = "ABSENT" if name not in values else "NULL" if values[name] is None else "OBSERVED"
        raw = values.get(name)
        retained, raw_type, retention = _safe_raw(raw)
        raw_unit = units.get(name) if type(units.get(name)) is str and len(units[name]) <= 128 else None
        normalized = normalized_unit = None
        if presence != "OBSERVED":
            evidence = Evidence("UNAVAILABLE", ("FEATURE_"+presence,))
        else:
            try:
                require(retention == "RETAINED", "INVALID", "INVALID_OR_OVERSIZE_RAW_FIELD")
                require(common.state == "VERIFIED", common.state, common.reason_codes[0])
                if name in units and units[name] is not None:
                    require(raw_unit is not None, "INVALID", "INVALID_OPTIONAL_UNIT_DECLARATION")
                normalized, normalized_unit = _normalized(name, raw, raw_unit, container, contract)
                if name == "oi_change":
                    normalized = None
                    evidence = Evidence("NOT_ESTABLISHED", ("OI_CHANGE_BASELINE_REQUIRED",))
                else:
                    evidence = Evidence("VERIFIED", ("DECLARED_UNIT_ARITHMETIC_ONLY",))
            except CheckError as exc:
                evidence = Evidence(exc.state, (exc.code,))
        observations.append(FieldObservation(name, presence, retained, raw_type, retention,
                            raw_unit, normalized, normalized_unit, evidence))
    safe_meta = lambda key: container.get(key) if type(container.get(key)) is str and len(container[key]) <= 512 else None
    decision, observed, received, available = clocks
    return ContextSnapshot(safe_meta("contract_id"), safe_meta("provider"), safe_meta("source_revision"),
                           safe_meta("source_id"), observed, received, available, decision,
                           common, tuple(observations))


def inspect_context(record, contract, *, decision_at, max_age_seconds):
    """Inspect eight optional fields independently using explicit supplied units."""
    return _inspect(record, contract, decision_at=decision_at,
                    max_age_seconds=max_age_seconds, fresh=True)


@dataclass(frozen=True)
class OIDelta:
    current_underlying_units: Decimal
    baseline_underlying_units: Decimal
    change_underlying_units: Decimal
    baseline_kind: str
    contract_id: str
    current_source_id: str
    baseline_source_id: str
    current_observed_at: datetime
    baseline_observed_at: datetime
    evidence_digest: str
    supplied_change_underlying_units: Decimal | None = None
    supplied_change_status: str = "ABSENT"
    source_authenticity: str = "NOT_ESTABLISHED"
    interpretation: str = "OPEN_INTEREST_CHANGE_NOT_ORDER_AGGRESSION_OR_DIRECTION"


def oi_delta(current, baseline, contract, *, decision_at, max_age_seconds,
             max_alignment_seconds, prior_session_date=None):
    """Comparable exact-contract OI change; no percentage on a zero baseline.

    A PRIOR_CLOSE join requires an explicit preceding-session declaration and
    15:30 IST baseline; this does not verify an exchange trading calendar.
    """
    try:
        alignment = _policy(max_alignment_seconds, "OI_ALIGNMENT_POLICY_NOT_ESTABLISHED")
        now = inspect_context(current, contract, decision_at=decision_at, max_age_seconds=max_age_seconds)
        before = _inspect(baseline, contract, decision_at=decision_at,
                          max_age_seconds=max_age_seconds, fresh=False)
        for snapshot in (now, before):
            require(snapshot.common_evidence.state == "VERIFIED", snapshot.common_evidence.state,
                    snapshot.common_evidence.reason_codes[0])
            require(snapshot.oi.state == "VERIFIED", snapshot.oi.state,
                    snapshot.oi.reason_codes[0])
        require(current.get("kind") == "CURRENT", "NOT_ESTABLISHED", "OI_CURRENT_KIND_NOT_ESTABLISHED")
        kind = baseline.get("kind")
        require(kind in ("INTRADAY", "PRIOR_CLOSE"), "NOT_ESTABLISHED", "OI_BASELINE_KIND_NOT_ESTABLISHED")
        require(now.oi.raw_unit == before.oi.raw_unit, "INVALID", "OI_UNIT_MISMATCH")
        require(before.observed_at < now.observed_at, "INVALID", "OI_BASELINE_NOT_PRIOR")
        current_day, baseline_day = (snapshot.observed_at.astimezone(IST).date() for snapshot in (now, before))
        if kind == "INTRADAY":
            require(current_day == baseline_day and
                    Decimal(str((now.observed_at-before.observed_at).total_seconds())) <= alignment,
                    "INVALID", "OI_INTRADAY_ALIGNMENT_MISMATCH")
        else:
            require(prior_session_date is not None, "NOT_ESTABLISHED", "PRIOR_SESSION_NOT_ESTABLISHED")
            prior = day(prior_session_date)
            clock = before.observed_at.astimezone(IST).time().replace(tzinfo=None)
            require(prior == baseline_day < current_day and clock == time(15, 30),
                    "INVALID", "INVALID_PRIOR_CLOSE_BASELINE")
        supplied_change = None
        change_status = now.oi_change.presence
        if change_status == "OBSERVED":
            require(now.oi_change.state == "NOT_ESTABLISHED" and
                    now.oi_change.reason_codes == ("OI_CHANGE_BASELINE_REQUIRED",),
                    now.oi_change.state, now.oi_change.reason_codes[0])
            require(now.oi_change.raw_unit == now.oi.raw_unit,
                    "INVALID", "OI_CHANGE_UNIT_MISMATCH")
            supplied_change, _ = _normalized("oi_change", current["fields"]["oi_change"],
                now.oi_change.raw_unit, current, contract)
            require(supplied_change == now.oi.value-before.oi.value,
                    "INVALID", "OI_CHANGE_BASELINE_MISMATCH")
            change_status = "MATCHED_SUPPLIED_BASELINE"
        result = OIDelta(now.oi.value, before.oi.value, now.oi.value-before.oi.value,
            kind, contract.contract_id, now.source_id, before.source_id,
            now.observed_at, before.observed_at,
            digest(dict(current=now.to_dict(), baseline=before.to_dict(), kind=kind,
                        prior_session_date=prior_session_date)),
            supplied_change_underlying_units=supplied_change,
            supplied_change_status=change_status)
        return Evidence("VERIFIED", ("SUPPLIED_OI_ARITHMETIC_ONLY", "NO_AGGRESSION_OR_DIRECTION_INFERENCE"), result)
    except CheckError as exc:
        return Evidence(exc.state, (exc.code,))


@dataclass(frozen=True)
class GreekScenario:
    premium_change_inr_per_underlying_unit: Decimal
    delta_component: Decimal
    gamma_component: Decimal
    vega_component: Decimal
    theta_component: Decimal
    contract_id: str
    source_id: str
    observed_at: datetime
    approximation: str = "LOCAL_GREEK_SCENARIO_ONLY_NOT_EXECUTION_PRICE"
    source_authenticity: str = "NOT_ESTABLISHED"


def greek_scenario(snapshot, *, underlying_change_inr, iv_change_fraction, elapsed_calendar_days):
    """Local Taylor scenario per underlying unit; never an actual premium fill."""
    try:
        require(isinstance(snapshot, ContextSnapshot), "UNAVAILABLE", "GREEK_CONTEXT_UNAVAILABLE")
        require(snapshot.common_evidence.state == "VERIFIED", snapshot.common_evidence.state,
                snapshot.common_evidence.reason_codes[0])
        for name in ("delta", "gamma", "vega", "theta"):
            field = snapshot.field(name)
            require(field.state == "VERIFIED", field.state, "SCENARIO_"+name.upper()+"_"+field.reason_codes[0])
        spot, iv, elapsed = map(number, (underlying_change_inr, iv_change_fraction, elapsed_calendar_days))
        require(elapsed >= 0, "INVALID", "NEGATIVE_CALENDAR_TIME")
        delta = snapshot.delta.value * spot
        gamma = Decimal(".5") * snapshot.gamma.value * spot**2
        vega = snapshot.vega.value * iv
        theta = snapshot.theta.value * elapsed
        result = GreekScenario(delta+gamma+vega+theta, delta, gamma, vega, theta,
                               snapshot.contract_id, snapshot.source_id, snapshot.observed_at)
        return Evidence("VERIFIED", ("SCENARIO_ONLY_NOT_EXECUTION",), result)
    except CheckError as exc:
        return Evidence(exc.state, (exc.code,))

"""Explicit synthetic field joins, not a source qualifier or prospective gate.

The D1 fixture specification is broader than this deliberately restricted D2
test-vector envelope. Native records, real captures and the complete D1 schema
are unsupported. No mapping can infer a token, unit, timestamp or data right.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
import hashlib
import json

from option_intelligence.evidence import (IST, CheckError, day, digest, json_value,
    number, require, text, timestamp)
from option_intelligence.fitness import FrictionAssumptions, analyze_option
from option_intelligence.identity import REQUIRED_FIELDS
from option_intelligence.quotes import QuotePolicy, SessionWindow
from . import SOURCE_MAPPING_ENABLED, VERSION

SCHEMA = "tradepulse.option-source-mapping-fixture.d2.v1"
REQUIREMENTS = ("DATED_MASTER", "TOKEN_TERMS_CROSSWALK", "PREMIUM_TICK",
    "LOT_QUANTITY_UNITS", "BOOK_SOURCE_CLOCKS", "SESSION_PHASES", "DATA_RIGHTS")
DOC_STATES = ("DOCUMENTED", "CONDITIONAL", "UNVERIFIED", "UNAVAILABLE", "CONTRADICTORY")
DATA_STATES = ("VERIFIED", "UNAVAILABLE", "STALE", "INVALID", "NOT_ESTABLISHED")
AUTHORITY_FLAGS = ("source_qualified", "prospective_ready", "forward_entry_allowed",
    "actionable", "execution_allowed", "historical_replay_allowed", "activation_allowed")
QUOTE_FIELDS = ("quote_id", "contract_id", "provider", "source_revision", "source_id",
    "observed_at", "received_at", "available_at", "bid_at", "ask_at", "bid", "ask",
    "bid_size", "ask_size", "price_unit", "quantity_unit")
GROUPS = {"contract": ("master", REQUIRED_FIELDS),
    "quote": ("quote", QUOTE_FIELDS),
    "policy": ("policy", tuple(QuotePolicy.__dataclass_fields__)),
    "session": ("session", tuple(SessionWindow.__dataclass_fields__)),
    "assumptions": ("assumptions", tuple(FrictionAssumptions.__dataclass_fields__))}


def mapping_unit(group, name):
    if name in ("strike", "tick_size", "bid", "ask", "entry_impact", "exit_impact"):
        return "INR"
    if name in ("round_trip_fees_inr", "risk_budget_inr", "capital_budget_inr"):
        return "INR_TOTAL"
    if name == "lot_size":
        return "UNDERLYING_UNITS_PER_CONTRACT"
    if name in ("bid_size", "ask_size"):
        return "DECLARED_QUANTITY_UNIT"
    if name.endswith("_at"):
        return "OFFSET_TIMESTAMP"
    if name in ("expiry", "valid_from", "valid_to", "effective_from", "effective_to", "session_date"):
        return "ISO_DATE"
    if name.endswith("_seconds"):
        return "SECONDS"
    if name == "premium_loss_fraction":
        return "FRACTION"
    return "EXPLICIT_VALUE"


def requirement_for(group, name):
    if name == "tick_size":
        return "PREMIUM_TICK"
    if name in ("lot_size", "bid_size", "ask_size", "quantity_unit", "price_unit", "multiplier"):
        return "LOT_QUANTITY_UNITS"
    if group == "contract":
        return "TOKEN_TERMS_CROSSWALK" if name in ("identifier", "symbol", "underlying", "underlying_identifier", "expiry", "strike", "option_type") else "DATED_MASTER"
    return "SESSION_PHASES" if group == "session" else "BOOK_SOURCE_CLOCKS" if group in ("quote", "policy") else "DATA_RIGHTS"


@dataclass(frozen=True)
class EvidenceRow:
    requirement: str
    evidence_id: str | None
    documentation_state: str | None
    declared_observed_state: str | None
    checked_state: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class MappingResult:
    state: str
    reason_codes: tuple[str, ...]
    fixture_id: str | None = None
    fixture_digest: str | None = None
    evidence_matrix: tuple[EvidenceRow, ...] = ()
    analysis_json: str | None = None
    original_bytes_sha256: str | None = None
    mapping_version: str = VERSION
    source_qualified: bool = field(default=False, init=False)
    prospective_ready: bool = field(default=False, init=False)
    forward_entry_allowed: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)
    execution_allowed: bool = field(default=False, init=False)
    historical_replay_allowed: bool = field(default=False, init=False)
    activation_allowed: bool = field(default=False, init=False)

    def to_dict(self):
        value = json_value(self)
        value["analysis"] = json.loads(value.pop("analysis_json")) if self.analysis_json is not None else None
        value.update(schema_version="tradepulse.option-source-mapping-result.d2.v1",
            validation_scope="SYNTHETIC_DECLARATIONS_AND_EXPLICIT_JOINS_ONLY",
            source_authenticity="NOT_ESTABLISHED", qualification_owner="CURSOR_MAIN",
            qualification_blockers=["SYNTHETIC_NOT_SOURCE_EVIDENCE", "NO_INDEPENDENT_SOURCE_QUALIFICATION",
                "NO_REAL_DATA_ENTITLEMENT", "OPTION_APEX_FORWARD_LIFECYCLE_DISABLED"],
            historical_option_pnl="BLOCKED_DATA_FOR_HISTORICAL_OPTION_PNL")
        return value


def decode_fixture(raw):
    """Bounded bytes/text only, never a path or URL to open/fetch."""
    require(isinstance(raw, (str, bytes)), "INVALID", "FIXTURE_BYTES_OR_TEXT_REQUIRED")
    try:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
        require(len(encoded) <= 262144, "INVALID", "FIXTURE_TOO_LARGE")
        def pairs(items):
            output = {}
            for key, value in items:
                require(key not in output, "INVALID", "DUPLICATE_JSON_KEY")
                output[key] = value
            return output
        def constant(_):
            raise CheckError("INVALID", "NONFINITE_JSON_CONSTANT")
        def exact_float(token):
            parsed = number(token)
            converted = float(parsed)
            require(Decimal(str(converted)) == parsed, "INVALID", "INEXACT_JSON_NUMBER_USE_DECIMAL_STRING")
            return converted
        value = json.loads(encoded.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant,
            parse_float=exact_float, parse_int=lambda token: int(number(token)))
        require(isinstance(value, dict), "INVALID", "FIXTURE_OBJECT_REQUIRED")
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise CheckError("INVALID", "INVALID_JSON_FIXTURE") from None


def _bounded_copy(bundle):
    require(isinstance(bundle, dict), "INVALID", "FIXTURE_OBJECT_REQUIRED")
    try:
        encoded = json.dumps(bundle, allow_nan=False, separators=(",", ":"))
        require(len(encoded.encode()) <= 262144, "INVALID", "FIXTURE_TOO_LARGE")
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, CheckError):
            raise
        raise CheckError("INVALID", "INVALID_JSON_FIXTURE") from None


def _reject_authority(value, depth=0):
    require(depth <= 32, "INVALID", "FIXTURE_NESTING_TOO_DEEP")
    if isinstance(value, dict):
        for key, item in value.items():
            if key in AUTHORITY_FLAGS:
                require(item is False, "INVALID", "CALLER_AUTHORITY_ASSERTION_REJECTED")
            _reject_authority(item, depth+1)
    elif isinstance(value, list):
        for item in value:
            _reject_authority(item, depth+1)


def _matrix(evidence, decision, provider):
    require(isinstance(evidence, list) and len(evidence) <= 32, "INVALID", "INVALID_EVIDENCE_LIST")
    require(all(isinstance(row, dict) for row in evidence), "INVALID", "INVALID_EVIDENCE_ROW")
    ids = [row.get("evidence_id") for row in evidence]
    require(all(isinstance(item, str) and item for item in ids) and len(set(ids)) == len(ids),
            "INVALID", "MISSING_OR_DUPLICATE_EVIDENCE_ID")
    require(all(row.get("requirement") in REQUIREMENTS for row in evidence),
            "INVALID", "UNKNOWN_EVIDENCE_REQUIREMENT")
    output = []
    for name in REQUIREMENTS:
        matches = [row for row in evidence if row.get("requirement") == name]
        row = matches[0] if len(matches) == 1 else {}
        doc, observed = row.get("documentation_state"), row.get("observed_state")
        try:
            require(len(matches) <= 1, "INVALID", "DUPLICATE_EVIDENCE_REQUIREMENT")
            require(bool(row), "UNAVAILABLE", "MANDATORY_EVIDENCE_MISSING")
            require(doc in DOC_STATES and observed in DATA_STATES, "INVALID", "EVIDENCE_STATE_AXIS_MISMATCH")
            require(row.get("provider") == provider, "INVALID", "EVIDENCE_PROVIDER_MISMATCH")
            require(row.get("scope") == "SYNTHETIC_OFFLINE_MAPPING", "INVALID", "EVIDENCE_SCOPE_MISMATCH")
            text(row.get("reference"))
            require(isinstance(row.get("limitations"), list) and bool(row["limitations"]),
                    "UNAVAILABLE", "EVIDENCE_LIMITATIONS_REQUIRED")
            require(timestamp(row.get("available_at")) <= decision, "UNAVAILABLE", "EVIDENCE_NOT_YET_AVAILABLE")
            start, end = timestamp(row.get("effective_from")), timestamp(row.get("effective_until"))
            require(start < end, "INVALID", "INVALID_EVIDENCE_EFFECTIVE_INTERVAL")
            require(start <= decision < end, "STALE", "EVIDENCE_OUTSIDE_EFFECTIVE_INTERVAL")
            require(doc != "CONTRADICTORY", "NOT_ESTABLISHED", "DOCUMENTATION_CONTRADICTORY")
            require(doc == "DOCUMENTED", "NOT_ESTABLISHED", "DOCUMENTATION_NOT_ESTABLISHED")
            require(observed == "VERIFIED", observed, "DECLARED_OBSERVATION_NOT_VERIFIED")
            checked, reasons = "VERIFIED", ("SYNTHETIC_EVIDENCE_RECORD_CHECKS_ONLY",)
        except CheckError as error:
            checked, reasons = error.state, (error.code,)
        output.append(EvidenceRow(name, row.get("evidence_id"), doc, observed, checked, reasons))
    return tuple(output)


def _map_inputs(bundle, rows):
    source, mappings = bundle.get("source"), bundle.get("mapping")
    require(isinstance(source, dict) and isinstance(mappings, list), "UNAVAILABLE", "SOURCE_OR_MAPPING_UNAVAILABLE")
    expected_hash = source.get("source_sha256")
    content = {key:value for key,value in source.items() if key != "source_sha256"}
    require(expected_hash == digest(content), "INVALID", "SOURCE_ARTIFACT_DIGEST_MISMATCH")
    by_id = {row.evidence_id:row.requirement for row in rows}
    expected = {group+"."+name for group,(_,names) in GROUPS.items() for name in names}
    targets = [item.get("target_path") for item in mappings if isinstance(item, dict)]
    require(len(targets) == len(mappings) and len(set(targets)) == len(targets),
            "INVALID", "INVALID_OR_DUPLICATE_MAPPING_TARGET")
    require(set(targets) <= expected, "INVALID", "UNKNOWN_MAPPING_TARGET")
    require(set(targets) == expected, "UNAVAILABLE", "MANDATORY_MAPPING_MISSING")
    result = {group:{} for group in GROUPS}
    for item in mappings:
        target = item["target_path"]
        group, name = target.split(".")
        source_group = GROUPS[group][0]
        require(item.get("source_path") == source_group+"."+name,
                "INVALID", "UNREVIEWED_FIELD_RENAME_OR_FALLBACK")
        presence = item.get("presence")
        require(presence in ("ABSENT", "NULL", "OBSERVED"), "INVALID", "INVALID_FIELD_PRESENCE")
        record = source.get(source_group)
        require(isinstance(record, dict), "UNAVAILABLE", "SOURCE_COMPONENT_UNAVAILABLE")
        actual = "ABSENT" if name not in record else "NULL" if record[name] is None else "OBSERVED"
        require(actual == presence, "INVALID", "FIELD_PRESENCE_MISMATCH")
        require(presence == "OBSERVED", "UNAVAILABLE", "MANDATORY_FIELD_"+presence)
        require(item.get("unit") == mapping_unit(group, name), "NOT_ESTABLISHED", "MAPPING_UNIT_NOT_ESTABLISHED")
        references = item.get("evidence_ids")
        require(isinstance(references, list) and bool(references) and
                all(ref in by_id for ref in references), "INVALID", "MAPPING_EVIDENCE_REFERENCE_MISMATCH")
        require(requirement_for(group, name) in {by_id[ref] for ref in references},
                "INVALID", "WRONG_EVIDENCE_REQUIREMENT_FOR_FIELD")
        result[group][name] = record[name]
    return source, result


def _seconds(delta):
    return Decimal(delta.days*86400+delta.seconds)+Decimal(delta.microseconds)/1000000


def _cover_source_events(bundle, source, values):
    master, quote = values["contract"], values["quote"]
    book_events = [quote[key] for key in ("observed_at", "bid_at", "ask_at")]+[source.get("size_at")]
    event_sets = {
        "DATED_MASTER": [master["source_observed_at"]],
        "TOKEN_TERMS_CROSSWALK": [master["source_observed_at"], *book_events],
        "PREMIUM_TICK": [master["source_observed_at"], *book_events],
        "LOT_QUANTITY_UNITS": [master["source_observed_at"], *book_events],
        "BOOK_SOURCE_CLOCKS": book_events,
        "SESSION_PHASES": [values["session"]["open_at"], values["session"]["close_at"], *book_events],
        "DATA_RIGHTS": [master["received_at"], master["available_at"], quote["received_at"], quote["available_at"]],
    }
    for row in bundle["evidence"]:
        start, end = timestamp(row["effective_from"]), timestamp(row["effective_until"])
        require(all(start <= timestamp(event) < end for event in event_sets[row["requirement"]]),
                "NOT_ESTABLISHED", row["requirement"]+"_SOURCE_EVENT_NOT_COVERED")


def map_synthetic_fixture(bundle, *, enabled=SOURCE_MAPPING_ENABLED):
    if enabled is not True:
        return MappingResult("DISABLED", ("SOURCE_MAPPING_FLAG_OFF",))
    rows, fixture_id, fixture_hash, raw_hash = (), None, None, None
    try:
        if isinstance(bundle, (bytes, str)):
            encoded = bundle.encode("utf-8") if isinstance(bundle, str) else bundle
            raw_hash = hashlib.sha256(encoded).hexdigest()
            bundle = decode_fixture(bundle)
        bundle = _bounded_copy(bundle)
        _reject_authority(bundle)
        allowed = {"schema_version", "fixture_id", "provenance", "read_only", "decision_at",
                   "intended_lots", "evidence", "source", "mapping", *AUTHORITY_FLAGS}
        require(not set(bundle)-allowed, "INVALID", "UNKNOWN_FIXTURE_FIELD")
        require(bundle.get("schema_version") == SCHEMA, "INVALID", "UNSUPPORTED_MAPPING_FIXTURE_SCHEMA")
        fixture_id = text(bundle.get("fixture_id"))
        fixture_hash = digest(bundle)
        require(bundle.get("provenance") == "SYNTHETIC_FIXTURE", "UNAVAILABLE", "REAL_CAPTURE_NOT_SUPPORTED_D2")
        require(bundle.get("read_only") is True, "INVALID", "READ_ONLY_FIXTURE_REQUIRED")
        decision = timestamp(bundle.get("decision_at"))
        source = bundle.get("source")
        require(isinstance(source, dict) and isinstance(source.get("master"), dict),
                "UNAVAILABLE", "SOURCE_MASTER_UNAVAILABLE")
        provider = source["master"].get("provider")
        rows = _matrix(bundle.get("evidence"), decision, provider)
        failure = next((row for row in rows if row.checked_state != "VERIFIED"), None)
        if failure:
            return MappingResult(failure.checked_state, failure.reason_codes,
                fixture_id, fixture_hash, rows, original_bytes_sha256=raw_hash)
        source, values = _map_inputs(bundle, rows)
        allowed_source = {"master", "quote", "policy", "session", "assumptions", "source_sha256",
            "size_at", "book_time_meaning", "membership", "context", "context_max_age_seconds", "depth"}
        require(not set(source)-allowed_source, "INVALID", "UNKNOWN_SOURCE_COMPONENT")
        _cover_source_events(bundle, source, values)
        require(source.get("book_time_meaning") == "EXCHANGE_BOOK_SNAPSHOT",
                "NOT_ESTABLISHED", "BOOK_CLOCK_SEMANTICS_NOT_ESTABLISHED")
        size_at = timestamp(source.get("size_at"))
        quote = values["quote"]
        require(size_at <= timestamp(quote["received_at"]) <= decision,
                "INVALID", "LIQUIDITY_CLOCK_ORDER_INVALID")
        require(0 <= _seconds(decision-size_at) <= number(values["policy"]["max_age_seconds"]),
                "STALE", "LIQUIDITY_SOURCE_CLOCK_STALE")
        clock_set = [size_at, *(timestamp(quote[name]) for name in ("observed_at", "bid_at", "ask_at"))]
        require(_seconds(max(clock_set)-min(clock_set)) <=
                number(values["policy"]["max_leg_skew_seconds"]), "STALE", "LIQUIDITY_BOOK_CLOCK_MISALIGNED")
        # Effective timestamp evidence cannot be widened into unproved full-day
        # validity. The authored date fields must be covered by master evidence.
        master_evidence = next(row for row in bundle["evidence"] if row["requirement"] == "DATED_MASTER")
        for clock in (values["contract"]["source_observed_at"],):
            require(timestamp(clock) <= decision, "UNAVAILABLE", "MASTER_OBSERVATION_NOT_AVAILABLE")
        lower = timestamp(master_evidence["effective_from"]).astimezone(IST)
        upper = timestamp(master_evidence["effective_until"]).astimezone(IST)
        require(day(values["contract"]["valid_from"]) == lower.date() and
                day(values["contract"]["valid_to"]) == (upper-timedelta(microseconds=1)).date(),
                "NOT_ESTABLISHED", "MASTER_DATE_PROJECTION_NOT_SUPPORTED")
        require(lower.time().isoformat() == "00:00:00" and upper.time().isoformat() == "00:00:00",
                "NOT_ESTABLISHED", "PARTIAL_DAY_MASTER_CANNOT_WIDEN_VALIDITY")
        policy_values, session_values, costs = values["policy"], values["session"], values["assumptions"]
        policy_values["available_at"] = timestamp(policy_values["available_at"])
        session_values["session_date"] = day(session_values["session_date"])
        for name in ("open_at", "close_at", "available_at"):
            session_values[name] = timestamp(session_values[name])
        for name in ("effective_from", "effective_to"):
            costs[name] = day(costs[name])
        costs["available_at"] = timestamp(costs["available_at"])
        analysis = analyze_option(values["contract"], quote, decision_at=decision,
            intended_lots=bundle.get("intended_lots"), policy=QuotePolicy(**policy_values),
            session=SessionWindow(**session_values), assumptions=FrictionAssumptions(**costs),
            membership=source.get("membership"), context_record=source.get("context"),
            context_max_age_seconds=source.get("context_max_age_seconds"),
            depth_record=source.get("depth"), provenance="SYNTHETIC_FIXTURE", enabled=True)
        payload = analysis.to_dict()
        failures = [analysis.identity]
        if analysis.quote is not None:
            failures.append(analysis.quote.evidence)
        failures.append(analysis.friction)
        issue = next((item for item in failures if item.state != "VERIFIED"), None)
        state, reasons = (issue.state, issue.reason_codes) if issue else (
            "VERIFIED", ("SYNTHETIC_MAPPING_ONLY", "SOURCE_QUALIFICATION_NOT_ESTABLISHED"))
        return MappingResult(state, reasons, fixture_id, fixture_hash, rows,
                             json.dumps(payload, sort_keys=True, allow_nan=False), raw_hash)
    except CheckError as error:
        return MappingResult(error.state, (error.code,), fixture_id, fixture_hash, rows,
                             original_bytes_sha256=raw_hash)
    except (TypeError, ValueError, ArithmeticError, RecursionError, KeyError):
        return MappingResult("INVALID", ("INVALID_MAPPING_FIXTURE",), fixture_id, fixture_hash, rows,
                             original_bytes_sha256=raw_hash)

"""Bounded offline context imports and additive, point-in-time candidate views.

No acquisition or sentiment inference. Local policy approval is distinct from
independently established publisher authority/rights. Normalized records supplied
to the matcher must come from this parser and integrity-checked persistence.
"""
import copy
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit

from candle_lineage import digest, encoded
from instrument_identity import spot_identity
from publisher_trust import PublisherTrustVerifier, TrustAnchorConfig

SOURCE_SCHEMA = "tradepulse.context-source.v1"
INGESTION_SCHEMA = "tradepulse.context-ingestion.v1"
CONTEXT_SCHEMA = "tradepulse.candidate-context.v1"
MAX_BYTES = 256 * 1024
MAX_RECORDS = 100
MAX_MATCH_RECORDS = 10000
IDENTITY_FIELDS = ("provider", "symbol", "identifier", "exchange", "segment",
    "instrument_type", "is_index", "source", "source_revision")


class ContextValidationError(ValueError):
    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _fail(code):
    raise ContextValidationError(code)


def _text(value, field, limit=256, optional=False):
    if optional and value is None:
        return None
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(char) < 32 for char in value)):
        _fail("CONTEXT_INVALID_" + field.upper())
    return value.strip()


def _time(value, field, optional=False):
    if optional and value is None:
        return None
    text = _text(value, field, 64)
    try:
        result = datetime.fromisoformat(text)
        if result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        _fail("CONTEXT_INVALID_" + field.upper())


def safe_source_url(value):
    """Accept only explicit public HTTPS links; never dereference them."""
    value = _text(value, "source_url", 2048)
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme != "https" or not host or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)
                or "\\" in value or any(c.isspace() for c in value)
                or "%" in parts.netloc or host.endswith(".") or host.lower() == "localhost"
                or host.lower().endswith((".local", ".localhost"))):
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError:
            if ":" in host or re.fullmatch(r"[0-9.]+", host):
                raise
            if ("." not in host or not re.fullmatch(r"[A-Za-z0-9.-]+", host)
                    or any(not label or label.startswith("-") or label.endswith("-")
                           for label in host.split("."))):
                raise ValueError()
    except (ValueError, TypeError):
        _fail("CONTEXT_UNSAFE_SOURCE_URL")
    return value


def _identity_key(identity):
    if not isinstance(identity, dict) or any(field not in identity for field in IDENTITY_FIELDS):
        _fail("CONTEXT_INVALID_INSTRUMENT_IDENTITY")
    if (type(identity["is_index"]) is not bool or identity["provider"] not in ("angelone", "dhan", "upstox")
            or any(not isinstance(identity[field], str) or not identity[field] or len(identity[field]) > 256
                   for field in IDENTITY_FIELDS if field != "is_index")
            or not re.fullmatch(r"[0-9a-f]{64}", identity["source_revision"])):
        _fail("CONTEXT_INVALID_INSTRUMENT_IDENTITY")
    return digest({field: identity[field] for field in IDENTITY_FIELDS})


def _trusted_identities(identities):
    if not isinstance(identities, (list, tuple)) or len(identities) > 100:
        _fail("CONTEXT_INVALID_TRUSTED_IDENTITIES")
    result = {}
    for identity in identities:
        key = _identity_key(identity)
        provider, symbol = identity["provider"], identity["symbol"]
        field = {"angelone": "angel_token", "upstox": "upstox_key", "dhan":
                 "dhan_security_id" if identity["is_index"] else "dhan_id"}.get(provider)
        if not field:
            _fail("CONTEXT_INVALID_INSTRUMENT_IDENTITY")
        master = {symbol: identity["master_record"]} if "master_record" in identity else None
        try:
            canonical = spot_identity(dict(symbol=symbol, **{field: identity["identifier"]}), provider, master)
            if _identity_key(canonical) != key:
                _fail("CONTEXT_INVALID_INSTRUMENT_IDENTITY")
        except (ValueError, TypeError, KeyError):
            _fail("CONTEXT_INVALID_INSTRUMENT_IDENTITY")
        if key in result:
            _fail("CONTEXT_AMBIGUOUS_MAPPING")
        result[key] = copy.deepcopy(identity)
    return result


class ContextSourcePolicy:
    """Explicit operator-owned policy; never construct from an import request.

    Each approval binds source_id to provider, exact public domains, source name,
    authority_reference and rights_reference. References mean locally approved
    evidence, not a finding that legal rights or publisher authority are proven.
    Manifests are supplied separately, indexed by original artifact SHA-256.
    """
    def __init__(self, *, trust_config, approvals, manifests_by_sha256):
        if not isinstance(trust_config, TrustAnchorConfig) or not isinstance(approvals, dict):
            _fail("CONTEXT_INVALID_SOURCE_POLICY")
        self._trust = trust_config
        self._approvals = copy.deepcopy(approvals)
        self._manifests = copy.deepcopy(manifests_by_sha256)
        if not isinstance(self._manifests, dict) or len(self._approvals) > 100 or len(self._manifests) > 100:
            _fail("CONTEXT_INVALID_SOURCE_POLICY")
        for checksum, manifest in self._manifests.items():
            if (not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)
                    or not isinstance(manifest, str) or len(manifest) > 128 * 1024):
                _fail("CONTEXT_INVALID_SOURCE_POLICY")
        for source, approval in self._approvals.items():
            _text(source, "source_id")
            if not isinstance(approval, dict):
                _fail("CONTEXT_INVALID_SOURCE_POLICY")
            for field in ("provider", "source_name", "authority_reference", "rights_reference"):
                _text(approval.get(field), field, 1024)
            domains = approval.get("domains")
            if not isinstance(domains, list) or not domains or len(domains) > 20:
                _fail("CONTEXT_INVALID_SOURCE_POLICY")
            for domain in domains:
                if urlsplit(safe_source_url("https://" + _text(domain, "domain"))).hostname != domain:
                    _fail("CONTEXT_INVALID_SOURCE_POLICY")

    @property
    def policy_id(self):
        # Artifact proofs can grow without changing who/what is approved. Every
        # retained artifact is still reverified against its actual manifest.
        return digest(["context-source-policy-v1", self._trust.fingerprint, self._approvals])

    def qualify(self, record, raw, collected):
        denied = dict(status="NOT_ESTABLISHED", allowed=False,
            reason_code="CONTEXT_SOURCE_UNVERIFIED", authority="NOT_ESTABLISHED", rights="NOT_ESTABLISHED")
        approval = self._approvals.get(record["source_id"])
        if not approval:
            return denied
        if (approval["provider"] != record["provider"] or approval["source_name"] != record["source_name"]
                or urlsplit(record["source_url"]).hostname not in approval["domains"]):
            return dict(denied, reason_code="CONTEXT_SOURCE_POLICY_MISMATCH")
        manifest = self._manifests.get(hashlib.sha256(raw).hexdigest())
        if manifest is None:
            return dict(denied, reason_code="CONTEXT_SIGNATURE_MISSING")
        result = PublisherTrustVerifier(self._trust).verify(manifest, raw, verification_time=collected,
            required_scope=dict(provider=record["provider"], exchange=record["instrument_identity"]["exchange"],
                market_segment=record["instrument_identity"]["segment"],
                instrument_scope=record["instrument_identity"]["symbol"]))
        if not result.allowed:
            return dict(denied, reason_code="CONTEXT_" + result.reason_code)
        signed = json.loads(manifest)
        if (signed["publisher_id"] != record["source_id"] or signed["artifact_type"] != "context-records"
                or signed["artifact_schema_version"] != SOURCE_SCHEMA
                or signed["rights_reference"] != approval["rights_reference"]):
            return dict(denied, reason_code="CONTEXT_SIGNED_SCOPE_MISMATCH")
        start, end = _time(result.effective_from, "effective_from"), _time(result.effective_until, "effective_until")
        timestamps = [collected] + [_time(record[field], field) for field in ("published_at", "event_at")
                                    if record[field] is not None]
        if any(timestamp < start or timestamp > end for timestamp in timestamps):
            return dict(denied, reason_code="CONTEXT_SIGNED_TIME_COVERAGE_MISMATCH")
        return dict(status="QUALIFIED_UNDER_LOCAL_POLICY", allowed=True, reason_code="CONTEXT_LOCAL_POLICY_QUALIFIED",
            authority="LOCALLY_APPROVED_REFERENCE", rights="LOCALLY_APPROVED_REFERENCE",
            authority_reference=approval["authority_reference"], rights_reference=approval["rights_reference"],
            publisher_id=result.publisher_id, key_id=result.key_id,
            signed_artifact_digest=result.signed_artifact_digest,
            independent_authority_established=False, independent_rights_established=False)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("CONTEXT_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _facts(record):
    fields = ("provider", "source_id", "source_name", "source_url",
        "source_record_ref", "published_at", "event_at", "instrument_identity", "original_ref",
        "title", "summary", "interpretation", "correction", "retracted", "source_conflict")
    if any(field not in record for field in fields):
        _fail("CONTEXT_RECORD_INTEGRITY_FAILURE")
    return {field: record[field] for field in fields}


def _reasons(record, as_of, max_age_seconds):
    reasons = []
    for field in ("published_at", "event_at", "collected_at"):
        value = record.get(field)
        if value is None:
            reasons.append("CONTEXT_" + field.upper() + "_MISSING")
        elif _time(value, field) > as_of:
            reasons.append("CONTEXT_NOT_AVAILABLE_AS_OF")
    if record.get("published_at") and (as_of - _time(record["published_at"], "published_at")).total_seconds() > max_age_seconds:
        reasons.append("CONTEXT_STALE")
    if record.get("retracted"):
        reasons.append("CONTEXT_RETRACTED")
    if record.get("conflict"):
        reasons.append("CONTEXT_CONFLICTING")
    verification = record.get("verification", {})
    if verification.get("allowed") is not True or verification.get("status") != "QUALIFIED_UNDER_LOCAL_POLICY":
        reasons.append(verification.get("reason_code", "CONTEXT_SOURCE_UNVERIFIED"))
    return sorted(set(reasons))


def parse_context_bytes(raw_bytes, *, provider, collected_at, trusted_identities, source_policy=None):
    """Parse an explicit offline JSON import. Missing timestamps remain missing."""
    if not isinstance(raw_bytes, bytes) or not 0 < len(raw_bytes) <= MAX_BYTES:
        _fail("CONTEXT_PAYLOAD_SIZE_LIMIT")
    provider = _text(provider, "provider", 64)
    if not re.fullmatch(r"[a-z][a-z0-9_\-]{0,63}", provider):
        _fail("CONTEXT_INVALID_PROVIDER")
    collected = _time(collected_at, "collected_at")
    trusted = _trusted_identities(trusted_identities)
    if source_policy is not None and not isinstance(source_policy, ContextSourcePolicy):
        _fail("CONTEXT_INVALID_SOURCE_POLICY")
    try:
        payload = json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=_object,
            parse_constant=lambda _: _fail("CONTEXT_NONFINITE_JSON"))
        encoded(payload)  # Also rejects exponent overflow (e.g. 1e999) in ignored fields.
        if not isinstance(payload, dict) or payload.get("schema_version", SOURCE_SCHEMA) != SOURCE_SCHEMA:
            _fail("CONTEXT_UNSUPPORTED_SCHEMA")
        rows = payload.get("records")
        if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
            _fail("CONTEXT_RECORD_LIMIT")
        records = []
        for row in rows:
            if not isinstance(row, dict):
                _fail("CONTEXT_INVALID_RECORD")
            key = _identity_key(row.get("instrument_identity"))
            matched = key in trusted
            identity = copy.deepcopy(trusted[key] if matched else row["instrument_identity"])
            record = dict(provider=provider, instrument_identity=identity, collected_at=collected.isoformat())
            for field, limit in (("source_id", 128), ("source_name", 256), ("source_record_ref", 1024),
                                 ("title", 1024), ("summary", 8192)):
                record[field] = _text(row.get(field), field, limit, optional=field in ("title", "summary"))
            record["source_url"] = safe_source_url(row.get("source_url"))
            record["original_ref"] = _text(row.get("original_ref"), "original_ref", 2048, optional=True)
            if record["original_ref"] and re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", record["original_ref"]):
                record["original_ref"] = safe_source_url(record["original_ref"])
            for field in ("published_at", "event_at"):
                timestamp = _time(row.get(field), field, optional=True)
                if timestamp and timestamp > collected:
                    _fail("CONTEXT_TIMESTAMP_AFTER_COLLECTION")
                record[field] = timestamp.isoformat() if timestamp else None
            for field in ("retracted", "conflict"):
                if type(row.get(field, False)) is not bool:
                    _fail("CONTEXT_INVALID_" + field.upper())
                record[field] = row.get(field, False)
            record["source_conflict"] = record["conflict"]
            record["correction"] = _text(row.get("correction"), "correction", 1024, optional=True)
            interpretation = row.get("interpretation")
            if interpretation is not None:
                if not isinstance(interpretation, dict):
                    _fail("CONTEXT_INVALID_INTERPRETATION")
                interpretation = dict(rule_id=_text(interpretation.get("rule_id"), "rule_id", 128),
                    text=_text(interpretation.get("text"), "interpretation", 2048),
                    status="SOURCE_SUPPLIED_UNVALIDATED_INTERPRETATION")
            record["interpretation"] = interpretation
            record["record_id"] = digest([provider, record["source_id"], record["source_record_ref"], key])
            record["content_id"] = digest(_facts(record))
            record["verification"] = (source_policy.qualify(record, raw_bytes, collected) if source_policy else
                dict(status="NOT_ESTABLISHED", allowed=False, reason_code="CONTEXT_SOURCE_UNVERIFIED",
                     authority="NOT_ESTABLISHED", rights="NOT_ESTABLISHED"))
            if not matched:
                record["verification"] = dict(status="NOT_ESTABLISHED", allowed=False,
                    reason_code="CONTEXT_MAPPING_UNAVAILABLE", authority="NOT_ESTABLISHED", rights="NOT_ESTABLISHED")
            records.append(record)
    except ContextValidationError:
        raise
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        _fail("CONTEXT_MALFORMED_PAYLOAD")
    distinct = {(r["record_id"], r["content_id"]): r for r in records}
    records = [distinct[key] for key in sorted(distinct)]
    counts = {}
    for record in records:
        counts.setdefault(record["record_id"], set()).add(record["content_id"])
    all_reasons = set()
    for record in records:
        if len(counts[record["record_id"]]) > 1:
            record["conflict"] = True
        reasons = _reasons(record, collected, 86400)
        record["freshness"] = dict(as_of=collected.isoformat(), status="STALE" if "CONTEXT_STALE" in reasons else
            "UNAVAILABLE" if any("MISSING" in reason for reason in reasons) else "FRESH")
        record["reason_codes"] = reasons
        record["status"] = "QUALIFIED" if not reasons else "WARNING_ONLY"
        all_reasons.update(reasons)
    original = hashlib.sha256(raw_bytes).hexdigest()
    policy_id = source_policy.policy_id if source_policy else "NO_POLICY"
    mapping_id = digest([trusted[key] for key in sorted(trusted)])
    return dict(schema_version=INGESTION_SCHEMA,
        ingestion_id=digest(["context-ingestion-v1", provider, collected.isoformat(), original, policy_id, mapping_id]),
        policy_id=policy_id, mapping_id=mapping_id,
        provider=provider, collected_at=collected.isoformat(), records=records,
        status="MISSING" if not records else "QUALIFIED" if not all_reasons else "WARNING_ONLY",
        reason_codes=sorted(all_reasons) if records else ["CONTEXT_MISSING"], original_sha256=original)


def context_for_candidate(records, candidate, *, as_of, max_age_seconds=86400):
    """Read a separate context overlay; never mutate or qualify a candidate."""
    reference = _time(as_of, "as_of")
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 31 * 86400:
        _fail("CONTEXT_INVALID_MAX_AGE")
    if not isinstance(records, list) or len(records) > MAX_MATCH_RECORDS or not isinstance(candidate, dict):
        _fail("CONTEXT_INVALID_MATCH_INPUT")
    candidate_id = _text(candidate.get("candidate_id"), "candidate_id", 512)
    result = dict(schema_version=CONTEXT_SCHEMA, candidate_id=candidate_id, status="MISSING",
        reason_codes=["CONTEXT_MISSING"], records=[], actionable=False, affects_ranking=False)
    source_reference = candidate.get("source_reference")
    identity = source_reference.get("instrument_identity") if isinstance(source_reference, dict) else None
    if not identity:
        identity = candidate.get("instrument_identity")
    if not identity:
        return dict(result, status="UNAVAILABLE", reason_codes=["CONTEXT_CANDIDATE_IDENTITY_MISSING"])
    key = _identity_key(identity)
    distinct = {}
    unavailable = set()
    for row in records:
        if not isinstance(row, dict):
            _fail("CONTEXT_INVALID_RECORD")
        if _identity_key(row.get("instrument_identity")) != key:
            continue
        record = copy.deepcopy(row)
        facts = _facts(record)
        # Conflict detected across imports is derived metadata, not a new source fact.
        logical = digest([record["provider"], record["source_id"], record["source_record_ref"], key])
        if digest(facts) != record.get("content_id") or logical != record.get("record_id"):
            _fail("CONTEXT_RECORD_INTEGRITY_FAILURE")
        reasons = _reasons(record, reference, max_age_seconds)
        if "CONTEXT_NOT_AVAILABLE_AS_OF" in reasons:
            unavailable.add("CONTEXT_NOT_AVAILABLE_AS_OF")
            continue  # Future source content is never disclosed in a historical view.
        record_key = (record["record_id"], record["content_id"])
        old = distinct.get(record_key)
        def order(value):
            return (value.get("verification", {}).get("allowed") is True,
                    value["collected_at"], encoded(value))
        if old is None or order(record) < order(old):
            distinct[record_key] = record
    selected = [distinct[key] for key in sorted(distinct)]
    by_logical = {}
    for row in selected:
        by_logical.setdefault(row["record_id"], set()).add(row["content_id"])
    reasons = set(unavailable)
    for row in selected:
        if len(by_logical[row["record_id"]]) > 1:
            row["conflict"] = True
        row["reason_codes"] = _reasons(row, reference, max_age_seconds)
        row["status"] = "QUALIFIED" if not row["reason_codes"] else "WARNING_ONLY"
        row["freshness"] = dict(as_of=reference.isoformat(), status="STALE" if "CONTEXT_STALE" in row["reason_codes"]
            else "UNAVAILABLE" if any("MISSING" in reason for reason in row["reason_codes"]) else "FRESH")
        reasons.update(row["reason_codes"])
    if not selected:
        return dict(result, status="UNAVAILABLE" if unavailable else "MISSING",
            reason_codes=sorted(unavailable) or ["CONTEXT_MISSING"])
    return dict(result, status="QUALIFIED" if not reasons else "WARNING_ONLY",
        reason_codes=sorted(reasons), records=selected)


def validate_ingestion(ingestion, raw_bytes, *, trusted_identities, source_policy=None):
    """Reparse the entire retained envelope against external mapping and policy.

    A qualified receipt cannot re-establish its own source policy after restart.
    Absence of the original operator policy fails closed.
    """
    if not isinstance(ingestion, dict) or ingestion.get("schema_version") != INGESTION_SCHEMA:
        _fail("CONTEXT_INGESTION_INTEGRITY_FAILURE")
    try:
        parsed = parse_context_bytes(raw_bytes, provider=ingestion["provider"],
            collected_at=ingestion["collected_at"], trusted_identities=trusted_identities, source_policy=source_policy)
        policy_id = ingestion["policy_id"]
        if policy_id != "NO_POLICY" and not re.fullmatch(r"[0-9a-f]{64}", policy_id):
            raise ValueError()
        expected = digest(["context-ingestion-v1", ingestion["provider"], parsed["collected_at"],
                           parsed["original_sha256"], policy_id, parsed["mapping_id"]])
        if (expected != ingestion["ingestion_id"] or parsed["original_sha256"] != ingestion["original_sha256"]
                or parsed["collected_at"] != ingestion["collected_at"] or parsed["mapping_id"] != ingestion["mapping_id"]):
            raise ValueError()
        if parsed != ingestion:
            raise ValueError()
    except (ValueError, KeyError, TypeError, RecursionError):
        _fail("CONTEXT_INGESTION_INTEGRITY_FAILURE")
    return True

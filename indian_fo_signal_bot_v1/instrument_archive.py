"""Offline instrument-master archives. Content integrity never confers authenticity.

V1 intervals are source declarations, not independently authenticated provider facts.
Legacy envelopes and undated Angel snapshots are retained but cannot authorize replay.
There is deliberately no downloader, signature claim, active-cache replacement or
automatic supersession. Local database writers remain inside the trust boundary.
"""
import argparse
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

from instrument_identity import (IdentityValidationError, canonical_symbol, dated_identity,
                                 digest, positive_integer, reject, PROVIDERS, INDICES)

SCHEMA = "tradepulse.instrument-master.v1"
PARSER_VERSION = "instrument-archive-v1"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
LIMITATION = "Source and effective dates are supplied declarations; publisher authenticity has not been independently established."


def aware_timestamp(value, field):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed.isoformat()
    except (ValueError, TypeError):
        reject("INVALID_ARCHIVE_TIMESTAMP", f"{field} requires an ISO timestamp with an explicit timezone.")


def iso_date(value, field):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
        return value
    except (ValueError, TypeError):
        reject("INVALID_EFFECTIVE_DATE", f"{field} requires YYYY-MM-DD.")


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            reject("INVALID_ARCHIVE_SCHEMA", "Duplicate JSON object keys are ambiguous.")
        result[key] = value
    return result


def _record(raw, provider):
    if not isinstance(raw, dict):
        reject("INVALID_ARCHIVE_SCHEMA", "Every master record must be an object.")
    required = ("symbol", "identifier", "exchange", "instrument_type", "multiplier")
    if any(k not in raw for k in required):
        reject("INCOMPLETE_ARCHIVE_IDENTITY", "Master record is missing required identity fields.")
    if raw.get("provider", provider) != provider or raw.get("data_mode", "LIVE") != "LIVE" or raw.get("is_simulated", False):
        reject("ARCHIVE_PROVIDER_MISMATCH", "Provider/simulation provenance conflicts with this archive.")
    symbol = canonical_symbol(raw["symbol"])
    token = raw["identifier"]
    kind = raw["instrument_type"]
    if not isinstance(token, str) or not token.strip() or token != token.strip():
        reject("INVALID_ARCHIVE_IDENTITY", "An explicit provider identifier is required.")
    if kind not in ("EQ", "INDEX_SPOT", "FUTIDX", "OPTIDX"):
        reject("UNSUPPORTED_ARCHIVE_INSTRUMENT", "Archive supports NSE equities, indices and explicit index contracts only.")
    index = kind != "EQ"
    exchange = "NFO" if kind in ("FUTIDX", "OPTIDX") else "NSE"
    segment = "NSE_FO_INDEX" if index else "NSE_EQUITY_INTRADAY"
    if (raw["exchange"] != exchange or raw.get("segment", segment) != segment
            or (index and symbol not in INDICES) or (not index and symbol in INDICES)):
        reject("ARCHIVE_SEGMENT_MISMATCH", "Symbol, exchange, segment and instrument type disagree.")
    if "is_index" in raw and (not isinstance(raw["is_index"], bool) or raw["is_index"] != (kind == "INDEX_SPOT")):
        reject("ARCHIVE_SEGMENT_MISMATCH", "Index classification conflicts with instrument type.")
    wire = "IDX_I" if kind == "INDEX_SPOT" else "NSE_EQ" if kind == "EQ" else "NSE_FNO"
    if raw.get("exchange_segment", wire) != wire or raw.get("exch_seg", exchange) != exchange:
        reject("ARCHIVE_SEGMENT_MISMATCH", "Provider exchange segment conflicts with normalized identity.")
    token_keys = {"angelone": ("angel_token",), "dhan": ("security_id", "dhan_id", "dhan_security_id"),
                  "upstox": ("upstox_key", "instrument_key")}[provider]
    if any(str(raw[k]) != token for k in token_keys if k in raw):
        reject("ARCHIVE_IDENTITY_MISMATCH", "Provider-specific token conflicts with normalized identifier.")
    if kind == "FUTIDX" and any(raw.get(k) is not None for k in ("strike", "option_type")):
        reject("ARCHIVE_CONTRACT_MISMATCH", "A futures record cannot carry option strike/side metadata.")
    field = {"angelone": "angel_token", "dhan": "dhan_security_id", "upstox": "upstox_key"}[provider]
    if kind in ("FUTIDX", "OPTIDX") and token in {str(r[field]) for r in INDICES.values()}:
        reject("ARCHIVE_CONTRACT_MISMATCH", "A pinned index-spot identifier cannot identify an executable derivative.")
    if isinstance(raw["multiplier"], bool) or raw["multiplier"] != 1:
        reject("UNSUPPORTED_MULTIPLIER", "Only explicit unit multipliers are supported.")
    result = dict(provider=provider, symbol=symbol, identifier=token, exchange=exchange,
                  segment=segment, instrument_type=kind, multiplier=1)
    for key in ("valid_from", "valid_to"):
        result[key] = iso_date(raw[key], key) if raw.get(key) is not None else None
    if bool(result["valid_from"]) != bool(result["valid_to"]):
        reject("INVALID_EFFECTIVE_DATE", "Both validity interval boundaries must be supplied together.")
    if result["valid_from"] and result["valid_to"] < result["valid_from"]:
        reject("INVALID_EFFECTIVE_DATE", "Effective interval is reversed.")
    if "lot_size" in raw:
        result["lot_size"] = positive_integer(raw["lot_size"], "lot_size")
        if kind == "EQ" and result["lot_size"] != 1:
            reject("INVALID_CONTRACT_QUANTITY", "Cash equities require unit shares.")
    if kind in ("FUTIDX", "OPTIDX"):
        if raw.get("underlying") != symbol or "lot_size" not in result:
            reject("INCOMPLETE_ARCHIVE_CONTRACT", "Index contracts require matching underlying and explicit lot size.")
        result.update(underlying=symbol, expiry=iso_date(raw.get("expiry"), "expiry"))
        if result["valid_to"] and result["expiry"] < result["valid_to"]:
            reject("INVALID_EFFECTIVE_DATE", "Contract validity cannot extend beyond its expiry.")
        if kind == "OPTIDX":
            strike = raw.get("strike")
            if (isinstance(strike, bool) or not isinstance(strike, (int, float))
                    or not math.isfinite(strike) or strike <= 0 or raw.get("option_type") not in ("CE", "PE")):
                reject("INVALID_ARCHIVE_CONTRACT", "Options require a finite positive strike and CE/PE side.")
            result.update(strike=strike, option_type=raw["option_type"])
    elif any(raw.get(k) is not None for k in ("underlying", "expiry", "strike", "option_type")):
        reject("ARCHIVE_CONTRACT_MISMATCH", "Spot/equity records cannot carry derivative contract fields.")
    if "trading_symbol" in raw:
        if not isinstance(raw["trading_symbol"], str) or not raw["trading_symbol"].strip():
            reject("INVALID_ARCHIVE_IDENTITY", "Trading symbol must be nonempty when supplied.")
        result["trading_symbol"] = raw["trading_symbol"]
        if kind in ("EQ", "INDEX_SPOT") and canonical_symbol(raw["trading_symbol"]) != symbol:
            reject("ARCHIVE_CONTRACT_MISMATCH", "Trading symbol disagrees with canonical symbol.")
        if kind == "OPTIDX":
            expiry = date.fromisoformat(result["expiry"])
            # Existing Angel master symbol formats, not an invented expiry calendar.
            if provider == "angelone":
                labels = [f"{symbol}{expiry.strftime(fmt).upper()}{result['strike']:g}{result['option_type']}"
                          for fmt in ("%d%b%Y", "%d%b%y")]
                if result["trading_symbol"] not in labels:
                    reject("ARCHIVE_CONTRACT_MISMATCH", "Option symbol disagrees with contract fields.")
    return result


def _contract_key(record):
    return tuple(record.get(k) for k in ("symbol", "exchange", "instrument_type", "expiry", "strike", "option_type"))


def _overlap(left, right):
    return (not left["valid_from"] or not right["valid_from"]
            or max(left["valid_from"], right["valid_from"]) <= min(left["valid_to"], right["valid_to"]))


def local_ingestion_timestamp():
    return datetime.now(timezone.utc).isoformat()


def prepare_archive(raw_bytes, provider, original_filename, source_reference, *,
                    captured_at=None, publisher_published_at=None, source_url=None, ingested_at=None,
                    input_kind="SUPPLIED_BYTES"):
    """Return an auditable candidate, including rejected bytes; never activate a partial file."""
    if provider not in PROVIDERS:
        reject("UNSUPPORTED_ARCHIVE_PROVIDER", "Unknown archive provider.")
    if (not isinstance(original_filename, str) or not original_filename or original_filename in (".", "..")
            or any(c in original_filename for c in '/\\:\x00') or original_filename.rstrip(' .') != original_filename):
        reject("UNSAFE_ARCHIVE_FILENAME", "Original filename must be a plain basename.")
    if not isinstance(raw_bytes, bytes) or len(raw_bytes) > MAX_ARCHIVE_BYTES:
        reject("INVALID_ARCHIVE_SIZE", "Archive must contain at most 64 MiB of original bytes.")
    if not isinstance(source_reference, str) or not source_reference.strip():
        reject("MISSING_ARCHIVE_PROVENANCE", "An explicit source description is required.")
    if input_kind not in ("SUPPLIED_BYTES", "LOCAL_FILE", "INLINE_SERIALIZATION"):
        reject("INVALID_ARCHIVE_PROVENANCE", "Unknown archive input origin.")
    metadata = dict(provider=provider, original_filename=original_filename,
                    format="JSON" if original_filename.lower().endswith(".json") else "UNSUPPORTED",
                    input_kind=input_kind, schema_version=None, source_type="USER_SUPPLIED_FILE",
                    effective_date_basis="UNKNOWN",
                    source_reference=source_reference, source_url=source_url,
                    captured_at=aware_timestamp(captured_at, "captured_at"),
                    publisher_published_at=aware_timestamp(publisher_published_at, "publisher_published_at"),
                    parser_version=PARSER_VERSION, publisher_authenticity="NOT_ESTABLISHED",
                    provenance_limitation=LIMITATION, original_sha256=hashlib.sha256(raw_bytes).hexdigest())
    if source_url is not None and (not isinstance(source_url, str) or not source_url.startswith("https://")):
        reject("INVALID_ARCHIVE_PROVENANCE", "Source URL must be an HTTPS description; it is never fetched.")
    candidate = dict(metadata=metadata, records=[], status="REJECTED", validation=None,
                     input_record_count=0, record_count=0, normalized_sha256=digest([]),
                     ingested_at=aware_timestamp(ingested_at or local_ingestion_timestamp(), "ingested_at"))
    try:
        if not original_filename.lower().endswith(".json"):
            reject("UNSUPPORTED_ARCHIVE_FORMAT", "Only local JSON archives are supported.")
        try:
            payload = json.loads(raw_bytes.decode("utf-8-sig"), object_pairs_hook=_strict_object,
                                 parse_constant=lambda _: reject("INVALID_ARCHIVE_SCHEMA", "Nonfinite JSON values are unsupported."))
        except (UnicodeError, ValueError, RecursionError) as exc:
            if isinstance(exc, IdentityValidationError):
                raise
            reject("INVALID_ARCHIVE_FORMAT", "Archive must be complete UTF-8 JSON.")
        if isinstance(payload, dict) and payload.get("schema_version") == SCHEMA:
            if payload.get("provider") != provider:
                reject("ARCHIVE_PROVIDER_MISMATCH", "Archive provider differs from the import provider.")
            if payload.get("data_mode", "LIVE") != "LIVE" or payload.get("is_simulated", False):
                reject("ARCHIVE_PROVIDER_MISMATCH", "A simulated archive cannot authorize live-provider history.")
            records = payload.get("records")
            metadata.update(schema_version=SCHEMA, source_type="USER_SUPPLIED_ARCHIVE", effective_date_basis="SOURCE_DECLARED_INTERVALS")
        elif isinstance(payload, dict) and payload.get("source") == "ARCHIVED_PROVIDER_MASTER":
            records = payload.get("records")
            metadata.update(schema_version="LEGACY_ENVELOPE", source_type="LEGACY_UNKNOWN", effective_date_basis="UNKNOWN")
            if not isinstance(records, list) or payload.get("sha256") != digest(records):
                reject("INVALID_LEGACY_DIGEST", "Legacy normalized-content digest is inconsistent.")
        elif isinstance(payload, list) and provider == "angelone":
            # Reuse the existing native Angel parser, with strict validation and no I/O.
            from brokers import AngelOneSmartAPIAdapter, BrokerDataError
            from config import BotConfig
            seen = set()
            for item in payload:
                if not isinstance(item, dict):
                    reject("INVALID_ARCHIVE_SCHEMA", "Native master rows must be objects.")
                key = (item.get("exch_seg"), str(item.get("token")))
                if key in seen:
                    reject("DUPLICATE_ARCHIVE_TOKEN", "Native master contains duplicate exchange/token assignments.")
                seen.add(key)
            adapter = AngelOneSmartAPIAdapter.__new__(AngelOneSmartAPIAdapter)
            adapter.config = BotConfig(angel_scrip_master_path="")
            try:
                equities, indices, options, _ = adapter._parse_and_validate_scrip_master_records(payload, strict=True)
            except BrokerDataError:
                reject("INVALID_NATIVE_MASTER", "Native Angel master failed existing instrument validation.")
            records = [dict(symbol=r["symbol"], identifier=r["angel_token"], exchange="NSE",
                            instrument_type="EQ" if r["symbol"] in equities else "INDEX_SPOT", multiplier=1,
                            trading_symbol=r["trading_symbol"]) for r in list(equities.values()) + list(indices.values())]
            records += [dict(r["instrument_identity"], symbol=r["index_symbol"], trading_symbol=r["symbol"])
                        for r in options]
            metadata.update(schema_version="ANGEL_NATIVE_JSON", source_type="USER_SUPPLIED_ANGEL_SNAPSHOT", effective_date_basis="UNKNOWN")
            candidate["input_record_count"] = len(payload)
        else:
            reject("UNSUPPORTED_ARCHIVE_SCHEMA", "Expected V1 normalized archive, legacy envelope or native Angel JSON list.")
        if not isinstance(records, list) or not records:
            reject("EMPTY_ARCHIVE", "Archive must contain a nonempty records list.")
        candidate["input_record_count"] = candidate["input_record_count"] or len(records)
        normalized = [_record(r, provider) for r in records]
        by_token, by_contract = {}, {}
        for record in normalized:
            token = (record["exchange"], record["identifier"])
            if token in by_token:
                reject("DUPLICATE_ARCHIVE_TOKEN", "Duplicate exchange/token assignment in one snapshot.")
            key = _contract_key(record)
            if key in by_contract and _overlap(by_contract[key], record):
                reject("AMBIGUOUS_ARCHIVE_IDENTITY", "Overlapping identity has conflicting token assignments.")
            by_token[token], by_contract[key] = record, record
        normalized.sort(key=lambda r: json.dumps(r, sort_keys=True))
        eligible = metadata["effective_date_basis"] == "SOURCE_DECLARED_INTERVALS" and all(r["valid_from"] for r in normalized)
        if metadata["effective_date_basis"] == "SOURCE_DECLARED_INTERVALS" and not eligible:
            metadata["effective_date_basis"] = "INCOMPLETE_SOURCE_DECLARATION"
        candidate.update(records=normalized, record_count=len(normalized), normalized_sha256=digest(normalized),
                         status="ELIGIBLE_LOCAL_RESEARCH" if eligible else "INCOMPLETE",
                         validation=dict(reason_code="SOURCE_DECLARED_COVERAGE" if eligible else "HISTORICAL_APPLICABILITY_UNKNOWN"))
    except IdentityValidationError as exc:
        candidate["validation"] = exc.rejection
    # Ingestion time is observational; it must not change archive identity/idempotence.
    candidate["archive_id"] = digest(dict(metadata=metadata, normalized_sha256=candidate["normalized_sha256"],
                                         status=candidate["status"], validation=candidate["validation"]))
    return candidate


def resolve_archive_declarations(archives, provider, symbol, identifier, exchange, instrument_type,
                     first_date, last_date, lot_size=None, archive_id=None):
    """Fail closed on any conflicting claim touching the period, including partial overlaps."""
    first_date, last_date = iso_date(first_date, "first_date"), iso_date(last_date, "last_date")
    if first_date > last_date:
        reject("INVALID_EFFECTIVE_DATE", "Requested date range is reversed.")
    if provider not in PROVIDERS:
        reject("UNSUPPORTED_ARCHIVE_PROVIDER", "Unknown historical archive provider.")
    relevant = [(a, r) for a in archives if a["metadata"]["provider"] == provider and a["status"] == "ELIGIBLE_LOCAL_RESEARCH"
                for r in a["records"] if r["valid_from"] <= last_date and r["valid_to"] >= first_date]
    requested_contracts = {_contract_key(r) for _, r in relevant if r["exchange"] == exchange and r["identifier"] == identifier}
    applicable = []
    for archive in archives:
        if archive["metadata"]["provider"] != provider or archive["status"] != "ELIGIBLE_LOCAL_RESEARCH":
            continue
        for record in archive["records"]:
            if record["valid_from"] > last_date or record["valid_to"] < first_date:
                continue
            same_token = record["exchange"] == exchange and record["identifier"] == identifier
            same_cash = instrument_type == "EQ" and record["instrument_type"] == "EQ" and record["symbol"] == symbol
            if same_token or same_cash or _contract_key(record) in requested_contracts:
                applicable.append((archive, record))
    # Claims with identical instrument facts can coexist; timestamps/newness never decide.
    facts = {digest({k: v for k, v in r.items() if k not in ("valid_from", "valid_to")}) for _, r in applicable}
    if len(facts) > 1:
        reject("AMBIGUOUS_ARCHIVE_COVERAGE", "Conflicting archived identity claims overlap the requested dates.")
    covered = [(a, r) for a, r in applicable if r["valid_from"] <= first_date and r["valid_to"] >= last_date
               and (archive_id is None or a["archive_id"] == archive_id)]
    if not covered:
        reject("HISTORICAL_ARCHIVE_COVERAGE_MISSING" if archives else "HISTORICAL_IDENTITY_UNVERIFIED", "No eligible archive covers the entire dataset; capture time and legacy dates cannot establish coverage.")
    archive, record = min(covered, key=lambda pair: pair[0]["archive_id"])
    envelope = dict(source="ARCHIVED_PROVIDER_MASTER", source_reference=archive["metadata"]["source_reference"],
                    records=[record], sha256=digest([record]))
    identity = dated_identity(envelope, symbol, provider, identifier, exchange, instrument_type, first_date, last_date, lot_size)
    identity.update(archive_id=archive["archive_id"], original_sha256=archive["metadata"]["original_sha256"],
                    normalized_sha256=archive["normalized_sha256"], archive_provenance=archive["metadata"],
                    historical_validity="SOURCE_DECLARED_ARCHIVE_COVERAGE",
                    supporting_archive_ids=sorted({a["archive_id"] for a, _ in applicable}))
    return identity


def resolve_archives(archives, provider, symbol, identifier, exchange, instrument_type,
                     first_date, last_date, lot_size=None, archive_id=None,
                     trust_config=None, verification_time=None):
    """LIVE resolver: coverage and instrument consistency cannot replace source qualification."""
    identity = resolve_archive_declarations(archives, provider, symbol, identifier, exchange, instrument_type,
                                            first_date, last_date, lot_size, archive_id)
    archive = next(a for a in archives if a["archive_id"] == identity["archive_id"])
    from source_qualification import assess_source_evidence
    assessment = assess_source_evidence(
        archive,
        archive.get("original_bytes"),
        trust_config=trust_config,
        verification_time=verification_time,
    )
    if not assessment["historical_eligibility"]["allowed"]:
        error = IdentityValidationError(
            "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT",
            "Archive integrity and declared intervals do not establish publisher authenticity or effective-date authority.",
        )
        error.rejection["source_qualification"] = assessment
        error.rejection["required_evidence"] = [
            "Independent archive-to-publisher source binding/authentication",
            "Authoritative instrument-specific historical effective intervals",
            "A supported verifier for that evidence",
        ]
        raise error
    identity["source_qualification"] = assessment
    identity["historical_validity"] = "PUBLISHER_TRUST_VERIFIED"
    identity["live_historical_eligible"] = True
    return identity


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline archived instrument-master ingestion and inspection.")
    parser.add_argument("--database", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("path")
    ingest.add_argument("--provider", choices=PROVIDERS, required=True)
    ingest.add_argument("--source-reference", required=True)
    ingest.add_argument("--import-root", default=".")
    ingest.add_argument("--captured-at")
    ingest.add_argument("--published-at")
    ingest.add_argument("--source-url")
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("archive_id")
    qualify = sub.add_parser("qualify", help="Assess source evidence; declarations cannot grant qualification.")
    qualify.add_argument("archive_id")
    args = parser.parse_args(argv)
    from storage import SQLitePersistenceStore
    try:
        with SQLitePersistenceStore(args.database) as store:
            if args.command == "ingest":
                result = store.ingest_instrument_master_file(args.path, args.provider, args.source_reference,
                    import_root=args.import_root, captured_at=args.captured_at,
                    publisher_published_at=args.published_at, source_url=args.source_url)
            elif args.command == "qualify":
                result = store.qualify_instrument_master_archive(args.archive_id)
            elif args.command == "list":
                result = [dict(a, source_qualification=store.qualify_instrument_master_archive(a["archive_id"]))
                          for a in store.list_instrument_master_archives()]
            else:
                result = store.get_instrument_master_archive(args.archive_id)
            if args.command in ("ingest", "show"):
                result = dict(result, source_qualification=store.qualify_instrument_master_archive(result["archive_id"]))
            print(json.dumps(result, sort_keys=True))
            if args.command == "qualify":
                return 0 if result["historical_eligibility"]["allowed"] else 1
            return 1 if isinstance(result, dict) and result.get("status") == "REJECTED" else 0
    except (IdentityValidationError, OSError) as exc:
        print(json.dumps(dict(status="error", rejection=getattr(exc, "rejection", {"reason_code": "ARCHIVE_FILE_ERROR"}))))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

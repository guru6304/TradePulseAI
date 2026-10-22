"""Archive evidence assessment, independent of structural validation and declarations.

An explicit publisher signature verifier is available; real operator trust roots and
independently authorized publisher artifacts are not supplied. Provider documentation establishes documentation
scope, never the origin/applicability of submitted bytes. No caller flag, URL,
filename, certificate-shaped object or saved assessment can confer those properties.

Phase 4A: PublisherTrustVerifier is integrated into assess_source_evidence.  When an
archive metadata field ``publisher_manifest_json`` is present, the verifier runs using
a locally-controlled trust configuration supplied by the operator.  Without authentic
trust anchors and signed manifests the result remains NOT_ESTABLISHED/BLOCKED.  The
integration is fail-closed: no positive verdict can be reached without a valid Ed25519
signature from a trusted, in-date, non-revoked key.
"""
import hashlib
import json

from instrument_identity import digest
from publisher_trust import (
    PublisherTrustVerifier,
    REASON_VERIFIER_UNAVAILABLE,
    TRUST_POLICY_VERSION as _TRUST_POLICY_VERSION,
)


POLICY_VERSION = "historical-source-evidence-v1"
DOCUMENTATION_REVIEW_DATE = "2026-10-18"
SOURCE_DOCUMENTATION = {
    "angelone": {
        "references": ["https://smartapi.angelone.in/docs"],
        "status": "ARCHIVE_SOURCE_NOT_INDEPENDENTLY_ASSESSED",
        "limitation": "Accessible documentation did not establish an authenticated historical master or applicable intervals.",
    },
    "dhan": {
        "references": ["https://dhanhq.co/docs/v2/instruments/"],
        "status": "PROVIDER_DOCUMENTATION_REVIEWED",
        "limitation": "Documentation lists instrument CSV sources; it does not bind an imported file or establish its historical intervals.",
    },
    "upstox": {
        "references": ["https://upstox.com/developer/api-documentation/instruments/",
                       "https://upstox.com/developer/api-documentation/get-expired-future-contracts/"],
        "status": "PROVIDER_DOCUMENTATION_REVIEWED",
        "limitation": "BOD files and expired-contract APIs are documented; no local file capture, authenticated response or historical interval is established here.",
    },
}


def assess_source_evidence(archive, original_bytes, trust_config=None, verification_time=None):
    """Assess established facts separately from retained user claims; performs no I/O.

    Storage additionally reparses original bytes and validates the immutable archive
    ID before invoking this policy. Content hashes are not publisher authentication.

    Phase 4A addition: when ``trust_config`` (a TrustAnchorConfig) is supplied and
    the archive metadata contains a ``publisher_manifest_json`` field, runs
    PublisherTrustVerifier and surfaces its structured result. Without authentic
    trust anchors and a signed manifest the result remains NOT_ESTABLISHED.
    The verifier is fail-closed: a positive allowed=True result requires a valid
    Ed25519 signature from a trusted, in-date, non-revoked key whose scope matches
    the archive provider. Synthetic test keys must never appear in trust_config at
    production call sites.
    """
    metadata = archive["metadata"]
    integrity = (isinstance(original_bytes, bytes)
                 and hashlib.sha256(original_bytes).hexdigest() == metadata["original_sha256"]
                 and digest(archive["records"]) == archive["normalized_sha256"])
    if integrity:
        # A caller-rehashed normalized object cannot replace the signed originals.
        from instrument_archive import prepare_archive
        parsed = prepare_archive(original_bytes, metadata["provider"], metadata["original_filename"],
            metadata["source_reference"], captured_at=metadata["captured_at"],
            publisher_published_at=metadata["publisher_published_at"], source_url=metadata["source_url"],
            input_kind=metadata["input_kind"])
        integrity = (parsed["archive_id"]==archive["archive_id"] and parsed["records"]==archive["records"]
                     and parsed["normalized_sha256"]==archive["normalized_sha256"])
    payload = None
    try:
        payload = json.loads(original_bytes.decode("utf-8-sig"))
    except (ValueError, UnicodeError, AttributeError, RecursionError):
        pass
    declared_synthetic = isinstance(payload, dict) and (
        payload.get("is_simulated") is True or payload.get("data_mode") == "SIMULATED"
        or payload.get("evidence_class") == "SYNTHETIC_FIXTURE")
    records = payload.get("records") if isinstance(payload, dict) else None
    if isinstance(records, list):
        declared_synthetic = declared_synthetic or any(isinstance(r, dict) and (
            r.get("is_simulated") is True or r.get("data_mode") == "SIMULATED") for r in records)
    claims_present = isinstance(payload, dict) and any(k in payload for k in (
        "source_evidence", "publisher_authenticity", "source_attribution", "effective_date_evidence",
        "capture_time_evidence", "independently_supported_intervals", "qualified", "verified"))
    intervals = [dict(symbol=r["symbol"], identifier=r["identifier"], valid_from=r["valid_from"], valid_to=r["valid_to"])
                 for r in archive["records"] if r.get("valid_from") and r.get("valid_to")]

    # --- Phase 4A: publisher trust verification ---
    # The trust_config comes exclusively from the caller (operator-controlled).
    # The archive itself cannot supply or modify it.
    trust_result = None
    trust_summary: dict = {
        "status": "NOT_ATTEMPTED",
        "supported_verification_mechanisms": [],
        "trust_policy_version": _TRUST_POLICY_VERSION,
        "detail": "No trust_config supplied to assess_source_evidence.",
    }
    manifest_json = metadata.get("publisher_manifest_json")
    if trust_config is not None and manifest_json is not None and integrity:
        verifier = PublisherTrustVerifier(trust_config)
        trust_result = verifier.verify(
            manifest_json,
            original_bytes,
            verification_time=verification_time,
            required_scope={"provider": metadata["provider"],
                "exchange": next(iter({r["exchange"] for r in archive["records"]})) if len({r["exchange"] for r in archive["records"]})==1 else "ALL",
                "market_segment": next(iter({r["segment"] for r in archive["records"]})) if len({r["segment"] for r in archive["records"]})==1 else "ALL"},
        )
        trust_summary = {
            "status": "VERIFIED" if trust_result.allowed else "REJECTED",
            "supported_verification_mechanisms": ["Ed25519"] if trust_result.allowed else [],
            "reason_code": trust_result.reason_code,
            "trust_policy_version": trust_result.trust_policy_version,
            "key_id": trust_result.key_id,
            "publisher_id": trust_result.publisher_id,
            "effective_from": trust_result.effective_from,
            "effective_until": trust_result.effective_until,
            "signed_artifact_digest": trust_result.signed_artifact_digest,
            "signature_algorithm": trust_result.signature_algorithm,
            "signed_publisher_time_claim": trust_result.signed_publisher_time_claim,
            "integrity_note": trust_result.integrity_note,
            "detail": trust_result.detail,
        }
    elif trust_config is not None and manifest_json is None:
        trust_summary = {
            "status": "NOT_ATTEMPTED",
            "supported_verification_mechanisms": [],
            "trust_policy_version": _TRUST_POLICY_VERSION,
            "detail": "No publisher_manifest_json in archive metadata; verification not possible.",
        }
    elif trust_config is not None and not integrity:
        trust_summary = {
            "status": "NOT_ATTEMPTED",
            "supported_verification_mechanisms": [],
            "trust_policy_version": _TRUST_POLICY_VERSION,
            "detail": "Content integrity check failed; trust verification skipped.",
        }

    publisher_trust_verified = trust_result is not None and trust_result.allowed
    if publisher_trust_verified:
        from datetime import datetime, time
        from strategies import IST
        start = datetime.fromisoformat(trust_result.effective_from)
        end = datetime.fromisoformat(trust_result.effective_until)
        publisher_trust_verified = all(r.get("valid_from") and r.get("valid_to") and
            start <= datetime.combine(datetime.fromisoformat(r["valid_from"]).date(), time(9,15),IST) and
            datetime.combine(datetime.fromisoformat(r["valid_to"]).date(),time(15,30),IST) <= end
            for r in archive["records"])
        if not publisher_trust_verified:
            trust_summary.update(status="REJECTED",reason_code="SIGNED_DATES_DO_NOT_COVER_RECORDS")
        signed_manifest=json.loads(manifest_json)
        symbols={r["symbol"] for r in archive["records"]}
        if (signed_manifest["artifact_type"]!="instrument-master"
                or signed_manifest["artifact_schema_version"]!=metadata["schema_version"]
                or signed_manifest["instrument_scope"]!="ALL" and signed_manifest["instrument_scope"] not in symbols
                or signed_manifest["instrument_scope"]!="ALL" and len(symbols)!=1):
            publisher_trust_verified=False
            trust_summary.update(status="REJECTED",reason_code="SIGNED_ARCHIVE_SCHEMA_OR_INSTRUMENT_SCOPE_MISMATCH")

    missing = []
    if not integrity:
        missing.append("CONTENT_INTEGRITY_NOT_ESTABLISHED")
    if declared_synthetic:
        missing.insert(0, "SYNTHETIC_DATA_IS_NOT_EXTERNAL_SOURCE_EVIDENCE")
    if not publisher_trust_verified:
        missing.append("SOURCE_ATTRIBUTION_NOT_INDEPENDENTLY_ESTABLISHED")
        missing.append("PUBLISHER_AUTHENTICITY_NOT_ESTABLISHED")
        missing.append("EFFECTIVE_DATE_AUTHORITY_NOT_ESTABLISHED")
    if archive["status"] != "ELIGIBLE_LOCAL_RESEARCH":
        missing.append("STRUCTURAL_VALIDITY_OR_DECLARED_COVERAGE_MISSING")

    # Independently supported date intervals: only from a verified trust result.
    independently_supported_intervals: list = []
    if publisher_trust_verified and trust_result is not None:
        independently_supported_intervals = [
            dict(
                effective_from=trust_result.effective_from,
                effective_until=trust_result.effective_until,
                key_id=trust_result.key_id,
                publisher_id=trust_result.publisher_id,
                authority="PUBLISHER_SIGNED_CLAIM",
                note=(
                    "Publisher-signed claim; not an independently timestamp-verified fact. "
                    "Capture time, publication time and key validity are distinct."
                ),
            )
        ]

    historical_allowed = (publisher_trust_verified and integrity
                          and not declared_synthetic
                          and archive["status"] == "ELIGIBLE_LOCAL_RESEARCH")

    return {
        "policy_version": POLICY_VERSION,
        "archive_id": archive["archive_id"],
        "original_sha256": metadata["original_sha256"],
        "normalized_sha256": archive["normalized_sha256"],
        "content_integrity": {"status": "MATCHES_RECORDED_DIGESTS" if integrity else "NOT_ESTABLISHED",
                              "scope": "LOCAL_CONTENT_CONSISTENCY_ONLY"},
        "source_attribution": {"status": "UNKNOWN" if metadata["source_type"] == "LEGACY_UNKNOWN" else "USER_DECLARED",
                               "source_reference": metadata["source_reference"], "source_url": metadata["source_url"],
                               "archive_source_binding": "NOT_INDEPENDENTLY_ESTABLISHED"},
        "publisher_authenticity": {
            "status": "VERIFIED" if publisher_trust_verified else "NOT_ESTABLISHED",
            "supported_verification_mechanisms": ["Ed25519"] if publisher_trust_verified else [],
            "publisher_trust_verification": trust_summary,
        },
        "capture_time": {"status": "USER_DECLARED" if metadata["captured_at"] else "UNKNOWN",
                         "timestamp": metadata["captured_at"]},
        "publication_time": {"status": "USER_DECLARED" if metadata["publisher_published_at"] else "UNKNOWN",
                             "timestamp": metadata["publisher_published_at"]},
        "ingestion_time": {"status": "LOCALLY_RECORDED", "timestamp": archive["ingested_at"],
                           "is_capture_time_evidence": False},
        "effective_dates": {"status": "DECLARED_ONLY" if intervals else "UNKNOWN",
                            "declared_intervals": intervals,
                            "independently_supported_intervals": independently_supported_intervals},
        "artifact_classification": "DECLARED_SYNTHETIC" if declared_synthetic else "EXTERNAL_ORIGIN_UNESTABLISHED",
        "submitted_qualification_claims": "PRESENT_UNVALIDATED" if claims_present else "NOT_SUPPLIED",
        "source_documentation": dict(SOURCE_DOCUMENTATION.get(metadata["provider"], {
            "references": [], "status": "UNSUPPORTED_SOURCE", "limitation": "No assessed source documentation."}),
            review_date=DOCUMENTATION_REVIEW_DATE, scope="DOCUMENTATION_ONLY_NOT_ARCHIVE_AUTHENTICATION"),
        "historical_eligibility": {
            "allowed": historical_allowed,
            "scope": "LIVE_HISTORICAL_REPLAY",
            "reason_code": (
                "PUBLISHER_TRUST_VERIFIED_SOURCE_QUALIFIED"
                if historical_allowed
                else "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT"
            ),
            "missing_evidence": missing,
        },
    }


def verify_source_bundle_bindings(archive, original_master_bytes, original_candle_bytes, bundle, *,
                                  provider, symbol, identifier, first_date, last_date):
    """Verify local exact-byte/scope prerequisites, never grant source authority.

    This supported, reject-only bundle contract cannot select a trust key,
    authenticator or positive verdict from submitted fields. No publisher
    protocol or independent effective-date authority has been established.
    Existing archive validation must precede this audit, as for the V1 assessor.
    """
    from datetime import date
    required={'schema_version','archive_id','provider','symbol','identifier','first_date','last_date',
              'interval_min','master_original_sha256','candles_original_sha256'}
    errors=[]
    try:
        if (not isinstance(bundle,dict) or set(bundle)!=required or bundle['schema_version']!='tradepulse.source-bundle.v1'
                or type(bundle['interval_min']) is not int or bundle['interval_min']!=5):
            raise ValueError()
        if (not isinstance(original_master_bytes,bytes) or not isinstance(original_candle_bytes,bytes)
                or not original_candle_bytes or len(original_candle_bytes)>64*1024*1024):
            raise ValueError()
        if date.fromisoformat(first_date).isoformat()!=first_date or date.fromisoformat(last_date).isoformat()!=last_date or first_date>last_date:
            raise ValueError()
        expected=dict(archive_id=archive['archive_id'],provider=provider,symbol=symbol,identifier=identifier,
                      first_date=first_date,last_date=last_date,
                      master_original_sha256=hashlib.sha256(original_master_bytes).hexdigest(),
                      candles_original_sha256=hashlib.sha256(original_candle_bytes).hexdigest())
        if any(bundle.get(key)!=value for key,value in expected.items()):
            errors.append('SOURCE_BUNDLE_CONTENT_OR_SCOPE_SUBSTITUTION')
        if (archive['metadata']['provider']!=provider
                or archive['metadata']['original_sha256']!=expected['master_original_sha256']
                or digest(archive['records'])!=archive['normalized_sha256']):
            errors.append('ARCHIVE_INTEGRITY_OR_PROVIDER_MISMATCH')
        matching=[r for r in archive['records'] if r['symbol']==symbol and r['identifier']==identifier
                  and r.get('valid_from') and r['valid_from']<=first_date and r.get('valid_to') and r['valid_to']>=last_date]
        if len(matching)!=1:
            errors.append('DECLARED_INSTRUMENT_DATE_COVERAGE_MISSING_OR_AMBIGUOUS')
    except (ValueError,TypeError,KeyError,ArithmeticError):
        errors.append('INVALID_OR_UNSUPPORTED_SOURCE_BUNDLE')
    missing=['PUBLISHER_AUTHENTICITY_NOT_ESTABLISHED','EFFECTIVE_DATE_AUTHORITY_NOT_ESTABLISHED',
             'HISTORICAL_CANDLE_SOURCE_AUTHENTICITY_NOT_ESTABLISHED']
    return dict(status='REJECTED' if errors else 'BINDINGS_MATCH_AUTHORITY_BLOCKED',
                content_binding_scope='LOCAL_BYTES_AND_DECLARATIONS_ONLY',errors=sorted(set(errors)),
                supported_authenticators=[],publisher_authenticity='NOT_ESTABLISHED',
                historical_eligibility=dict(allowed=False,reason_code='HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT',
                                            missing_evidence=missing))

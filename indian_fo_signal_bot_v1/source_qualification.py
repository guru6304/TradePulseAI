"""Archive evidence assessment, independent of structural validation and declarations.

No archive authenticator or independently authoritative historical-date evidence is
available in this checkout. Public provider documentation establishes documentation
scope, never the origin/applicability of submitted bytes. No caller flag, URL,
filename, certificate-shaped object or saved assessment can confer those properties.
"""
import hashlib
import json

from instrument_identity import digest


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


def assess_source_evidence(archive, original_bytes):
    """Assess established facts separately from retained user claims; performs no I/O.

    Storage additionally reparses original bytes and validates the immutable archive
    ID before invoking this policy. Content hashes are not publisher authentication.
    There are deliberately no supported authenticity/date-authority validators yet.
    """
    metadata = archive["metadata"]
    integrity = (isinstance(original_bytes, bytes)
                 and hashlib.sha256(original_bytes).hexdigest() == metadata["original_sha256"]
                 and digest(archive["records"]) == archive["normalized_sha256"])
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
    missing = ["SOURCE_ATTRIBUTION_NOT_INDEPENDENTLY_ESTABLISHED",
               "PUBLISHER_AUTHENTICITY_NOT_ESTABLISHED", "EFFECTIVE_DATE_AUTHORITY_NOT_ESTABLISHED"]
    if not integrity:
        missing.insert(0, "CONTENT_INTEGRITY_NOT_ESTABLISHED")
    if declared_synthetic:
        missing.insert(0, "SYNTHETIC_DATA_IS_NOT_EXTERNAL_SOURCE_EVIDENCE")
    if archive["status"] != "ELIGIBLE_LOCAL_RESEARCH":
        missing.append("STRUCTURAL_VALIDITY_OR_DECLARED_COVERAGE_MISSING")
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
        "publisher_authenticity": {"status": "NOT_ESTABLISHED", "supported_verification_mechanisms": []},
        "capture_time": {"status": "USER_DECLARED" if metadata["captured_at"] else "UNKNOWN",
                         "timestamp": metadata["captured_at"]},
        "publication_time": {"status": "USER_DECLARED" if metadata["publisher_published_at"] else "UNKNOWN",
                             "timestamp": metadata["publisher_published_at"]},
        "ingestion_time": {"status": "LOCALLY_RECORDED", "timestamp": archive["ingested_at"],
                           "is_capture_time_evidence": False},
        "effective_dates": {"status": "DECLARED_ONLY" if intervals else "UNKNOWN",
                            "declared_intervals": intervals, "independently_supported_intervals": []},
        "artifact_classification": "DECLARED_SYNTHETIC" if declared_synthetic else "EXTERNAL_ORIGIN_UNESTABLISHED",
        "submitted_qualification_claims": "PRESENT_UNVALIDATED" if claims_present else "NOT_SUPPLIED",
        "source_documentation": dict(SOURCE_DOCUMENTATION.get(metadata["provider"], {
            "references": [], "status": "UNSUPPORTED_SOURCE", "limitation": "No assessed source documentation."}),
            review_date=DOCUMENTATION_REVIEW_DATE, scope="DOCUMENTATION_ONLY_NOT_ARCHIVE_AUTHENTICATION"),
        "historical_eligibility": {"allowed": False, "scope": "LIVE_HISTORICAL_REPLAY",
                                   "reason_code": "HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT", "missing_evidence": missing},
    }

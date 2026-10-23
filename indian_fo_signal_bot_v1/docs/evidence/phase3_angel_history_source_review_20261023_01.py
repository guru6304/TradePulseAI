"""Retain public-source review and strictly bounded prior-report reconciliation."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
paths = ["docs/TRADEPULSE_CONTINUOUS_ACCEPTANCE_REPORT.md",
         "docs/reports/TRADEPULSE_CAPABILITY_ACCEPTANCE_REPORT_20261019_FORENSIC_AUDIT.md",
         "docs/reports/TRADEPULSE_BLOCKERS_AND_NEXT_ACTIONS_20261019_FORENSIC_AUDIT.md"]
binding = {name: hashlib.sha256((APP / name).read_bytes()).hexdigest() for name in paths}
review = dict(scope="PUBLIC_DOCUMENTATION_AND_RETAINED_REPORT_RECONCILIATION_NO_PRIVATE_API_REQUEST",
    recorded_at=datetime.now(timezone.utc).isoformat(), retained_report_sha256s=binding,
    official_references=[
        dict(url="https://smartapi.angelone.in/docs", kind="PROVIDER_DOCUMENTATION",
            direct_open="ACCESS_DENIED_PAGE", search_index="HISTORICAL_API_CONTRACT_AVAILABLE",
            established=["Historical route getCandleData", "FIVE_MINUTE interval; documented max100days/request",
                "Request exchange,symboltoken,interval,fromdate,todate; row timestamp,open,high,low,close,volume"]),
        dict(url="https://raw.githubusercontent.com/angel-one/smartapi-python/main/SmartApi/smartConnect.py",
            kind="OFFICIAL_SDK_SOURCE", established=["Production HTTPS origin and historical route",
                "getCandleData uses POST", "Bearer authorization and SmartAPI headers"],
            implementation_policy="Do not import SDK; avoid its header logging, redirect following, profile fetch or automatic session hooks."),
        dict(url="https://github.com/angel-one/smartapi-python/blob/main/README.md", kind="OFFICIAL_SDK_EXAMPLE",
            established=["Historical request date formatting and explicit exchange/token/interval/window"]),
        dict(url="https://smartapi.angelone.in/faq", kind="PROVIDER_FAQ",
            direct_open="ACCESS_DENIED_PAGE", search_index="FAQ_CONTENT_AVAILABLE",
            established=["FAQ describes service including historical data as free"],
            not_established=["Account-specific historical endpoint entitlement", "Research/redistribution licence",
                "Publisher detached Ed25519 manifest", "Approved operator rights grant"])
    ],
    reconciliation=dict(
        authentication=dict(status="REPORTED_PRIOR_SUCCESS_NOT_REESTABLISHED", timestamp="2026-10-19 around10:51:51IST",
            original_sanitized_transport_receipt_found=False),
        quote=dict(status="RETAINED_REPORT_ASSERTS_SUCCESS", symbol="RELIANCE", exchange="NSE", identifier="2885",
            endpoint="https://apiconnect.angelone.in/rest/secure/angelbroking/market/v1/quote/",
            report_timestamp="2026-10-19T10:51:51+05:30", reported_ltp=1220.3, reported_age_seconds=.622),
        historical_403=dict(status="RETAINED_REPORT_ASSERTS_REJECTION", symbol="RELIANCE", exchange="NSE",
            endpoint="https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData",
            http_status=403, error_category="ACCESS_DENIED", original_request_window="NOT_RETAINED",
            exact_original_request_time="NOT_RETAINED", provider_cause="NOT_ESTABLISHED",
            caveat="Earlier prose hypothesizes entitlement/app/IP causes; later correction explicitly says account-specific cause was not established."),
        historical_74_bars=dict(status="USER_REPORTED_ONLY", interval_min=5, original_response_found=False,
            sanitized_transport_receipt_found=False, exact_timestamp="NOT_ESTABLISHED", exact_request_scope="NOT_ESTABLISHED"),
        comparison=dict(quote_vs_history="DIFFERENT_ENDPOINTS", historical403_vs74="INSUFFICIENT_BOUND_REQUEST_EVIDENCE",
            credentials_context="NOT_COMPARED_OR_DISCLOSED", proof_of_current_access=False,
            observation="Fixture tests that simulate403 are engineering evidence only, not an independent real request receipt.")),
    fresh_requests_by_this_review=0,
    historical_qualification=dict(status="BLOCKED", authenticated_HTTPS_is_publisher_signature=False,
        detached_publisher_manifest_supplied=False, approved_root_supplied=False, rights_document_supplied=False,
        operator_research_scope_supplied=False, dated_instrument_authority_supplied=False,
        codes=["PUBLISHER_TRUST_ROOT_MISSING", "PUBLISHER_AUTHENTICITY_UNVERIFIED", "HISTORICAL_RIGHTS_DOCUMENT_MISSING",
            "HISTORICAL_RESEARCH_SCOPE_UNAPPROVED", "HISTORICAL_INSTRUMENT_MASTER_MISSING", "OPTION_EXECUTION_DATA_MISSING"]))
target = APP / "docs/evidence/phase3_angel_history_source_review_20261023_01.json"
with target.open("x", encoding="utf-8") as stream:
    json.dump(review, stream, indent=2)
    stream.write("\n")
print(json.dumps(dict(path=target.relative_to(APP).as_posix(), sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    reconciliation="PRIOR403_REPORTED_AND74UNBOUND_CURRENT_ACCESS_NOT_REESTABLISHED", private_api_calls=0)))

# Angel historical capture: offline handoff, 2026-10-23

Historical acquisition mechanics are implemented and offline-tested. Real API
acquisition is reserved for the coordinating agent after the complete offline
suite and explicit safe preflight. This report records the Track A handoff,
not any subsequent live request or a historical-study acceptance.

The official [historical API documentation](https://smartapi.angelone.in/docs)
specifies `getCandleData`, `FIVE_MINUTE`, bounded date parameters and six-field
OHLCV rows. Its indexed table permits up to 100 days for five-minute requests;
this implementation limits acquisition to one completed standard NSE session.
Direct document/FAQ opens returned an access-denied page during review, while
their indexed content remained accessible. The
[official SDK source](https://raw.githubusercontent.com/angel-one/smartapi-python/main/SmartApi/smartConnect.py)
independently confirms the production origin, POST route and authentication
header structure. SDK logging and automatic session/profile behavior are not
imported into the acquisition implementation.

The [SmartAPI FAQ](https://smartapi.angelone.in/faq) describes historical access
as free. That statement establishes neither account-specific endpoint access nor
permission to redistribute data. No publisher-detached Ed25519 artifact, reviewed
rights document or approved research-use grant was established by this review.

## Retained success/403 reports

The retained continuous-acceptance report describes RELIANCE NSE token `2885`
quote success at `2026-10-19 10:51:51 IST`, LTP `1220.3`, followed by rejection of
the separate historical endpoint with HTTP 403. These are retained report claims;
the original account-specific transport capture is absent from the inspected
public evidence. Later text in the same report correctly states that the
account-specific cause remains unestablished. Earlier entitlement/app/IP prose
is insufficient to prove a cause.

The user's reported 74-bar response has no matching original response or bound
sanitized receipt in the inspected public workspace. Its exact request time,
window and credential context cannot be compared with the 403. Offline tests
named after candle-403 behavior are fixtures, not additional real observations.
The quote and historical requests use different endpoints. A fresh successful
historical response would establish that invocation only; it would not explain
the earlier rejection or establish WebSocket acceptance.

The source review and hashes of the retained reports are in
[phase3_angel_history_source_review_20261023_01.json](../evidence/phase3_angel_history_source_review_20261023_01.json).

## Capture interface and controls

`angel_history_capture.capture_one_history(adapter, symbol_meta, session_date,
private_root, stage, *, transport=None, allow_live_request=False)` reuses an
already-authenticated read-only Angel adapter. It never logs in, refreshes a
token, retries, follows redirects, places orders or starts a scheduler.

The coordinating caller must first verify the current cash mapping and load it
into the existing adapter master registry. Pinned identity and loaded-master
token must agree. A current master is not proof of historical identity validity.
The adapter data-provider setting may be `angelone` or `paper_sim`; Telegram must
remain dry-run and the production scheduler disabled. The only network route is
the fixed historical POST endpoint. Real execution is outside this module.

The request covers one fully completed configured trading day, `09:15` through
the `15:25` five-minute bar start. It expects 75 completed bars. Missing bars are
reported without filling them. A 74-bar fixture retains exactly 74 observations
and reports one missing interval. Dates are not silently extended or paginated.
The caller must authorize a real request explicitly with
`allow_live_request=True`; an injected transport always produces SIMULATED
candidate rows, even if that flag is supplied.

For real calls, `private_root` must descend from the application's `.local/`
directory, for example `.local/phase3-angel/history`. A fresh stage is reserved
before the single request. Reusing it fails before another request. The private
stage contains `request.json`, the untouched `response.bin`, separate
`normalized_candidate.json` when validation succeeds, and `capture_receipt.json`.
Responses exceeding 8 MiB retain an explicitly incomplete `response_prefix.bin`
and cannot produce normalized data. Timeout is bounded to eight seconds.

Returned public metadata includes request scope, current mapping revision,
HTTP status, validated HTTP Date/content type, response and normalization hashes,
counts, coverage and quality. Response bodies, arbitrary server error text,
headers and credential material remain outside public receipts. HTTP 403 is
reported without guessing an entitlement, IP, token or throttling cause.

## Verification and acceptance

The focused command was:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning docs\evidence\phase3_angel_history_verify_20261023_01.py
```

It executed **25/25 tests**, zero failures/errors/skips and no unraisable errors,
in **14.088 seconds**, with identical source snapshots before and after. This
includes 12 acquisition cases and the existing 13 historical-study cases.
[Receipt](../evidence/phase3_angel_history_focused_20261023_01.json) and
[log](../evidence/phase3_angel_history_focused_20261023_01.txt) bind the actual run.
No real private API request was made by these tests or this source review.

| Gate at this offline handoff | Status |
|---|---|
| Bounded capture, byte retention, normalization and failure handling | OFFLINE PASS |
| Current real historical endpoint access | NOT ATTEMPTED by Track A worker |
| Publisher source authority | BLOCKED |
| Rights document and research-use approval | BLOCKED |
| Historical dated instrument authority | BLOCKED |
| Real frozen cash study | BLOCKED |
| Option execution study | Separate missing-data dependency |
| Phase 3 continuous WebSocket/candle acceptance | Separate Track B gate |

Open historical dependencies are `PUBLISHER_TRUST_ROOT_MISSING`,
`PUBLISHER_AUTHENTICITY_UNVERIFIED`, `HISTORICAL_RIGHTS_DOCUMENT_MISSING`,
`HISTORICAL_RESEARCH_SCOPE_UNAPPROVED`, `HISTORICAL_INSTRUMENT_MASTER_MISSING`
and separate `OPTION_EXECUTION_DATA_MISSING`. A successful authenticated capture
remains a candidate under the unchanged qualification policy. No locally created
signature or approval may substitute for authentic publisher/rights evidence.

# Read-only option metadata and quote fixture contract — D1

Proposed contract **`tradepulse.option-fixture.d1.v1`**, assessed **3 November 2026 IST**, against approved `4d132c6`. This is a typed research artifact design, not an implemented parser, provider adapter, trust credential, API route or execution permission. Companion documents: [capability evidence](TP_OPTIONS_SOURCE_CAPABILITY_MATRIX_D1.md) and [gap/acquisition plan](TP_OPTIONS_DATA_GAP_AND_ACQUISITION_PLAN_D1.md).

The fixture is the smallest auditable bundle that separates raw observations, normalization evidence, legal/data scope and a proposed join into existing `option_intelligence`. Missing hard facts produce a retained blocked fixture. They must not be supplied with a familiar value merely to satisfy a validator. Optional context remains independently missing. All fixture outputs and downstream research results are non-actionable; Main owns eventual admission and lifecycle.

## Version, immutability and two kinds of evidence

- `schema_version` is exactly `tradepulse.option-fixture.d1.v1`; `fixture_id` identifies immutable content. A correction produces a new revision and `supersedes`, never overwrites an earlier fixture. Hash canonical fixture content excluding its ID/hash fields; raw-asset hashes cover original bytes, not reserialized provider objects. UTC/offset timestamps and decimal strings are canonicalized under an explicitly versioned encoder before hashing.
- `provenance` is `SYNTHETIC_FIXTURE` or `UNVERIFIED_CAPTURE`. No producer-controlled `qualified:true`, `source_qualified`, signature-shaped string or local checksum can authorize source trust. Genuine qualification needs Main's independently reviewed trust/entitlement process.
- Documentation classification is the matrix enum `DOCUMENTED|CONDITIONAL|UNVERIFIED|UNAVAILABLE|CONTRADICTORY`. Observed-field validation is the existing `VERIFIED|UNAVAILABLE|STALE|INVALID|NOT_ESTABLISHED`. They are separate axes. DOCUMENTED does not map automatically to VERIFIED; VERIFIED never implies authentic or entitled.
- Presence is `ABSENT|NULL|OBSERVED`. An observed0 is valid when the field allows0; null is not0. Raw fields, original units and source paths survive rejected normalization. Mutable or overlarge unsupported objects are not silently truncated into valid data.
- Read-only means `read_only:true`, `actionable:false`, `execution_allowed:false`, `historical_replay_allowed:false`. A fixture file can be inspected offline; it cannot fetch data, renew a token, refresh a cache, initialize operational storage, call scanner APIs or enter a paper account.

## Minimal common types

These declarations are documentation for a future separately reviewed loader; no runtime file is added by D1. `object` raw values are bounded JSON scalars, never arbitrary Python objects. Numbers normalized into price/Greek fields use finite decimal strings; quantities use whole integers. Unknown is null plus an explicit state, never an omitted uncertainty.

```python
from typing import Literal, TypedDict

DocState = Literal["DOCUMENTED", "CONDITIONAL", "UNVERIFIED", "UNAVAILABLE", "CONTRADICTORY"]
DataState = Literal["VERIFIED", "UNAVAILABLE", "STALE", "INVALID", "NOT_ESTABLISHED"]
Presence = Literal["ABSENT", "NULL", "OBSERVED"]

class EvidenceRef(TypedDict):
    evidence_id: str
    url_or_local_artifact: str
    artifact_sha256: str | None
    source_version: str | None
    published_at_or_date: str | None
    effective_from: str | None
    effective_until: str | None
    checked_at: str
    locator: str
    classification: DocState
    claim_scope: str

class FieldValue(TypedDict):
    presence: Presence
    raw_value: object
    raw_path: str | None
    raw_unit: str | None
    value: str | int | None
    unit: str | None
    evidence_ids: list[str]
    state: DataState
    reason_codes: list[str]

class Clock(TypedDict):
    value: str | None
    raw_value: str | int | None
    raw_path: str | None
    meaning: Literal["EXCHANGE_BOOK_SNAPSHOT", "BOOK_LEG_UPDATE", "TRADE", "PROVIDER_GENERATED", "PROVIDER_RECEIVED", "CLIENT_RECEIVED", "APPLICATION_AVAILABLE", "UNKNOWN"]
    epoch_and_timezone: str | None
    resolution_seconds: str | None
    evidence_ids: list[str]
    state: DataState

class SourceEnvelope(TypedDict):
    source_id: str
    provider: str
    endpoint_or_feed_version: str
    capture_revision: str
    vendor_revision: str | None
    raw_artifact_sha256: str
    raw_locator: str
    parser_version: str | None
    source_authenticity: Literal["NOT_ESTABLISHED"]
    received_at: Clock
    available_at: Clock

class Permission(TypedDict):
    use: Literal["ACCESS", "INTERNAL_CAPTURE", "RETAIN", "OFFLINE_REPLAY", "NON_DISPLAY_ANALYSIS", "DISPLAY", "REDISTRIBUTE", "DERIVED_EXTERNAL"]
    decision: Literal["ALLOWED", "DENIED", "UNKNOWN"]
    evidence_ids: list[str]
    effective_from: str | None
    effective_until: str | None
    retention_days: int | None
    conditions: list[str]

class Entitlement(TypedDict):
    entitlement_id: str
    licensee_scope: str
    account_scope_ref: str | None
    provider_plan: str | None
    exchange: str
    segments: list[str]
    instruments_scope: str
    available_at: str | None
    permissions: list[Permission]
    evidence_ids: list[str]
    state: DataState

class Fixture(TypedDict):
    schema_version: Literal["tradepulse.option-fixture.d1.v1"]
    fixture_id: str
    revision: int
    supersedes: str | None
    provenance: Literal["SYNTHETIC_FIXTURE", "UNVERIFIED_CAPTURE"]
    read_only: Literal[True]
    actionable: Literal[False]
    execution_allowed: Literal[False]
    historical_replay_allowed: Literal[False]
    decision_at: str
    evidence: list[EvidenceRef]
    entitlement: Entitlement | None
    master: dict[str, object]
    quote: dict[str, object] | None
    optional_context: list[dict[str, object]]
    fee_friction: dict[str, object] | None
    joins: list[dict[str, object]]
    blockers: list[str]
```

`dict` payloads above must conform to the component field tables below, with no additional unreviewed normalized fields. The envelope allows a blocked bundle without inventing missing payloads. `capture_revision` is assigned locally; nullable `vendor_revision` is populated only when actually supplied. A local label must not masquerade as a provider revision. This is a proposed design: Python TypedDict annotations alone do not enforce it or confer authentication. A future loader must reject duplicate JSON keys, nonfinite constants, bad encoding, oversized records and unknown schema versions, and retain rejection reasons.

## Component contracts

| Component / type ID | Required fields and types | Evidence and join rule |
|---|---|---|
| Dated master `tradepulse.option-master-fixture.d1.v1` | `master_id:str`, `revision:str`, `source:SourceEnvelope`, `terms:list[ContractTerm]`, `coverage:{from,to,instrument_scope,completeness}`, `listing_state:FieldValue`, `status:FieldValue`, `effective_dates_evidence_ids:list[str]` | A current file proves only its observed contents. Do not set historical `valid_from` to first capture or `valid_to` to expiry without authoritative coverage evidence. Intraday changes require new revisions and as-of knowledge clocks. Missing validity/listing authority blocks genuine normalization, even if a caller declaration can pass research structural checks. |
| Exact `ContractTerm` | `provider/token`, exchange/segment/type, exact trading label, underlying and underlying token, expiry ISO date, strike INR, CE/PE, integer lot, premium tick INR, multiplier1, unit declarations, effective interval, trading status; each sourced field has FieldValue/evidence | Bind provider token **and** canonical terms **and** effective interval **and** master revision. Token reuse cannot overwrite old identity. Calendar/holiday changes cannot be inferred from a familiar weekly label. Record broker↔exchange crosswalk as its own dated evidence. |
| Quote `tradepulse.option-quote-fixture.d1.v1` | SourceEnvelope; `quote_id`, `contract_term_ref`, `master_revision`, `bid/ask:FieldValue`, `bid_size/ask_size:FieldValue`; `snapshot_at,bid_at,ask_at,size_at:Clock`; `phase_ref`, `sequence:str|null`, `correction_revision:int`, quote-policy reference | Source clocks must date the book state and quantities. A provider generation/receipt stamp or LTT is not an exchange book timestamp. Separate update clocks stay separate. Shared snapshot time may date both sides only with explicit atomic current-book semantics and bounded clock error. No duplicate tick promotion or missing packet interpolation. |
| Clock bundle `tradepulse.option-clocks-fixture.d1.v1` | Named clocks above; `client_clock_id`, `clock_sync_evidence`, `max_clock_error_seconds`, optional `receive_monotonic_ns`, timezone/epoch/precision and conversion evidence | Retain raw epoch and offset conversion. Client receive is captured locally, application availability after parsing/validation, both independent of provider time. `source<=received<=available<=decision`; no arbitrary negative-age tolerance. Clock uncertainty must fit the selected policy. Unknown source time remains unknown even if latency seems small. |
| Tick / lot / quantity `tradepulse.option-units-fixture.d1.v1` | `field_path`, raw denomination, exact conversion numerator/denominator, output unit, dated contract/lot reference, source/schema version and evidence IDs | INR premium **per underlying unit**; quantities UNDERLYING_UNITS or CONTRACTS with exact dated lot conversion once. Premium tick, strike and book-price scaling are separate. Intended quantity must be whole lots; displayed sizes need only be nonnegative integer units, not lot multiples. Validate exact ticks without a guessed epsilon. No universal0.05 stock-option tick. |
| Depth `tradepulse.option-depth-fixture.d1.v1` | Exact contract/master/source; bid/ask arrays of `{price:FieldValue,quantity:FieldValue,orders:FieldValue|null}`; independent source clocks/sequences; level count; phase | Optional. Preserve sorted unique sides; align source/decision and verify top against quote. More than30 levels cannot pass current research depth inspector: retain raw200-level observation separately, explicitly extract at most30 only under a reviewed projection with original coverage, never imply full-book processing. No quantity imbalance becomes aggressor flow. |
| Greek / IV `tradepulse.option-context-fixture.d1.v1` | Exact contract/source/revision; field source clocks; IV/delta/gamma/vega/theta FieldValue; model/provider convention/version, optional `theta_calendar_basis`, uncertainty/status | Optional. IV fraction versus percent; delta premiumINR/underlyingINR; gamma premiumINR/underlyingINR²; vega per IV fraction or percentage point; theta calendar-day or year with declared365 basis. No inference from numerical scale. Different observation times require separate records, not one falsely fresh context envelope. |
| OI and volume `tradepulse.option-activity-fixture.d1.v1` | Exact contract/source/revision; FieldValue counts/change; `kind:CURRENT|INTRADAY|PRIOR_CLOSE|UNKNOWN`; quantity unit; source/publication clocks; prior-session/calendar ref; volume window `[start,end]`, cumulative/reset/correction convention | Optional OI requires comparable dated baseline. Previous close price is never previous OI. Dummy or unexplained OI-change stays INVALID/NOT_ESTABLISHED, not a zero. Count lot conversion once; signed change can be negative. Volume needs exact interval/cumulative reset to avoid double counting. A3s request does not date exchange OI at3s. |
| Fees/friction `tradepulse.option-cost-fixture.d1.v1` | Effective-dated broker plan, exchange/segment, buy/sell, intraday/closed/exercised treatment; quantity and price basis; brokerage, taxes/levies/GST/stamp/other components with evidence, cost-model version; impact and uncertainty assumptions | Cost inputs distinguish cited actual fee schedule from research estimates. Must cover whole-lot intended quantity and both legs; no double spread subtraction. Current package consumes only aggregate round-trip fees/impact/budgets, so retain fee components and their coverage in the wrapper. Missing required fees means cost UNAVAILABLE; no unsupported current tariff is invented in D1. |
| Provenance / entitlement `tradepulse.option-rights-fixture.d1.v1` | Source artifact hashes, version/locators; independently reviewed licensee/account/plan and segment scope; permission per use; effective dates, retention/deletion, downstream restrictions; no secrets | ACCESS alone never authorizes RETAIN/REPLAY/DISPLAY/REDISTRIBUTE. A public documentation URL or paid invoice is not necessarily the underlying-use grant. Missing permission stays UNKNOWN and blocks that use; DENIED cannot be overridden by synthetic provenance. No credentials/account identifiers or permission to acquire real data are bundled here. |

Effective intervals in the wrapper use **`[from,until)`** with explicit timestamps. Existing research identity fields `valid_from/valid_to` use inclusive ISO dates. A reviewed date projection must prove coverage of the event and preserve finer intraday bounds in the wrapper; it must not widen a same-day or partial interval. The entire original raw fixture remains available for the eventual Main authority check.

## Binding to the approved research package

| Existing structure at4d132c6 | Proposed explicit projection | Acceptance limit |
|---|---|---|
| `validate_contract` / `ExactOptionContract` | `provider,identifier,symbol,underlying,underlying_identifier,exchange,segment,instrument_type,option_type,expiry,strike,lot_size,tick_size,multiplier,price_unit,quantity_unit,valid_from,valid_to,contract_status,source,source_revision,master_id,master_sha256,source_observed_at,received_at,available_at`; stock membership separately | Every mandatory value has an evidence-backed projection or the fixture remains blocked. Digest from this package is representation-sensitive to source revision by design, with canonical numeric terms; do not confuse it with Main's JSON identity digest. Authenticity/listing remain NOT_ESTABLISHED in the research output. |
| `inspect_quote` / `QuoteMetrics` | `quote_id,contract_id,provider,source_revision,source_id,observed_at,received_at,available_at,bid_at,ask_at,bid,ask,bid_size,ask_size,price_unit,quantity_unit` | `source_revision` here is the bound **master** revision; local capture and nullable vendor revisions belong in wrapper SourceEnvelope. Qualification of liquidity time is stronger than this projection: wrapper preserves `size_at`; current inspector has no independent size-clock field. Projection alone cannot establish Main readiness. |
| `QuotePolicy` | Source ID, evidence reference/availability, documented cadence and timestamp resolution, max age3s pilot and leg skew1s pilot | Only provide observed/cited cadence with its limits; ping interval, throttle limit or response generation interval cannot supply it. No general guarantee means NOT_ESTABLISHED, not invented1s. A policy change needs a new version/review. |
| `SessionWindow` | Explicit date, normal research window, phase, source reference, availability | Approved code expects09:15–15:30 NORMAL. D1 discovered current exchange-phase/close differences. Preserve the code; real schedule that does not fit must remain BLOCKED_CALENDAR_CONTRACT_REVIEW. A daytime observation may support a separately declared **research subwindow**, but that must not misstate exchange close or discard phase data. |
| `inspect_depth` | Same current decision and exact contract/source; price/quantity arrays; normalized units; max30 levels, top agrees with quote | No silent native bid/ask reversal, reordering corrupt data, clock invention or deeper-size substitution. Separate unknown levels remain unknown. |
| `inspect_context`, `oi_delta`, `greek_scenario` | Named scalar fields/units; source/received/available; context age policy; volume window; OI baseline kind/prior-session date; declared theta basis | Separate freshness policy per actual field family; optional unavailable data do not veto valid quote arithmetic. A prior-close OI timestamp/session must come from the effective dated calendar, not the current package's synthetic15:30 convention when the source close differs. |
| `FrictionAssumptions` / `estimate_friction` | Version/source/effective dates/availability; unit entry/exit impact, aggregate fees, whole-lot risk/capital scenario budgets;25/35/45% loss fraction | Arithmetic only; declared impact is not measured impact, budgets are not account capacity. No one-source quote estimate is actual entry or P&L. |
| `IntelligenceResult` | Retain complete original fixture reference, configuration/hash and wrapper blockers alongside the non-actionable result | Current API has no entitlement/field-authority validator. A sidecar is necessary; adding a property to JSON is not integrating a source gate. D1 implements no adapter and no wrapper consumer. |

No legacy-record cast: native token, segment, price scaling and time fields differ by endpoint. `tradepulse.option-capture.v1` preserves raw presence but its missing source clocks/units must not be filled from receive time or unrelated metadata. The historical `tradepulse.option-observations.v1` archive is a third distinct schema, not a prospective quote.

## Main3902c3f read-only compatibility finding

The existing fetched tracking ref `origin/main` resolved to **`3902c3f0a4d8f13d5e0392485a5cef67d68ee734`**; its commit object and files were inspected with `git show`, without a new fetch, merge, checkout or branch mutation. This is exact-revision inspection, not a claim that the server's latest branch was revalidated. It adds optional retained numeric premium tick and `option_preflight.prospective_preflight` (`tradepulse.option-prospective-preflight.v1`). That code remains absent from this branch.

Main's declaration includes exact normalized OPTIDX identity/master, `quantity_units`, retained tick, `quote_identity_digest`, `source_revision`, bid/ask/both sizes, `quote_at,bid_at,ask_at,liquidity_at,received_at,available_at`, INR/UNDERLYING_UNITS. Its mechanics use same-date master,<=5s source age,<=1s skew and<=2% spread. Research uses its own<=3s pilot and segment-specific spread **comparison**, not an interchangeable gate. Structurally valid Main input still returns `INDEPENDENT_SOURCE_QUALIFICATION_UNAVAILABLE`, with qualification/readiness/entry all false.

A later typed adapter would need separate reviewed projections for Main numeric versus research Decimal-string fields and each identity digest. It must provide true `liquidity_at`, preserve underlying/source/candle linkage and defer every prospective decision to Main. Do not merge new optional tick support by copying Main modules or weaken research tests to mimic it. Existing tick-loss compatibility tests remain correctly bound to4d132c6, not a test of3902c3f.

## Fully synthetic normalized vector

This example is wholly authored, not an authoritative provider payload, actual listed contract, current lot/tick or permission grant. The Upstox-shaped identifier only exercises that provider's accepted **syntax**. It has no real entitlement. The `normalized` block is intentionally already authored in the existing package's input shape; it demonstrates a join target, not a native conversion. The wrapper is not passed to a nonexistent loader.

```json
{
  "schema_version": "tradepulse.option-fixture-test-vector.d1.v1",
  "target_fixture_schema": "tradepulse.option-fixture.d1.v1",
  "fixture_id": "AUTHORED_D1_VECTOR_01",
  "revision": 0,
  "supersedes": null,
  "provenance": "SYNTHETIC_FIXTURE",
  "read_only": true,
  "actionable": false,
  "execution_allowed": false,
  "historical_replay_allowed": false,
  "decision_at": "2026-11-03T10:00:00+05:30",
  "intended_lots": 1,
  "entitlement": null,
  "source_authenticity": "NOT_ESTABLISHED",
  "blockers": ["SYNTHETIC_NOT_MARKET_EVIDENCE", "NO_REAL_DATA_ENTITLEMENT"],
  "normalized": {
    "contract": {
      "provider": "upstox", "identifier": "NSE_FO|999999",
      "symbol": "SYNTHETIC_D1_OPTION_CE", "underlying": "NIFTY",
      "underlying_identifier": "NSE_INDEX|Nifty 50", "exchange": "NFO",
      "segment": "NSE_FO_INDEX", "instrument_type": "OPTIDX", "option_type": "CE",
      "expiry": "2026-11-05", "strike": "25000.00", "lot_size": 50,
      "tick_size": "0.05", "multiplier": 1, "price_unit": "INR",
      "quantity_unit": "UNDERLYING_UNITS", "valid_from": "2026-11-03",
      "valid_to": "2026-11-03", "contract_status": "ACTIVE",
      "source": "AUTHORED_SYNTHETIC_ONLY", "source_revision": "D1_AUTHORED_MASTER_V1",
      "master_id": "AUTHORED_D1_MASTER", "master_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
      "source_observed_at": "2026-11-03T09:00:00+05:30",
      "received_at": "2026-11-03T09:00:01+05:30",
      "available_at": "2026-11-03T09:00:02+05:30"
    },
    "quote": {
      "quote_id": "AUTHORED_D1_QUOTE", "contract_id": null,
      "provider": "upstox", "source_revision": "D1_AUTHORED_MASTER_V1",
      "source_id": "AUTHORED_D1_BOOK", "observed_at": "2026-11-03T09:59:59+05:30",
      "received_at": "2026-11-03T09:59:59.500000+05:30",
      "available_at": "2026-11-03T10:00:00+05:30",
      "bid_at": "2026-11-03T09:59:59+05:30", "ask_at": "2026-11-03T09:59:59+05:30",
      "bid": "101.50", "ask": "102.00", "bid_size": 50, "ask_size": 50,
      "price_unit": "INR", "quantity_unit": "UNDERLYING_UNITS"
    },
    "quote_policy": {
      "source_id": "AUTHORED_D1_BOOK", "evidence_reference": "AUTHORED_NOT_VENDOR_CADENCE",
      "available_at": "2026-11-03T09:00:00+05:30",
      "documented_cadence_seconds": "1", "timestamp_resolution_seconds": "0.001",
      "max_age_seconds": "3", "max_leg_skew_seconds": "1"
    },
    "session": {
      "session_date": "2026-11-03", "open_at": "2026-11-03T09:15:00+05:30",
      "close_at": "2026-11-03T15:30:00+05:30", "phase": "NORMAL",
      "source_reference": "AUTHORED_RESEARCH_WINDOW_NOT_EXCHANGE_CALENDAR",
      "available_at": "2026-11-03T09:00:00+05:30"
    },
    "assumptions": {
      "version": "AUTHORED_D1_COSTS", "source_reference": "ZERO_FEE_SYNTHETIC_MATH_ONLY",
      "effective_from": "2026-11-03", "effective_to": "2026-11-03",
      "available_at": "2026-11-03T09:00:00+05:30",
      "entry_impact": "0", "exit_impact": "0", "round_trip_fees_inr": "0",
      "risk_budget_inr": "2000", "capital_budget_inr": "10000", "premium_loss_fraction": "0.35"
    }
  },
  "expected": {
    "contract_checks": "VERIFIED", "quote_checks": "VERIFIED", "source_authenticity": "NOT_ESTABLISHED",
    "entry_estimate": "102.00", "premium_stop": "66.30", "premium_target": "166.30",
    "gross_premium_risk_inr": "1785.00", "snapshot_friction_inr": "25.00",
    "actionable": false
  }
}
```

This separate `tradepulse.option-fixture-test-vector.d1.v1` envelope is **not structurally a Fixture**: it contains authored normalized targets/expectations instead of full raw evidence/component manifests. It cannot be accepted by a future Fixture loader. The test harness alone obtains `contract_id` from `validate_contract(...).contract.contract_id` and binds it to this authored quote with `intended_lots=1`. A null contract reference is **not** acceptable quote input; tests must demonstrate it fails before binding. Do not hardcode/copy a digest across master revisions. In a genuine fixture every asserted fact would additionally need raw evidence, rights, clock/phase and unit references from the component tables.

## Synthetic negative vectors and proposed acceptance criteria

| Vector | Change from the authored example / construction | Required result |
|---|---|---|
| V01 | Bind computed exact contract reference; supply declared synthetic policy/session/costs | Existing supplied checks pass; E102,S66.30,T166.30,one-lot risk1785,F25. All operational flags false; wrapper remains synthetic/unentitled. |
| V02 | Leave `contract_id:null`; then supply different provider/token/side/expiry/lot/tick/revision reference | Missing→UNAVAILABLE; mismatch→INVALID. Never take a matching symbol label as proof. |
| V03 | Remove tick or effective-date evidence; raw tick5 with unresolved denomination | Contract join blocked; no assumed0.05 or5INR. Source matrix class remains independent of validation. |
| V04 | Move BOTH bid/ask times to09:59:57 exactly; then move BOTH1microsecond older at decision10:00 | Scoped VERIFIED at3s boundary, STALE above3s; zero leg skew isolates age. No use of receive clock to refresh it. |
| V05 | Remove source/leg time; use only LTT or provider-generated time | Required quote time UNAVAILABLE/NOT_ESTABLISHED; no synthetic source event. |
| V06 | Size49 then0 for one side; negative/fractional sizes; unitUNKNOWN | Insufficient nonnegative size→UNAVAILABLE; malformed→INVALID; unknown unit→NOT_ESTABLISHED. No use of deeper totals to fill L1. |
| V07 | bid=ask; bid>ask; off-tick price | INVALID under the approved research locked/crossed/on-tick policies. |
| V08 | Optional fields ABSENT, NULL, OBSERVED0; raw `oi_change` without baseline | Preserve presence; missing IV/Greeks do not veto quote. Unjoined OI change NOT_ESTABLISHED; no fake percentage or institution attribution. |
| V09 | CONTRACTS versus UNDERLYING_UNITS baseline, different contract revision, unknown prior close | Reject incompatible join; require actual source/time/unit evidence. Known OI0 is valid; missing is not0. |
| V10 | IV20PERCENT versus0.20FRACTION; vega perpoint versusfraction; annualtheta missing365basis | Only explicit conventions normalize. Vega point→fraction×100; theta annual→calendar day÷365 only declared; missing convention NOT_ESTABLISHED. |
| V11 | Signed PE delta with matched PE identity; positive PE delta | Preserve valid negative delta; reject sign mismatch; never normalize abs(delta) silently. |
| V12 | New contract/status/phase after original availability; future received/available clock | No lookahead; immutable correction/superseding revision, re-evaluate at later time only. |
| V13 | Rights absent/unknown/expired/denied; source signature unknown; merely paid endpoint | Wrapper blocks corresponding genuine use; current research arithmetic cannot override it. Synthetic tests still never become market evidence. |
| V14 | Replay requested from OHLC/LTP, rolling ATM strikes or late unavailable quote | No exact historical bid/ask P&L; retain `BLOCKED_DATA_FOR_HISTORICAL_OPTION_PNL`. No Main lifecycle implemented by this contract. |
| V15 | Existing native/core/capture records passed directly, including current3902c3f preflight declaration | No implicit cast; any later adapter is separate, source-bound and Main-reviewed. Preserve all current false permissions. |

Proposed genuine-fixture acceptance requires **all** mandatory identity, clock, quote/size, phase, unit, rights and provenance joins to be independently evidenced; optional fields report their own coverage. Exact duplicates are idempotent; conflicting revisions remain visible. No G0/data-quality acceptance is claimed from the synthetic vector, a TypedDict compilation, pass count or source URL.

Main's prospective execution acceptance additionally requires a previously qualified underlying directional thesis, complete candle/source linkage, fresh exact same-contract quote at the later trigger, valid fees/capital/exposure and Main's own gates, actual later bid-side exits/invalidation/time policy and recovery. Historical P&L additionally requires lawful complete historical bid/ask/size/clock coverage and point-in-time masters. D1 supplies neither and grants neither.

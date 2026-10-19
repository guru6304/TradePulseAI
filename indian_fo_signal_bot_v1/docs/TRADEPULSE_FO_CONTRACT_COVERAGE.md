# TradePulse AI - contract coverage and Phase 5A/5B limits

Reviewed 2026-10-18. This report describes source inspection and **offline synthetic fixtures**, not current exchange membership, genuine broker responses or accepted F&O execution. Final commands/counts are in the [engineering report](TRADEPULSE_PHASE5A_ENGINEERING_REPORT.md).

## Provider and instrument coverage

| Scope | Angel One | Upstox | Dhan | External dependency / next acceptance |
| --- | --- | --- | --- | --- |
| Cash EQ | Existing pinned/current-master identity and quote/candle adapter; offline PASS | Existing pinned identity and quote/candle adapter; offline PASS | Existing pinned identity and candle adapter; existing fixture coverage | Real cash-data acceptance NOT_TESTED in this mission. Obtain one separately authorized matching quote/completed-candle observation. |
| NIFTY/BANKNIFTY spot | Pinned spot mappings, offline quote checks | Pinned spot mappings, offline quote checks | Pinned spot mappings and existing tests | Index-specific operational candle acceptance is separate. `INDEX_SPOT` is non-executable, with no executable lot/multiplier. |
| FUTIDX | Normalized local declaration inspection only; no accepted live contract-candle resolver | Same | Same | BLOCKED. Need authoritative current dated master, exact token/expiry/lot/units and real contract-bound candles. |
| FUTSTK | Normalized local declaration inspection only | Same | Same | BLOCKED. No native stock-futures universe/execution path is delivered. Cash shares do not establish derivative membership. |
| OPTIDX | Existing master-bound option identity and conditional analytical/proposal mechanics; no operational acceptance | Chain/expiry analytics exist; no supported executable contract resolver | Chain analytics exist; no supported executable contract resolver | Existing Angel gates still require exact master contracts, matching expiry/strike/side/lot and verified prior-session OI. No real acceptance. Historical option fills remain unimplemented. |
| OPTSTK | Normalized local declaration inspection only | Same | Same | BLOCKED. No stock-options execution universe/contract candles or accepted analytics path was added. |
| Chain/OI/Greeks | Existing Greeks/quote-OI assembly and prior-close baseline gates | Existing chain/PCR/expiry parsers | Existing chain/PCR/expiry parsers | Parser evidence is PARTIAL, not contract eligibility. Entitlements, source identity and current/prior observations require separate evidence. |
| Historical identities | Existing archive schema handles EQ/INDEX_SPOT/FUTIDX/OPTIDX declarations | Same schema restrictions; native master import unsupported | Same schema restrictions; native master import unsupported | Source authenticity/effective-date authority BLOCKED for every provider. See the [provenance design](TRADEPULSE_HISTORICAL_PROVENANCE_DESIGN.md). |

No accepted current F&O master artifact was available or acquired. No provider was switched. All six normalized instrument types remain `eligible=False`; successful declaration inspection never registers an executor, changes broker mappings, authorizes a proposal, or releases historical replay.

## Existing-model extension and ingestion boundary

`instrument_identity.py` extends the existing dictionary identity with `ContractIdentity` / `ContractResolution` type annotations. `validate_contract_identity`, `prepare_contract_master` and `resolve_contract_identity` validate local normalized JSON with schema `tradepulse.contract-master.v1`. This is an explicit declaration format, **not another provider-native parser or historical archive verifier**. Existing `spot_identity`, `option_contract`, `dated_identity` and live signal checks retain their gates.

Common fields are provider, exchange, segment, instrument type, contract/cash symbol, provider identifier, units, declared validity interval, source/version/digests and status. Type-specific requirements are:

| Type | Required quantity / identity terms |
| --- | --- |
| EQ | NSE / NSE_EQUITY_INTRADAY; canonical share symbol; INR/SHARES; lot 1 and unit multiplier 1; no derivative terms |
| INDEX_SPOT | NSE / NSE_FO_INDEX; supported canonical index; INDEX_POINTS/NOT_EXECUTABLE; lot/multiplier inapplicable |
| FUTIDX / FUTSTK | NFO / correct index-or-stock segment; explicit contract label, matching underlying spot record/identifier, expiry, positive integer lot, multiplier 1, INR/UNDERLYING_UNITS; no strike/side |
| OPTIDX / OPTSTK | Derivative fields above plus finite positive strike and explicit CE/PE. Present call/put pairs at identical underlying/expiry/strike must agree on quantity and declared validity terms. |

Only the repository's unit multiplier convention is supported. Other multiplier/unit models reject rather than infer conversion. Derivatives require their underlying spot identity and covering interval in the same declaration. If only one option side is declared it remains partial inspection evidence; the application never infers the missing side or claims paired chain readiness.

Original bounded bytes, schema/parser revision, declared source/version/capture time and normalized records bind the candidate ID. A hash proves consistency only. Supplied verified/qualified/signature/URL claims do not confer trust. Duplicate identifiers, ambiguous terms, conflicting lots/pairs, unsupported provider/type, malformed dates/strikes/expiry/units, inactive/expired records and stale intervals produce explicit reasons. Valid unique in-date declarations return `BLOCKED_UNQUALIFIED_MASTER`; invalid bodies are retained as REJECTED candidates where safe.

`SQLitePersistenceStore.ingest_contract_master_bytes` stores original bytes in `contract_master_candidates`; every get/list/resolve reparses and compares them with metadata, normalized content and ID. The existing SQLite layer supplies persistence. `inspect_contract_resolution` is inspection only. Read-only GET/HEAD routes `/api/contract-masters` and `/api/contract-resolution` (also `/api/v1/...`) expose summaries/resolution; no HTTP import/download/activation endpoint exists. They make no broker request and cannot create paper entries or readiness receipts.

## Verification and closeout

`test_phase5a_contracts` contributes **20 executed tests** to the final **78-test focused selection** (exit 0); the pre-closeout 19-test module passed separately. Tests cover all three providers/six types, malformed/duplicate masters, ID/underlying/expiry/side/lot/unit conflicts, ambiguity, stale/expired status, byte/metadata/flag substitution and transport prohibition. The added paired-quantity/date regression first failed in six provider/field subcases; the narrow validator correction now passes.

`test_phase5a_integration` verifies actual store ingestion, restart/tamper rejection, additive migrations and read-only API behavior. Source inspection plus passing fixtures establish local consistency and failure behavior. They do not establish current master authority, an executable derivative universe, exchange calendars, provider entitlement or historical validity. The next contract task is to obtain an independently attributable original current-master artifact and specify a supported provider-native conversion/trust boundary before considering activation; keep all unqualified candidates blocked.

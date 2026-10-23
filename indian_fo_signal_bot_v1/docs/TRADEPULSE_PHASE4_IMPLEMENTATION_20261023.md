# Phase 4 offline implementation handover, 2026-10-23

The scanner evaluates the existing five strategies and returns structured
evaluation records alongside its existing signal fields. This is offline
engineering work. Candidate status and stored LIVE-shaped data do not establish
current feed acceptance, execution authority, profitability or predictive accuracy.
Older dated reports in this package remain historical.

The path is the existing adapter and canonical candle policy, completed bars,
strategy evaluators, scanner sizing and risk validation, deterministic ranking,
SQLite records and the existing API/dashboard. Feed selection remains separate
from execution mode. No extra provider, REST fallback, transport or scheduler is
started by evaluation or by an explanation read.

`POST /api/scan` retains its existing fields and adds `strategy_evaluations`,
`candidate_evaluations`, `evaluation_schema_version` and `actionable=false`.
Strategy records distinguish `DETECTED`, `REJECTED` and `UNAVAILABLE`, with
machine reason codes, actual visited rule checks, warm-up counts and source
references. Checks skipped by a short circuit are not invented. Detected setups
can still be rejected at scanner sizing or geometry validation. Qualified
candidates remain `CANDIDATE_ONLY`, including when their data mode is LIVE.

`GET /api/scans` adds `evaluation` to each retained scan. `GET /api/signals` adds
`candidate_evaluation` to each reconciled candidate. Older records without these
details return unavailable details. Current explanations are stored in the new
additive `scan_evaluations` table; existing schema initialization performs the
transactional migration. Retained cash scans bind the same explanation lists into
their existing immutable result. Missing, corrupted or inconsistent records fail
closed. Do not repair checksums to conceal inconsistent source facts.

The dashboard uses the existing cards, inspector and scan-history table. It shows
numeric gross target RR where supported, rule checks, warning codes and
insufficient-history reasons. Legacy ratio strings are nominal labels. Numeric
RR uses actual target distance divided by actual entry-to-stop distance in INR.
Estimated stop-exit charges do not establish net target RR, liquidity, spreads,
slippage or fills. Those unsupported quantities remain unavailable. Setup quality
is a rule score, never a win probability or an empirical performance measure.

Ranking remains quality descending, actual numeric T1 RR descending, stable
identity and full serialized candidate content for ties. Its policy identifier is
`QUALITY_THEN_TARGET1_REWARD_RISK_THEN_IDENTITY_V1`. It prioritizes valid candidates;
it does not allocate capital or override risk, data, warm-up or identity gates.

The five-minute warm-up minima remain Order Block 30, VWAP 35, ORB 30 and
Supertrend 200. Option Apex retains its separate option-chain and aligned OI
requirements. Session VWAP cannot be inferred if the current session's 09:15 bar
is missing. ORB retains its explicit opening-range coverage rules.

Angel in-memory history is bounded to 300 five-minute and 750 one-minute bars.
Selection retains independently contiguous completed session runs and a qualified
current tail; it never fills gaps or promotes partial candles. Healthy heartbeat
retention outside the cash session does not grant scanner freshness or LIVE
permission. Reconnect and restart discard this cache and explicitly report
`NOT_RESTORED`; retained database rows are not silently loaded as trusted warm-up.
Insufficient history remains unavailable. Existing raw event and packet budgets
remain unchanged.

An attached stream's qualification is checked during acquisition, before signal
writes, before result commit and before output. Disconnect or quality loss before
commit rolls back the result and outbox while leaving accepted pending input
recoverable. Loss after commit preserves the historical candidate but suppresses
preview and reports current readiness as unavailable. Explicit offline recovery
uses retained input and does not represent a fresh observation or delivery.

Keep both local `.env` files and saved risk/execution settings unchanged. Keep
execution in paper mode, Telegram in dry-run mode and background scheduling
disabled. Do not use offline fixtures as genuine market evidence.

Use the existing isolated interpreter and strict verifier:

```powershell
.venv_phase4\Scripts\python.exe -B -W error::ResourceWarning verify_offline.py --stage phase4_review_unique
```

Every run needs a new stage. The verifier blocks external network access, executes
the canonical Python suite and dashboard tests, checks JavaScript syntax, compiles
the Python source and binds exact test IDs, source bytes and log hashes. Validate
the matching retained receipt with `verify_offline.py --validate-evidence PATH`.
The final implementation receipts, report and release closeout reside in the
original repository under `docs/evidence/phase4_implementation_*`,
`docs/evidence/master_phase4_implementation_*` and
`docs/reports/phase4_implementation_completion_20261023_01.md`. Machine evidence is
handed over separately from the public source ZIP. No private database, `.env`,
raw market capture or `.local` input belongs in the release archive.

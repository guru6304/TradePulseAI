# Task 3 continuation — Track B operator blockers

Current status: BLOCKED_AWAITING_OPERATOR_INPUT. The actual local preflight failed before any socket opened. Independent verification continues. The scope preflight code defect was corrected and all 33 focused tests passed; this is offline evidence only.

**Blocker:** `DHAN_SPECIFIC_CREDENTIALS_MISSING_OR_PLACEHOLDER`

**Affected task:** Track B, `TRACK_B_LOCAL_PREFLIGHT`.

**What happened:** Actual application configuration classifies both DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN as PLACEHOLDER; no values were emitted.

**Evidence:** [docs/evidence/task3_completion_track_b_20261023_01.json](task3_completion_track_b_20261023_01.json), [docs/evidence/task3_completion_track_b_20261023_01_preflight.txt](task3_completion_track_b_20261023_01_preflight.txt). Command: `.venv_phase4\Scripts\python.exe -B dhan_feed_control.py`; exit 1; sanitized error: `DHAN_SPECIFIC_CREDENTIALS_MISSING_OR_PLACEHOLDER`.

**Why it is blocked:** Valid Dhan-specific client ID and access token configured privately through the existing application environment process.

**Who must act:** OPERATOR.

**Required action:**

1. Configure DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN privately in indian_fo_signal_bot_v1/.env or the invoking process environment; the repository-root .env is not the default file used by config.py.
2. Use valid Dhan-issued account/API credentials; do not substitute Upstox/Angel values or paste any secret into chat.
3. Retain ACTIVE_BROKER=paper_sim, TELEGRAM_DRY_RUN=true and ENABLE_BACKGROUND_SCHEDULER=false.
4. Run the local preflight from the application directory. Only after all blockers clear and exactly one verified instrument is configured, run the already-authorized 15-second read-only probe.

**How to fix it safely:** Supply configuration locally through the existing application environment process. Never put credentials or authentication material in chat, evidence or release archives. Keep paper simulation, Telegram dry-run and disabled scheduler intact.

**Verification command:** From `indian_fo_signal_bot_v1`, run `.venv_phase4\Scripts\python.exe -B dhan_feed_control.py`.

**Expected result:** This blocker disappears. Once the separate instrument blocker is resolved, preflight returns status PASS, instrument_count 1, live_requests false; authentication still requires the actual authorized probe.

**Current status:** AWAITING_OPERATOR. No real Dhan authentication, subscription, observation, candle acceptance or live shutdown has been attempted. Other independent Task 3 work continues; full Task 3 acceptance remains blocked.

**Blocker:** `EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED`

**Affected task:** Track B, `TRACK_B_LOCAL_PREFLIGHT`.

**What happened:** Actual application DHAN_FEED_INSTRUMENTS_JSON resolves to an empty list; instrument_count is 0, so no instrument has been selected or verified for this probe.

**Evidence:** [docs/evidence/task3_completion_track_b_20261023_01.json](task3_completion_track_b_20261023_01.json), [docs/evidence/task3_completion_track_b_20261023_01_preflight.txt](task3_completion_track_b_20261023_01_preflight.txt). Command: `.venv_phase4\Scripts\python.exe -B dhan_feed_control.py`; exit 1; sanitized error: `EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED`.

**Why it is blocked:** DHAN_FEED_INSTRUMENTS_JSON containing exactly one permitted canonical instrument metadata record whose symbol, provider identifier and exchange segment agree with the existing verified mapping policy.

**Who must act:** OPERATOR.

**Required action:**

1. Select exactly one permitted instrument and verify its Dhan security identifier and exchange segment against the accepted mapping source.
2. Configure the one-record JSON list privately in indian_fo_signal_bot_v1/.env or the invoking process environment under DHAN_FEED_INSTRUMENTS_JSON.
3. Do not invent a security identifier, use an alias to bypass identity checks, or broaden the initial probe to multiple instruments.
4. Rerun local preflight; after credentials and safety checks also pass, use only the authorized --smoke --seconds 15 command.

**How to fix it safely:** Supply configuration locally through the existing application environment process. Never put credentials or authentication material in chat, evidence or release archives. Keep paper simulation, Telegram dry-run and disabled scheduler intact.

**Verification command:** From `indian_fo_signal_bot_v1`, run `.venv_phase4\Scripts\python.exe -B dhan_feed_control.py`.

**Expected result:** This blocker disappears, instrument_count is exactly 1 and canonical mapping validation passes. With the separate credential blocker resolved, local preflight returns PASS without opening a socket.

**Current status:** AWAITING_OPERATOR. No real Dhan authentication, subscription, observation, candle acceptance or live shutdown has been attempted. Other independent Task 3 work continues; full Task 3 acceptance remains blocked.

After both local blockers clear, the already-authorized command is `.venv_phase4\Scripts\python.exe -B dhan_feed_control.py --smoke --seconds 15`, restricted to exactly one verified instrument. A 15-second probe cannot automatically establish completed-candle acceptance and must not be extended automatically.

# Task 3 resumption: exact operator blockers

Dhan credential presence is now sufficient locally; authentication has not been attempted.

**Blocker:** `HISTORICAL_CASH_DATA_MISSING`

**Affected task:** TRACK_A / `TRACK_A_CASH_STUDY`

**What happened:** No original eligible historical cash OHLCV file exists at the selected input root.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json, docs/evidence/task3_completion_baseline_20261023_01.json; command C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02; exit 2.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\source\cash_observations.json

**Who must act:** OPERATOR.

**Required action:**

1. Place the original signed cash-observations dataset under the selected input root; retain original bytes.
2. Supply cash_manifest.json and study_plan.json following --help. Do not synthesize bars or use the retained instrument snapshot as price history.

**How to fix it safely:** Configure the named local files; never share credentials, private keys, licences or source datasets in chat.

**Verification command:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_03

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Other independent checks are finished; Task 3 remains blocked.

**Blocker:** `PUBLISHER_TRUST_ROOT_MISSING`

**Affected task:** TRACK_A / `TRACK_A_SOURCE_AUTHENTICITY`

**What happened:** No usable independently approved publisher root loaded from the separate operator policy directory.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json, docs/evidence/task3_completion_baseline_20261023_01.json; command C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02; exit 2.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\operator\publisher_trust.json

**Who must act:** OPERATOR.

**Required action:**

1. Obtain the independently approved publisher Ed25519 PUBLIC root through the operator's trusted process.
2. Store the TrustAnchorConfig constructor record in publisher_trust.json. Never provide private keys or install test fixture roots.

**How to fix it safely:** Configure the named local files; never share credentials, private keys, licences or source datasets in chat.

**Verification command:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_03

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Other independent checks are finished; Task 3 remains blocked.

**Blocker:** `PUBLISHER_AUTHENTICITY_UNVERIFIED`

**Affected task:** TRACK_A / `TRACK_A_SOURCE_AUTHENTICITY`

**What happened:** Neither the current cash source nor dated master has completed genuine current-root source verification; retained master hashes alone confer no authority.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json, docs/evidence/task3_completion_baseline_20261023_01.json; command C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02; exit 2.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\source\cash_manifest.json and C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\source\master_manifest.json

**Who must act:** OPERATOR.

**Required action:**

1. Obtain detached publisher manifests binding the exact original source and master bytes, provider/symbol/schema and effective interval.
2. Use independently approved operator roots; filenames, URLs and locally self-signed artifacts are insufficient.

**How to fix it safely:** Configure the named local files; never share credentials, private keys, licences or source datasets in chat.

**Verification command:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_03

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Other independent checks are finished; Task 3 remains blocked.

**Blocker:** `HISTORICAL_RIGHTS_DOCUMENT_MISSING`

**Affected task:** TRACK_A / `TRACK_A_RIGHTS_APPROVAL`

**What happened:** No actual hash-matching rights document was loaded from operator policy paths.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json, docs/evidence/task3_completion_baseline_20261023_01.json; command C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02; exit 2.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\operator\rights_documents plus rights_policy.json documents mapping

**Who must act:** OPERATOR.

**Required action:**

1. Place the provider/source licence or permission document privately beneath rights_documents/.
2. Map its exact SHA256 to its relative path in rights_policy.json; retain scope and review evidence locally.

**How to fix it safely:** Configure the named local files; never share credentials, private keys, licences or source datasets in chat.

**Verification command:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_03

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Other independent checks are finished; Task 3 remains blocked.

**Blocker:** `HISTORICAL_RESEARCH_SCOPE_UNAPPROVED`

**Affected task:** TRACK_A / `TRACK_A_RIGHTS_APPROVAL`

**What happened:** No current operator-reviewed grant has matched the exact source/master hashes, symbol, publisher, research use and effective window.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json, docs/evidence/task3_completion_baseline_20261023_01.json; command C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02; exit 2.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\operator\rights_policy.json

**Who must act:** OPERATOR.

**Required action:**

1. Have the authorized operator review the actual rights document.
2. Supply grants with all fields in --help, HISTORICAL_RESEARCH permission, exact artifact hashes and nonrevoked, current validity; no dataset/HTTP-supplied approval.

**How to fix it safely:** Configure the named local files; never share credentials, private keys, licences or source datasets in chat.

**Verification command:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_03

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Other independent checks are finished; Task 3 remains blocked.

**Blocker:** `HISTORICAL_INSTRUMENT_MASTER_MISSING`

**Affected task:** TRACK_A / `TRACK_A_CASH_STUDY`

**What happened:** No eligible authentic dated master loaded. The retained raw Angel snapshot was previously rejected INVALID_NATIVE_MASTER and has no established effective-date authority.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json, docs/evidence/task3_completion_baseline_20261023_01.json; command C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02; exit 2.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\source\instrument_master.json

**Who must act:** OPERATOR.

**Required action:**

1. Provide original authentic V1 dated EQ master records covering the selected cash instrument and study dates.
2. Provide master_manifest.json; the existing native capture cannot substitute dated source authority.

**How to fix it safely:** Configure the named local files; never share credentials, private keys, licences or source datasets in chat.

**Verification command:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_03

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Other independent checks are finished; Task 3 remains blocked.

**Blocker:** `OPTION_EXECUTION_DATA_MISSING`

**Affected task:** TRACK_A / `TRACK_A_OPTION_STUDY`

**What happened:** No separate exact-contract historical option execution package was supplied or evaluated; cash inputs cannot satisfy this gate.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json, docs/evidence/task3_completion_baseline_20261023_01.json; command None; exit None.

**Why it is blocked:** A separately authorized local option request using tradepulse.option-request.v1 and genuine signed master/option-observations artifacts.

**Who must act:** OPERATOR.

**Required action:**

1. Retain actual dated CE/PE contracts, observed premiums and executable bid/ask/depth, timestamp-aligned underlying data, OI and prior-session closing baseline.
2. Use the existing run_frozen_study(..., option_request=..., data_mode='LIVE', rights_policy=...) API with separate approved roots/rights. This cash helper cannot verify an option study.

**How to fix it safely:** Configure the named local files; never share credentials, private keys, licences or source datasets in chat.

**Verification command:** NOT_APPLICABLE_TO_CASH_HELPER: separately configured run_frozen_study(..., option_request=..., data_mode=LIVE, rights_policy=...) required

**Expected result:** Separate genuine option source, rights, contract and execution evidence passes the existing option-study gates; cash input checks cannot resolve this dependency.

**Current status:** AWAITING_OPERATOR. Other independent checks are finished; Task 3 remains blocked.

**Blocker:** `EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED`

**Affected task:** TRACK_B / `TRACK_B_LOCAL_PREFLIGHT`

**What happened:** Local configuration contains zero explicitly configured instruments. Dhan credential presence checks now pass.

**Evidence:** docs/evidence/task3_resumption_dhan_preflight_20261023_01.json; command .venv_phase4\Scripts\python.exe -B dhan_feed_control.py; exit 1.

**Why it is blocked:** DHAN_FEED_INSTRUMENTS_JSON with exactly one permitted canonical metadata record backed by the project trusted provider/master mapping.

**Who must act:** OPERATOR.

**Required action:**

1. Select one permitted symbol using its verified Dhan security ID and exchange segment; do not invent or borrow another provider token.
2. Set the one-record JSON list in indian_fo_signal_bot_v1/.env or the documented process environment.
3. Keep Telegram dry-run and scheduler disabled; resolve the separate paper_sim profile blocker.
4. Run local preflight; only when all checks pass use the already-authorized --smoke --seconds 15 probe.

**How to fix it safely:** Configure the named local files; never share credentials, private keys, licences or source datasets in chat.

**Verification command:** .venv_phase4\Scripts\python.exe -B dhan_feed_control.py

**Expected result:** instrument_count 1 and canonical validation succeeds; with the separate runtime profile satisfied, status PASS and live_requests false.

**Current status:** AWAITING_OPERATOR. Other independent checks are finished; Task 3 remains blocked.

**Blocker:** `PAPER_SIM_SAFETY_PROFILE_REQUIRED`

**Affected task:** TRACK_B / `SAFE_RUNTIME_PROFILE`

**What happened:** Effective ACTIVE_BROKER is dhan. The Task 3 authorized probe requires paper_sim; Telegram is dry-run and scheduler disabled. No setting was changed by the agent.

**Evidence:** docs/evidence/task3_resumption_runtime_profile_20261023_01.json; command ['C:\\Users\\HP\\Downloads\\indian_fo_signal_bot_phase3b\\indian_fo_signal_bot_v1\\.venv_phase4\\Scripts\\python.exe', '-B', '-c', "from config import BotConfig; import json,sys; c=BotConfig(); ok=c.active_broker=='paper_sim' and c.telegram_dry_run is True and c.enable_background_scheduler is False; print(json.dumps(dict(status='PASS' if ok else 'BLOCKED',active_broker=c.active_broker,telegram_dry_run=c.telegram_dry_run,enable_background_scheduler=c.enable_background_scheduler,live_requests=False))); sys.exit(0 if ok else 1)"]; exit 1.

**Why it is blocked:** ACTIVE_BROKER=paper_sim in the application .env, preserving the newly supplied Dhan credential entries.

**Who must act:** OPERATOR.

**Required action:**

1. Change only ACTIVE_BROKER to paper_sim in indian_fo_signal_bot_v1/.env, or the process override if intentionally using one. The application file supplied this run's settings.
2. Retain TELEGRAM_DRY_RUN=true and ENABLE_BACKGROUND_SCHEDULER=false. Do not put credential values in chat or reports.
3. Run the exact safe-profile diagnostic recorded in the evidence, then local Dhan preflight; no live probe until the profile and instrument checks both pass.

**How to fix it safely:** Configure the named local files; never share credentials, private keys, licences or source datasets in chat.

**Verification command:** .venv_phase4\Scripts\python.exe -B -c "from config import BotConfig; c=BotConfig(); print(c.active_broker, c.telegram_dry_run, c.enable_background_scheduler); assert c.active_broker=='paper_sim' and c.telegram_dry_run is True and c.enable_background_scheduler is False"

**Expected result:** Effective active_broker paper_sim, telegram_dry_run true, enable_background_scheduler false; a separate one-instrument preflight must also pass.

**Current status:** AWAITING_OPERATOR. Other independent checks are finished; Task 3 remains blocked.


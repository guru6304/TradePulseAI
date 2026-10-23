**Blocker:** `HISTORICAL_CASH_DATA_MISSING`

**Affected task:** Track A / `TRACK_A_CASH_STUDY`

**What happened:** No original eligible historical cash OHLCV file exists at the selected input root.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json; command `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02`; exit 2; sanitized error `HISTORICAL_CASH_DATA_MISSING`.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\source\cash_observations.json is required by the existing gate.

**Who must act:** OPERATOR.

**Required action:**

1. Place the original signed cash-observations dataset under the selected input root; retain original bytes.
2. Supply cash_manifest.json and study_plan.json following --help. Do not synthesize bars or use the retained instrument snapshot as price history.

**How to fix it safely:** Configure the named files locally in the selected data/operator roots. Keep source documents, account data, credentials and private keys out of chat. Use a fresh --stage for the next receipt.

**Verification command:** `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02` (use a fresh --stage for helper checks).

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Independent verification continues; Task 3 remains blocked.

**Blocker:** `PUBLISHER_TRUST_ROOT_MISSING`

**Affected task:** Track A / `TRACK_A_SOURCE_AUTHENTICITY`

**What happened:** No usable independently approved publisher root loaded from the separate operator policy directory.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json; command `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02`; exit 2; sanitized error `PUBLISHER_TRUST_ROOT_MISSING`.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\operator\publisher_trust.json is required by the existing gate.

**Who must act:** OPERATOR.

**Required action:**

1. Obtain the independently approved publisher Ed25519 PUBLIC root through the operator's trusted process.
2. Store the TrustAnchorConfig constructor record in publisher_trust.json. Never provide private keys or install test fixture roots.

**How to fix it safely:** Configure the named files locally in the selected data/operator roots. Keep source documents, account data, credentials and private keys out of chat. Use a fresh --stage for the next receipt.

**Verification command:** `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02` (use a fresh --stage for helper checks).

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Independent verification continues; Task 3 remains blocked.

**Blocker:** `PUBLISHER_AUTHENTICITY_UNVERIFIED`

**Affected task:** Track A / `TRACK_A_SOURCE_AUTHENTICITY`

**What happened:** Neither the current cash source nor dated master has completed genuine current-root source verification; retained master hashes alone confer no authority.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json; command `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02`; exit 2; sanitized error `PUBLISHER_AUTHENTICITY_UNVERIFIED`.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\source\cash_manifest.json and C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\source\master_manifest.json is required by the existing gate.

**Who must act:** OPERATOR.

**Required action:**

1. Obtain detached publisher manifests binding the exact original source and master bytes, provider/symbol/schema and effective interval.
2. Use independently approved operator roots; filenames, URLs and locally self-signed artifacts are insufficient.

**How to fix it safely:** Configure the named files locally in the selected data/operator roots. Keep source documents, account data, credentials and private keys out of chat. Use a fresh --stage for the next receipt.

**Verification command:** `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02` (use a fresh --stage for helper checks).

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Independent verification continues; Task 3 remains blocked.

**Blocker:** `HISTORICAL_RIGHTS_DOCUMENT_MISSING`

**Affected task:** Track A / `TRACK_A_RIGHTS_APPROVAL`

**What happened:** No actual hash-matching rights document was loaded from operator policy paths.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json; command `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02`; exit 2; sanitized error `HISTORICAL_RIGHTS_DOCUMENT_MISSING`.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\operator\rights_documents plus rights_policy.json documents mapping is required by the existing gate.

**Who must act:** OPERATOR.

**Required action:**

1. Place the provider/source licence or permission document privately beneath rights_documents/.
2. Map its exact SHA256 to its relative path in rights_policy.json; retain scope and review evidence locally.

**How to fix it safely:** Configure the named files locally in the selected data/operator roots. Keep source documents, account data, credentials and private keys out of chat. Use a fresh --stage for the next receipt.

**Verification command:** `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02` (use a fresh --stage for helper checks).

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Independent verification continues; Task 3 remains blocked.

**Blocker:** `HISTORICAL_RESEARCH_SCOPE_UNAPPROVED`

**Affected task:** Track A / `TRACK_A_RIGHTS_APPROVAL`

**What happened:** No current operator-reviewed grant has matched the exact source/master hashes, symbol, publisher, research use and effective window.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json; command `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02`; exit 2; sanitized error `HISTORICAL_RESEARCH_SCOPE_UNAPPROVED`.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\operator\rights_policy.json is required by the existing gate.

**Who must act:** OPERATOR.

**Required action:**

1. Have the authorized operator review the actual rights document.
2. Supply grants with all fields in --help, HISTORICAL_RESEARCH permission, exact artifact hashes and nonrevoked, current validity; no dataset/HTTP-supplied approval.

**How to fix it safely:** Configure the named files locally in the selected data/operator roots. Keep source documents, account data, credentials and private keys out of chat. Use a fresh --stage for the next receipt.

**Verification command:** `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02` (use a fresh --stage for helper checks).

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Independent verification continues; Task 3 remains blocked.

**Blocker:** `HISTORICAL_INSTRUMENT_MASTER_MISSING`

**Affected task:** Track A / `TRACK_A_CASH_STUDY`

**What happened:** No eligible authentic dated master loaded. The retained raw Angel snapshot was previously rejected INVALID_NATIVE_MASTER and has no established effective-date authority.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json; command `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02`; exit 2; sanitized error `HISTORICAL_INSTRUMENT_MASTER_MISSING`.

**Why it is blocked:** C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.local\task3-history\source\instrument_master.json is required by the existing gate.

**Who must act:** OPERATOR.

**Required action:**

1. Provide original authentic V1 dated EQ master records covering the selected cash instrument and study dates.
2. Provide master_manifest.json; the existing native capture cannot substitute dated source authority.

**How to fix it safely:** Configure the named files locally in the selected data/operator roots. Keep source documents, account data, credentials and private keys out of chat. Use a fresh --stage for the next receipt.

**Verification command:** `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02` (use a fresh --stage for helper checks).

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Independent verification continues; Task 3 remains blocked.

**Blocker:** `OPTION_EXECUTION_DATA_MISSING`

**Affected task:** Track A / `TRACK_A_OPTION_STUDY`

**What happened:** No separate exact-contract historical option execution package was supplied or evaluated; cash inputs cannot satisfy this gate.

**Evidence:** docs/evidence/task3_completion_track_a_20261023_01_operator_check_02.json; command `C:\Users\HP\Downloads\indian_fo_signal_bot_phase3b\indian_fo_signal_bot_v1\.venv_phase4\Scripts\python.exe -B docs\evidence\task3_completion_track_a_20261023_01_verify.py --check-inputs --input-root .local/task3-history/source --operator-policy .local/task3-history/operator --stage operator_check_02`; exit 2; sanitized error `OPTION_EXECUTION_DATA_MISSING`.

**Why it is blocked:** A separately authorized local option request using tradepulse.option-request.v1 and genuine signed master/option-observations artifacts. is required by the existing gate.

**Who must act:** OPERATOR.

**Required action:**

1. Retain actual dated CE/PE contracts, observed premiums and executable bid/ask/depth, timestamp-aligned underlying data, OI and prior-session closing baseline.
2. Use the existing run_frozen_study(..., option_request=..., data_mode='LIVE', rights_policy=...) API with separate approved roots/rights. This cash helper cannot verify an option study.

**How to fix it safely:** Configure the named files locally in the selected data/operator roots. Keep source documents, account data, credentials and private keys out of chat. Use a fresh --stage for the next receipt.

**Verification command:** `PROGRAMMATIC_API: historical_study.run_frozen_study(engine, strategy_id='strat_3_option_apex_oi', symbol=approved_symbol, provider=approved_provider, backtest_config=option_config, plan=frozen_plan, option_request=original_option_request, data_mode='LIVE', rights_policy=operator_rights). The objects must be constructed from separately approved local inputs; this cash helper has no option-study CLI.` (use a fresh --stage for helper checks).

**Expected result:** The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.

**Current status:** AWAITING_OPERATOR. Independent verification continues; Task 3 remains blocked.


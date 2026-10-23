"""Offline operator entrypoint for existing historical qualification/study APIs.

Only explicit --run-cash-study opens the selected private research database.
Trust/rights files come from --operator-policy, separately from --input-root.
No keys, grants, source observations or approvals are generated.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
import verify_offline as verification

PREFIX = "task3_completion_track_a_20261023_01"
MAX_BYTES = 64 * 1024 * 1024

CONTRACT = """Run from the application directory. No input directories are created.
Recommended private locations (ignored by Git): --input-root .local/task3-history/source
  --operator-policy .local/task3-history/operator
  --private-db .local/task3-history/operator/study.sqlite3 (run mode only).
Input root files (original bytes, no credentials):
  cash_observations.json: {schema_version: tradepulse.cash-observations.v1, candles: [...]}
    Candles: aware ISO timestamp at completed 5m bar START, positive OHLC, nonnegative
    volume/open_interest, is_complete=true, data_mode=LIVE, is_simulated=false.
    Full configured NSE sessions; no fabricated corrections, duplicates or forward fill.
  cash_manifest.json: genuine detached tradepulse.publisher-manifest.v1 JSON,
    artifact_type=cash-observations, artifact_schema_version as above.
  instrument_master.json: tradepulse.instrument-master.v1 JSON with provider and
    dated EQ records: canonical symbol, exact provider identifier, exchange=NSE,
    instrument_type=EQ, multiplier=1, valid_from/valid_to (YYYY-MM-DD).
  master_manifest.json: genuine detached publisher manifest for instrument-master.
  study_plan.json: {schema_version: tradepulse.local-cash-study.v1, provider: ...,
    symbol: ..., instrument_token: ..., strategy_id: ..., training_sessions: N,
    test_sessions: M, optional step_sessions: M, backtest_config: {...},
    optional configured_holidays: [YYYY-MM-DD,...]}.
    Use an existing cash strategy; freeze plan/cost assumptions before evaluation.
    BacktestConfig keys follow backtest_engine.py; optional cost_model follows
    IndianCostModel. Scope/type/archive ID are set by this helper, never bypassed.
Separately operator-selected policy directory:
  publisher_trust.json: exact TrustAnchorConfig constructor object with
    policy_version (publisher_trust.TRUST_POLICY_VERSION), anchors, optional
    permitted_artifact_types/permitted_providers. Each independently approved root
    has publisher_id,key_id,algorithm=Ed25519,public_key_der_b64 (PUBLIC DER SPKI),
    aware not_before/not_after,revoked (bool). Never provide private signing keys.
  rights_policy.json: {grants:[...],documents:{document_SHA256:relative_document_path}}.
    Paths stay beneath this policy directory (e.g. rights_documents/licence.pdf).
    Each independently reviewed grant: rights_reference,publisher_id,provider,
    document_sha256,artifact_sha256s,symbols,allowed_uses containing HISTORICAL_RESEARCH,
    revoked=false,effective_from/effective_until,approved_at,review_due_at,
    approved_by,approval_reference. This is operator review, not legal verification.
--check-inputs validates supplied files without a database or study. Exit 2 means
operator evidence is missing/ineligible, not a software test failure. --run-cash-study
requires --private-db beneath the operator-policy directory; it reuses the existing
engine and retains exact originals/results in that private SQLite database. Public
receipts contain hashes/status/counts/metrics only, never document/source contents.
Use a fresh --stage on each run; prior evidence is never overwritten.
No HTTP trust configuration, network acquisition or broad market download occurs.
"""


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(raw):
    from historical_study import strict_json
    return strict_json(raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"))


def contained(base, relative):
    base = base.resolve()
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("INPUT_PATH_OUTSIDE_SELECTED_ROOT")
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError("INPUT_PATH_OUTSIDE_SELECTED_ROOT")
    return path


def read_file(base, relative):
    path = contained(base, relative)
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("INPUT_RESOURCE_LIMIT")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("INPUT_RESOURCE_LIMIT")
    return raw


def workspace_inventory():
    excluded = {".git", ".aws", ".codex", ".agents", ".local", ".credentials", ".secrets",
        "env", ".env", "private", ".private", "node_modules", "__pycache__"}
    names, parsed, unparsed, roots, grants, sources = [], [], [], [], [], []
    for directory, folders, files in os.walk(APP.parent):
        folders[:] = [name for name in folders if name.lower() not in excluded and
            not name.lower().startswith((".venv", "venv")) and not (Path(directory) / name).is_symlink()
            and not getattr(Path(directory) / name, "is_junction", lambda: False)()]
        for name in files:
            if name.startswith(".env"):
                continue
            path = Path(directory) / name
            if path.is_symlink():
                continue
            names.append(path)
            if path.parent != APP / "docs/evidence" or path.suffix != ".json":
                continue
            try:
                value = read_json(path.read_bytes())
                parsed.append(path.relative_to(APP).as_posix())
            except (ValueError, UnicodeError, OSError):
                unparsed.append(path.relative_to(APP).as_posix())
                continue
            if isinstance(value, dict):
                if value.get("schema_version") in ("tradepulse.cash-observations.v1",
                        "tradepulse.option-observations.v1", "tradepulse.publisher-manifest.v1",
                        "tradepulse.instrument-master.v1"):
                    sources.append(path.relative_to(APP).as_posix())
                if value.get("anchors"):
                    roots.append(path.relative_to(APP).as_posix())
                if value.get("grants"):
                    grants.append(path.relative_to(APP).as_posix())
    suffixes = {".csv", ".parquet", ".jsonl", ".ndjson", ".xlsx", ".pdf", ".pub", ".der", ".cer", ".pem", ".sqlite", ".sqlite3", ".db"}
    prior = APP / "docs/evidence/task3_track_a_input_discovery_verified.json"
    prior_report = read_json(prior.read_bytes())
    master = APP / prior_report["retained_public_master_candidate"]["path"]
    return dict(scope="NONPRIVATE_WORKSPACE_FILE_METADATA_AND_PUBLIC_EVIDENCE_SCHEMAS",
        candidate_data_document_key_database_paths=[p.relative_to(APP.parent).as_posix()
            for p in names if p.suffix.lower() in suffixes],
        parsed_public_receipts=len(parsed), unparsed_public_receipt_paths=unparsed,
        original_source_schema_files=sources, operator_anchor_records_in_public_evidence=roots,
        operator_rights_grants_in_public_evidence=grants,
        prior_discovery=dict(path=prior.relative_to(APP).as_posix(), sha256=sha(prior.read_bytes())),
        retained_master=dict(path=master.relative_to(APP).as_posix(), stored_sha256=sha(master.read_bytes()),
            prior_bytes_unchanged=sha(master.read_bytes()) == prior_report["retained_public_master_candidate"]["stored_sha256"],
            prior_parser_status="REJECTED", prior_parser_reason="INVALID_NATIVE_MASTER",
            previous_observed_master_records=153621, previous_nse_eq_identity_rows=2728,
            price_observations=False, publisher_authenticity="NOT_ESTABLISHED"),
        scope_limitation="No excluded private locations, .env values or operational database contents read.")


def blocker(code, gate, finding, requirement, steps, command, evidence, timestamp, *, classification="OPERATOR_INPUT", related=()):
    return dict(blocker_code=code, classification=classification, severity="BLOCKING",
        affected_track="TRACK_A", affected_acceptance_gate=gate, status="AWAITING_OPERATOR",
        observed_finding=finding, evidence_paths=evidence, exact_failed_command=command,
        exit_code=2, redacted_error=code, root_cause_confidence="HIGH",
        required_input_or_correction=requirement, who_must_act="OPERATOR",
        safe_resolution_steps=steps, verification_command_after_resolution=command,
        expected_result_after_resolution="The affected gate passes on genuine supplied evidence; current receipt records source/config hashes and no unresolved blocker for this gate.",
        related_blockers=list(related), timestamp=timestamp)


def evaluate(args):
    from historical_study import OperatorRightsPolicy, qualify_artifact, aware, walk_forward_plan
    from instrument_archive import prepare_archive, resolve_archives
    from publisher_trust import TrustAnchorConfig
    now = datetime.now(timezone.utc)
    data_root, policy_root = args.input_root.resolve(), args.operator_policy.resolve()
    data = {name: read_file(data_root, name) for name in ("cash_observations.json", "cash_manifest.json",
        "instrument_master.json", "master_manifest.json", "study_plan.json")}
    policy = {name: read_file(policy_root, name) for name in ("publisher_trust.json", "rights_policy.json")}
    checks, trust, rights, documents = {}, None, None, {}
    if policy["publisher_trust.json"]:
        trust = TrustAnchorConfig(**read_json(policy["publisher_trust.json"]))
    if policy["rights_policy.json"]:
        operator_record = read_json(policy["rights_policy.json"])
        for checksum, path in operator_record["documents"].items():
            raw = read_file(policy_root, path)
            if raw is None or sha(raw) != checksum:
                checks["rights_document_integrity"] = "MISSING_OR_MISMATCH"
            else:
                documents[checksum] = raw
        rights = OperatorRightsPolicy(operator_record["grants"], documents)
    present = {name: raw is not None and bool(raw) for name, raw in {**data, **policy}.items()}
    checks.update(input_presence=present, source_hashes={name: sha(raw) for name, raw in data.items() if raw},
        operator_policy_hashes={name: sha(raw) for name, raw in policy.items() if raw},
        original_price_candle_count=0, coverage_start=None, coverage_end=None, quality_status="NOT_ASSESSED",
        publisher_qualifications=[], dated_master_status="NOT_ASSESSED", identity_status="NOT_ASSESSED", study=None)
    if data["study_plan.json"] and data["cash_observations.json"]:
        plan_input = read_json(data["study_plan.json"])
        if plan_input.get("schema_version") != "tradepulse.local-cash-study.v1":
            raise ValueError("STUDY_PLAN_SCHEMA_INVALID")
        from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel, STRATEGY_BACKTEST_ELIGIBILITY
        if plan_input.get("strategy_id") not in STRATEGY_BACKTEST_ELIGIBILITY or plan_input["strategy_id"] == "strat_3_option_apex_oi":
            raise ValueError("SUPPORTED_CASH_STRATEGY_REQUIRED")
        config_values = dict(plan_input["backtest_config"])
        if "cost_model" in config_values:
            config_values["cost_model"] = IndianCostModel(**config_values["cost_model"])
        config_values.update(execution_scope="HISTORICAL_RESEARCH", instrument_type="EQ")
        cfg = BacktestConfig(**config_values)
        cfg.validate()
        observations = read_json(data["cash_observations.json"])
        bars = observations.get("candles")
        if observations.get("schema_version") != "tradepulse.cash-observations.v1" or not isinstance(bars, list) or not bars:
            raise ValueError("CASH_OBSERVATIONS_SCHEMA_INVALID")
        first = min(aware(row["timestamp"]) for row in bars)
        last = max(aware(row["timestamp"]) for row in bars) + timedelta(minutes=5)
        checks.update(original_price_candle_count=len(bars), coverage_start=first.isoformat(), coverage_end=last.isoformat(),
            provider=plan_input["provider"], symbol=plan_input["symbol"], instrument_token=plan_input["instrument_token"])
        for source_name, manifest_name, kind, schema in (
                ("cash_observations.json", "cash_manifest.json", "cash-observations", "tradepulse.cash-observations.v1"),
                ("instrument_master.json", "master_manifest.json", "instrument-master", "tradepulse.instrument-master.v1")):
            if data[source_name] and data[manifest_name]:
                value = qualify_artifact(data[source_name], data[manifest_name].decode("utf-8-sig"),
                    trust_config=trust, rights_policy=rights, provider=plan_input["provider"], exchange="NSE",
                    segment="NSE_EQUITY_INTRADAY", symbol=plan_input["symbol"], artifact_type=kind,
                    schema_version=schema, coverage_start=first.isoformat(), coverage_end=last.isoformat(),
                    verification_time=now.isoformat())
                checks["publisher_qualifications"].append(dict(source_name=source_name, allowed=value["allowed"],
                    publisher_verified=value.get("publisher_verification", {}).get("allowed", False),
                    rights_verified=value.get("rights", {}).get("allowed", False), missing_evidence=value["missing_evidence"],
                    artifact_sha256=value["artifact_sha256"]))
        if data["instrument_master.json"]:
            master = prepare_archive(data["instrument_master.json"], plan_input["provider"], "instrument_master.json", "EXPLICIT_OPERATOR_LOCAL_INPUT")
            checks["dated_master_status"] = master["status"]
            if master["status"] == "ELIGIBLE_LOCAL_RESEARCH" and data["master_manifest.json"] and trust is not None:
                master["original_bytes"] = data["instrument_master.json"]
                master["metadata"]["publisher_manifest_json"] = data["master_manifest.json"].decode("utf-8-sig")
                try:
                    resolve_archives([master], plan_input["provider"], plan_input["symbol"], plan_input["instrument_token"],
                        "NSE", "EQ", first.date().isoformat(), last.date().isoformat(), trust_config=trust, verification_time=now)
                    checks["identity_status"] = "RESOLVED_DATED_AUTHENTIC_IDENTITY"
                except ValueError as exc:
                    checks["identity_status"] = "REJECTED"
                    reason = getattr(exc, "rejection", {}).get("reason_code", "DATED_IDENTITY_REJECTED")
                    checks["identity_reason"] = reason if re.fullmatch(r"[A-Z0-9_]{1,100}", str(reason)) else "DATED_IDENTITY_REJECTED"
        from historical_data import validate_and_prepare_historical_dataset
        quality = validate_and_prepare_historical_dataset(bars, plan_input["symbol"], "NSE_EQUITY_INTRADAY", "NSE",
            plan_input["provider"], plan_input["instrument_token"], interval_min=5, data_mode="LIVE",
            reference_time_ist=now, retrieved_at_ist=now, configured_holidays=plan_input.get("configured_holidays", []),
            allow_identical_duplicates=False, sort_chronologically=False, reject_forming_candles=True)["manifest"]
        checks["quality_status"] = quality["quality_status"]
        checks["quality_counts"] = {key: quality[key] for key in ("bars_count", "sessions_count", "missing_bars_count", "duplicate_bars_coalesced", "filtered_forming_count")}
        plan = walk_forward_plan(sorted({aware(bar["timestamp"]).date().isoformat() for bar in bars}),
            training_sessions=plan_input["training_sessions"], test_sessions=plan_input["test_sessions"],
            step_sessions=plan_input.get("step_sessions"))
        qualified = (len(checks["publisher_qualifications"]) == 2 and all(q["allowed"] for q in checks["publisher_qualifications"])
            and checks["dated_master_status"] == "ELIGIBLE_LOCAL_RESEARCH" and quality["quality_status"] == "COMPLETE_VERIFIED"
            and checks["identity_status"] == "RESOLVED_DATED_AUTHENTIC_IDENTITY")
        if args.run_cash_study and qualified:
            if not args.private_db:
                raise ValueError("EXPLICIT_PRIVATE_DATABASE_REQUIRED")
            # File path, parents and symlinks must stay beneath the separate
            # operator policy root. The dataset cannot select its own policy.
            private_db = Path(args.private_db).resolve()
            if not private_db.is_relative_to(policy_root) or private_db == policy_root:
                raise ValueError("PRIVATE_DATABASE_OUTSIDE_OPERATOR_ROOT")
            from config import BotConfig
            from storage import SQLitePersistenceStore
            from historical_study import run_frozen_study
            with SQLitePersistenceStore(str(private_db)) as store:
                saved = store.ingest_instrument_master_bytes(data["instrument_master.json"], plan_input["provider"],
                    "instrument_master.json", "EXPLICIT_OPERATOR_LOCAL_INPUT")
                cfg.historical_instrument_archive_id = saved["archive_id"]
                engine = DeterministicBacktestEngine(BotConfig(active_broker="paper_sim", telegram_dry_run=True,
                    enable_background_scheduler=False, configured_holidays=plan_input.get("configured_holidays", [])), store,
                    publisher_trust_config=trust, publisher_manifests={saved["archive_id"]: data["master_manifest.json"].decode("utf-8-sig")})
                result = run_frozen_study(engine, strategy_id=plan_input["strategy_id"], symbol=plan_input["symbol"],
                    provider=plan_input["provider"], backtest_config=cfg, plan=plan, candles=bars,
                    data_mode="LIVE", instrument_token=plan_input["instrument_token"], rights_policy=rights,
                    cash_source=dict(original_bytes=data["cash_observations.json"], manifest_json=data["cash_manifest.json"].decode("utf-8-sig")))
                checks["study"] = dict(status=result["real_historical_study_status"], study_id=result["study_id"],
                    input_evidence_id=result["input_evidence_id"], result_evidence_id=result.get("result_evidence_id"),
                    private_database=str(private_db), missing_evidence=result["missing_evidence"],
                    folds=[dict(train_sessions=fold["train_sessions"], test_sessions=fold["test_sessions"], metrics=fold["run"]["metrics"])
                        for fold in result["folds"]], empirical_performance_claim_allowed=False)
    return checks, trust, rights, documents


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=CONTRACT,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-inputs", action="store_true")
    mode.add_argument("--run-cash-study", action="store_true")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--operator-policy", type=Path, required=True)
    parser.add_argument("--private-db", type=Path)
    parser.add_argument("--stage", default="current")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_]{1,40}", args.stage):
        parser.error("Use a short lowercase new stage")
    input_selected, policy_selected = args.input_root.resolve(), args.operator_policy.resolve()
    if input_selected.is_relative_to(policy_selected) or policy_selected.is_relative_to(input_selected):
        parser.error("Data and operator-controlled policy roots must be separate, non-nested directories")
    prefix = APP / "docs/evidence" / (PREFIX + "_" + args.stage)
    for suffix in (".json", "_blockers.md"):
        if prefix.with_name(prefix.name + suffix).exists():
            parser.error("Evidence stage exists; choose a fresh --stage")
    before = verification.source_snapshot(APP)
    timestamp = verification.timestamp()
    command = subprocess.list2cmdline([sys.executable, "-B", str(Path(__file__).relative_to(APP))] + sys.argv[1:])
    with ExitStack() as stack:
        verification.offline_network(stack)
        inventory = workspace_inventory()
        try:
            checks, trust, rights, documents = evaluate(args)
            error = None
        except (ValueError, TypeError, KeyError, OSError) as exc:
            checks, trust, rights, documents = {}, None, None, {}
            error = dict(error_type=type(exc).__name__, reason="SUPPLIED_LOCAL_INPUT_SCHEMA_PATH_OR_VALIDATION_REJECTED")
    sources = checks.get("publisher_qualifications", [])
    source_ok = len(sources) == 2 and all(row["publisher_verified"] for row in sources)
    rights_ok = len(sources) == 2 and all(row["rights_verified"] for row in sources)
    study_ok = (checks.get("study") or {}).get("status") == "QUALIFIED_REPRODUCIBLE_BOUNDED_STUDY"
    # Options remain a separate, unmet data dependency in this cash-only helper.
    input_root, policy_root = args.input_root.resolve(), args.operator_policy.resolve()
    definitions = []
    presence = checks.get("input_presence", {})
    def add(code, gate, finding, need, steps, classification="OPERATOR_INPUT", related=()):
        definitions.append((code, gate, finding, need, steps, classification, related))
    if not presence.get("cash_observations.json"):
        add("HISTORICAL_CASH_DATA_MISSING", "TRACK_A_CASH_STUDY", "No original eligible historical cash OHLCV file exists at the selected input root.",
            str(input_root / "cash_observations.json"), ["Place the original signed cash-observations dataset under the selected input root; retain original bytes.",
                "Supply cash_manifest.json and study_plan.json following --help. Do not synthesize bars or use the retained instrument snapshot as price history."])
    if trust is None or not getattr(trust, "_anchors", []):
        add("PUBLISHER_TRUST_ROOT_MISSING", "TRACK_A_SOURCE_AUTHENTICITY", "No usable independently approved publisher root loaded from the separate operator policy directory.",
            str(policy_root / "publisher_trust.json"), ["Obtain the independently approved publisher Ed25519 PUBLIC root through the operator's trusted process.",
                "Store the TrustAnchorConfig constructor record in publisher_trust.json. Never provide private keys or install test fixture roots."], related=("PUBLISHER_AUTHENTICITY_UNVERIFIED",))
    if not source_ok:
        add("PUBLISHER_AUTHENTICITY_UNVERIFIED", "TRACK_A_SOURCE_AUTHENTICITY", "Neither the current cash source nor dated master has completed genuine current-root source verification; retained master hashes alone confer no authority.",
            str(input_root / "cash_manifest.json") + " and " + str(input_root / "master_manifest.json"),
            ["Obtain detached publisher manifests binding the exact original source and master bytes, provider/symbol/schema and effective interval.",
                "Use independently approved operator roots; filenames, URLs and locally self-signed artifacts are insufficient."], related=("PUBLISHER_TRUST_ROOT_MISSING",))
    if not documents:
        add("HISTORICAL_RIGHTS_DOCUMENT_MISSING", "TRACK_A_RIGHTS_APPROVAL", "No actual hash-matching rights document was loaded from operator policy paths.",
            str(policy_root / "rights_documents") + " plus rights_policy.json documents mapping", ["Place the provider/source licence or permission document privately beneath rights_documents/.",
                "Map its exact SHA256 to its relative path in rights_policy.json; retain scope and review evidence locally."], classification="DATA_RIGHTS")
    if not rights_ok:
        add("HISTORICAL_RESEARCH_SCOPE_UNAPPROVED", "TRACK_A_RIGHTS_APPROVAL", "No current operator-reviewed grant has matched the exact source/master hashes, symbol, publisher, research use and effective window.",
            str(policy_root / "rights_policy.json"), ["Have the authorized operator review the actual rights document.",
                "Supply grants with all fields in --help, HISTORICAL_RESEARCH permission, exact artifact hashes and nonrevoked, current validity; no dataset/HTTP-supplied approval."], classification="DATA_RIGHTS", related=("HISTORICAL_RIGHTS_DOCUMENT_MISSING",))
    if checks.get("dated_master_status") != "ELIGIBLE_LOCAL_RESEARCH":
        add("HISTORICAL_INSTRUMENT_MASTER_MISSING", "TRACK_A_CASH_STUDY", "No eligible authentic dated master loaded. The retained raw Angel snapshot was previously rejected INVALID_NATIVE_MASTER and has no established effective-date authority.",
            str(input_root / "instrument_master.json"), ["Provide original authentic V1 dated EQ master records covering the selected cash instrument and study dates.",
                "Provide master_manifest.json; the existing native capture cannot substitute dated source authority."], related=("PUBLISHER_AUTHENTICITY_UNVERIFIED",))
    elif checks.get("identity_status") == "REJECTED":
        add("HISTORICAL_INSTRUMENT_IDENTITY_UNRESOLVED", "TRACK_A_CASH_STUDY", "Supplied dated metadata failed the existing exact provider/symbol/identifier/period resolver.",
            str(input_root / "instrument_master.json"), ["Supply the authentic dated master/manifest matching the exact selected provider, canonical cash symbol and identifier.",
                "Do not edit signed source bytes or infer historical identity from current tokens."], related=("PUBLISHER_AUTHENTICITY_UNVERIFIED",))
    if checks.get("quality_status") not in (None, "NOT_ASSESSED", "COMPLETE_VERIFIED"):
        add("HISTORICAL_COVERAGE_INSUFFICIENT", "TRACK_A_CASH_STUDY", "Supplied cash data failed the existing complete-session quality gate.",
            str(input_root / "cash_observations.json"), ["Obtain a sufficiently complete authorized original dataset; do not forward-fill missing sessions or bars."])
    add("OPTION_EXECUTION_DATA_MISSING", "TRACK_A_OPTION_STUDY", "No separate exact-contract historical option execution package was supplied or evaluated; cash inputs cannot satisfy this gate.",
        "A separately authorized local option request using tradepulse.option-request.v1 and genuine signed master/option-observations artifacts.",
        ["Retain actual dated CE/PE contracts, observed premiums and executable bid/ask/depth, timestamp-aligned underlying data, OI and prior-session closing baseline.",
            "Use the existing run_frozen_study(..., option_request=..., data_mode='LIVE', rights_policy=...) API with separate approved roots/rights. This cash helper cannot verify an option study."])
    evidence_path = prefix.with_suffix(".json").relative_to(APP).as_posix()
    evidence = [evidence_path, "docs/evidence/task3_completion_baseline_20261023_01.json"]
    blockers = [blocker(code, gate, finding, need, steps, command, evidence, timestamp,
        classification=kind, related=related) for code, gate, finding, need, steps, kind, related in definitions]
    for item in blockers:
        item["required_for_current_cash_acceptance"] = item["blocker_code"] != "OPTION_EXECUTION_DATA_MISSING"
        if item["blocker_code"] == "OPTION_EXECUTION_DATA_MISSING":
            item["severity"] = "DEFERRED_DEPENDENCY"
            item["verification_command_after_resolution"] = (
                "PROGRAMMATIC_API: historical_study.run_frozen_study(engine, strategy_id='strat_3_option_apex_oi', "
                "symbol=approved_symbol, provider=approved_provider, backtest_config=option_config, plan=frozen_plan, "
                "option_request=original_option_request, data_mode='LIVE', rights_policy=operator_rights). "
                "The objects must be constructed from separately approved local inputs; this cash helper has no option-study CLI.")
    after = verification.source_snapshot(APP)
    cash_input_ok = (source_ok and rights_ok and checks.get("dated_master_status") == "ELIGIBLE_LOCAL_RESEARCH"
        and checks.get("quality_status") == "COMPLETE_VERIFIED" and checks.get("identity_status") == "RESOLVED_DATED_AUTHENTIC_IDENTITY")
    code = 0 if cash_input_ok and (not args.run_cash_study or study_ok) and not error and before == after else 2
    for item in blockers:
        item["exit_code"] = code
    result = dict(schema_version="tradepulse.task3-operator-historical-check.v1", timestamp=timestamp,
        source_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip(),
        command=command, exit_code=code, mode="RUN_CASH_STUDY" if args.run_cash_study else "CHECK_INPUTS",
        source_before=before, source_after=after, source_unchanged=before == after,
        inventory=inventory, input_checks=checks, error=error, blockers=blockers,
        acceptance=dict(TRACK_A_SOURCE_AUTHENTICITY="PASS" if source_ok else "BLOCKED",
            TRACK_A_RIGHTS_APPROVAL="PASS" if rights_ok else "BLOCKED",
            TRACK_A_CASH_STUDY="PASS" if study_ok else "NOT_ATTEMPTED" if cash_input_ok else "BLOCKED",
            TRACK_A_OPTION_STUDY="BLOCKED_SEPARATE_DATA_DEPENDENCY"),
        authentic_cash_study_executed=checks.get("study") is not None, external_network_permitted=False,
        operational_database_opened=False, private_research_database_opened=checks.get("study") is not None,
        operator_root_or_rights_created=False, existing_evidence_overwritten=False,
        track_a_mandatory_status="ACCEPTED" if study_ok else "INPUT_CHECKS_PASSED_STUDY_NOT_RUN" if cash_input_ok else "BLOCKED_AWAITING_OPERATOR_INPUT")
    with prefix.with_suffix(".json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    with prefix.with_name(prefix.name + "_blockers.md").open("x", encoding="utf-8") as handle:
        for item in blockers:
            handle.write("**Blocker:** `" + item["blocker_code"] + "`\n\n")
            handle.write("**Affected task:** Track A / `" + item["affected_acceptance_gate"] + "`\n\n")
            handle.write("**What happened:** " + item["observed_finding"] + "\n\n")
            handle.write("**Evidence:** " + evidence_path + "; command `" + command + "`; exit " + str(code) + "; sanitized error `" + item["redacted_error"] + "`.\n\n")
            handle.write("**Why it is blocked:** " + item["required_input_or_correction"] + " is required by the existing gate.\n\n")
            handle.write("**Who must act:** OPERATOR.\n\n**Required action:**\n\n")
            for index, step in enumerate(item["safe_resolution_steps"], 1):
                handle.write(str(index) + ". " + step + "\n")
            handle.write("\n**How to fix it safely:** Configure the named files locally in the selected data/operator roots. Keep source documents, account data, credentials and private keys out of chat. Use a fresh --stage for the next receipt.\n\n")
            handle.write("**Verification command:** `" + item["verification_command_after_resolution"] + "` (use a fresh --stage for helper checks).\n\n")
            handle.write("**Expected result:** " + item["expected_result_after_resolution"] + "\n\n")
            handle.write("**Current status:** AWAITING_OPERATOR. Independent verification continues; Task 3 remains blocked.\n\n")
    print(json.dumps(dict(receipt=evidence_path, exit_code=code, acceptance=result["acceptance"],
        blocker_codes=[row["blocker_code"] for row in blockers], source_unchanged=before == after)))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

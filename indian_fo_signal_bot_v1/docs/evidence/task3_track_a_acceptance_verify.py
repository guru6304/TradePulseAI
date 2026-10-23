"""Read local public candidates; execute existing offline Track A tests only.

Writes task3 evidence exclusively. Never initializes an operational store, obtains
data, installs roots/approvals, accesses secrets, or claims fixture study acceptance.
"""
from collections import Counter
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import gc
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import warnings
import zipfile

APP = Path(__file__).resolve().parents[2]
WORKSPACE = APP.parent
sys.path.insert(0, str(APP))
import verify_offline as verification


def checksum(raw):
    return hashlib.sha256(raw).hexdigest()


def save(name, result):
    target = APP / "docs/evidence" / name
    with target.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    return dict(path=target.relative_to(APP).as_posix(), sha256=checksum(target.read_bytes()))


def discover():
    excluded = {".git", ".aws", ".codex", "node_modules", "__pycache__", ".agents"}
    files, exclusions = [], []
    for folder, directories, names in os.walk(WORKSPACE):
        for name in list(directories):
            if name in excluded or name.lower().startswith((".venv", "venv")):
                exclusions.append((Path(folder) / name).relative_to(WORKSPACE).as_posix())
                directories.remove(name)
        files.extend(Path(folder) / name for name in names if not name.startswith(".env"))
    data_suffixes = {".csv", ".parquet", ".jsonl", ".ndjson", ".xlsx"}
    databases = {".db", ".sqlite", ".sqlite3"}
    documents = {".pdf", ".doc", ".docx", ".rtf"}
    keys = {".pub", ".der", ".cer", ".pem"}
    paths = lambda items: sorted(p.relative_to(WORKSPACE).as_posix() for p in items)
    metadata_files, source_files, roots, grants = [], [], [], []
    # Structured data records are inspected only in public project evidence and
    # by schema. No .env, arbitrary private file or operational DB is opened.
    for path in files:
        if path.suffix.lower() != ".json" or APP / "docs/evidence" not in path.parents:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError, OSError):
            continue
        metadata_files.append(path)
        if not isinstance(value, dict):
            continue
        schema = value.get("schema_version")
        if schema in ("tradepulse.cash-observations.v1", "tradepulse.option-observations.v1",
                      "tradepulse.instrument-master.v1", "tradepulse.publisher-manifest.v1"):
            source_files.append(path)
        if isinstance(value.get("anchors"), list) and value["anchors"]:
            roots.append(path)
        if isinstance(value.get("grants"), list) and value["grants"]:
            grants.append(path)
    candidate_members = []
    for path in files:
        if path.suffix.lower() != ".zip" or APP / "docs/evidence" not in path.parents:
            continue
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if Path(name).suffix.lower() in data_suffixes
                       or Path(name).suffix.lower() == ".json" and "manifest" not in Path(name).name.lower()]
            candidate_members.append(dict(archive=path.relative_to(APP).as_posix(),
                candidate_data_members=members))
    result = dict(scope="WORKSPACE_NONPRIVATE_FILE_INVENTORY_AND_PUBLIC_EVIDENCE_SCHEMA_INSPECTION",
        workspace=str(WORKSPACE), files_seen=len(files), excluded_directories=sorted(exclusions),
        environment_file_values_read=False, operational_database_contents_read=False,
        standalone_data_files=paths(p for p in files if p.suffix.lower() in data_suffixes),
        operational_database_files=paths(p for p in files if p.suffix.lower() in databases),
        possible_rights_document_files=paths(p for p in files if p.suffix.lower() in documents),
        possible_public_key_files=paths(p for p in files if p.suffix.lower() in keys),
        inspected_public_json_receipts=len(metadata_files), actual_source_schema_files=paths(source_files),
        nonempty_operator_anchor_records_discovered=paths(roots),
        nonempty_operator_rights_grant_records_discovered=paths(grants), software_archive_member_inspection=candidate_members,
        scope_limitation="Does not establish absence of private material outside this workspace or inspect excluded credentials.",
        eligible_cash_instruments=0, qualifying_cash_candle_count=0, qualifying_option_observation_count=0,
        historical_cash_coverage_start=None, historical_cash_coverage_end=None,
        authentic_cash_study_executed=False, authentic_option_study_executed=False)
    capture_path = APP / "docs/evidence/angel_public_master_20261019_capture.json"
    artifact_path = APP / "docs/evidence/angel_public_master_20261019.json.gz"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    compressed = artifact_path.read_bytes()
    with gzip.open(artifact_path, "rb") as handle:
        raw = handle.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("Retained master exceeds existing archive bounds")
    rows = json.loads(raw)
    from instrument_archive import prepare_archive
    from source_qualification import assess_source_evidence
    candidate = prepare_archive(raw, "angelone", "angel_public_master_20261019.json",
        "EXISTING_UNATTESTED_PUBLIC_CAPTURE_REASSESSED_LOCALLY_NO_NETWORK",
        captured_at=capture["captured_at"], source_url=capture["source_url"])
    assessment = assess_source_evidence(candidate, raw, trust_config=None,
        verification_time=datetime.now(timezone.utc))
    result["retained_public_master_candidate"] = dict(
        path=artifact_path.relative_to(APP).as_posix(), provider="angelone",
        captured_at_claim=capture["captured_at"], original_bytes=len(raw), compressed_bytes=len(compressed),
        original_sha256=checksum(raw), stored_sha256=checksum(compressed),
        existing_capture_receipt_hashes_match=(checksum(raw) == capture["original_sha256"]
            and checksum(compressed) == capture["stored_sha256"]),
        input_record_count=len(rows), provider_segments=dict(Counter(str(row.get("exch_seg")) for row in rows)),
        observed_nse_cash_rows=sum(row.get("exch_seg") == "NSE" and
            str(row.get("symbol", "")).endswith("-EQ") for row in rows),
        observed_nfo_types=dict(Counter(str(row.get("instrumenttype")) for row in rows if row.get("exch_seg") == "NFO")),
        archive_status=candidate["status"], normalized_record_count=candidate["record_count"],
        archive_validation=candidate["validation"], archive_id=candidate["archive_id"],
        publisher_authenticity=assessment["publisher_authenticity"]["status"],
        historical_eligibility=assessment["historical_eligibility"],
        schema_version=candidate["metadata"]["schema_version"],
        effective_date_basis=candidate["metadata"]["effective_date_basis"],
        actual_price_observations=False, corporate_actions_or_adjustment_history_supplied=False,
        interpretation="Retained unqualified instrument snapshot; hash matches local receipt only, not independently authenticated provider publication.")
    result["missing_evidence"] = ["ORIGINAL_HISTORICAL_CASH_OHLCV_AND_SIGNED_MANIFEST",
        "INDEPENDENTLY_APPROVED_PUBLISHER_ED25519_ROOTS",
        "ACTUAL_RIGHTS_DOCUMENT_AND_CURRENT_OPERATOR_APPROVAL_SCOPE",
        "DATED_INSTRUMENT_MASTER_WITH_AUTHENTIC_EFFECTIVE_PERIOD",
        "EXACT_OPTION_PREMIUM_BID_ASK_DEPTH_OI_AND_PRIOR_CLOSING_BASELINE"]
    return result


started, before = verification.timestamp(), verification.source_snapshot(APP)
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
unraisable = []
log = APP / "docs/evidence/task3_track_a_focused_current.txt"
with log.open("x", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream), ExitStack() as stack:
    verification.offline_network(stack)
    stack.enter_context(patch("sys.unraisablehook", side_effect=lambda event: unraisable.append(type(event.exc_value).__name__)))
    warnings.simplefilter("error", ResourceWarning)
    discovery = discover()
    discovery_receipt = save("task3_track_a_input_discovery.json", discovery)
    modules = ["test_historical_study", "test_option_execution", "test_phase4_acceptance", "test_publisher_trust"]
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    expected = list(verification.case_ids(suite))
    timed = time.monotonic()
    outcome = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=verification.ExecutionResult).run(suite)
    elapsed = time.monotonic() - timed
    tests = verification.python_result(outcome, expected)
    gc.collect()
after = verification.source_snapshot(APP)
passed = tests["status"] == "PASS" and before == after and not unraisable
receipt = dict(scope="TASK3_CURRENT_OFFLINE_QUALIFICATION_AND_LOCAL_INPUT_DISCOVERY_NO_REAL_STUDY_ACCEPTANCE",
    command=[sys.executable, "-B", "-W", "error::ResourceWarning", "docs/evidence/task3_track_a_acceptance_verify.py"],
    started_at=started, completed_at=verification.timestamp(), source_revision=head,
    source_before=before, source_after=after, source_unchanged=before == after,
    python=tests, duration_seconds=round(elapsed, 3), unraisable_errors=unraisable,
    logs={log.relative_to(APP).as_posix(): checksum(log.read_bytes())}, input_discovery=discovery_receipt,
    acceptance=dict(OFFLINE_QUALIFICATION_TESTS="PASS" if passed else "BLOCKED",
        AUTHENTIC_SOURCE_VERIFICATION="BLOCKED", RIGHTS_AND_SCOPE_VERIFICATION="BLOCKED",
        CASH_HISTORICAL_STUDY="BLOCKED", OPTION_HISTORICAL_STUDY="BLOCKED"),
    external_network_requests=0, real_source_or_study_acceptance_claimed=False,
    missing_evidence=discovery["missing_evidence"], status="PASS" if passed else "FAIL", exit_code=0 if passed else 1)
target = save("task3_track_a_focused_current.json", receipt)
print(json.dumps(dict(status=receipt["status"], source_revision=head, tests=tests["executed"],
    passed=tests["passed"], failures=tests["failures"], errors=tests["errors"], skipped=tests["skipped"],
    duration_seconds=receipt["duration_seconds"], acceptance=receipt["acceptance"], receipt=target,
    discovery=discovery_receipt), indent=2))
sys.exit(receipt["exit_code"])

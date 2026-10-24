"""Read-only independent ZIP/current-source/retained-proof inspection.

Uses only the standard library. No application import, provider, transport,
credential/configuration read, database access, extraction or test execution.
Only a unique new JSON receipt is written; an existing receipt is never replaced.
"""
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile


APP = Path(__file__).resolve().parents[2]
EVIDENCE = APP / "docs" / "evidence"
ARCHIVE = EVIDENCE / "phase45_release_20261024_01.zip"
STRICT = EVIDENCE / "master_phase45_20261024_03.json"
BROWSER = EVIDENCE / "phase45_browser_20261024_04.json"
OUTPUT = EVIDENCE / "phase45_release_independent_20261024_01.json"
EXPECTED_ARCHIVE_SHA = "6646949db0219f8921700b2cf4aae0d51667538491e1f9e06f01294f32517d1e"


def require(condition, code):
    if not condition:
        raise ValueError(code)


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha_file(path):
    return sha_bytes(path.read_bytes())


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def safe_relative(name):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name,
            "UNSAFE_RELATIVE_PATH")
    pure = PurePosixPath(name)
    require(not pure.is_absolute() and pure.as_posix() == name
            and all(part not in ("", ".", "..") for part in pure.parts), "UNSAFE_RELATIVE_PATH")
    path = APP.joinpath(*pure.parts)
    require(path.resolve().is_relative_to(APP.resolve()) and not path.is_symlink(), "ESCAPED_OR_SYMLINK_PATH")
    return path


def source_map():
    # Independently reproduce the documented canonical source inventory without
    # importing the verifier or any application module.
    paths = (list(APP.glob("*.py")) + list(APP.glob("test_*.js"))
             + list((APP / "public").rglob("*"))
             + [APP / "requirements.txt", APP / ".env.example"])
    return {path.relative_to(APP).as_posix(): sha_file(path)
            for path in sorted(paths) if path.is_file()}


def strict_proof(current):
    value = load_json(STRICT)
    require(value.get("kind") == "EXECUTED_OFFLINE_VERIFICATION"
            and value.get("status") == "PASS" and value.get("exit_code") == 0,
            "STRICT_STATUS_INVALID")
    require(value.get("source_before") == value.get("source_after") == current,
            "STRICT_SOURCE_NOT_CURRENT")
    require(value.get("unraisable_errors") == [], "STRICT_UNRAISABLE_ERRORS")
    python = value["python"]
    ids = python["executed_ids"]
    require(python.get("status") == "PASS" and python.get("exit_code") == 0
            and python["expected_ids"] == ids == python["passed_ids"]
            and len(ids) == len(set(ids)) == python["executed"] == python["passed"]
            and len(ids) > 0
            and all(python[key] == 0 for key in
                    ("failures", "errors", "skipped", "expected_failures", "unexpected_successes")),
            "STRICT_PYTHON_EXECUTION_INVALID")
    required_ids = {
        "test_bot.TestIndianFOSignalBotPhase1F.test_p1f_concurrent_promise_all_burst_across_all_dashboard_endpoints",
        *["test_context_http.TestStoredContextPayloadGuards." + method for method in (
            "test_nontext_original_outbox_payload_is_graceful_persistence_failure",
            "test_nontext_context_decision_returns503_from_supported_alert_api",
            "test_oversized_or_nontext_stored_snapshot_is_rejected_before_decoding",
            "test_oversized_or_nontext_stored_source_json_is_rejected_before_decoding",
            "test_integer_or_oversized_original_bytes_rejected_before_source_validator",
            "test_corrupt_receipt_type_or_size_is_rejected_before_decoding",
            "test_corrupt_existing_import_inventory_returns_storage_failure")],
    }
    require(required_ids.issubset(ids), "STRICT_REQUIRED_REGRESSIONS_MISSING")
    checks = value["checks"]
    require(len(checks) >= 3 and all(item["status"] == "PASS" and item["exit_code"] == 0
                                    for item in checks), "STRICT_CHECK_STATUS_INVALID")
    node = [item for item in checks if isinstance(item["command"], list)
            and item["command"][0] == "node" and "--check" not in item["command"]]
    syntax = [item for item in checks if isinstance(item["command"], list)
              and item["command"][0] == "node" and "--check" in item["command"]]
    compile_checks = [item for item in checks if "compiled_files" in item]
    require(len(node) == len(syntax) == len(compile_checks) == 1, "STRICT_REQUIRED_CHECKS_MISSING")
    node = node[0]
    require(node["executed"] == node["passed"] > 0 and node["failures"] == node["skipped"] == 0,
            "STRICT_NODE_COUNTS_INVALID")
    compiled = compile_checks[0]["compiled_files"]
    require(type(compiled) is int and compiled > 0
            and compiled == len(list(APP.glob("*.py"))),
            "STRICT_COMPILE_INVENTORY_INVALID")
    required_logs = {python["log"]} | {item["log"] for item in checks if "log" in item}
    require(required_logs.issubset(value["logs"]), "STRICT_LOG_INVENTORY_INVALID")
    for name, expected in value["logs"].items():
        require(name.startswith("docs/evidence/") and sha_file(safe_relative(name)) == expected,
                "STRICT_LOG_HASH_MISMATCH")
    return dict(path=STRICT.relative_to(APP).as_posix(), sha256=sha_file(STRICT),
                status="PASS", python_executed=len(ids), python_passed=python["passed"],
                node_executed=node["executed"], compiled_files=compiled, source_files=len(current),
                required_regressions_checked=sorted(required_ids),
                test_modules=dict(sorted(Counter(case.split(".")[0] for case in ids).items())),
                logs=value["logs"], retained_execution_only=True, no_test_rerun=True)


def browser_proof(current):
    value = load_json(BROWSER)
    require(value.get("status") == "PASS" and value.get("exit_code") == 0
            and value.get("chrome_exit_code") == 0 and value.get("source_unchanged") is True,
            "BROWSER_STATUS_INVALID")
    sources = value["source_after"]
    require(sources == value["source_before"] and sources
            and all(current.get(name) == expected for name, expected in sources.items()),
            "BROWSER_SOURCE_NOT_CURRENT")
    checks = value["checks"]
    require(checks and len({item["name"] for item in checks}) == len(checks)
            and all(item["passed"] is True for item in checks), "BROWSER_CHECKS_INVALID")
    require(value["runtime_exceptions"] == [] and value["server_thread_stopped"] is True
            and value["temporary_profile_removed"] is True, "BROWSER_CLEANUP_OR_RUNTIME_INVALID")
    helper = EVIDENCE / "phase45_browser_verify_20261024_01.py"
    require(sha_file(helper) == value["helper_sha256"], "BROWSER_HELPER_HASH_MISMATCH")
    log_name = value["log_file"]
    require(PurePosixPath(log_name).name == log_name
            and sha_file(EVIDENCE / log_name) == value["log_sha256"], "BROWSER_LOG_HASH_MISMATCH")
    return dict(path=BROWSER.relative_to(APP).as_posix(), sha256=sha_file(BROWSER), status="PASS",
                checks=len(checks), source_files=len(sources), product=value["browser"]["product"],
                helper_sha256=value["helper_sha256"], log_sha256=value["log_sha256"],
                cleanup_confirmed=True, source_current=True, no_browser_rerun=True,
                limitations=value["limitations"])


def release_allowlist():
    # Read literals from the current audited packager rather than executing it.
    tree = ast.parse((APP / "release_management.py").read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ReleasePackager")
    lists = {}
    for node in owner.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"CORE_MODULES", "REQUIRED_ASSETS", "PUBLIC_DOCUMENTS"}:
                    lists[target.id] = ast.literal_eval(node.value)
    require(set(lists) == {"CORE_MODULES", "REQUIRED_ASSETS", "PUBLIC_DOCUMENTS"}
            and all(isinstance(value, list) and all(isinstance(name, str) for name in value)
                    for value in lists.values()), "PACKAGER_LITERAL_ALLOWLIST_INVALID")
    expected = set().union(*map(set, lists.values()))
    expected.update(path.name for path in APP.glob("test_*.py"))
    expected.update(path.name for path in APP.glob("test_*.js"))
    if (APP / "README.md").is_file():
        expected.add("README.md")
    require({"context_data.py", "context_workflow.py", "docs/TRADEPULSE_PHASE45_HANDOVER_20261024.md"}
            .issubset(expected), "NEW_MODULE_OR_HANDOVER_NOT_PACKAGED")
    return expected, lists


def check_public_path(name):
    safe_relative(name)
    lower = name.lower()
    parts = PurePosixPath(lower).parts
    leaf = parts[-1]
    require(not any(part in {".git", ".codex", ".agents", ".local", "__pycache__", "evidence"}
                    or part.startswith(".venv") for part in parts), "PRIVATE_ARCHIVE_DIRECTORY")
    require(not (leaf.startswith(".env") and leaf != ".env.example")
            and not leaf.endswith((".db", ".sqlite", ".sqlite3", "-wal", "-shm", ".pyc", ".zip",
                                   ".pem", ".key")), "PRIVATE_ARCHIVE_FILE")
    require("raw" not in parts and not lower.startswith("docs/evidence/"), "RAW_OR_MACHINE_EVIDENCE_INCLUDED")


def archive_check(current):
    expected, declarations = release_allowlist()
    require(ARCHIVE.stat().st_size <= 70 * 1024 * 1024, "ARCHIVE_SIZE_LIMIT")
    archive_sha = sha_file(ARCHIVE)
    require(archive_sha == EXPECTED_ARCHIVE_SHA, "ARCHIVE_EXPECTED_HASH_MISMATCH")
    before = {name: sha_file(safe_relative(name)) for name in sorted(expected)}
    with zipfile.ZipFile(ARCHIVE) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        require(len(names) == len(set(names)) == len({name.casefold() for name in names}),
                "ARCHIVE_DUPLICATE_OR_CASE_COLLISION")
        require(set(names) == expected | {"RELEASE_MANIFEST.json"}, "ARCHIVE_EXACT_ALLOWLIST_MISMATCH")
        require(sum(entry.file_size for entry in entries) <= 64 * 1024 * 1024,
                "ARCHIVE_EXPANDED_SIZE_LIMIT")
        for entry in entries:
            require(not entry.is_dir() and entry.file_size <= 16 * 1024 * 1024
                    and ((entry.external_attr >> 16) & 0o170000) != 0o120000
                    and not entry.flag_bits & 1, "ARCHIVE_UNSAFE_ENTRY")
            if entry.filename != "RELEASE_MANIFEST.json":
                check_public_path(entry.filename)
        manifest_bytes = archive.read("RELEASE_MANIFEST.json")
        manifest = json.loads(manifest_bytes)
        require(set(manifest) == {"kind", "live_acceptance", "files"}
                and manifest["kind"] == "OFFLINE_RELEASE_CANDIDATE"
                and manifest["live_acceptance"] is False
                and set(manifest["files"]) == expected, "ARCHIVE_MANIFEST_SCOPE_INVALID")
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        require(manifest_bytes == canonical, "ARCHIVE_MANIFEST_NOT_CANONICAL")
        checked = {}
        for name in sorted(expected):
            body = archive.read(name)
            actual = dict(size_bytes=len(body), sha256=sha_bytes(body))
            require(manifest["files"][name] == actual, "ARCHIVE_MANIFEST_CONTENT_MISMATCH")
            local_body = safe_relative(name).read_bytes()
            require(local_body == body and before[name] == actual["sha256"], "ARCHIVE_CURRENT_FILE_MISMATCH")
            if name in current:
                require(current[name] == actual["sha256"], "ARCHIVE_STRICT_SOURCE_MISMATCH")
            checked[name] = actual
        require(archive.testzip() is None, "ARCHIVE_CRC_FAILURE")
    after = {name: sha_file(safe_relative(name)) for name in sorted(expected)}
    require(before == after and sha_file(ARCHIVE) == archive_sha, "ARCHIVE_OR_CURRENT_FILES_CHANGED_DURING_READ")
    return dict(path=ARCHIVE.relative_to(APP).as_posix(), sha256=archive_sha, size_bytes=ARCHIVE.stat().st_size,
                payload_files=len(expected), zip_entries=len(entries), manifest_sha256=sha_bytes(manifest_bytes),
                crc_checked=True, exact_literal_allowlist=True, exact_current_bytes=True,
                manifest_hashes_and_sizes=True, source_and_archive_stable=True,
                private_path_exclusions_checked=True, extraction_performed=False,
                literal_declarations=declarations, files=checked,
                credential_content_comparison="NOT_REPEATED_SEPARATE_COORDINATOR_PRIVATE_CHECK",
                publisher_authentication="NOT_ESTABLISHED", live_acceptance=False)


def main():
    if OUTPUT.exists():
        raise SystemExit("UNIQUE_RECEIPT_ALREADY_EXISTS")
    result = dict(schema_version="tradepulse.independent-release-check.v1", status="FAIL", exit_code=1,
                  started_at=datetime.now(timezone.utc).isoformat(),
                  reviewer="/root/phase45_perf_review", helper_sha256=sha_file(Path(__file__)),
                  command=[sys.executable, "-B", "-W", "error::ResourceWarning",
                           Path(__file__).relative_to(APP).as_posix()],
                  scope="READ_ONLY_ZIP_SOURCE_AND_RETAINED_RECEIPTS_NO_TEST_RERUN",
                  operational_database_opened=False, configuration_or_credentials_read=False,
                  application_imported=False, network_or_message_action=False)
    try:
        current = source_map()
        result["strict"] = strict_proof(current)
        result["browser"] = browser_proof(current)
        result["archive"] = archive_check(current)
        require(source_map() == current, "CURRENT_SOURCE_CHANGED_DURING_INSPECTION")
        result.update(status="PASS", exit_code=0, archive_sha256=result["archive"]["sha256"],
                      files=result["archive"]["payload_files"], source_unchanged=True,
                      source=current, exact_current_zip=True)
    except Exception as exc:
        # No untrusted payload, archive content, configuration or raw traceback
        # enters the evidence. Failed executions retain their unique receipt.
        result["failure"] = dict(type=type(exc).__name__, code=str(exc) if isinstance(exc, ValueError)
                                 and re.fullmatch(r"[A-Z_]+", str(exc)) else "INSPECTION_FAILED")
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    with OUTPUT.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(dict(status=result["status"], exit_code=result["exit_code"],
                          receipt=OUTPUT.relative_to(APP).as_posix(),
                          archive_sha256=result.get("archive", {}).get("sha256"),
                          payload_files=result.get("archive", {}).get("payload_files"))))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

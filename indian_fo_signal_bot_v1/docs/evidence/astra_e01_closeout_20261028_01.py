"""Bind limited E01 browser evidence and the narrow D01 typed-rejection repair."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
EVIDENCE = APP / "docs/evidence"
BASELINE = EVIDENCE / "astra_e01_baseline_20261027_01.json"
MANIFEST = EVIDENCE / "astra_browser_assets_20261027_02.json"
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence

SCOPE = "E01_LIMITED_BROWSER_PAGINATION_AND_D01_MISSING_STATUS_REJECTION_NOT_MISSION_ACCEPTANCE"
CHANGES = {"public/index.html", "test_cash_dashboard.js", "option_observations.py", "test_option_observations.py"}
NAMES = ["TRADEPULSE_ASTRA_" + name + ".md" for name in
         ("MASTER_EXECUTION_REPORT", "CHECKPOINT", "PROGRESS", "TASK_LEDGER")]
REQUIRED_PROBES = {
    "real_chart_tailwind_fonts", "card_keyboard_selection_preserves_focus",
    "card_selection_semantic", "space_preserves_selected_card_focus",
    "asynchronous_refresh_restores_same_focused_card",
    "asynchronous_refresh_does_not_steal_search_focus",
    "empty_refresh_has_visible_read_only_focus_fallback",
    "delayed_signals_request_is_pending", "focus_moved_during_request_is_not_stolen",
    "failed_refresh_preserves_visible_retry_focus", "successful_retry_keeps_visible_read_only_focus",
    "delayed_error_does_not_steal_moved_focus",
    "overlapping_signal_responses_have_distinct_ordered_payloads",
    "late_signal_response_cannot_restore_cards_or_steal_focus",
    "header_leaves_mobile_reading_space", "canvas_and_icon_control_names",
    "backtest_canvas_names_hypothetical_gross_net_model",
    "option_canvas_names_open_interest_change", "rendered_animation_inventory",
    "real_signal_chart_has_native_canvas", "tabs_arrow_navigation",
    "tabs_end_navigation", "tabs_home_navigation",
    "http_503_clears_cached_ranks_and_signal_prices",
    "delayed_rank_request_started", "delayed_rank_response_completed",
    "late_rank_response_cannot_restore_old_current_state",
}
PAGINATION_PROBES = {
    "production_dom_and_initial_pages", "signals_first_page",
    "signals_middle_page_native_next", "signals_last_page_native_next", "signals_previous_page_native_key",
    "signals_page_size_10_resets_offset", "signals_page_size_50_resets_offset",
    "signal_page_size_change_keeps_control_focus", "symbol_filter_resets_later_page_offset",
    "symbol_filter_response_keeps_search_focus", "empty_symbol_filter_truthful_range",
    "pagination_overlap_uses_distinct_filter_reads", "late_page_cannot_replace_new_filter",
    "late_page_cannot_steal_search_focus", "shrinking_signal_total_never_shows_inverted_range",
    "positive_total_empty_signal_page_keeps_retained_total", "failed_signal_page_withholds_old_range_and_cards",
    "scans_first_page", "scans_middle_page_native_next", "scans_last_page_native_next",
    "scans_previous_page_native_key", "scan_status_filter_resets_later_offset",
    "scan_filter_change_keeps_control_focus", "empty_scan_filter_truthful_range",
    "shrinking_scan_total_never_shows_inverted_range", "positive_total_empty_scan_page_keeps_retained_total",
    "failed_scan_page_withholds_old_range_and_rows",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def within(root, name):
    path = (root / name).resolve()
    assert path.is_relative_to(root.resolve()), "artifact outside declared root"
    assert path.is_file(), str(path.relative_to(APP))
    return path


def exclusive(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def preserved(baseline):
    for name, checksum in baseline["preserved_documents"].items():
        assert sha(within(APP, name)) == checksum, name
    # Saved configuration is only hashed; values and fingerprints are not emitted.
    for name, checksum in baseline["saved_config_hashes"].items():
        assert sha(Path(name)) == checksum, "saved configuration changed"
    for name, checksum in baseline["external_source_hashes"].items():
        assert sha(within(APP, name)) == checksum, name
    assert set(baseline["handoff"]) == set(NAMES)
    for row in baseline["handoff"].values():
        body = base64.b64decode(row["original_bytes_base64"], validate=True)
        assert hashlib.sha256(body).hexdigest() == row["sha256"], "archived handoff damaged"


def validate_assets():
    data = read(MANIFEST)
    assert data["status"] == "PASS" and not data["errors"]
    assert len(data["assets"]) == 16 and len(data["licenses"]) == 4
    cache = APP / ".local/astra_browser_assets_20261027_01"
    bindings = {}
    assets = {}
    for row in data["assets"] + data["licenses"]:
        path = within(APP, row["path"])
        assert path.is_relative_to(cache.resolve()), "asset outside isolated cache"
        assert path.stat().st_size == row["size_bytes"] and sha(path) == row["sha256"]
        assert row["url"].startswith("https://") and row["final_url"].startswith("https://")
        bindings[path.relative_to(APP).as_posix()] = row["sha256"]
    for row in data["assets"]:
        assert row["url"] not in assets, "duplicate asset URL"
        assets[row["url"]] = row["sha256"]
    acquisition = EVIDENCE / "astra_browser_asset_acquire_20261027_01.py"
    assert sha(acquisition) == data["helper_sha256"]
    return assets, bindings


def validate_browser(path, browser, source, assets, *, pagination=False):
    data = read(path)
    assert data["status"] == "PASS" and data["exit_code"] == 0
    assert data["browser"] == browser and data["browser_exit_code"] == 0
    assert data["source_unchanged"] is True
    assert data["source_before"] == data["source_after"] == data["source_sha256"]
    assert set(data["source_before"]) == {"public/index.html", "test_cash_dashboard.js"}
    assert all(source[name] == checksum for name, checksum in data["source_before"].items())
    assert data["server_thread_stopped"] is True and data["temporary_profile_removed"] is True
    assert 0 < data["browser_run_seconds"] < 60
    assert data["application_modules_imported"] is False
    assert data["operational_database_accessed"] is False and data["environment_files_read"] is False
    assert data["external_assets_omitted"] is False
    assert not data["javascript_exceptions"] and not data["browser_crashes"] and not data["fixture_server_failures"]
    assert data["asset_manifest_sha256"] == sha(MANIFEST)
    prep = data["html_preparation"]
    assert prep["source_html_sha256"] == prep["served_html_sha256"] == source["public/index.html"]
    assert prep["production_inline_scripts_unchanged"] is True
    assert prep["chart_stub"] is False and prep["tailwind_stub"] is False
    assert prep["external_links_omitted"] == prep["external_scripts_omitted"] == 0
    assert prep["manifest_sha256"] == sha(MANIFEST)
    checks = data["checks"]
    assert checks and all(row["passed"] is True for row in checks)
    names = {row["name"] for row in checks}
    assert len(names) == len(checks), "duplicate browser check names"
    assert data["cases"] == checks
    assert data["assertions"] == dict(total=len(checks), passed=len(checks))
    if pagination:
        assert data["scope"] == "AUTHORED_BROWSER_EXISTING_PAGINATION_NOT_BACKEND_OR_PAPER_ACCEPTANCE"
        for viewport in ("desktop", "narrow"):
            assert {viewport + "." + name for name in PAGINATION_PROBES} <= names
    else:
        for viewport in ("desktop", "tablet", "mobile", "narrow"):
            assert {viewport + "." + name for name in REQUIRED_PROBES} <= names
            for tab in ("tab-terminal", "tab-option-apex", "tab-strategies", "tab-brokers-telegram"):
                assert {viewport + "." + tab + "." + name for name in
                        ("tab_semantics", "controls_within_viewport", "accessibility_tree_tab_names")} <= names
    assert {"external_fetch_blocked_before_transport", "post_scan_probe_blocked_before_fixture_server",
            "only_get_head_reached_exact_fixture_origin", "no_scan_or_mutation_reached_server",
            "no_javascript_exceptions_or_browser_crashes", "no_fixture_server_failures"} <= names
    assert data["actual_fixture_requests"] and all(row["method"] in ("GET", "HEAD")
        and row["path"] != "/api/scan" for row in data["actual_fixture_requests"])
    assert data["cdp_allowed_requests"] and all(row["host"] == "127.0.0.1" and
        row["scheme"] == "http" and row["method"] in ("GET", "HEAD") for row in data["cdp_allowed_requests"])
    assert data["cached_assets_fulfilled"] and all(assets.get(row["url"]) == row["sha256"]
        for row in data["cached_assets_fulfilled"])
    if not pagination:
        assert len(data["rendered_animation_inventory"]) == 4
        assert {row["viewport"] for row in data["rendered_animation_inventory"]} == {"desktop", "tablet", "mobile", "narrow"}
    bindings = {}
    for row in data["artifacts"]:
        artifact = within(EVIDENCE, row["file"])
        assert sha(artifact) == row["sha256"], row["file"]
        bindings[artifact.relative_to(APP).as_posix()] = row["sha256"]
    assert len(data["screenshots"]) >= (2 if pagination else 20)
    for row in data["screenshots"]:
        assert bindings["docs/evidence/" + row["file"]] == row["sha256"]
    helper = within(APP, data["command"][4])
    assert sha(helper) == data["helper_sha256"]
    assert bindings[helper.relative_to(APP).as_posix()] == data["helper_sha256"]
    probe_prefix = "astra_browser_pagination_probes_" if pagination else "astra_browser_ui_probes_"
    probe_helpers = [name for name in bindings if Path(name).name.startswith(probe_prefix)]
    assert len(probe_helpers) == 1 and bindings[probe_helpers[0]] == data["probe_helper_sha256"]
    assert sha(within(EVIDENCE, data["log_file"])) == data["log_sha256"]
    return dict(receipt=path.name, sha256=sha(path), checks=len(checks),
                seconds=data["browser_run_seconds"], browser_version=data["browser_version"]), bindings


def validate_node(source, expected_count):
    path = EVIDENCE / "astra_e01_pagination_node_after_20261029_03.json"
    data = read(path)
    assert data["command"] == ["node", "test_cash_dashboard.js"] and data["exit_code"] == 0
    assert data["executed"] == data["passed"] == expected_count and expected_count > 0
    assert not data["failures"] and not data["skipped"]
    assert data["source_before"] == data["source_after"]
    assert set(data["source_before"]) == {"public/index.html", "test_cash_dashboard.js"}
    assert all(source[name] == checksum for name, checksum in data["source_after"].items())
    assert sha(within(APP, data["log"])) == data["log_sha256"]
    return dict(receipt=path.name, sha256=sha(path), executed=data["executed"], passed=data["passed"])


def validate_d01(source, baseline):
    focused_path = EVIDENCE / "astra_d01_contract_status_after_20261028_01.json"
    focused = read(focused_path)
    assert focused["kind"] == "EXECUTED_FOCUSED_OFFLINE_VERIFICATION"
    assert focused["status"] == "PASS" and focused["exit_code"] == 0
    assert focused["executed"] > 0 and focused["executed"] == focused["passed"]
    assert focused["expected_ids"] == focused["executed_ids"] == focused["passed_ids"]
    assert len(set(focused["executed_ids"])) == focused["executed"]
    assert not any(focused[name] for name in
        ("errors", "failures", "skipped", "expected_failures", "unexpected_successes", "unraisable_errors"))
    assert focused["source_before"] == focused["source_after"]
    for name in ("option_observations.py", "test_option_observations.py"):
        assert focused["source_after"][name] == source[name], name
    assert any(name.endswith(".test_missing_contract_status_rejects_with_typed_error_without_mutating_inputs")
        for name in focused["executed_ids"])
    assert sha(within(APP, focused["log"])) == focused["log_sha256"]
    before_path = EVIDENCE / "astra_d01_contract_status_before_20261028_01.json"
    before = read(before_path)
    assert before["status"] == "FAIL" and before["exit_code"] == 1 and before["errors"] == 3
    assert before["source_before"] == before["source_after"]
    assert before["source_after"]["option_observations.py"] == baseline["source"]["option_observations.py"]
    assert before["source_after"]["test_option_observations.py"] == source["test_option_observations.py"]
    assert sha(within(APP, before["log"])) == before["log_sha256"]
    probe_path = EVIDENCE / "astra_d01_contract_status_probe_after_20261028_01.json"
    probe = read(probe_path)
    assert probe["status"] == probe["diagnostic_execution"] == "PASS"
    assert probe["case_count"] == probe["contract_satisfied_count"] == len(probe["cases"]) == 8
    assert not probe["leaked_keyerror_cases"] and not probe["forbidden_io_attempts"]
    assert probe["source_unchanged"] is True and probe["source_sha256_before"] == probe["source_sha256_after"]
    assert all(source[name] == checksum for name, checksum in probe["source_sha256_after"].items())
    assert all(row["contract_satisfied"] and row["inputs_unchanged"] for row in probe["cases"])
    assert probe["environment_files_read"] is False and probe["operational_database_accessed"] is False
    assert probe["provider_requests"] == 0 and probe["fixture_module_imported"] is False
    helper = EVIDENCE / "astra_d01_contract_status_probe_after_20261028_01.py"
    assert sha(helper) == probe["helper_sha256"]
    prior_probe_path = within(EVIDENCE, probe["prior_probe_receipt"])
    assert sha(prior_probe_path) == probe["prior_probe_sha256"]
    prior_probe = read(prior_probe_path)
    assert len(prior_probe["leaked_keyerror_cases"]) == 3
    assert [(row["name"], row["input_sha256"]) for row in probe["cases"]] == [
        (row["name"], row["input_sha256"]) for row in prior_probe["cases"]]
    prior_helper = EVIDENCE / "astra_d01_contract_status_probe_20261028_01.py"
    assert sha(prior_helper) == prior_probe["helper_sha256"]
    return dict(focused_receipt=focused_path.name, focused_sha256=sha(focused_path),
        focused_tests=focused["executed"], before_receipt=before_path.name, before_sha256=sha(before_path),
        diagnostic_receipt=probe_path.name, diagnostic_sha256=sha(probe_path), diagnostic_cases=probe["case_count"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", default="20261029_02")
    parser.add_argument("--receipt", default="master_astra_e01_20261029_02.json")
    parser.add_argument("--chrome", default="astra_browser_assets_after_chrome_20261029_03.json")
    parser.add_argument("--edge", default="astra_browser_assets_after_edge_20261029_03.json")
    parser.add_argument("--pagination-chrome", default="astra_browser_pagination_after_chrome_20261029_03.json")
    parser.add_argument("--pagination-edge", default="astra_browser_pagination_after_edge_20261029_03.json")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    assert re.fullmatch(r"[a-z0-9_]{2,60}", args.stage), "invalid stage"
    for name in (args.receipt, args.chrome, args.edge, args.pagination_chrome, args.pagination_edge):
        assert re.fullmatch(r"[a-z0-9_]+\.json", name), "receipt must be a simple filename"
    closeout = EVIDENCE / ("astra_e01_closeout_" + args.stage + ".json")
    target = (EVIDENCE / ("astra_e01_closeout_validation_" + args.stage + ".json")) if args.validate_only else closeout
    assert not target.exists(), "unique stage required; never overwrite retained evidence"
    baseline = read(BASELINE)
    preserved(baseline)
    source = source_snapshot(APP)
    assert set(source) == set(baseline["source"]), "source file set changed"
    changes = {name for name in source if source[name] != baseline["source"][name]}
    assert changes == CHANGES, changes
    proof_path = within(EVIDENCE, args.receipt)
    proof = validate_evidence(proof_path)
    node_count = next(row["executed"] for row in proof["checks"] if isinstance(row["command"], list)
        and row["command"][0] == "node" and "executed" in row)
    node_result = validate_node(source, node_count)
    d01 = validate_d01(source, baseline)
    assets, cache_bindings = validate_assets()
    browser_results, artifact_bindings = {}, {}
    for browser, name in (("chrome", args.chrome), ("edge", args.edge)):
        browser_results[browser], bindings = validate_browser(within(EVIDENCE, name), browser, source, assets)
        artifact_bindings.update(bindings)
    pagination_results = {}
    for browser, name in (("chrome", args.pagination_chrome), ("edge", args.pagination_edge)):
        pagination_results[browser], bindings = validate_browser(within(EVIDENCE, name), browser, source, assets,
            pagination=True)
        artifact_bindings.update(bindings)
    now = datetime.now(timezone.utc).isoformat()
    if args.validate_only:
        saved = read(closeout)
        assert saved["status"] == "PASS" and saved["scope"] == SCOPE
        assert saved["source"] == source and saved["receipt"] == args.receipt
        assert saved["receipt_sha256"] == sha(proof_path) and saved["browser"] == browser_results
        assert saved["pagination_browser"] == pagination_results and saved["focused_node"] == node_result
        assert saved["cache_files"] == cache_bindings
        assert saved["d01_repair"] == d01
        assert all(sha(within(APP, name)) == checksum for name, checksum in saved["files"].items())
        result = dict(status="PASS", scope=SCOPE, recorded_at=now, closeout_sha256=sha(closeout),
            source_files=len(source), files=len(saved["files"]), cached_public_files=len(cache_bindings),
            preserved_documents=len(baseline["preserved_documents"]), current_receipt_validated=True,
            browser_assertions_validated={key: value["checks"] for key, value in browser_results.items()},
            pagination_assertions_validated={key: value["checks"] for key, value in pagination_results.items()},
            focused_node_tests_validated=node_result["executed"],
            new_tests_executed=False)
    else:
        required = [APP / "docs/project" / name for name in NAMES]
        required += [APP / "docs/reports/astra_e01_ui_review_20261029_01.md",
            APP / "docs/reports/astra_e01_completion_20261029_01.md",
            APP / "docs/reports/astra_e01_ui_review_20261029_02.md",
            APP / "docs/reports/astra_e01_completion_20261029_02.md",
            APP / "docs/reports/astra_e01_pagination_next_20261029_01.md",
            APP / "docs/reports/astra_browser_production_assets_plan_20261027_01.md",
            BASELINE, MANIFEST, proof_path, Path(__file__)]
        assert all(path.is_file() for path in required), "required handoff or review missing"
        files = set(required)
        files.update(within(APP, name) for name in proof["logs"])
        files.update(within(APP, name) for name in artifact_bindings)
        for prefix in ("astra_browser_", "astra_e01_", "astra_d01_contract_status_"):
            files.update(path for path in EVIDENCE.glob(prefix + "*") if path.is_file()
                and path != closeout and not path.name.startswith("astra_e01_closeout_validation_"))
        master = (APP / "docs/project/TRADEPULSE_ASTRA_MASTER_EXECUTION_REPORT.md").read_text(encoding="utf-8")
        assert len(re.findall(r"^## \d+\. ", master, re.M)) == 18, "master report sections"
        node = next(row["executed"] for row in proof["checks"] if isinstance(row["command"], list)
            and row["command"][0] == "node" and "executed" in row)
        compiled = next(row["compiled_files"] for row in proof["checks"] if "compiled_files" in row)
        result = dict(status="PASS", scope=SCOPE, recorded_at=now, source=source,
            changed_source=sorted(changes),
            head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip(),
            receipt=args.receipt, receipt_sha256=sha(proof_path), python=proof["python"]["executed"],
            node=node, compiled=compiled, browser=browser_results, pagination_browser=pagination_results,
            focused_node=node_result, d01_repair=d01,
            preserved_documents=len(baseline["preserved_documents"]),
            prior_handoff_archived=True, saved_config_and_owner_changes_preserved=True,
            cache_files=cache_bindings, public_asset_count=len(assets), public_license_count=4,
            files={path.relative_to(APP).as_posix(): sha(path) for path in sorted(files)},
            limitations=["Authored HTTP fixtures do not establish genuine backend or live-market integration",
                "Bounded viewport, keyboard and semantic checks do not establish full WCAG conformance",
                "Computed CSS animation inventory does not establish JavaScript animation acceptance",
                "No empirical strategy, production latency, legal, commercial or release acceptance",
                "Public asset cache is local evidence, not a newly packaged release"],
            provider_requests=0, operational_db="NOT_OPENED_CONTENTS_UNATTESTED", release_zip="NOT_BUILT")
    exclusive(target, result)
    print(json.dumps(dict(status="PASS", receipt=target.name, source_files=len(source),
        files=len(result.get("files", [])) if isinstance(result.get("files"), dict) else result.get("files"),
        browser_checks={key: value["checks"] for key, value in browser_results.items()},
        pagination_checks={key: value["checks"] for key, value in pagination_results.items()})))


if __name__ == "__main__":
    main()

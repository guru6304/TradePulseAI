"""Update the four mutable handoffs after final E01/D01 evidence passes."""
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
PROOF = "master_astra_e01_20261029_02.json"
CHANGES = {"public/index.html", "test_cash_dashboard.js", "option_observations.py", "test_option_observations.py"}
NAMES = ["TRADEPULSE_ASTRA_" + name + ".md" for name in
         ("MASTER_EXECUTION_REPORT", "CHECKPOINT", "PROGRESS", "TASK_LEDGER")]
sys.path.insert(0, str(APP))
from verify_offline import validate_evidence


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def section(content, number, body):
    start = re.search(rf"^## {number}\. .*\n", content, re.M)
    end = re.search(rf"^## {number + 1}\. ", content, re.M)
    assert start and end
    return content[:start.end()] + "\n" + body.strip() + "\n\n" + content[end.start():]


def ledger_row(content, identifier, columns):
    row = "|" + "|".join([identifier] + columns) + "|"
    pattern = rf"^\|{re.escape(identifier)}\|.*$"
    if re.search(pattern, content, re.M):
        return re.sub(pattern, lambda match: row, content, flags=re.M)
    return content.rstrip() + "\n" + row + "\n"


def main():
    proof = validate_evidence(EVIDENCE / PROOF)
    python = proof["python"]["executed"]
    node = next(row["executed"] for row in proof["checks"] if isinstance(row["command"], list)
                and row["command"][0] == "node" and "executed" in row)
    compiled = next(row["compiled_files"] for row in proof["checks"] if "compiled_files" in row)
    counts = f"{python}/{python} Python, {node}/{node} Node, {compiled} compiled Python files"
    baseline = read(EVIDENCE / "astra_e01_baseline_20261027_01.json")
    changed = {name for name, checksum in proof["source_before"].items()
               if baseline["source"].get(name) != checksum}
    assert set(proof["source_before"]) == set(baseline["source"]) and changed == CHANGES
    previous_docs = len(baseline["preserved_documents"])
    summaries = {}
    for kind in ("assets", "pagination"):
        summaries[kind] = {}
        for browser in ("chrome", "edge"):
            data = read(EVIDENCE / f"astra_browser_{kind}_after_{browser}_20261029_03.json")
            assert data["status"] == "PASS" and data["exit_code"] == 0
            assert data["assertions"]["passed"] == data["assertions"]["total"] == len(data["checks"]) > 0
            assert all(row["passed"] is True for row in data["checks"])
            assert data["source_unchanged"] and data["source_before"] == data["source_after"]
            assert all(proof["source_before"][name] == checksum for name, checksum in data["source_after"].items())
            assert data["browser_exit_code"] == 0 and data["server_thread_stopped"] and data["temporary_profile_removed"]
            summaries[kind][browser] = data["assertions"]["passed"]
    assets_text = " and ".join(f"{name.title()} {count}/{count}" for name, count in summaries["assets"].items())
    pages_text = " and ".join(f"{name.title()} {count}/{count}" for name, count in summaries["pagination"].items())
    focused_node = read(EVIDENCE / "astra_e01_pagination_node_after_20261029_03.json")
    assert focused_node["exit_code"] == 0 and focused_node["passed"] == focused_node["executed"] == node
    assert focused_node["source_before"] == focused_node["source_after"]
    assert all(proof["source_before"][name] == checksum for name, checksum in focused_node["source_after"].items())
    for name in ("astra_e01_ui_review_20261029_02.md", "astra_e01_completion_20261029_02.md"):
        assert (APP / "docs/reports" / name).is_file(), name
    now = datetime.now(timezone.utc).isoformat()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
    paths = [APP / "docs/project" / name for name in NAMES]
    old = {path.name: path.read_bytes() for path in paths}
    next_action = ("E01.2d: verify the existing bounded paper journal in the actual browser using an explicit "
                   "authored fixture account: retained totals/truncation, unsafe text, missing/stale marks, "
                   "reconciliation failure and failed/late reports; retain GET-only reads and zero financial mutations.")
    master = old[NAMES[0]].decode("utf-8")
    master = ("# TradePulse Astra master execution report\n\n"
        "Mission TRADEPULSE-ASTRA-OWNER-2026-10-24-V1. Client date2026-10-29, Asia/Kolkata.\n"
        "**PARTIAL VERIFIED OFFLINE ENGINEERING; MASTER MISSION INCOMPLETE.**\n\n"
        f"Last updated UTC: {now}. Current HEAD `{head}`; branch main.\n"
        "The owner's dev branch and Antigravity work remain for later review/merge.\n\n" +
        master[master.index("## 1. Executive verdict"):])
    master = section(master, 1, f"""
E01.2b and E01.2c are verified within bounded authored-fixture scope. Actual production
assets pass **{assets_text}**, four widths/four tabs. Existing signal/scan pagination
passes **{pages_text}**, desktop/320px, including filters, delayed reads, positive-total
empty pages and failed pages. Header obstruction, card/refresh/retry focus, tab
semantics and chart descriptions are corrected. A mobile retry ordering defect is
fixed by restoring focus after all cards and the inspector finish rendering.
D01.2a rejects missing OI contract status with the existing typed validation error.

Current canonical **{counts}** passed with zero failures/errors/skips/unraisables
and unchanged source during execution. One new Python test covers three absent-status
subcases; two Node regressions cover pagination truthfulness. Current proof: `{PROOF}`.
See [completion](../reports/astra_e01_completion_20261029_02.md) and
[independent review](../reports/astra_e01_ui_review_20261029_02.md).

Broader accessibility/contrast, actual-browser paper journal, actual backend/live
consumer, genuine historical/OOS evidence, broader paper policies, production latency
and customer readiness remain incomplete. No provider/order/send, saved-setting,
operational database or Git mutation occurred. Public dependency downloads were
separately authorized and retained outside the release bundle.

Next: {next_action}
""")
    start = master.index("\n\n", master.index("## 2. Audit manifest"))
    end = master.index("Owner-confirmed parallel changes", start)
    master = master[:start] + "\n\n" + (
        "This slice changes only public/index.html, test_cash_dashboard.js, option_observations.py\n"
        "and test_option_observations.py. No application module was added. E01 baseline\n"
        f"retains {previous_docs} earlier documents and four original handoffs; intermediate\n"
        "handoffs are archived before this update. The E01 closeout and separate validation\n"
        "bind current source, executed tests, browser artifacts, assets and final handoffs.\n"
        "Prior D01 and E01 stage01 proofs remain historical after pagination/layout fixes.\n\n") + master[end:]
    master = re.sub(r"Current externally advanced HEAD `[^`]+`", f"Current externally advanced HEAD `{head}`", master)
    master = master.replace(
        "actual Chrome/Edge DOM and keyboard checks pass; external-asset styling/mobile visual/new delivery acceptance NOT_ESTABLISHED",
        "Chrome/Edge assets214 each/four widths and pagination60 each/desktop320 verified; browser paper journal, full accessibility/contrast and new delivery acceptance remain open")
    findings = ("|E04 focus/mobile usability, corrected|Actual fixtures reproduced lost selection/refresh/retry focus, missing tab semantics and obstructive mobile header; final assets03 pass214 per browser.|\n"
        "|E05 chart descriptions, corrected|OI change and hypothetical gross/net model are labeled accurately; no empirical result is implied.|\n"
        "|E06 pagination truthfulness, corrected|Before browser50/56 and Node38/40 reproduced inverted ranges and stale range after503. Empty current pages retain positive totals; failed pages clear old ranges. Final pagination60 per browser and Node40 pass.|\n"
        "|E07 mobile retry visibility, corrected|Edge assets02 passed213/214 with the correctly focused retry card offscreen. Focus now restores after cards and inspector render; final assets03 Chrome214/Edge214 pass.|\n"
        "|D02 typed validation, corrected|Missing current/baseline/both OI status leaked3KeyErrors; ACTIVE-only get check now rejects with typed error. Focused32 and same8diagnostic cases pass without input mutation.|\n")
    pos = master.index("Negative controls: offline runner")
    master = master[:pos].rstrip() + "\n" + findings + "\n" + master[pos:]
    master = master.replace("product/security and production-assets visual/accessibility approval remain open.",
        "product/security approval remains open. Limited E01 browser/pagination review is recorded in section15.")
    ux_start = master.index("\n\n", master.index("## 12. UX and product differentiation"))
    ux_end = master.index("| Priority / feature", ux_start)
    master = master[:ux_start] + "\n\n" + f"""
Current renderer coverage is {node} Node tests. Actual production-assets {assets_text}
pass at1440/768/390/320 widths; pagination {pages_text} pass at desktop/320px.
Verified scenarios include native previous/next, sizes10/20/50, filter resets, delayed
reads, empty/error/shrinking totals, selected tab semantics and visible retry focus.
Screenshots cover captured viewports; positive chart rendering covers the signal chart.
Computed contrast is NOT_EVALUATED. No CSS animation was rendered in the checked
fixture state; JavaScript reduced motion and WCAG conformance remain unestablished.
Actual-browser bounded paper journal is E01.2d; its existing40-row cap and complete
ledger API remain preserved. Existing vanilla JS and paper authority remain.

""" + master[ux_end:]
    master = re.sub(r"^\|E01 /5,6 /UI\|.*$",
        "|E01 /5,6 /UI|E01.2b/c VERIFIED_LIMITED|Assets214 and pagination60 each in Chrome/Edge; paper-journal browser and broader accessibility/contrast pending.|", master, flags=re.M)
    master = master.replace("Full product/security and production-assets visual/accessibility acceptance remain open.",
        "Final E01/D01 scoped review passes; full product/security, paper-journal browser and accessibility conformance remain open.")
    master = master.replace("runtime D01 admission, broader lifecycle, browser and full review remain.",
        "runtime D01 admission, broader lifecycle, paper-journal browser and full accessibility/product review remain.")
    v_start = master.index("\n\n", master.index("## 15. Verification ledger"))
    v_end = master.index("**Historical C03 canonical proof:", v_start)
    master = master[:v_start] + "\n\n" + f"""**Current source:** `{PROOF}`: PASS {counts}; zero failures/errors/skips/
unraisables, exact executed IDs and unchanged source. RUN:
`.venv_phase4\\Scripts\\python.exe -B -W error::ResourceWarning verify_offline.py --stage astra_e01_20261029_02`.
Final assets03 {assets_text}; pagination03 {pages_text}; focused Node{node}/{node}.
Actual production HTML and16cached assets/4licenses are used. No JavaScript exceptions,
crashes or unexpected fixture requests; browsers exited, servers stopped and profiles
were removed. Focused D0132/32 and identical-input diagnostic8/8 pass. Exact hashes,
logs, screenshots and handoffs are bound by the E01 closeout/separate validation.
Final scoped review is in astra_e01_ui_review_20261029_02.md.

Before browser04 passed186/210 with24genuine focus/retry/label failures. Earlier
receipts preserve focus-reset, identical-read serialization and CDP-pumping harness
mistakes; interim after04 was209/210 due to the harness race. Later pagination before
was50/56; its two added Node regressions gave38/40 before repair, then40/40. Edge
assets02 was213/214 with a correctly focused retry card offscreen; restoration now
follows full rendering and final assets03 pass in both browsers. Failures remain intact.

**Historical E01 stage01:** master_astra_e01_20261029_01.json passed1185Python,
38Node and101compiled before pagination/layout repairs. Earlier completion/review01
are preserved and do not identify the final source.
**Historical D01:** master_astra_d01_20261027_01.json passed1184Python/38Node/
101compiled at that source boundary. Its56new tests and numerical/clock diagnostics
remain retained; current proof includes the later typed-rejection fix. The original
D01 reviewer authored option tests, not production. Later scoped review is independent.

""" + master[v_end:]
    master = section(master, 17, f"""
Completed: E01.2b limited assets/mobile/semantic checks, E01.2c existing signal/scan
pagination, and D01.2a typed rejection. Current proof `{PROOF}`: {counts}.
Assets {assets_text}; pagination {pages_text}. No command remains running at this
checkpoint. Master mission remains incomplete. Owner dev/Antigravity work is preserved;
no merge/stage/commit, provider/order/send or operational database action occurred.

Safe first command: `Get-Content docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md`.
Single next action: **{next_action}**
Preserve accepted B01/C03/D01 scopes and use unique evidence stages. Reuse retained
assets; do not repeat the baseline audit or full suite without a relevant change.
Resume instruction: `CONTINUE FROM CHECKPOINT`.
""")
    assert len(re.findall(r"^## \d+\. ", master, re.M)) == 18
    checkpoint = f"""# TradePulse checkpoint - 2026-10-29, E01.2b/c and D01.2a verified

Updated UTC: {now}. Client date2026-10-29, Asia/Kolkata.
Phase5 limited UI/pagination and Phase2/3 typed-error repair complete; mission INCOMPLETE.
Branch main HEAD{head}. Owner dev/Antigravity work untouched; no Git writes.
Last verified: {PROOF} PASS {counts}.
Assets {assets_text} at four widths/four tabs; pagination {pages_text} at desktop/320px.
D01focused32/32, diagnostic8/8, Nodefocused{node}/{node}; final scoped review02.
Changed source: public/index.html, test_cash_dashboard.js, option_observations.py,
test_option_observations.py. Saved env and owner-confirmed source/helper preserved.
No provider/order/send/scheduler/operationalDB action; no release ZIP built.
No command is running. Final E01 closeout and separate validation identify bindings.
All{previous_docs}baseline documents and original4handoffs retained; current prior bytes archived.
E01.2 overall INCOMPLETE: paper-journal browser and full accessibility/contrast remain.
Other open work: runtime-qualified observations, broader paper triggers, measured latency,
genuine history/OOS/live and customer gates. Previous E01stage01 proof is historical.
Exact next action: {next_action}
Resume instruction: CONTINUE FROM CHECKPOINT.

## Historical checkpoints

""" + old[NAMES[1]].decode("utf-8")
    progress = old[NAMES[2]].decode("utf-8") + f"""

## 2026-10-29 - E01.2b/c and D01.2a verified

Updated UTC{now}. Current canonical {counts}, zero failures/errors/skips/unraisables.
Assets {assets_text}; pagination {pages_text}; focused Node{node}/{node}.
Retained pagination50/56 and Node38/40 before failures, then corrected current-page
empty/error wording. Edge213/214 exposed a focused mobile retry card outside the viewport;
restoring focus after the full render passes final214 per browser. D01 absent status
rejects with typed error;32focused/8same-input diagnostic cases pass. Final scoped
review02 is retained. Only4source paths changed; no provider/env/operationalDB/Git/order/
send action. Owner dev work preserved. Prior handoffs archived and historical proofs
kept; broad mission/customer release remains incomplete.
Next: {next_action}
"""
    ledger = old[NAMES[3]].decode("utf-8")
    ledger = ledger_row(ledger, "E01", ["5/6", "Truthful displays and bounded paper journal", "VERIFIED_COMPLETE",
        f"{node} current Node tests; limited renderer/read safety scope, browser b/c verified separately; paper-journal browser pending"])
    ledger = ledger_row(ledger, "F02.1", ["6", "Current-slice canonical and preserved history", "VERIFIED_COMPLETE",
        f"{python} Python/{node} Node/{compiled} compile; final E01b/c+D01 typed-error source/log/handoff bindings"])
    ledger = ledger_row(ledger, "E01.2", ["5", "Browser/mobile/accessibility/pagination acceptance", "IN_PROGRESS",
        "E01.2b/c verified limited; actual-browser paper journal, broader accessibility and contrast pending"])
    ledger = ledger_row(ledger, "E01.2b", ["5", "Production-assets visual/mobile/accessibility acceptance", "VERIFIED_COMPLETE_LIMITED",
        "Final assets03 Chrome214/Edge214, four widths/tabs; focus after full render; full contrast/WCAG unavailable"])
    ledger = ledger_row(ledger, "E01.2c", ["5", "Existing signal/scan browser pagination", "VERIFIED_COMPLETE_LIMITED",
        "Before50/56+Node38/40; final pagination60 each andNode40; current-page empty/error truthfulness"])
    ledger = ledger_row(ledger, "D01.2a", ["2/3", "Missing OI status typed rejection", "VERIFIED_COMPLETE",
        "Before3KeyErrors, focused32/32, same8diagnostic cases, current canonical; no admission authority"])
    ledger = ledger_row(ledger, "E01.2d", ["5/6", "Actual-browser bounded paper-journal fixtures", "NOT_STARTED",
        "Explicit authored account, totals/truncation, unsafe text, missing/stale marks, failed/late reports; GET-only"])
    archive = EVIDENCE / "astra_e01_handoff_previous_20261029_02.json"
    assert not archive.exists(), "previous handoff archive is immutable"
    with archive.open("x", encoding="utf-8") as stream:
        json.dump(dict(recorded_at=now, handoff={name: dict(
            sha256=hashlib.sha256(value).hexdigest(), original_bytes_base64=base64.b64encode(value).decode())
            for name, value in old.items()}), stream, indent=2, sort_keys=True)
    for path, text in zip(paths, (master, checkpoint, progress, ledger)):
        path.write_text(text, encoding="utf-8")
    print(json.dumps(dict(status="PASS", python=python, node=node, compiled=compiled,
        browser_checks=summaries, checkpoint_updated_at=now, archived_handoffs=len(old), next_task="E01.2d")))


if __name__ == "__main__":
    main()

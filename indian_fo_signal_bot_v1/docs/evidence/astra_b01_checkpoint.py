"""Bind the completed ORB slice and advance the mutable mission checkpoint."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_offline import validate_evidence, source_snapshot
from astra_preservation_check import sha, historical_receipt


def main():
    name = "master_astra_orb_trigger_20261025_02.json"
    proof = validate_evidence(APP / "docs/evidence" / name)
    count = proof["python"]["executed"]
    node = next(c["executed"] for c in proof["checks"] if isinstance(c["command"], list) and c["command"][0] == "node" and "executed" in c)
    compiled = next(c["compiled_files"] for c in proof["checks"] if "compiled_files" in c)
    baseline = json.loads((APP / "docs/evidence/astra_baseline_20261024_01.json").read_text())
    for path, checksum in baseline["preserved_documents"].items():
        assert sha(APP / path) == checksum, path
    assert all(sha(Path(path)) == checksum for path, checksum in baseline["saved_config_hashes"].items())
    assert sha(Path(r"C:\Users\HP\Downloads\TradePulse_AI_BRD_and_Project_Status_2026-10-24.docx")) == baseline["brd_sha256"]
    historical = [historical_receipt("master_phase45_20261024_03.json", "phase45_release_20261024_01.zip"),
                  historical_receipt("master_phase6_20261024_01.json", "phase6_release_20261024_01.zip")]
    now = datetime.now(timezone.utc).isoformat()
    preservation = dict(status="PASS", recorded_at=now, scope="B01_ORB_OFFLINE_SLICE_NOT_MISSION_ACCEPTANCE",
        current_receipt=name, current_receipt_sha256=sha(APP / "docs/evidence" / name),
        source=source_snapshot(APP), python=count, node=node, compiled_files=compiled,
        prior_documents_preserved=len(baseline["preserved_documents"]), both_env_files_preserved=True,
        original_brd_preserved=True, historical=historical, operational_db="NOT_OPENED_CONTENTS_UNATTESTED",
        paper_trigger="ORB_PROSPECTIVE_MECHANICS_VERIFIED_OTHER_STRATEGIES_UNAVAILABLE",
        dynamic_ranking="PURE_PROTOTYPE_INTEGRATION_NEXT", provider_requests=0)
    evidence = APP / "docs/evidence/astra_b01_preservation_20261025_01.json"
    with evidence.open("x", encoding="utf-8") as stream:
        json.dump(preservation, stream, indent=2, sort_keys=True)
        stream.write("\n")
    report = APP / "docs/project/TRADEPULSE_ASTRA_MASTER_EXECUTION_REPORT.md"
    content = report.read_text(encoding="utf-8")
    archive = APP / "docs/evidence/astra_master_before_b01_20261025_01.md"
    with archive.open("x", encoding="utf-8") as stream:
        stream.write(content)
    def section(number, title, body):
        nonlocal content
        start = content.index(f"## {number}. ")
        end = content.index(f"## {number + 1}. ", start)
        content = content[:start] + f"## {number}. {title}\n\n" + body.strip() + "\n\n" + content[end:]
    section(1, "Executive verdict", f"""
**PARTIAL VERIFIED OFFLINE ENGINEERING; MASTER MISSION INCOMPLETE.** B01's
premature automatic next-close path is now blocked. New automatic ORB entries
require a versioned, retained prospective trigger and current scanner health.
The canonical current-source proof passes {count}/{count} Python tests, {node}/{node}
Node tests and {compiled} compiled root Python files, with zero failures, errors,
skips or unraisable exceptions. This is software evidence using synthetic input.

ORB_FOLLOW_THROUGH_CLOSE_V1 freezes the confirmed signal candle high/low, then
requires a later completed directional close cross with original range
invalidation. It is an explicit experimental paper rule, not empirical strategy
promotion. Other strategies cannot inherit it; their automatic entries remain
unavailable. Legacy manual accounting and committed-effect recovery remain
supported without authorizing new legacy automatic fills.

Previously verified GET/HEAD safety, study-session coverage, descriptive strategy
metadata, truthful dashboard fields and read-only paper journal remain covered.
The deterministic rank-change module is still a pure prototype: C03.2 will connect
authenticated retained inputs, atomic rank persistence and a read-only API/UI.
No saved settings, operational databases, provider requests, real orders or sends
were changed. Personal alpha, genuine live acceptance, empirical performance and
commercial release remain separate gates; the six-phase roadmap is preserved.
""")
    content = content.replace("Last regenerated UTC: 2026-10-25T02:03:10.934194+00:00", "Last updated UTC: " + now)
    content = content.replace("Existing accounting regressions pass; B01 DEFECT_REPRODUCED and NOT_REPAIRED; no new auto-trigger acceptance or customer release",
        "B01 ORB prospective mechanics and legacy automatic rejection VERIFIED_CURRENT_SOURCE_AND_TEST; other strategy/contract triggers, live evidence and customer release unavailable")
    content = content.replace("T[New ORB trigger draft] -. integration pending .-> F", "T[Retained ORB future trigger and scanner guard] --> F")
    content = content.replace("Retained synthetic entry100/high 99/fill98 reproduction. No repaired coordinator/portfolio. Draft only; OPEN.",
        "Before reproduction retained. Repaired automatic path: legacy rejection; new source-bound ORB future trigger with atomic guards. Offline proof only; other strategy triggers unavailable.")
    content = content.replace("test_astra_ranking.py. The unintegrated docs/drafts/astra_paper_triggers_20261025_01.py is a draft, not tested\nbehavior.",
        "test_astra_ranking.py. B01 additionally changes forward_paper.py/paper_portfolio.py, adds paper_triggers.py and test_astra_paper_triggers.py, and migrates four existing workflow/recovery test modules. Both original docs/drafts/ files remain preserved; production is independently tested.")
    section(10, "Paper engine detailed verdict", """
The original failure is retained: legacy automatic close policy filled98 when
threshold100 was never reached (high99). The repaired coordinator rejects new
automatic decisions under that legacy policy. Old manual ledger APIs remain for
explicit compatibility tests; they are not the scanner's automatic entry path.
Existing account configuration hashes are never silently migrated.

New `paper_triggers.py` implements only `ORB_FOLLOW_THROUGH_CLOSE_V1`. The existing
ORB detector/formula remains unchanged. A qualified stored detector result fixes
signal high for LONG or low for SHORT; a strictly later completed close must cross
that extreme from the preceding observed close. Every intervening five-minute
observation must be retained and fresh when consumed. A missing observation cannot
be backfilled later. Touch is not cross. Range invalidation or T1 already touched
before the close blocks entry. Same-session/account square-off applies, without
an arbitrary three-bar setup TTL. Fill uses the observed close plus the configured
adverse cost model; cash lot1 is explicit, qualified tick rounding remains
NOT_MODELED_NO_QUALIFIED_TICK. These are mechanics, not an executable-price claim.

The decision stores strategy/source hashes, original candle/evaluation links,
contract, queue time, observation decisions and trigger timestamp. Direct entry
replays original retained inputs under the same SQLite write transaction. It checks
the actual scanner guard before staging effects and after staging the first mark.
Late clock or stream degradation rolls back the position, events and reservation.
Unsupported strategy policies, stale/missing/forged inputs and unconfirmed/direct
calls cannot fill. Concurrent callbacks produce one entry. Existing stop-first
collisions, exposure/sizing/cost checks, marks, full-T1 exit and EOD reconciliation
remain in the same ledger. No second accounting system was introduced.

Independent review found missing decision-identity and recovery timestamp links;
these are repaired and regression-tested. A final recovery-envelope finding was
reproduced as six failing tamper subcases, then repaired. Committed-effect recovery
checks decision/account/run/config/candidate and immutable event/position links
without demanding today's strategy code or fresh market data. The reviewer hit
its usage limit after the last finding; root reviewed and tested the final repair,
so no final independent sign-off beyond those documented findings is claimed.

Actual offline HTTP/scanner tests prove retained ORB detection, waiting, a future
cross, fill102.6 versus reference102, risk rejection, mark/exit and restart. API
and existing dashboard paper journal expose the persisted rule/timestamps. All
25 initial boundary tests and35 HTTP tests passed; the final combined107-test
run adds migration, concurrency and corruption coverage before canonical proof.
These are separate isolated synthetic scenarios, not a performance cohort.
No genuine trade count, win rate, expectancy or live acceptance is inferred.
Other cash strategies and exact CE/PE automatic future triggers remain unavailable;
partial/T2/trailing lifecycle and qualified tick/execution assumptions remain work.
""")
    content = content.replace("|B01 /6 /paper owner|IN_PROGRESS, P0 OPEN|Review docs/drafts/astra_paper_triggers_20261025_01.py against actual committed schema; wire explicit ORB contract in forward_paper.py and paper_portfolio.py; direct-entry, invalidation, expiry, gaps, concurrency, rollback, restart and UI tests. Migrate unsafe automatic legacy behavior without changing recorded historical accounting.|",
        "|B01 /6 /paper owner|ORB SLICE VERIFIED; broader lifecycle INCOMPLETE|Premature automatic legacy path blocked, ORB source-bound trigger/recovery/rollback/API mechanics verified. Other cash/F&O trigger policies, qualified tick/execution assumptions and later lifecycle remain explicit independent work.| ")
    old15 = content[content.index("## 15. "):content.index("## 16. ")]
    old15 = old15.replace("**RUN after completed source edits:** canonical strict receipt", "**Historical prior slice:** canonical strict receipt")
    old15 = old15.replace("Both workers later hit usage limits; no final paper approval is implied.", "Those workers later hit usage limits; the subsequent B01 review and tests are described above.")
    start = content.index("## 15. ")
    end = content.index("## 16. ")
    content = content[:start] + old15.replace("## 15. Verification ledger\n", f"""## 15. Verification ledger

**Latest executed canonical proof:** `../evidence/{name}` passes{count}/{count}
Python,{node}/{node}Node,{compiled}compiled files; zero failures/errors/skips/unraisables.
Source-before equals source-after; exact IDs/log hashes retained. Command:
`.venv_phase4\\Scripts\\python.exe -B -W error::ResourceWarning verify_offline.py --stage astra_orb_trigger_20261025_02`.

New focused receipts: orb_boundaries_20261025_02 PASS25; orb_http_20261025_02
PASS35; orb_integrated_20261025_01 PASS107. Earlier sandbox failures, legacy
inventory failures and one migration assertion mismatch remain preserved.
orb_recovery_before_20261025_01 intentionally fails six tamper subcases before
the recovery-envelope fix; the final combined/canonical runs include the repair.
`astra_b01_preservation_20261025_01.json` checks522 original documents, both env
files, original BRD and both historical archives without operational DB access.

""") + content[end:]
    section(17, "Next-session checkpoint", """
Exact next task: **C03.2 — authenticate and atomically retain dynamic candidate
rank snapshots, then expose bounded read-only history/current API and UI.** B01's
ORB slice is verified; do not recreate the old trigger draft or repeat initial
audit. Broader strategy/contract trigger policies remain unavailable explicitly.

Use the existing `opportunity_ranking` functions; add store validation of actual
batch identity/timestamps/digests and qualified signal/evaluation geometry before
ranking. Persist under `candle_lineage.finish` in the existing scan transaction,
bind the committed descriptor and test rollback/tamper/restart/order/expiry.
Current ranks use source chronology and exact profile scope; read endpoints never
acquire input, recompute persisted ranks, queue decisions or create paper effects.
Durable simulated input support is absent, so ordinary SIMULATED scans stay
unavailable for authenticated ranking until that path is implemented separately.

Safe first command: `Get-Content docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md`.
Reusable continuation: `CONTINUE FROM CHECKPOINT. Preserve verified B01 ORB and
prior evidence, finish C03.2 at its exact recorded step, no provider calls/orders,
then continue the existing six-phase task ledger.`
""")
    report.write_text(content, encoding="utf-8")
    checkpoint = APP / "docs/project/TRADEPULSE_ASTRA_CHECKPOINT.md"
    old = checkpoint.read_text(encoding="utf-8")
    checkpoint.write_text(f"""# TradePulse Astra execution checkpoint

## Current verified boundary — B01 ORB, updated {now}

Mission incomplete. Current phase6 B01 ORB slice VERIFIED OFFLINE; next C03.2
phase4/5 authenticated rank persistence/API/UI. Canonical{name}:PASS{count}Python,
{node}Node,{compiled}compiled; zero failures/errors/skips/unraisables. Validation
and preservation PASS;107 combined regression tests passed first. Source hashes
are in that canonical receipt and astra_b01_preservation_20261025_01.json.

Production changes paper_triggers.py, forward_paper.py, paper_portfolio.py and
scanner_engine.py implement explicit future ORB close cross with retained source,
atomic decision/event/position checks and real scanner health guards. Legacy
automatic entries reject; manual legacy accounting/committed recovery preserved.
28 new trigger tests registered; four workflow/recovery modules migrated.
Other strategy/F&O trigger rules and empirical/live acceptance remain unavailable.

No commands running at this verified boundary. A rank-store worker is waiting
for GO before C03 edits. Root owns storage/candle_lineage/scanner/server/tests;
rank worker will exclusively own new rank_history.py. No source edits occurred
during canonical run. No provider, real order, message, env, operational DB or
Git mutation. Both drafts, prior receipts and release archives retained.

Exact next action: start C03.2 against committed batch/signal/evaluation contracts;
rank_history.initialize/record/validate_descriptor/read_current planned with root
transaction hooks. Keep current versus historical/expired views explicit and
test source forgery, rollback, ordering, scope and read-only API/UI. Continue
existing master report and task ledger; no broad re-planning or initial audit.

## Historical resumption notes below (superseded)

""" + old, encoding="utf-8")
    ledger = APP / "docs/project/TRADEPULSE_ASTRA_TASK_LEDGER.md"
    text = ledger.read_text(encoding="utf-8")
    lines = text.splitlines()
    replacements = {
        "B01": "|B01|6|Strategy-specific automatic paper lifecycle|PARTIAL_VERIFIED|ORB offline slice verified; other strategy/contract triggers unavailable|",
        "B01.2": "|B01.2|6|ORB future contract and atomic guard|VERIFIED_COMPLETE|28 new tests plus canonical; explicit experimental rule, no empirical promotion|",
        "B01.3": "|B01.3|6|Legacy automatic rejection and preserved recovery|VERIFIED_COMPLETE|No new legacy automatic entries; manual accounting and committed recovery tested|",
        "B01.4": "|B01.4|6|Negative/concurrency/rollback/scanner/API acceptance|VERIFIED_COMPLETE|107 combined tests then canonical; review findings reproduced/repaired|",
        "C03.2": "|C03.2|4/5|Retained source validation/persistence/API/UI|IN_PROGRESS|Interface planned; implementation starts after B01 current-source preservation|",
        "F02.1": f"|F02.1|6|Current-slice canonical and preserved history|VERIFIED_COMPLETE|{count}Python/{node}Node/{compiled}compile; source/log/preservation check PASS|",
    }
    for index, line in enumerate(lines):
        parts = line.split("|")
        if len(parts) > 2 and parts[1] in replacements:
            lines[index] = replacements[parts[1]]
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    progress = APP / "docs/project/TRADEPULSE_ASTRA_PROGRESS.md"
    with progress.open("a", encoding="utf-8") as stream:
        stream.write(f"\n## B01 verified boundary — {now}\n\nCombined107/107 passed; canonical{count}/{count}Python,{node}/{node}Node,{compiled}compile. Zero failures/errors/skips/unraisables. Preservation522docs/env/BRD/oldarchives PASS. Recovery corruption before-fix failure retained. Master report/checkpoint/ledger updated. Next C03.2; no operational/provider/config/Git actions.\n")
    bindings = {str(path.relative_to(APP)).replace("\\", "/"): sha(path)
                for path in (report, checkpoint, ledger, progress, evidence, APP / "docs/evidence" / name)}
    with (APP / "docs/evidence/astra_b01_checkpoint_closeout_20261025_01.json").open("x", encoding="utf-8") as stream:
        json.dump(dict(status="PASS", scope="B01_VERIFIED_BOUNDARY_NOT_FULL_MISSION", files=bindings,
            source=source_snapshot(APP), recorded_at=now), stream, indent=2, sort_keys=True)
        stream.write("\n")
    assert all(sha(APP / path) == value for path, value in bindings.items())
    print(json.dumps(dict(status="PASS", python=count, node=node, compiled=compiled, files=len(bindings))))


if __name__ == "__main__":
    main()

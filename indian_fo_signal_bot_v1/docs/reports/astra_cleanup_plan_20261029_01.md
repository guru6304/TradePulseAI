# TradePulse cleanup inventory, 2026-10-29

**Read-only inventory complete. No deletion or source reorganization was performed.**
The owner's cleanup request permits removal of disposable files while retaining
required and future-use material. This inventory distinguishes generated caches
from source, operating state and reproducibility evidence.

The [exact inventory](../evidence/astra_cleanup_inventory_20261029_01.json) proposes
**105 untracked Python bytecode files, totaling 4,557,163 bytes**, under only:

- `__pycache__/`
- `docs/evidence/__pycache__/`

Each candidate records its resolved absolute path, relative path, size and
modification time. These ordinary `.pyc`/`.pyo` files are regenerated from source.
The root agent should recheck that each candidate remains a regular file within
the workspace and outside protected directories before removing it. Delete exact
files first; remove their parent cache directory only if it is then empty. A
later test run may regenerate caches, so the final cleanup receipt should record
the actual files removed rather than assume this snapshot is unchanged.

**All 274 discovered public images are referenced and hash-bound by retained
public JSON evidence. No image qualifies for deletion.** Current source and old
failure screenshots are required by baseline, closeout or browser-artifact
bindings. Removing them would break those receipts. The inventory lists the
public referring/binding documents for each image without reading credentials
or private payloads.

No loose `.tmp`/`.temp`/backup-suffix files or empty public directories were
found. `task2_history_m24ad64e/` remains access-denied and uninspected; its contents
cannot be declared disposable. Do not take ownership or force removal of an
unknown directory. The tracked empty `public/rea` belongs to accepted source
snapshots and is retained pending a separately justified source change.

The larger public files are retained audit/release ZIPs, including the pre-existing
workspace `historical_audit_logs.zip`. The pre-existing
`upstox_acceptance_result.txt` is also historical evidence. Ignored status does not
make either disposable.

Keep source/tests in the application root: current imports, canonical test
discovery and release manifests depend on that layout. The existing `public/`,
`docs/reports/`, `docs/evidence/`, `docs/project/` and `docs/drafts/` directories
already separate runtime UI, reports, reproducibility receipts, mutable handoffs
and preserved drafts. A concise layout/retention guide can make this structure
clear without a risky module migration.

Protected and untouched: Git/worktree metadata and the owner's other branch,
environment/credential files, operational database/WAL/SHM, dependency environment,
all private `.local/` content (including the required offline asset cache), source
and test files, historical reports/releases and original handoff archives. The
inventory did not descend into private/dependency directories, import application
modules, run tests, contact a provider or mutate Git.

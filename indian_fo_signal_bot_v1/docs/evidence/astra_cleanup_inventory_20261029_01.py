"""Read-only public-workspace cleanup inventory; never delete or inspect secrets."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

APP = Path(__file__).resolve().parents[2]
WORKSPACE = APP.parent.resolve()
OUTPUT = APP / "docs/evidence/astra_cleanup_inventory_20261029_01.json"
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico"}
PUBLIC_TEXT = {".json", ".md", ".py", ".js", ".html", ".yml", ".yaml"}
PROTECTED_DIRS = {".git", ".codex", ".agents", ".aws", ".local", ".venv_phase4",
                  ".venv", "venv", "env", "node_modules", ".credentials", ".secrets"}
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def relative(path):
    return path.relative_to(WORKSPACE).as_posix()


def protected_file(path):
    name = path.name.lower()
    return (name.startswith(".env") or name.endswith((".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3",
            ".pem", ".key", ".p12", ".pfx")) or "credential" in name or "secret" in name)


def main():
    assert not OUTPUT.exists(), "Inventory stages are immutable"
    files, errors, skipped, empty_dirs = [], [], Counter(), []

    def scan(directory):
        try:
            entries = list(os.scandir(directory))
        except PermissionError:
            errors.append(dict(path=relative(directory), reason="ACCESS_DENIED_NOT_INSPECTED_OR_DELETED"))
            return
        if not entries:
            empty_dirs.append(relative(directory))
        for entry in entries:
            path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(metadata, "st_file_attributes", 0) & REPARSE:
                    skipped["reparse_or_symlink"] += 1
                elif entry.is_dir(follow_symlinks=False):
                    if path.name in PROTECTED_DIRS:
                        skipped["protected_directory_not_descended"] += 1
                    else:
                        scan(path)
                elif entry.is_file(follow_symlinks=False):
                    assert path.resolve().is_relative_to(WORKSPACE)
                    if protected_file(path):
                        skipped["protected_file_metadata_only"] += 1
                    else:
                        files.append((path, metadata))
            except (PermissionError, OSError) as exc:
                errors.append(dict(path=relative(path), reason=type(exc).__name__))

    scan(WORKSPACE)
    tracked = set(subprocess.check_output(["git", "ls-files", "-z"], cwd=WORKSPACE).decode().split("\0"))
    images = [path for path, _ in files if path.suffix.lower() in IMAGES]
    image_by_name = defaultdict(list)
    for image in images:
        image_by_name[image.name].append(image)
    references, bindings = defaultdict(set), defaultdict(set)
    reference_sources = 0
    parse_errors = []
    for path, metadata in files:
        if path.suffix.lower() not in PUBLIC_TEXT or "__pycache__" in path.parts:
            continue
        # Only public source/document text is read. No private-directory payload,
        # environment value, operational database or archived binary is opened.
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeError, PermissionError, OSError):
            continue
        reference_sources += 1
        mentioned = [name for name in image_by_name if name in body]
        for name in mentioned:
            for image in image_by_name[name]:
                if image != path:
                    references[image].add(relative(path))
        if path.suffix.lower() != ".json" or not mentioned:
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            parse_errors.append(relative(path))
            continue
        # Receipts use both {path: checksum} maps and {file/path, sha256} rows.
        # Hash membership plus the exact filename provides conservative binding.
        for name in mentioned:
            for image in image_by_name[name]:
                checksum = hashlib.sha256(image.read_bytes()).hexdigest()
                if checksum in body:
                    bindings[image].add(relative(path))
    image_rows = []
    for image in sorted(images):
        image_rows.append(dict(path=relative(image), size_bytes=image.stat().st_size,
            tracked=relative(image) in tracked, reference_count=len(references[image]),
            hash_binding_count=len(bindings[image]),
            referenced_by=sorted(references[image]), hash_bound_by=sorted(bindings[image]),
            decision="KEEP_REQUIRED_EVIDENCE" if bindings[image] else "KEEP_ROLE_NOT_PROVEN_DISPOSABLE"))
    candidates = []
    for path, metadata in files:
        if "__pycache__" not in path.parts or path.suffix.lower() not in {".pyc", ".pyo"}:
            continue
        # Only ordinary project cache files qualify, never interpreter/dependency caches.
        assert not any(part in PROTECTED_DIRS for part in path.relative_to(WORKSPACE).parts)
        assert relative(path) not in tracked, "Tracked cache is not automatically disposable"
        candidates.append(dict(path=relative(path), absolute_path=str(path.resolve()),
            size_bytes=metadata.st_size, mtime_ns=metadata.st_mtime_ns,
            reason="UNTRACKED_REGENERABLE_PROJECT_PYTHON_BYTECODE", action="DELETE_CANDIDATE"))
    totals = defaultdict(lambda: dict(files=0, size_bytes=0))
    for path, metadata in files:
        parts = path.relative_to(WORKSPACE).parts
        category = "/".join(parts[:2]) if len(parts) > 1 else parts[0]
        totals[category]["files"] += 1
        totals[category]["size_bytes"] += metadata.st_size
    loose_temp = [dict(path=relative(path), size_bytes=metadata.st_size, tracked=relative(path) in tracked,
        decision="KEEP_UNTIL_ROLE_AND_ACTIVITY_ARE_ESTABLISHED") for path, metadata in files
        if path.suffix.lower() in {".tmp", ".temp"} or path.name.endswith("~")]
    result = dict(schema="tradepulse.safe-cleanup-inventory.v1", status="PASS_READ_ONLY_INVENTORY",
        recorded_at=datetime.now(timezone.utc).isoformat(), workspace=str(WORKSPACE),
        source_helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        provider_requests=0, deletions=0, environment_or_private_payloads_read=False,
        images=image_rows, image_count=len(image_rows),
        image_hash_bound_count=sum(bool(row["hash_binding_count"]) for row in image_rows),
        image_deletion_candidates=[], reference_source_files_read=reference_sources,
        cache_deletion_candidates=sorted(candidates, key=lambda row: row["path"]),
        candidate_file_count=len(candidates), candidate_size_bytes=sum(row["size_bytes"] for row in candidates),
        directory_categories=dict(sorted(totals.items())),
        largest_public_files=sorted([dict(path=relative(path), size_bytes=metadata.st_size)
            for path, metadata in files], key=lambda row: row["size_bytes"], reverse=True)[:15],
        uncertain_temp_files=loose_temp, empty_public_directories=sorted(empty_dirs),
        not_inspected=errors, skipped_categories=dict(skipped), public_json_parse_errors=parse_errors,
        protected_required=["Application and test source, root configuration and Git/worktree metadata",
            "Environment/credentials, operational DB/WAL/SHM, virtual environment and dependencies",
            "All private .local content, including the required retained asset cache",
            "Historical source/report/evidence/release artifacts and original handoff archives",
            "Pre-existing root historical_audit_logs.zip and upstox_acceptance_result.txt",
            "Tracked empty public/rea is part of accepted source snapshots; retained"],
        cleanup_policy="Root must recheck containment, regular-file type and protected paths before deletion; remove only exact bytecode candidates and empty resulting cache directories.")
    with OUTPUT.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("status", "image_count", "image_hash_bound_count",
        "candidate_file_count", "candidate_size_bytes", "not_inspected")}))


if __name__ == "__main__":
    main()

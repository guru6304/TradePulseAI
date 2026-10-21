"""TradePulse AI — Release Packaging, Backup Recovery, and Operational Health Management.

Implements M12 capability:
1. ReleasePackager: Reproducible release manifest, checksum verification, runtime matrix.
2. DatabaseBackupRecovery: Online SQLite backup, integrity verification, point-in-time rollback drills.
3. OperationalHealthMonitor: Local configuration safety, persistence health, operational readiness checks.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple


SUPPORTED_PYTHON_MIN = (3, 10)
SUPPORTED_PYTHON_MAX = (3, 14)


class ReleaseManagementError(Exception):
    """Raised when release packaging, backup, or recovery verification fails."""


class ReleasePackager:
    """Creates and validates reproducible release package manifests."""

    CORE_MODULES = [
        "config.py",
        "brokers.py",
        "diagnostics.py",
        "scanner_engine.py",
        "server.py",
        "instrument_identity.py",
        "paper_portfolio.py",
        "historical_data.py",
        "backtest_engine.py",
        "forward_paper.py",
        "readiness_policy.py",
        "research_protocol.py",
        "source_qualification.py",
        "storage.py",
        "strategies.py",
        "upstox_diagnostics.py",
        "telegram_bot.py",
        "configuration_check.py",
        "instrument_archive.py",
        "performance_acceptance.py",
        "release_management.py",
    ]

    REQUIRED_ASSETS = [
        "public/index.html",
        ".env.example",
    ]

    def __init__(self, root_dir: Optional[str] = None):
        self.root = Path(root_dir or Path(__file__).resolve().parent)

    def check_runtime_compatibility(self) -> Dict[str, Any]:
        """Validates current Python runtime version against the supported matrix."""
        version = sys.version_info[:2]
        compatible = SUPPORTED_PYTHON_MIN <= version <= SUPPORTED_PYTHON_MAX
        return {
            "current_version": f"{version[0]}.{version[1]}",
            "supported_range": f"{SUPPORTED_PYTHON_MIN[0]}.{SUPPORTED_PYTHON_MIN[1]} - {SUPPORTED_PYTHON_MAX[0]}.{SUPPORTED_PYTHON_MAX[1]}",
            "compatible": compatible,
        }

    def generate_manifest(self) -> Dict[str, Any]:
        """Generates a verifiable SHA-256 manifest of all core modules and assets."""
        manifest = {
            "version": "1.0.0-release-candidate",
            "runtime": self.check_runtime_compatibility(),
            "files": {},
            "missing_files": [],
        }

        all_targets = self.CORE_MODULES + self.REQUIRED_ASSETS
        hasher = hashlib.sha256()

        for rel_path in sorted(all_targets):
            file_path = self.root / rel_path
            if not file_path.exists() or not file_path.is_file():
                manifest["missing_files"].append(rel_path)
                continue

            content = file_path.read_bytes()
            file_hash = hashlib.sha256(content).hexdigest()
            manifest["files"][rel_path] = {
                "size_bytes": len(content),
                "sha256": file_hash,
            }
            hasher.update(file_hash.encode("ascii"))

        manifest["manifest_digest"] = hasher.hexdigest()
        manifest["is_complete"] = len(manifest["missing_files"]) == 0
        return manifest

    def verify_manifest(self, manifest: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Check the complete fixed release scope; hashes establish integrity only."""
        errors: List[str] = []
        targets = set(self.CORE_MODULES + self.REQUIRED_ASSETS)
        if (not isinstance(manifest, dict) or manifest.get("is_complete") is not True
                or manifest.get("missing_files") != []
                or not isinstance(manifest.get("files"), dict)
                or set(manifest["files"]) != targets):
            return False, ["A complete manifest of the exact release scope is required."]
        files = manifest["files"]
        hasher = hashlib.sha256()
        for rel_path in sorted(targets):
            expected = files[rel_path]
            if (not isinstance(expected, dict) or type(expected.get("size_bytes")) is not int
                    or expected["size_bytes"] < 0 or not isinstance(expected.get("sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]) is None):
                errors.append(f"Invalid file metadata: {rel_path}")
                continue
            hasher.update(expected["sha256"].encode("ascii"))
            file_path = self.root / rel_path
            try:
                file_path.resolve().relative_to(self.root.resolve())
                content = file_path.read_bytes()
            except (OSError, ValueError):
                errors.append(f"Missing, unreadable or escaped release file: {rel_path}")
                continue
            actual_hash = hashlib.sha256(content).hexdigest()
            if actual_hash != expected["sha256"] or len(content) != expected["size_bytes"]:
                errors.append(f"Content mismatch: {rel_path}")
        if manifest.get("manifest_digest") != hasher.hexdigest():
            errors.append("Manifest digest mismatch.")
        return (len(errors) == 0, errors)


class DatabaseBackupRecovery:
    """Manages transactional online backups, integrity verification, and rollback drills."""

    def __init__(self, db_path: str, backup_dir: Optional[str] = None):
        self.db_path = str(db_path)
        self.backup_dir = Path(backup_dir or Path(db_path).parent / "backups")

    def perform_backup(self, backup_name: Optional[str] = None) -> Dict[str, Any]:
        """Performs a safe online SQLite backup without locking active readers."""
        if self.db_path == ":memory:":
            raise ReleaseManagementError("Cannot perform disk backup of an in-memory database.")

        source_path = Path(self.db_path)
        if not source_path.exists():
            raise ReleaseManagementError(f"Source database file does not exist: {self.db_path}")

        filename = backup_name or f"backup_{Path(self.db_path).stem}_{os.urandom(4).hex()}.db"
        if (not isinstance(filename, str) or not filename or filename in (".", "..")
                or any(c in filename for c in ("/", "\\", ":", "\x00"))):
            raise ReleaseManagementError("Backup name must be a single local filename.")
        dest_path = self.backup_dir / filename
        if dest_path.resolve() == source_path.resolve():
            raise ReleaseManagementError("Backup destination must differ from the source.")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            with dest_path.open("xb"):
                pass  # Reserve a new destination; never overwrite a prior recovery artifact.
        except FileExistsError:
            raise ReleaseManagementError("Backup destination already exists.") from None

        src_conn = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            # Check source integrity before backup
            cursor = src_conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            integrity_result = cursor.fetchone()
            if not integrity_result or integrity_result[0] != "ok":
                raise ReleaseManagementError(f"Source database failed integrity check: {integrity_result}")

            dst_conn = sqlite3.connect(str(dest_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

        # Compute backup file hash and verify destination integrity
        backup_bytes = dest_path.read_bytes()
        backup_hash = hashlib.sha256(backup_bytes).hexdigest()

        verify_conn = sqlite3.connect(str(dest_path))
        try:
            cursor = verify_conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            check = cursor.fetchone()
            if not check or check[0] != "ok":
                raise ReleaseManagementError(f"Backup file failed integrity check: {check}")
        finally:
            verify_conn.close()

        return {
            "status": "BACKUP_COMPLETED",
            "source_db": self.db_path,
            "backup_path": str(dest_path),
            "size_bytes": len(backup_bytes),
            "sha256": backup_hash,
            "integrity_verified": True,
        }

    def verify_restore_drill(self, backup_path: str) -> Dict[str, Any]:
        """Restore into an isolated database and compare complete logical content.

        This proves SQLite recovery mechanics, not paper-ledger reconciliation or
        publisher authenticity. The source backup is opened read-only throughout.
        """
        bp = Path(backup_path)
        if not bp.is_file():
            raise ReleaseManagementError("Backup file not found.")
        report = dict(status="RESTORE_FAILED", backup_path=str(bp), integrity="FAILED",
                      table_count=0, rollback_ready=False, restored_to_isolated_database=False,
                      logical_content_matches=False)
        try:
            with tempfile.TemporaryDirectory(prefix="tradepulse_restore_") as directory:
                source = sqlite3.connect(bp.resolve().as_uri() + "?mode=ro", uri=True)
                try:
                    source.execute("BEGIN")  # One consistent snapshot for both copy and comparison.
                    if source.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                        return report
                    restored = sqlite3.connect(str(Path(directory) / "restored.db"))
                    try:
                        source.backup(restored)
                        report["restored_to_isolated_database"] = True
                        if restored.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                            return report
                        def logical_digest(connection):
                            digest = hashlib.sha256()
                            for statement in connection.iterdump():
                                digest.update(statement.encode("utf-8"))
                                digest.update(b"\n")
                            return digest.hexdigest()
                        matches = logical_digest(source) == logical_digest(restored)
                        report.update(logical_content_matches=matches, integrity="ok",
                            table_count=restored.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0],
                            rollback_ready=matches, status="RESTORE_VERIFIED" if matches else "RESTORE_FAILED")
                    finally:
                        restored.close()
                finally:
                    source.close()
        except (sqlite3.Error, OSError, ValueError):
            # No database content or uncontrolled exception text crosses this boundary.
            report.update(status="RESTORE_FAILED", rollback_ready=False)
        return report


class OperationalHealthMonitor:
    """Inspects runtime health, safe operational flags, and storage readiness."""

    def __init__(self, config_instance: Any = None):
        if config_instance is None:
            from config import BotConfig
            self.config = BotConfig()
        else:
            self.config = config_instance

    def evaluate_health(self) -> Dict[str, Any]:
        """Returns structured status of operational safety, flags, and storage."""
        runtime = ReleasePackager().check_runtime_compatibility()

        safe_flags = {
            "telegram_dry_run": bool(self.config.telegram_dry_run),
            "enable_background_scheduler": bool(self.config.enable_background_scheduler),
            "safe_for_audit": bool(self.config.telegram_dry_run is True and self.config.enable_background_scheduler is False),
        }

        configuration_valid = False
        try:
            self.config.validate(require_live_credentials=True)
            configuration_valid = True
        except (ValueError, TypeError):
            pass
        from storage import resolve_sqlite_path
        db_health = dict(is_memory=False, accessible=False, integrity="NOT_CHECKED")
        try:
            path = resolve_sqlite_path(self.config.database_url)
            db_health["is_memory"] = path == ":memory:"
            # In-memory is a configured ephemeral capability, not a checked existing store.
            if path == ":memory:":
                db_health.update(accessible=True, integrity="EPHEMERAL_NOT_PERSISTENT")
            elif Path(path).is_file():
                connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
                try:
                    ok = connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
                    db_health.update(accessible=ok, integrity="ok" if ok else "FAILED")
                finally:
                    connection.close()
        except (ValueError, TypeError, OSError, sqlite3.Error):
            db_health.update(accessible=False, integrity="FAILED")
        broker = str(self.config.active_broker or "").strip().lower()
        if broker not in ("paper_sim", "simulated", "sim", "angelone", "upstox", "dhan"):
            broker = "UNCONFIGURED"

        return {
            "status": "HEALTHY" if (safe_flags["safe_for_audit"] and runtime["compatible"]
                                     and configuration_valid and db_health["accessible"]) else "DEGRADED",
            "scope": "LOCAL_HEALTH_ONLY",
            "configuration_valid": configuration_valid,
            "authentication": "NOT_TESTED",
            "runtime": runtime,
            "safe_flags": safe_flags,
            "database": db_health,
            "active_broker": broker,
        }

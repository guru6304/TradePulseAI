"""TradePulse AI — Release Packaging, Backup Recovery, and Operational Health Management.

Implements M12 capability:
1. ReleasePackager: Reproducible release manifest, checksum verification, runtime matrix.
2. DatabaseBackupRecovery: Online SQLite backup, integrity verification, point-in-time rollback drills.
3. OperationalHealthMonitor: Local configuration safety, persistence health, operational readiness checks.
"""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import zipfile
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
        "candle_lineage.py",
        "verify_offline.py",
        "contract_universe.py",
        "historical_pagination.py",
        "notification_outbox.py",
        "publisher_trust.py",
        "option_execution.py",
        "historical_study.py",
        "dhan_feed.py",
        "dhan_feed_control.py",
        "angel_feed.py",
        "angel_feed_control.py",
        "angel_history_capture.py",
    ]

    REQUIRED_ASSETS = [
        "public/index.html",
        ".env.example",
        "requirements.txt",
    ]

    # Public handover documents linked by README/runbook. Evidence stays in the
    # repository at the explicit location described in RELEASE_EVIDENCE_LOCATION.
    PUBLIC_DOCUMENTS = [
        "docs/TRADEPULSE_PHASE4_IMPLEMENTATION_20261023.md",
        "docs/TRADEPULSE_OPERATIONS_RUNBOOK.md", "docs/TRADEPULSE_EXECUTION_LEDGER.md",
        "docs/RELEASE_EVIDENCE_LOCATION.md", "docs/OFFICIAL_SOURCE_FEASIBILITY.md",
        "docs/BROKER_RECOVERY_ENGINEERING_REPORT.md", "docs/TRADEPULSE_CAPABILITY_MATRIX.md",
        "docs/TRADEPULSE_COMPLETION_ROADMAP.md", "docs/UPSTOX_CONFIGURATION_FIX_REPORT.md",
        "docs/UPSTOX_READINESS_IMPLEMENTATION.md", "docs/UPSTOX_HTTP_ERROR_REPORT.md",
        "docs/reports/TRADEPULSE_TASK3_FORENSIC_STABILITY_AND_READINESS_REPORT.md",
        "docs/TRADEPULSE_PHASE5A_ENGINEERING_REPORT.md", "docs/TRADEPULSE_FO_CONTRACT_COVERAGE.md",
        "docs/TRADEPULSE_HISTORICAL_PROVENANCE_DESIGN.md", "docs/TRADEPULSE_PAPER_PORTFOLIO_REPORT.md",
        "docs/TRADEPULSE_PHASE4_ENGINEERING_REPORT.md", "docs/TRADEPULSE_MARKET_DATA_ACCEPTANCE_MATRIX.md",
        "docs/PHASE_3B_REPORT.md", "docs/PHASE_3B_TEST_REPORT.md", "docs/PHASE_3B_STRATEGY_ELIGIBILITY.md",
        "docs/PHASE_3B_BACKTEST_METHODOLOGY.md", "docs/PHASE_3A_IMPLEMENTATION_REPORT.md",
        "docs/PHASE_2C_IMPLEMENTATION_REPORT.md",
        "docs/reports/TRADEPULSE_TASK2_PARALLEL_IMPLEMENTATION_REPORT.md",
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

    @staticmethod
    def _bundle_path_allowed(name):
        return (name in set(ReleasePackager.CORE_MODULES + ReleasePackager.REQUIRED_ASSETS)
                or re.fullmatch(r"test_[a-z0-9_]+\.(py|js)", name) is not None
                or name == "README.md" or name in ReleasePackager.PUBLIC_DOCUMENTS)

    def build_bundle(self, destination):
        """Deterministic local candidate, including its offline verification tools.

        Only explicitly permitted public source is read. Existing artifacts are
        never overwritten; no credentials, databases or machine logs are included.
        """
        targets = set(self.CORE_MODULES + self.REQUIRED_ASSETS)
        targets.update(p.name for p in self.root.glob("test_*.py"))
        targets.update(p.name for p in self.root.glob("test_*.js"))
        targets.update(self.PUBLIC_DOCUMENTS)
        if (self.root/"README.md").is_file():
            targets.add("README.md")
        contents = {}
        for name in sorted(targets):
            path = self.root/name
            if not self._bundle_path_allowed(name) or path.is_symlink():
                raise ReleaseManagementError("Invalid release source path.")
            try:
                path.resolve().relative_to(self.root.resolve())
                contents[name] = path.read_bytes()
            except (OSError, ValueError):
                raise ReleaseManagementError("Missing or escaped release source.") from None
        manifest = dict(kind="OFFLINE_RELEASE_CANDIDATE", live_acceptance=False,
            files={name: dict(size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
                   for name, body in contents.items()})
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        contents["RELEASE_MANIFEST.json"] = manifest_bytes
        try:
            with Path(destination).open("xb") as output, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, body in sorted(contents.items()):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system, info.external_attr = 3, 0o100644 << 16
                    archive.writestr(info, body)
        except OSError:
            raise ReleaseManagementError("Release destination unavailable or already exists.") from None
        return self.inspect_bundle(destination)

    def inspect_bundle(self, path):
        """Validate the declared archive in place, without extracting any path."""
        try:
            if Path(path).stat().st_size>70*1024*1024:
                raise ValueError()
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                names = [entry.filename for entry in entries]
                if (len(names)!=len(set(names)) or "RELEASE_MANIFEST.json" not in names
                        or sum(entry.file_size for entry in entries)>64*1024*1024
                        or any(entry.file_size>16*1024*1024 or entry.is_dir()
                               or entry.external_attr>>16 & 0o170000 == 0o120000 for entry in entries)):
                    raise ValueError()
                manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
                files = manifest["files"]
                required = set(self.CORE_MODULES + self.REQUIRED_ASSETS + self.PUBLIC_DOCUMENTS +
                               ["test_bot.py", "test_cash_dashboard.js"])
                if (manifest.get("kind")!="OFFLINE_RELEASE_CANDIDATE" or manifest.get("live_acceptance") is not False
                        or not required.issubset(files) or set(names)!=set(files)|{"RELEASE_MANIFEST.json"}
                        or any(not self._bundle_path_allowed(name) for name in files)):
                    raise ValueError()
                for name, metadata in files.items():
                    body = archive.read(name)
                    if metadata!={"size_bytes":len(body), "sha256":hashlib.sha256(body).hexdigest()}:
                        raise ValueError()
            return dict(status="PASS", scope="OFFLINE_RELEASE_CANDIDATE", files=len(files),
                sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                manifest_sha256=hashlib.sha256(json.dumps(manifest, sort_keys=True,
                    separators=(",", ":")).encode("utf-8")).hexdigest(), publisher_authentication="NOT_ESTABLISHED")
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError):
            raise ReleaseManagementError("Release archive failed integrity or scope validation.") from None


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

    def verify_application_restore(self, backup_path, as_of):
        """Open only an isolated restored copy and reconcile real application facts.

        SQLite integrity alone cannot qualify rollback. No scanner, broker,
        notification sender or account creation service runs in this drill.
        """
        from storage import SQLitePersistenceStore
        from strategies import parse_ist_timestamp
        from notification_outbox import _checked, _check_attempts
        report = dict(status="APPLICATION_RESTORE_FAILED", rollback_ready=False,
            cash_scans_checked=0, paper_accounts_checked=0, notification_intents_checked=0,
            scope="ISOLATED_LOCAL_RESTORE_NO_LIVE_ACCEPTANCE")
        store = None
        try:
            reference = parse_ist_timestamp(as_of)
            backup = Path(backup_path).resolve()
            if not backup.is_file():
                return report
            before = hashlib.sha256(backup.read_bytes()).hexdigest()
            if not self.verify_restore_drill(str(backup))["rollback_ready"]:
                return report
            with tempfile.TemporaryDirectory(prefix="tradepulse_application_restore_") as directory:
                restored = Path(directory)/"restored.db"
                with closing(sqlite3.connect(backup.as_uri()+"?mode=ro", uri=True)) as source:
                    with closing(sqlite3.connect(restored)) as target:
                        source.backup(target)
                store = SQLitePersistenceStore(str(restored))
                try:
                    with store.paper_transaction(write=False) as conn:
                        scans = [r[0] for r in conn.execute("SELECT run_id FROM cash_candle_scans ORDER BY run_id")]
                        accounts = [r[0] for r in conn.execute("SELECT account_id FROM paper_accounts ORDER BY account_id")]
                        for row in conn.execute("SELECT * FROM notification_outbox ORDER BY intent_id"):
                            _checked(row)
                            _check_attempts(conn, row)
                            report["notification_intents_checked"] += 1
                    for run_id in scans:
                        store.load_cash_scan(run_id)
                        report["cash_scans_checked"] += 1
                    for account in accounts:
                        paper = store.get_paper_portfolio_report(account, as_of=reference)
                        if paper.get("reconciliation", {}).get("status")!="OK":
                            raise ValueError("RESTORED_LEDGER_REQUIRES_RECONCILIATION")
                        report["paper_accounts_checked"] += 1
                    if not scans and not accounts:
                        raise ValueError("EMPTY_DATABASE_IS_NOT_APPLICATION_QUALIFICATION")
                    if hashlib.sha256(backup.read_bytes()).hexdigest()!=before:
                        raise ValueError("BACKUP_CHANGED_DURING_DRILL")
                    report.update(status="APPLICATION_RESTORE_VERIFIED", rollback_ready=True,
                                  backup_sha256=before, backup_unchanged=True)
                finally:
                    store.close()
        except Exception:
            # Fixed reason only; no ledger payload, identity or exception message.
            report.update(reason_code="APPLICATION_RESTORE_REQUIRES_INSPECTION")
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


def main(argv=None):
    """Explicit local artifacts and isolated recovery; no server or live calls."""
    import argparse
    parser = argparse.ArgumentParser(description="Local release candidate and isolated application recovery")
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("bundle").add_argument("--output", required=True, type=Path)
    sub.add_parser("inspect").add_argument("--archive", required=True, type=Path)
    drill = sub.add_parser("restore-drill")
    drill.add_argument("--backup", required=True, type=Path)
    drill.add_argument("--as-of", required=True, help="Explicit aware reference timestamp")
    args = parser.parse_args(argv)
    try:
        if args.operation == "bundle":
            report = ReleasePackager().build_bundle(args.output)
        elif args.operation == "inspect":
            report = ReleasePackager().inspect_bundle(args.archive)
        else:
            report = DatabaseBackupRecovery(str(args.backup)).verify_application_restore(str(args.backup), args.as_of)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] in ("PASS", "APPLICATION_RESTORE_VERIFIED") else 1
    except Exception:
        print(json.dumps(dict(status="FAIL", reason_code="LOCAL_RELEASE_OPERATION_REQUIRES_INSPECTION")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

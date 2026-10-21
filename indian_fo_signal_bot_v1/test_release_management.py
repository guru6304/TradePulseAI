"""Unit tests for ReleasePackager, DatabaseBackupRecovery, and OperationalHealthMonitor."""
import os
import copy
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import test_bot
from release_management import (
    ReleasePackager,
    DatabaseBackupRecovery,
    OperationalHealthMonitor,
    ReleaseManagementError,
)
from config import BotConfig


class TestReleaseManagement(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_runtime_compatibility(self):
        packager = ReleasePackager()
        res = packager.check_runtime_compatibility()
        self.assertTrue(res["compatible"])
        self.assertIn("3.", res["current_version"])

    def test_manifest_generation_and_verification(self):
        packager = ReleasePackager()
        manifest = packager.generate_manifest()
        self.assertTrue(manifest["is_complete"], f"Missing: {manifest['missing_files']}")
        self.assertIn("manifest_digest", manifest)
        self.assertIn("config.py", manifest["files"])

        valid, errors = packager.verify_manifest(manifest)
        self.assertTrue(valid, errors)
        self.assertEqual(len(errors), 0)

    def test_database_backup_and_restore_drill(self):
        db_file = self.temp_path / "test_live.db"
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, name TEXT);")
        cursor.execute("INSERT INTO records (name) VALUES ('trade_1'), ('trade_2');")
        conn.commit()
        conn.close()

        backup_mgr = DatabaseBackupRecovery(str(db_file), backup_dir=str(self.temp_path / "backups"))
        backup_res = backup_mgr.perform_backup("custom_backup.db")

        self.assertEqual(backup_res["status"], "BACKUP_COMPLETED")
        self.assertTrue(backup_res["integrity_verified"])
        self.assertTrue(Path(backup_res["backup_path"]).exists())

        # Test restore verification drill
        restore_res = backup_mgr.verify_restore_drill(backup_res["backup_path"])
        self.assertEqual(restore_res["status"], "RESTORE_VERIFIED")
        self.assertEqual(restore_res["integrity"], "ok")
        self.assertEqual(restore_res["table_count"], 1)
        self.assertTrue(restore_res["rollback_ready"])

    def test_backup_fails_on_memory_db(self):
        mgr = DatabaseBackupRecovery(":memory:")
        with self.assertRaises(ReleaseManagementError):
            mgr.perform_backup()

    def test_operational_health_monitor(self):
        cfg = BotConfig(
            database_url=":memory:",
            active_broker="paper_sim",
            telegram_dry_run=True,
            enable_background_scheduler=False,
        )
        monitor = OperationalHealthMonitor(cfg)
        health = monitor.evaluate_health()
        self.assertEqual(health["status"], "HEALTHY")
        self.assertTrue(health["safe_flags"]["safe_for_audit"])
        self.assertEqual(health["active_broker"], "paper_sim")

    def test_manifest_rejects_empty_partial_and_incomplete_claims(self):
        packager = ReleasePackager()
        complete = packager.generate_manifest()
        partial = copy.deepcopy(complete)
        partial["files"].pop("brokers.py")
        for manifest in ({}, None, {"files": {}}, partial,
                         dict(complete, is_complete=False),
                         dict(complete, missing_files=["brokers.py"]),
                         dict(complete, manifest_digest="0" * 64)):
            with self.subTest(shape=type(manifest).__name__):
                self.assertFalse(packager.verify_manifest(manifest)[0])

    def test_manifest_rejects_unknown_paths_before_reading_files(self):
        packager = ReleasePackager()
        manifest = packager.generate_manifest()
        manifest["files"]["../.env"] = {"size_bytes": 0, "sha256": "0" * 64}
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Must reject paths before I/O")):
            self.assertFalse(packager.verify_manifest(manifest)[0])

    def test_manifest_rejects_malformed_file_metadata(self):
        packager = ReleasePackager()
        for metadata in (None, {}, {"size_bytes": True, "sha256": "0" * 64},
                         {"size_bytes": 0, "sha256": "invalid"}):
            manifest = packager.generate_manifest()
            manifest["files"]["config.py"] = metadata
            self.assertFalse(packager.verify_manifest(manifest)[0])

    def test_manifest_covers_every_production_module(self):
        root = Path(__file__).parent
        production = {p.name for p in root.glob("*.py") if not p.name.startswith("test_")}
        self.assertEqual(set(ReleasePackager.CORE_MODULES), production)

    def test_restore_rejects_corrupt_backup_and_missing_file(self):
        mgr = DatabaseBackupRecovery(str(self.temp_path / "unused.db"))
        corrupt = self.temp_path / "corrupt.db"
        corrupt.write_bytes(b"offline corrupt backup fixture")
        report = mgr.verify_restore_drill(str(corrupt))
        self.assertFalse(report["rollback_ready"])
        self.assertEqual(report["status"], "RESTORE_FAILED")
        self.assertEqual(corrupt.read_bytes(), b"offline corrupt backup fixture")
        with self.assertRaises(ReleaseManagementError):
            mgr.verify_restore_drill(str(self.temp_path / "missing.db"))

    def test_restore_really_copies_and_compares_logical_content(self):
        source = self.temp_path / "source.db"
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, body BLOB)")
            conn.execute("INSERT INTO data VALUES (1, ?)", (b"offline fixture",))
        mgr = DatabaseBackupRecovery(str(source))
        source_before = source.read_bytes()
        backup = mgr.perform_backup()
        before = Path(backup["backup_path"]).read_bytes()
        report = mgr.verify_restore_drill(backup["backup_path"])
        self.assertTrue(report["restored_to_isolated_database"])
        self.assertTrue(report["logical_content_matches"])
        self.assertEqual(report["table_count"], 1)
        self.assertEqual(Path(backup["backup_path"]).read_bytes(), before)
        self.assertEqual(source.read_bytes(), source_before)

    def test_backup_rejects_escape_and_existing_destination(self):
        source = self.temp_path / "source.db"
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute("CREATE TABLE data (id INTEGER)")
        mgr = DatabaseBackupRecovery(str(source), str(self.temp_path / "backups"))
        for name in ("../outside.db", str(source), "nested/backup.db", "..\\outside.db"):
            with self.subTest(name=name), self.assertRaises(ReleaseManagementError):
                mgr.perform_backup(name)
        result = mgr.perform_backup("fixed.db")
        before = Path(result["backup_path"]).read_bytes()
        with self.assertRaises(ReleaseManagementError):
            mgr.perform_backup("fixed.db")
        self.assertEqual(Path(result["backup_path"]).read_bytes(), before)

    def test_health_does_not_claim_missing_or_corrupt_storage_accessible(self):
        missing = self.temp_path / "missing.db"
        corrupt = self.temp_path / "corrupt.db"
        corrupt.write_bytes(b"not sqlite")
        for db in (missing, corrupt):
            cfg = BotConfig(database_url=str(db), telegram_dry_run=True, enable_background_scheduler=False)
            report = OperationalHealthMonitor(cfg).evaluate_health()
            self.assertFalse(report["database"]["accessible"])
            self.assertEqual(report["status"], "DEGRADED")
        self.assertFalse(missing.exists())

    def test_health_rejects_invalid_config_without_echoing_values(self):
        cfg = BotConfig(active_broker="INVALID_CANARY", telegram_dry_run=True,
                        enable_background_scheduler=False)
        report = OperationalHealthMonitor(cfg).evaluate_health()
        self.assertEqual(report["status"], "DEGRADED")
        self.assertFalse(report["configuration_valid"])
        self.assertNotIn("INVALID_CANARY", str(report))


if __name__ == "__main__":
    unittest.main()

"""Unit tests for ReleasePackager, DatabaseBackupRecovery, and OperationalHealthMonitor."""
import os
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


if __name__ == "__main__":
    unittest.main()

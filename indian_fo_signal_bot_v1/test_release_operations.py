"""Offline release bytes and restored application invariants, never live delivery."""
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
import zipfile

import test_bot
from release_management import DatabaseBackupRecovery, ReleaseManagementError, ReleasePackager


class TestReleaseBundle(unittest.TestCase):
    def test_reproducible_bundle_excludes_private_state_and_runs_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = (Path(directory)/name for name in ("first.zip", "second.zip"))
            packager = ReleasePackager()
            one, two = packager.build_bundle(first), packager.build_bundle(second)
            self.assertEqual(one["sha256"], two["sha256"])
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(packager.inspect_bundle(first)["status"], "PASS")
            with zipfile.ZipFile(first) as archive:
                names = archive.namelist()
                self.assertNotIn("verify_live_quick.py", names)
                self.assertIn("test_bot.py", names)
                self.assertIn("test_cash_dashboard.js", names)
                self.assertIn("docs/TRADEPULSE_OPERATIONS_RUNBOOK.md", names)
                self.assertIn("docs/TRADEPULSE_EXECUTION_LEDGER.md", names)
                self.assertIn("docs/RELEASE_EVIDENCE_LOCATION.md", names)
                # README/runbook Markdown links must resolve inside the delivered ZIP.
                import posixpath
                import re
                for doc in ("README.md", "docs/TRADEPULSE_OPERATIONS_RUNBOOK.md"):
                    for link in re.findall(r"\]\(([^)]+)\)", archive.read(doc).decode("utf-8-sig")):
                        if "://" not in link and not link.startswith("#"):
                            target = posixpath.normpath(posixpath.join(posixpath.dirname(doc), link.split("#")[0]))
                            self.assertIn(target, names, (doc, link))
                self.assertFalse(any(n == ".env" or n.endswith((".db", ".sqlite")) or "evidence/" in n for n in names))
                extracted = Path(directory)/"extracted"
                # This archive was generated above and scope-validated first.
                archive.extractall(extracted)
            bootstrap = subprocess.run([sys.executable, "-B", "-c",
                "import unittest,test_bot,publisher_trust,option_execution,historical_study,dhan_feed,dhan_feed_control; assert publisher_trust._CRYPTO_AVAILABLE; from verify_offline import case_ids; "
                "cases=list(case_ids(unittest.defaultTestLoader.loadTestsFromName('test_bot'))); "
                "assert len(cases)==len(set(cases)) and len(cases)>0; "
                "assert not any('FailedTest' in c for c in cases); print('BOOTSTRAP_OK')"],
                cwd=extracted, capture_output=True, text=True, timeout=30)
            self.assertEqual(bootstrap.returncode, 0, bootstrap.stderr)
            self.assertIn("BOOTSTRAP_OK", bootstrap.stdout)
            with self.assertRaises(ReleaseManagementError):
                packager.build_bundle(first)
            self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(), one["sha256"])

    def test_bundle_rejects_corrupt_content_and_undeclared_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"bundle.zip"
            packager = ReleasePackager()
            packager.build_bundle(target)
            with zipfile.ZipFile(target, "a") as archive:
                archive.writestr("../.env", "OFFLINE_NOT_A_SECRET")
            with self.assertRaises(ReleaseManagementError):
                packager.inspect_bundle(target)

    def test_bundle_detects_changed_source_bytes_with_original_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            original, changed = Path(directory)/"original.zip", Path(directory)/"changed.zip"
            packager = ReleasePackager()
            packager.build_bundle(original)
            with zipfile.ZipFile(original) as source, zipfile.ZipFile(changed, "w") as target:
                for name in source.namelist():
                    target.writestr(name, b"OFFLINE_CHANGED_BYTES" if name=="brokers.py" else source.read(name))
            with self.assertRaises(ReleaseManagementError):
                packager.inspect_bundle(changed)


class TestApplicationRestore(unittest.TestCase):
    def setUp(self):
        from test_cash_workflow import TestCashWorkflow
        self.workflow = TestCashWorkflow()
        self.workflow.setUp()
        self.addCleanup(self.workflow.doCleanups)
        self.workflow.use_orb_account()
        code, scan = self.workflow.request("POST", "/api/scan")
        self.assertEqual(code, 200)
        self.workflow.advance_orb_trigger()
        self.assertEqual(self.workflow.request("POST", "/api/scan")[0], 200)
        self.manager = DatabaseBackupRecovery(self.workflow.engine.store.db_path,
            str(Path(self.workflow.fixture.temp.name)/"backups"))

    def test_restore_reopens_real_store_reconciles_cash_paper_and_outbox(self):
        backup = self.manager.perform_backup("valid.db")
        target = Path(backup["backup_path"])
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        report = self.manager.verify_application_restore(str(target), self.workflow.orb.now)
        self.assertEqual(report["status"], "APPLICATION_RESTORE_VERIFIED")
        self.assertGreater(report["cash_scans_checked"], 0)
        self.assertEqual(report["paper_accounts_checked"], 1)
        self.assertGreater(report["notification_intents_checked"], 0)
        self.assertEqual(before, hashlib.sha256(target.read_bytes()).hexdigest())
        _, paper = self.workflow.request("GET", "/api/paper-portfolio?account_id=offline-cash")
        self.assertEqual(paper["accounting"]["open_positions"], 1)
        self.assertEqual(paper["reconciliation"]["status"], "OK")

    def test_sqlite_integrity_alone_cannot_pass_tampered_application_restore(self):
        with self.workflow.engine.store.paper_transaction() as conn:
            conn.execute("UPDATE signals SET position_qty=position_qty+1")
        backup = self.manager.perform_backup("tampered.db")
        self.assertTrue(self.manager.verify_restore_drill(backup["backup_path"])["rollback_ready"])
        report = self.manager.verify_application_restore(backup["backup_path"], self.workflow.orb.now)
        self.assertEqual(report["status"], "APPLICATION_RESTORE_FAILED")
        self.assertFalse(report["rollback_ready"])
        self.assertNotIn("OFFLINE", json.dumps(report))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Actual SQLite failures, isolated memory fixtures; no operational store access."""
import unittest
import test_phase45_integration as fixtures


class TestActualContextSQLiteFailures(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.TestPhase45IndependentIntegration()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.engine,_,self.raw=self.case.engine()

    def test_actual_sqlite_snapshot_failure_keeps_phase4_and_marks_context_unavailable(self):
        with self.engine.store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER authored_context_failure BEFORE INSERT ON scan_context_snapshots "
                         "BEGIN SELECT RAISE(ABORT,'authored SQLite failure'); END")
        result=self.engine.run_single_scan()
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['total_signals'],1)
        self.assertEqual(result['context']['status'],'UNAVAILABLE')
        self.assertEqual(self.engine.store.load_cash_scan(result['run_id'])['status'],'COMMITTED')
        self.assertEqual(self.engine.store.query_signals()['total_count'],1)

    def test_actual_sqlite_import_failure_returns503_and_rolls_back_source(self):
        with self.engine.store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER authored_import_failure BEFORE INSERT ON context_ingestions "
                         "BEGIN SELECT RAISE(ABORT,'authored SQLite failure'); END")
        code,payload=self.case.handler(self.engine)._handle_context_import(dict(provider='offline_notices',
            collected_at='2026-10-23T08:40:00+00:00',payload=self.raw.decode()))
        self.assertEqual(code,503)
        self.assertEqual(payload['status'],'UNAVAILABLE')
        self.assertEqual(self.engine.store.list_context_ingestions()['total_count'],0)

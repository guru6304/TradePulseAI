"""Three configured weekday sessions, synthetic prices, real persistent ledger."""
from datetime import datetime
import unittest

import test_bot
from paper_portfolio import PaperPortfolio, FORWARD_FILL_POLICY
from storage import SQLitePersistenceStore


class TestPaperSessionQualification(unittest.TestCase):
    def test_three_sessions_restart_repeated_callbacks_and_stable_eod_statements(self):
        from test_phase5a_paper import TestPhase5APaperPortfolio
        fixture = TestPhase5APaperPortfolio()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        paper = fixture._service(fill_policy=FORWARD_FILL_POLICY, cost_model_json="{}")
        statements, fees = {}, 0
        for index, day in enumerate(("2026-10-16", "2026-10-19", "2026-10-20"), 1):
            fixture._set_time("10:10", date=day)
            candidate = fixture._candidate(paper)
            body = dict(candidate.to_dict(), timestamp=day+" 10:00:00")
            bar = fixture._bar(candidate, timestamp=day+"T10:05:00+05:30")
            opened = paper.enter(body, bar, "entry-"+day)
            fixture.store.close()
            fixture.store = SQLitePersistenceStore(fixture.database)
            self.addCleanup(fixture.store.close)
            paper = PaperPortfolio(fixture.store, paper.config, clock=lambda: fixture.now)
            self.assertTrue(paper.enter(body, bar, "entry-"+day)["idempotent"])
            fixture._set_time("10:15", date=day)
            exit_bar = fixture._bar(candidate, timestamp=day+"T10:10:00+05:30", high=125, low=99, close=121)
            closed = paper.process_bar(opened["position_id"], exit_bar, "exit-"+day)
            self.assertEqual(closed["exit_reason"], "TARGET")
            self.assertTrue(paper.process_bar(opened["position_id"], exit_bar, "exit-"+day)["idempotent"])
            fixture._set_time("16:00", date=day)
            report = fixture.store.get_paper_session_report(paper.config.account_id, day, as_of=fixture.now)
            self.assertEqual(report["eod_status"], "RECONCILED")
            self.assertEqual(report["accounting"]["entries_in_session"], 1)
            snapshot = paper.snapshot()
            self.assertEqual(snapshot["reconciliation"]["status"], "OK")
            self.assertEqual(snapshot["accounting"]["closed_positions"], index)
            self.assertEqual(snapshot["accounting"]["open_positions"], 0)
            self.assertGreater(snapshot["accounting"]["fees_paid_inr"], fees)
            fees = snapshot["accounting"]["fees_paid_inr"]
            statements[day] = report["statement_sha256"]
        for day, checksum in statements.items():
            self.assertEqual(fixture.store.get_paper_session_report(paper.config.account_id, day,
                as_of=fixture.now)["statement_sha256"], checksum)


if __name__ == "__main__":
    unittest.main(verbosity=2)

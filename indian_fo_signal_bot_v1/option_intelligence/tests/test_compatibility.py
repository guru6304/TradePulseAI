"""Synthetic cross-schema boundaries; no store, transport or runtime activation."""
import ast
from copy import deepcopy
from pathlib import Path
import sys
import unittest

# This existing fixture module applies the credential-free test_bot bootstrap
# before any core imports. Its fixture setUp constructs only in-memory records.
import test_option_observations as capture_fixtures
from instrument_identity import validate_contract_identity

from option_intelligence.context import inspect_context
from option_intelligence.identity import validate_contract
from option_intelligence.quotes import inspect_quote
from .test_identity import DECISION, contract_record
from .test_quotes import contract, policy, session


class TestOptionIntelligenceCompatibility(unittest.TestCase):
    @staticmethod
    def capture():
        fixture = capture_fixtures.TestOptionObservations()
        fixture.setUp()
        return fixture.parse()

    def test_existing_normalized_identity_drops_tick_and_is_not_new_contract_input(self):
        raw = contract_record(strike=25000, tick_size=.05)
        original = deepcopy(raw)
        normalized = validate_contract_identity(raw, provider="upstox", as_of=DECISION)
        self.assertEqual(original, raw)
        self.assertEqual(raw["identifier"], normalized["identifier"])
        self.assertEqual(raw["lot_size"], normalized["lot_size"])
        self.assertNotIn("tick_size", normalized)
        self.assertEqual("NOT_ESTABLISHED", normalized["historical_validity"])

        result = validate_contract(normalized, decision_at=DECISION)
        self.assertEqual("UNAVAILABLE", result.evidence.state)
        self.assertEqual(("MISSING_TICK_SIZE",), result.evidence.reason_codes)
        self.assertIsNone(result.contract)

    def test_actual_capture_keeps_unavailable_clocks_units_and_no_permissions(self):
        capture = self.capture()
        self.assertEqual("STRUCTURALLY_VALID_UNQUALIFIED", capture["status"])
        self.assertEqual("SYNTHETIC_FIXTURE", capture["provenance"])
        self.assertEqual("UNAVAILABLE", capture["capabilities"]["source_time"])
        self.assertEqual("UNAVAILABLE", capture["capabilities"]["normalized_units"])
        self.assertEqual("NOT_ESTABLISHED", capture["capabilities"]["publisher_authority"])
        self.assertTrue(capture["observations"])
        for row in capture["observations"]:
            with self.subTest(identifier=row["identity"]["identifier"]):
                self.assertIsNone(row["source_time"])
                self.assertEqual("UNAVAILABLE_SOURCE_TIME", row["source_time_status"])
                self.assertEqual("OBSERVED", row["fields"]["bid_price"]["presence"])
                self.assertGreater(row["fields"]["bid_price"]["numeric_value"], 0)
                for field in row["fields"].values():
                    self.assertIsNone(field["normalized_value"])
                    self.assertEqual("UNAVAILABLE_UNIT_CONTRACT", field["unit_status"])
                for owner in (capture, row):
                    for flag in ("eligible", "actionable", "historical_replay_allowed"):
                        self.assertIs(owner[flag], False)

    def test_actual_capture_cannot_be_auto_promoted_into_new_snapshot_boundaries(self):
        capture = self.capture()
        row = capture["observations"][0]
        original = deepcopy((capture, row))
        identity = validate_contract(row["identity"], decision_at=capture["decision_at"])
        self.assertEqual("UNAVAILABLE", identity.evidence.state)
        self.assertIn("MISSING_TICK_SIZE", identity.evidence.reason_codes)
        self.assertIsNone(identity.contract)

        # Having raw bid/ask/Greeks does not make either old envelope a new
        # explicit clock/unit/identity record. No adapter or field guess occurs.
        quote = inspect_quote(row, contract(), decision_at=DECISION, intended_lots=1,
                              policy=policy(), session=session())
        self.assertEqual("UNAVAILABLE", quote.evidence.state)
        self.assertIn("CONTRACT_ID_UNAVAILABLE", quote.evidence.reason_codes)
        self.assertIsNone(quote.metrics)
        context = inspect_context(row, contract(), decision_at=DECISION, max_age_seconds=3)
        self.assertNotEqual("VERIFIED", context.common_evidence.state)
        self.assertTrue(all(field.value is None for field in context.fields))
        self.assertEqual(original, (capture, row))

    def test_runtime_package_imports_cannot_reach_production_or_transport_services(self):
        package = Path(__file__).resolve().parents[1]
        # Verification entrypoints may import existing offline test harnesses;
        # they are not runtime calculation modules.
        harnesses = {"verify.py", "verify_checkpoint.py"}
        modules = tuple(path for path in package.glob("*.py") if path.name not in harnesses)
        self.assertGreaterEqual(len(modules), 6)
        forbidden = {
            "brokers", "config", "scanner_engine", "strategies", "storage", "server",
            "forward_paper", "paper_portfolio", "paper_triggers", "opportunity_ranking",
            "rank_history", "option_execution", "option_observations", "instrument_identity",
            "requests", "urllib", "http", "socket", "sqlite3", "subprocess", "os", "pathlib",
        }
        for path in modules:
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports = tuple(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        imports = ((node.module or "").split(".")[0],)
                    else:
                        imports = ()
                    for name in imports:
                        self.assertNotIn(name, forbidden)
                        self.assertIn(name, sys.stdlib_module_names)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        self.assertNotIn(node.func.id, {"__import__", "eval", "exec", "open"})


if __name__ == "__main__":
    unittest.main()

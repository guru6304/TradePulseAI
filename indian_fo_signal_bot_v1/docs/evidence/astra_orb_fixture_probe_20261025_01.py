"""OFFLINE draft-schema probe; no production trigger acceptance claim."""
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import sys
import unittest

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import digest, offline_network, timestamp
from test_astra_paper_triggers import ORBScannerFixture


def main():
    output = Path(__file__).with_suffix(".json")
    if output.exists():
        raise FileExistsError("Preserve the existing receipt; use a new stage")
    draft = APP / "docs/drafts/astra_paper_triggers_20261025_01.py"
    spec = importlib.util.spec_from_file_location("astra_orb_draft_probe", draft)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scenarios = []
    with ExitStack() as stack:
        offline_network(stack)
        for side in ("LONG", "SHORT"):
            owner = unittest.TestCase()
            try:
                fixture = ORBScannerFixture(owner, side)
                first = fixture.scan()
                candidate = fixture.candidate(first)
                queued = fixture.now
                with fixture.store.lineage_read() as conn:
                    contract = module.build_contract(fixture.store, conn, first["run_id"], candidate, "15:15")
                decision = dict(source_scan_run_id=first["run_id"], candidate=candidate,
                                trigger_contract=contract, queued_at_ist=queued.isoformat())
                from paper_portfolio import PaperAccountConfig
                config = PaperAccountConfig(account_id="schema-probe", run_id="offline",
                    provider="angelone", source_data_mode="LIVE", square_off_ist="15:15")
                bars = ([(102, 102.3, 101.5, 102.2), (102.2, 102.8, 101.7, 102.6)] if side == "LONG"
                        else [(98, 98.5, 97.7, 97.8), (97.8, 98.3, 97.2, 97.4)])
                observations = []
                for open_, high, low, close in bars:
                    fixture.append_bar(open=open_, high=high, low=low, close=close)
                    later = fixture.scan()
                    with fixture.store.lineage_read() as conn:
                        observation = module.observation_record(fixture.store, conn, decision,
                            fixture.retained_bar(later), later["run_id"], fixture.now, config)
                    observations.append(observation)
                    decision["trigger_evaluations"] = list(observations)
                assert [o["status"] for o in observations] == ["WAITING", "TRIGGERED"]
                scenarios.append(dict(side=side, signal=candidate, contract=contract, observations=observations,
                    retained_scan_status=fixture.work(first)["status"], provider_requests="MOCKED_ONLY"))
            finally:
                if not owner.doCleanups():
                    raise AssertionError("Fixture cleanup failed")
    report = dict(status="PASS_DRAFT_SCHEMA_ONLY", timestamp=timestamp(), scenarios=scenarios,
        draft=draft.relative_to(APP).as_posix(), draft_sha256=digest(draft),
        fixture_sha256=digest(APP / "test_astra_paper_triggers.py"),
        scope="Synthetic wire fixture, genuine scanner and retained evaluations; no production entry or live acceptance.")
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(dict(status=report["status"], sides=[s["side"] for s in scenarios],
        decisions=[[o["status"] for o in s["observations"]] for s in scenarios])))


if __name__ == "__main__":
    main()

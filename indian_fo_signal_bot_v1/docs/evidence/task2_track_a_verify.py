"""Execute local offline Track A tests and retain source-bound receipts."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

root = Path(__file__).resolve().parents[2]
stage = sys.argv[1] if len(sys.argv) > 1 else "final"
if not re.fullmatch(r"[a-z0-9_]{1,40}", stage):
    raise ValueError("Invalid receipt stage")
files = ["historical_study.py", "option_execution.py", "test_historical_study.py",
         "test_option_execution.py", "test_phase4_acceptance.py", "test_publisher_trust.py"]
snapshot = lambda: {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
before = snapshot()
command = [sys.executable, "-B", "-W", "error::ResourceWarning", "-m", "unittest",
           "test_historical_study", "test_option_execution", "test_phase4_acceptance", "test_publisher_trust", "-v"]
completed = subprocess.run(command, cwd=root, capture_output=True, text=True)
output = completed.stdout + completed.stderr
after = snapshot()
log = root / ("docs/evidence/task2_track_a_focused_" + stage + ".txt")
with log.open("x", encoding="utf-8") as handle:
    handle.write(output)
match = re.search(r"Ran (\d+) tests? in ([\d.]+)s", output)
result = dict(schema_version="tradepulse.track-a-focused-receipt.v1", command=command,
    scope="LOCAL_OFFLINE_FIXTURES_NOT_REAL_DATA_RIGHTS_OR_PROVIDER_ACCEPTANCE",
    created_at=datetime.now(timezone.utc).isoformat(), exit_code=completed.returncode,
    tests_run=int(match[1]) if match else None, duration_seconds=float(match[2]) if match else None,
    passed=completed.returncode == 0 and before == after,
    source_before=before, source_after=after, source_unchanged=before == after,
    log_path=str(log.relative_to(root)), log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
    real_historical_study_status="BLOCKED", authentic_source_verification="NOT_PERFORMED",
    blockers=["APPROVED_PUBLISHER_ROOTS", "INDEPENDENT_AUTHENTIC_PROVIDER_ARTIFACTS",
              "RIGHTS_DOCUMENTS_AND_OPERATOR_REVIEW", "EXECUTABLE_HISTORICAL_OPTION_BID_ASK_DEPTH_OI"])
with (root / ("docs/evidence/task2_track_a_focused_" + stage + ".json")).open("x", encoding="utf-8") as handle:
    json.dump(result, handle, indent=2)
print(json.dumps(result, indent=2))
sys.exit(0 if result["passed"] else 1)

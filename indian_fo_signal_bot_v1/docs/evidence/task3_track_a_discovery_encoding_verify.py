"""Complete public evidence metadata inventory across UTF-8 and UTF-16 receipts."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
folder = APP / "docs/evidence"
prior = folder / "task3_track_a_input_discovery.json"
report = json.loads(prior.read_text(encoding="utf-8"))
inspected, unavailable, source_files, roots, grants = [], [], [], [], []
for path in sorted(folder.glob("*.json")):
    raw = path.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        value = json.loads(raw.decode(encoding))
    except (ValueError, UnicodeError):
        unavailable.append(dict(path=path.relative_to(APP).as_posix(), bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(), reason="EMPTY" if not raw else "NOT_PARSEABLE_JSON"))
        continue
    inspected.append(dict(path=path.relative_to(APP).as_posix(), encoding=encoding,
        sha256=hashlib.sha256(raw).hexdigest()))
    if not isinstance(value, dict):
        continue
    if value.get("schema_version") in ("tradepulse.cash-observations.v1", "tradepulse.option-observations.v1",
            "tradepulse.instrument-master.v1", "tradepulse.publisher-manifest.v1"):
        source_files.append(path.relative_to(APP).as_posix())
    if isinstance(value.get("anchors"), list) and value["anchors"]:
        roots.append(path.relative_to(APP).as_posix())
    if isinstance(value.get("grants"), list) and value["grants"]:
        grants.append(path.relative_to(APP).as_posix())
report.update(recorded_at=datetime.now(timezone.utc).isoformat(),
    initial_discovery_receipt=dict(path=prior.relative_to(APP).as_posix(),
        sha256=hashlib.sha256(prior.read_bytes()).hexdigest()),
    encoding_aware_public_receipt_inventory=inspected,
    public_receipt_encoding_counts=dict(Counter(row["encoding"] for row in inspected)),
    unparseable_public_receipts=unavailable,
    inspected_public_json_receipts=len(inspected), actual_source_schema_files=source_files,
    nonempty_operator_anchor_records_discovered=roots,
    nonempty_operator_rights_grant_records_discovered=grants,
    supplemental_scope="Public evidence files only; UTF-16 build/validation receipts retained, no operational or secret content read.",
    acceptance=dict(AUTHENTIC_SOURCE_VERIFICATION="BLOCKED", RIGHTS_AND_SCOPE_VERIFICATION="BLOCKED",
        CASH_HISTORICAL_STUDY="BLOCKED", OPTION_HISTORICAL_STUDY="BLOCKED"))
target = folder / "task3_track_a_input_discovery_verified.json"
with target.open("x", encoding="utf-8") as handle:
    json.dump(report, handle, indent=2)
    handle.write("\n")
print(json.dumps(dict(path=target.relative_to(APP).as_posix(), sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    parsed_public_receipts=len(inspected), encoding_counts=report["public_receipt_encoding_counts"],
    unparseable=unavailable, actual_source_schema_files=source_files, operator_roots=roots, operator_grants=grants,
    acceptance=report["acceptance"]), indent=2))

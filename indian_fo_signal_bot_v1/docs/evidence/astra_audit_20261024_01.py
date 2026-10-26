"""Fresh, non-destructive mission baseline. Never opens operational databases."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from zipfile import ZipFile
from xml.etree import ElementTree as ET

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot, validate_evidence

BRD = Path(r"C:\Users\HP\Downloads\TradePulse_AI_BRD_and_Project_Status_2026-10-24.docx")
MISSION = Path(r"C:\Users\HP\.codex\attachments\5c15dd24-0992-494f-87a9-4c8752dd1fc6\Pasted text.txt")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, data):
    path = APP / "docs/evidence" / name
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def main():
    documents = {p.relative_to(APP).as_posix(): digest(p) for p in sorted((APP / "docs").rglob("*"))
                 if p.is_file() and not p.name.startswith("astra_")}
    config = {str(p): digest(p) for p in (APP / ".env", APP.parent / ".env") if p.is_file()}
    safety = {}
    for path in (APP.parent / ".env", APP / ".env"):
        if path.exists():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                key, _, value = line.partition("=")
                if key.strip() in ("ACTIVE_BROKER", "TELEGRAM_DRY_RUN", "ENABLE_BACKGROUND_SCHEDULER"):
                    safety[key.strip()] = value.strip().strip("\"'")
    proof = validate_evidence(APP / "docs/evidence/master_phase6_20261024_01.json")
    with ZipFile(BRD) as archive:
        tree = ET.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = ["".join(t.text or "" for t in p.findall(".//w:t", ns)) for p in tree.findall(".//w:p", ns)]
    write("astra_brd_extracted_20261024_01.json", dict(original_sha256=digest(BRD), paragraphs=paragraphs))
    releases = {p.name: digest(p) for p in sorted(APP.glob("*.zip"))}
    write("astra_baseline_20261024_01.json", dict(
        kind="READ_ONLY_PRE_IMPLEMENTATION_BASELINE", created_at=datetime.now(timezone.utc).isoformat(),
        head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip(),
        git_status=subprocess.check_output(["git", "status", "--short"], cwd=APP, text=True),
        source=source_snapshot(APP), preserved_documents=documents, saved_config_hashes=config,
        saved_safety_categories=safety, brd_sha256=digest(BRD), mission_sha256=digest(MISSION),
        releases=releases, retained_phase6_validation=dict(status="PASS", python=proof["python"]["executed"],
            checks=proof["checks"], receipt_sha256=digest(APP / "docs/evidence/master_phase6_20261024_01.json")),
        operational_databases="NOT_OPENED_OR_READ; CONTENTS_UNATTESTED", provider_requests=0))
    print(json.dumps(dict(status="PASS", source_files=len(source_snapshot(APP)), preserved_documents=len(documents),
                          retained_python_tests=proof["python"]["executed"], scope="NO_NEW_TEST_EXECUTION")))


if __name__ == "__main__":
    main()

"""Validate actual Phase 3 evidence and build/inspect its private-data-free source ZIP."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

APP = Path(__file__).resolve().parents[2]
EVIDENCE = APP/'docs/evidence'
sys.path.insert(0, str(APP))
from verify_offline import validate_evidence, source_snapshot
from release_management import ReleasePackager
from config import BotConfig


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, data):
    with (EVIDENCE/name).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, allow_nan=False)


def main():
    proof = validate_evidence(EVIDENCE/'master_phase3_angel_20261023_03.json')
    if '--prepare-release' in sys.argv:
        print(json.dumps(ReleasePackager(str(APP)).build_bundle(
            EVIDENCE/'phase3_angel_release_20261023_02.zip')))
        return
    baseline = json.loads((EVIDENCE/'phase3_angel_baseline_20261023_01.json').read_text())
    preserved = {name: (APP/name).is_file() and sha(APP/name) == expected
                 for name, expected in baseline['prior_evidence'].items()}
    previous_validation = json.loads((EVIDENCE/'phase3_angel_closeout_validation_20261023_01.json').read_text())
    previous_phase3 = {name: (APP/name).is_file() and sha(APP/name) == expected
                      for name, expected in previous_validation['bound_files'].items()}
    private = {name: (APP.parent/name).is_file() and sha(APP.parent/name) == expected
               for name, expected in baseline['private_files'].items()}
    cfg = BotConfig()
    safety = dict(saved_provider=cfg.active_broker, telegram_dry_run=cfg.telegram_dry_run,
                  enable_background_scheduler=cfg.enable_background_scheduler,
                  env_and_original_database_unchanged=all(private.values()))
    if not (all(preserved.values()) and all(previous_phase3.values()) and all(private.values()) and cfg.telegram_dry_run is True
            and cfg.enable_background_scheduler is False):
        raise ValueError('PRESERVATION_OR_SAFETY_BINDING_FAILED')
    bundle = EVIDENCE/'phase3_angel_release_20261023_02.zip'
    packager = ReleasePackager(str(APP))
    built = packager.build_bundle(bundle) if not bundle.exists() else packager.inspect_bundle(bundle)
    inspected = packager.inspect_bundle(bundle)
    write('phase3_angel_release_build_20261023_02.json', built)
    write('phase3_angel_release_inspect_20261023_02.json', inspected)
    # Check only genuine configured secret values; never serialize them or matches.
    secrets = [str(getattr(cfg, key) or '').encode() for key in
        ('angel_api_key', 'angel_client_code', 'angel_totp_secret', 'dhan_access_token',
         'dhan_client_id', 'upstox_access_token', 'telegram_bot_token', 'gemini_api_key')]
    secrets = [value for value in secrets if len(value) >= 8]
    files = [p for p in EVIDENCE.glob('*phase3_angel*') if p.is_file() and p.suffix in ('.json', '.txt', '.py', '.md')]
    files += list((APP/'docs/reports').glob('*phase3_angel*'))
    hits = [p.name for p in files if any(secret in p.read_bytes() for secret in secrets)]
    with zipfile.ZipFile(bundle) as archive:
        zipped_hits = [name for name in archive.namelist()
                       if any(secret in archive.read(name) for secret in secrets)]
        scope_safe = all(not ('.local/' in name or name.endswith(('.db', '.sqlite', '.sqlite3')) or
                              Path(name).name == '.env') for name in archive.namelist())
    if hits or zipped_hits or not scope_safe:
        raise ValueError('SECRET_OR_PRIVATE_RELEASE_SCOPE_FAILURE')
    lineage = {}
    for probe in EVIDENCE.glob('phase3_angel_probe_*.json'):
        data = json.loads(probe.read_text())
        if data.get('scope') != 'READ_ONLY_ANGEL_FEED_SMOKE':
            continue
        stage = probe.stem.removeprefix('phase3_angel_probe_')
        if not re.fullmatch('[a-z0-9_]{1,48}', stage):
            continue
        db = APP/'.local/phase3-angel'/stage/'live.sqlite3'
        if not db.is_file():
            continue
        connection = sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts = {name: connection.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in
                      ('angel_feed_events', 'angel_feed_rejections', 'angel_feed_candles', 'angel_feed_forming',
                       'signals', 'scan_runs') if name in tables}
            lineage[stage] = dict(sha256=sha(db), integrity=connection.execute('PRAGMA integrity_check').fetchone()[0],
                                  row_counts=counts)
        finally:
            connection.close()
    report = dict(status='PASS', scope='SOURCE_LOG_RELEASE_AND_PRESERVATION_INTEGRITY_ONLY',
        recorded_at=datetime.now(timezone.utc).isoformat(),
        head=subprocess.check_output(['git','rev-parse','HEAD'], cwd=APP, text=True).strip(),
        tested_source_revision=proof['source_revision'], source_matches_executed_receipt=True,
        python_executed=proof['python']['executed'], python_passed=proof['python']['passed'], checks=proof['checks'],
        prior_evidence_count=len(preserved), prior_evidence_unchanged=all(preserved.values()),
        previous_phase3_evidence_bound_files_unchanged=all(previous_phase3.values()),
        preserved_private_files=private, safety=safety, secret_scan='PASS', release_scope_safe=scope_safe,
        release=built, private_lineage=lineage,
        bound_files={p.relative_to(APP).as_posix(): sha(p) for p in files if p.name != Path(__file__).name},
        source_snapshot=source_snapshot(APP), live_phase3_accepted=False,
        historical_study_accepted=False, phase4_authorized=False)
    write('phase3_angel_closeout_validation_20261023_02.json', report)
    print(json.dumps(dict(status='PASS', python=report['python_passed'], prior_evidence=len(preserved),
                          release_files=built['files'], secret_scan='PASS', private_lineage=lineage)))


if __name__ == '__main__':
    main()

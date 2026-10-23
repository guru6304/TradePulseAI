"""Read-only sanitized baseline; never serializes configuration secrets."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from verify_offline import source_snapshot
from config import BotConfig

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    cfg = BotConfig()
    receipt = APP/'docs/evidence/phase3_angel_baseline_20261023_01.json'
    evidence = APP/'docs/evidence'
    paths = [p for p in evidence.rglob('*') if p.is_file() and not p.name.startswith('phase3_angel_')]
    report = dict(captured_at=datetime.now(timezone.utc).isoformat(),
        head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=APP, text=True).strip(),
        working_tree=subprocess.check_output(['git', 'status', '--short'], cwd=APP, text=True),
        source=source_snapshot(APP), prior_evidence={p.relative_to(APP).as_posix(): sha(p) for p in paths},
        private_files={p.relative_to(APP.parent).as_posix(): sha(p) for p in
                       [APP/'.env', APP.parent/'.env', APP/'tradepulse_phase1d.db'] if p.is_file()},
        configuration=dict(active_broker=cfg.active_broker if cfg.active_broker in
            ('paper_sim','angelone','dhan','upstox') else 'INVALID',
            angel_credentials_configured=cfg.is_broker_credentials_configured('angelone'),
            telegram_dry_run=cfg.telegram_dry_run,
            scheduler_enabled=cfg.enable_background_scheduler,
            angel_master_path_configured=bool(cfg.angel_scrip_master_path)), live_requests=False)
    with receipt.open('x', encoding='utf-8') as out:
        json.dump(report, out, indent=2)
    print(json.dumps(dict(receipt=receipt.name, head=report['head'], configuration=report['configuration'],
                          prior_evidence_count=len(paths), source_files=len(report['source']))))

if __name__ == '__main__':
    main()

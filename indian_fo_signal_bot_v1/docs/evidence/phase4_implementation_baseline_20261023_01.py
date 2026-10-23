"""Exclusive pre-implementation snapshot; no provider or database access."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP))
from verify_offline import source_snapshot,validate_evidence

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

proof=validate_evidence(APP/'docs/evidence/master_phase3_angel_20261023_03.json')
paths=[p for p in (APP/'docs').rglob('*') if p.is_file() and not p.is_symlink()
       and not p.name.startswith('phase4_implementation_') and '__pycache__' not in p.parts]
data=dict(timestamp=datetime.now(timezone.utc).isoformat(),head=subprocess.check_output(
    ['git','rev-parse','HEAD'],cwd=APP,text=True).strip(),worktree=subprocess.check_output(
    ['git','status','--short'],cwd=APP,text=True),source=source_snapshot(APP),
    prior_documents={p.relative_to(APP).as_posix():sha(p) for p in paths},
    configuration_hashes={p.relative_to(APP.parent).as_posix():sha(p) for p in
                          (APP/'.env',APP.parent/'.env') if p.is_file()},
    database_handling='NOT_OPENED_OR_HASHED',provider_requests=0,
    baseline_proof='docs/evidence/master_phase3_angel_20261023_03.json',
    baseline_executed=proof['python']['executed'])
with (APP/'docs/evidence/phase4_implementation_baseline_20261023_01.json').open('x',encoding='utf-8') as out:
    json.dump(data,out,indent=2)
print(json.dumps(dict(status='PASS',baseline_tests=data['baseline_executed'],source_files=len(data['source']),
                      prior_documents=len(data['prior_documents']))))

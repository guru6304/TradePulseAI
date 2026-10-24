"""Read-only starting snapshot for Phase 4 closure and Phase 5 engineering."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP))
from verify_offline import validate_evidence,source_snapshot,timestamp
from release_management import ReleasePackager

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

proof=validate_evidence(APP/'docs/evidence/master_phase4_implementation_20261023_02.json')
archive=APP/'docs/evidence/phase4_implementation_release_20261023_02.zip'
release=ReleasePackager(APP).inspect_bundle(archive)
assert release['sha256']=='4e32d72553ab7b3572ffc115ca845f15e65971181958fc87e6bd02f5c0829aa2'
with zipfile.ZipFile(archive) as z:
    manifest=json.loads(z.read('RELEASE_MANIFEST.json'))
    assert all(z.read(name)==(APP/name).read_bytes() for name in manifest['files'])
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=APP,text=True).strip()
assert head=='f56927389f07b6cca52abebc6e9d22debd0a50d4'
paths=[p for p in (APP/'docs').rglob('*') if p.is_file() and not p.is_symlink()
       and '__pycache__' not in p.parts and not p.name.startswith('phase45_')]
data=dict(status='PASS',recorded_at=timestamp(),head=head,
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=APP,text=True).strip(),
    worktree=subprocess.check_output(['git','status','--short'],cwd=APP,text=True),
    source=source_snapshot(APP),prior_documents={p.relative_to(APP).as_posix():sha(p) for p in paths},
    configuration_hashes={p.relative_to(APP.parent).as_posix():sha(p) for p in (APP/'.env',APP.parent/'.env') if p.is_file()},
    prior_proof=dict(path='docs/evidence/master_phase4_implementation_20261023_02.json',sha256=sha(APP/'docs/evidence/master_phase4_implementation_20261023_02.json'),
        result='VALIDATED_RETAINED_EXECUTION_NOT_NEW_SUITE',python=proof['python']['executed'],checks=proof['checks']),
    prior_release=release,release_matches_current_files=True,
    database_handling='OPERATIONAL_DATABASE_WAL_SHM_NOT_OPENED_OR_HASHED',provider_requests=0,
    command=[sys.executable,'-B','-W','error::ResourceWarning',str(Path(__file__).relative_to(APP))],exit_code=0)
with (APP/'docs/evidence/phase45_baseline_20261023_01.json').open('x',encoding='utf-8') as out:
    json.dump(data,out,indent=2)
print(json.dumps(dict(status='PASS',head=head,source_files=len(data['source']),preserved_documents=len(paths),baseline_tests=proof['python']['executed'])))

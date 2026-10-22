"""Actual interpreter crypto check, using a public test-only seed; no transport."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import cryptography
import tzdata
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from config import BotConfig

key=Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
message=b"OFFLINE_TEST_ONLY"
signature=key.sign(message)
key.public_key().verify(signature,message)
try:
    key.public_key().verify(signature,message+b"CHANGED")
except InvalidSignature:
    tampered_rejected=True
else:
    raise AssertionError("Tampered bytes accepted")
config=BotConfig()
assert config.telegram_dry_run is True and config.enable_background_scheduler is False
report=dict(status="PASS",interpreter=sys.executable,python=sys.version.split()[0],
    cryptography=cryptography.__version__,tzdata=tzdata.__version__,
    real_ed25519_verification="PASS",modified_bytes_rejected=tampered_rejected,signature_size=len(signature),
    active_broker=config.active_broker,telegram_dry_run=config.telegram_dry_run,
    enable_background_scheduler=config.enable_background_scheduler,network_requests=0,
    evidence_scope="OFFLINE_TEST_KEYS_ONLY_NO_PUBLISHER_ACCEPTANCE")
print(json.dumps(report))

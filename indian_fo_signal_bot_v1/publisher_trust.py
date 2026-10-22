"""Publisher trust verification for instrument-master archives.

A valid publisher signature authenticated by a locally-controlled trust anchor
proves that the signed bytes correspond to a specific key.  It does NOT by
itself prove:
  - the publisher is an authoritative/licensed source for the claimed exchange,
  - any publisher-supplied timestamp is objectively accurate, or
  - the artifact is licensed or the effective dates are independently verified.

Capture time, publication time, key validity and artifact effective dates are
distinct concepts and are checked separately.

Trust anchors are loaded exclusively from a local trust configuration
controlled by the operator, NEVER from the artifact under verification.
A signed artifact cannot choose or add its own trusted public key.

If the ``cryptography`` package is unavailable, all verification attempts
return VERIFIER_UNAVAILABLE (fail-closed).  This is documented as an external
dependency blocker; HMAC or custom asymmetric crypto is never substituted.

Dependency required for live verification:
  cryptography >= 42   (Python 3.10-3.14 supported wheel)
  Install: pip install "cryptography>=42"
  Install the repository's requirements.txt into the interpreter running tests.
  Dependency availability is measured in that runtime, never inferred from a
  previous installer timeout. Missing backends remain fail-closed.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Reason codes — kept consistent with existing source_qualification.py codes.
# ---------------------------------------------------------------------------
REASON_UNKNOWN_PUBLISHER           = "UNKNOWN_PUBLISHER"
REASON_MISSING_TRUST_ANCHOR        = "MISSING_TRUST_ANCHOR"
REASON_UNSUPPORTED_SIG_ALGORITHM   = "UNSUPPORTED_SIGNATURE_ALGORITHM"
REASON_INVALID_SIGNATURE           = "INVALID_SIGNATURE"
REASON_DIGEST_MISMATCH             = "ARTIFACT_DIGEST_MISMATCH"
REASON_REVOKED_KEY                 = "REVOKED_KEY"
REASON_TRUST_ANCHOR_NOT_VALID      = "TRUST_ANCHOR_NOT_VALID"
REASON_UNSUPPORTED_ARTIFACT_SCHEMA = "UNSUPPORTED_ARTIFACT_SCHEMA"
REASON_OUTSIDE_EFFECTIVE_DATE      = "OUTSIDE_EFFECTIVE_DATE_RANGE"
REASON_MISSING_RIGHTS              = "MISSING_RIGHTS_EVIDENCE"
REASON_CONFLICTING_ARTIFACT        = "CONFLICTING_ARTIFACT"
REASON_UNTRUSTED_PUBLISHER_SIG     = "UNTRUSTED_PUBLISHER_SIGNATURE"
REASON_VERIFIER_UNAVAILABLE        = "VERIFIER_UNAVAILABLE"
REASON_MISSING_MANIFEST_FIELD      = "MISSING_REQUIRED_MANIFEST_FIELD"
REASON_DUPLICATE_MANIFEST_KEY      = "DUPLICATE_MANIFEST_KEY"
REASON_MALFORMED_MANIFEST          = "MALFORMED_MANIFEST"
REASON_SCOPE_MISMATCH              = "SIGNED_SCOPE_MISMATCH"
REASON_NAIVE_TIMESTAMP             = "NAIVE_OR_AMBIGUOUS_TIMESTAMP"

# Supported manifest schema version(s).
SUPPORTED_MANIFEST_SCHEMAS = {"tradepulse.publisher-manifest.v1"}

# The only supported signature algorithm in this version.
# A separate algorithm label from the hash label is intentional: the two are
# not interchangeable.
SUPPORTED_SIG_ALGORITHM = "Ed25519"
SUPPORTED_DIGEST_ALGORITHM = "sha256"

# Current trust-policy version; bumped on any breaking policy change.
TRUST_POLICY_VERSION = "publisher-trust-policy-v1"

# Fields that must be present in a signed manifest (duplicates are rejected).
REQUIRED_MANIFEST_FIELDS = frozenset({
    "schema_version",
    "publisher_id",
    "key_id",
    "artifact_type",
    "artifact_schema_version",
    "artifact_digest_sha256",
    "provider",
    "exchange",
    "market_segment",
    "instrument_scope",
    "record_coverage",
    "publisher_publication_time",
    "capture_observation_time",
    "effective_from",
    "effective_until",
    "rights_reference",
    "signature_algorithm",
    "signature",
})

# ---------------------------------------------------------------------------
# Cryptographic back-end — conditional import, never substituted.
# ---------------------------------------------------------------------------
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import]
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives.serialization import (  # type: ignore[import]
        Encoding,
        PublicFormat,
        load_der_public_key,
    )
    from cryptography.exceptions import InvalidSignature  # type: ignore[import]
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    Ed25519PublicKey = None  # type: ignore[assignment,misc]
    Encoding = None  # type: ignore[assignment,misc]
    PublicFormat = None  # type: ignore[assignment,misc]
    load_der_public_key = None  # type: ignore[assignment,misc]
    InvalidSignature = Exception  # type: ignore[assignment,misc]


def _crypto_available() -> bool:
    """Return True if the asymmetric-signature back-end is importable."""
    return _CRYPTO_AVAILABLE


# ---------------------------------------------------------------------------
# Internal exception
# ---------------------------------------------------------------------------

class _VerificationError(Exception):
    """Internal early-exit with a structured reason code."""
    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(detail or reason_code)
        self.reason_code = reason_code
        self.detail = detail


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_utc(value: Any, field: str) -> datetime:
    """Parse an ISO-8601 string as a timezone-aware UTC datetime.

    Naive (no tzinfo) datetimes are explicitly rejected: they are ambiguous.
    """
    if not isinstance(value, str):
        raise _VerificationError(
            REASON_NAIVE_TIMESTAMP,
            f"{field}: timestamp must be a string, got {type(value).__name__}.",
        )
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise _VerificationError(
            REASON_NAIVE_TIMESTAMP,
            f"{field}: cannot parse as ISO-8601: {value!r}.",
        )
    if dt.utcoffset() is None:
        raise _VerificationError(
            REASON_NAIVE_TIMESTAMP,
            f"{field}: naive datetime is ambiguous; an explicit UTC offset is required.",
        )
    return dt.astimezone(timezone.utc)


def _strict_json_object(pairs: list) -> dict:
    """Reject duplicate JSON object keys — they are structurally ambiguous."""
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise _VerificationError(
                REASON_DUPLICATE_MANIFEST_KEY,
                f"Duplicate manifest key: {key!r}.",
            )
        result[key] = value
    return result


# Fields excluded from the signed payload (the signature itself and any
# transport/envelope fields that must not influence the signed content).
_EXCLUDED_FROM_SIGNED_PAYLOAD = frozenset({"signature"})


def canonical_signed_payload(manifest: dict) -> bytes:
    """Return the deterministic UTF-8 bytes that the publisher signs.

    Rules:
    - Only REQUIRED_MANIFEST_FIELDS minus {"signature"} are included.
    - Keys are sorted lexicographically (json.dumps sort_keys=True).
    - No trailing whitespace or newlines.
    - UTF-8 encoded, no BOM.

    The same algorithm must be used when verifying and when producing a test
    signature.  Any extension/custom fields are excluded from the signed
    payload; adding them does not invalidate existing signatures.
    """
    signed_fields = REQUIRED_MANIFEST_FIELDS - _EXCLUDED_FROM_SIGNED_PAYLOAD
    payload = {k: manifest[k] for k in signed_fields if k in manifest}
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Trust anchor data structures
# ---------------------------------------------------------------------------

class TrustAnchorConfig:
    """Locally-controlled trust configuration.

    This object is the sole authoritative source of trusted public keys.
    An artifact under verification CANNOT contribute to or modify it.

    Args:
        policy_version:   Must match TRUST_POLICY_VERSION.
        anchors:          List of anchor dicts, each with fields:
            publisher_id       -- canonical provider identifier string
            key_id             -- opaque string, unique within the config
            algorithm          -- must be SUPPORTED_SIG_ALGORITHM ("Ed25519")
            public_key_der_b64 -- base64-encoded DER SubjectPublicKeyInfo bytes
            not_before         -- ISO-8601 UTC datetime string (key activation)
            not_after          -- ISO-8601 UTC datetime string (key expiry)
            revoked            -- bool; True means this key is revoked
        permitted_artifact_types: Optional set of allowed artifact type strings.
        permitted_providers:      Optional set of allowed provider strings.
    """

    def __init__(
        self,
        policy_version: str,
        anchors: list,
        permitted_artifact_types=None,
        permitted_providers=None,
    ) -> None:
        if policy_version != TRUST_POLICY_VERSION:
            raise ValueError(
                f"Unsupported trust policy version: {policy_version!r}. "
                f"Expected {TRUST_POLICY_VERSION!r}."
            )
        self._policy_version = policy_version
        self._anchors: list = []
        seen_key_ids: set = set()
        for anchor in anchors:
            kid = anchor.get("key_id", "")
            if not isinstance(kid, str) or not kid:
                raise ValueError("Each trust anchor must have a non-empty key_id.")
            if kid in seen_key_ids:
                raise ValueError(f"Duplicate key_id in trust configuration: {kid!r}.")
            seen_key_ids.add(kid)
            if anchor.get("algorithm") != SUPPORTED_SIG_ALGORITHM:
                raise ValueError(
                    f"Trust anchor {kid!r} uses unsupported algorithm "
                    f"{anchor.get('algorithm')!r}; only {SUPPORTED_SIG_ALGORITHM} is supported."
                )
            # Validate time fields eagerly so bad configs fail at load time.
            _parse_utc(anchor["not_before"], f"anchor[{kid}].not_before")
            _parse_utc(anchor["not_after"], f"anchor[{kid}].not_after")
            if not isinstance(anchor.get("revoked"), bool):
                raise ValueError(f"Trust anchor {kid!r}: 'revoked' must be a boolean.")
            if not isinstance(anchor.get("publisher_id"), str) or not anchor["publisher_id"]:
                raise ValueError(
                    f"Trust anchor {kid!r}: 'publisher_id' must be a non-empty string."
                )
            # Validate the DER-encoded key can be loaded (only when crypto available).
            if _CRYPTO_AVAILABLE:
                try:
                    der = base64.b64decode(anchor["public_key_der_b64"])
                    key = load_der_public_key(der)  # type: ignore[name-defined]
                    if not isinstance(key, Ed25519PublicKey):  # type: ignore[arg-type]
                        raise ValueError("Expected Ed25519PublicKey.")
                except Exception as exc:
                    raise ValueError(
                        f"Trust anchor {kid!r}: invalid public_key_der_b64: {exc}"
                    ) from exc
            self._anchors.append(dict(anchor))
        self._permitted_artifact_types = (
            set(permitted_artifact_types) if permitted_artifact_types is not None else None
        )
        self._permitted_providers = (
            set(permitted_providers) if permitted_providers is not None else None
        )

    @property
    def policy_version(self) -> str:
        return self._policy_version

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(dict(policy=self._policy_version,anchors=self._anchors,
            artifacts=sorted(self._permitted_artifact_types) if self._permitted_artifact_types is not None else None,
            providers=sorted(self._permitted_providers) if self._permitted_providers is not None else None),
            sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

    def find_anchor(self, publisher_id: str, key_id: str):
        """Return matching anchor dict or None.  Matching is exact on both fields."""
        for anchor in self._anchors:
            if anchor["publisher_id"] == publisher_id and anchor["key_id"] == key_id:
                return dict(anchor)
        return None

    def is_permitted_artifact_type(self, artifact_type: str) -> bool:
        if self._permitted_artifact_types is None:
            return True
        return artifact_type in self._permitted_artifact_types

    def is_permitted_provider(self, provider: str) -> bool:
        if self._permitted_providers is None:
            return True
        return provider in self._permitted_providers


# ---------------------------------------------------------------------------
# Verification result
# ---------------------------------------------------------------------------

class TrustVerificationResult:
    """Structured, sanitised verification outcome.

    Attributes are deliberately read-only after construction to prevent
    callers from mutating the result after the fact.
    """

    __slots__ = (
        "_allowed", "_reason_code", "_detail", "_trust_policy_version",
        "_key_id", "_publisher_id", "_effective_from", "_effective_until",
        "_signed_artifact_digest", "_signature_algorithm",
        "_signed_publisher_time_claim", "_integrity_note",
        "_trust_config_digest",
    )

    _INTEGRITY_NOTE = (
        "A valid signature proves bytes correspond to a key; "
        "it does not prove publisher authority, data licence, "
        "or that publisher-claimed times are objectively correct."
    )

    def __init__(
        self,
        *,
        allowed: bool,
        reason_code: str,
        detail: str = "",
        trust_policy_version: str = TRUST_POLICY_VERSION,
        key_id=None,
        publisher_id=None,
        effective_from=None,
        effective_until=None,
        signed_artifact_digest=None,
        signature_algorithm=None,
        signed_publisher_time_claim=None,
        integrity_note: str = _INTEGRITY_NOTE,
        trust_config_digest=None,
    ) -> None:
        self._allowed = allowed
        self._reason_code = reason_code
        self._detail = detail
        self._trust_policy_version = trust_policy_version
        self._key_id = key_id
        self._publisher_id = publisher_id
        self._effective_from = effective_from
        self._effective_until = effective_until
        self._signed_artifact_digest = signed_artifact_digest
        self._signature_algorithm = signature_algorithm
        self._signed_publisher_time_claim = signed_publisher_time_claim
        self._integrity_note = integrity_note
        self._trust_config_digest=trust_config_digest

    @property
    def allowed(self) -> bool:
        return self._allowed

    @property
    def reason_code(self) -> str:
        return self._reason_code

    @property
    def detail(self) -> str:
        return self._detail

    @property
    def trust_policy_version(self) -> str:
        return self._trust_policy_version

    @property
    def key_id(self):
        return self._key_id

    @property
    def publisher_id(self):
        return self._publisher_id

    @property
    def effective_from(self):
        return self._effective_from

    @property
    def effective_until(self):
        return self._effective_until

    @property
    def signed_artifact_digest(self):
        return self._signed_artifact_digest

    @property
    def signature_algorithm(self):
        return self._signature_algorithm

    @property
    def signed_publisher_time_claim(self):
        return self._signed_publisher_time_claim

    @property
    def integrity_note(self) -> str:
        return self._integrity_note

    def as_dict(self) -> dict:
        """Return a JSON-serialisable representation of this result."""
        return {
            "allowed": self._allowed,
            "reason_code": self._reason_code,
            "detail": self._detail,
            "trust_policy_version": self._trust_policy_version,
            "publisher_id": self._publisher_id,
            "key_id": self._key_id,
            "effective_from": self._effective_from,
            "effective_until": self._effective_until,
            "signed_artifact_digest": self._signed_artifact_digest,
            "signature_algorithm": self._signature_algorithm,
            "signed_publisher_time_claim": self._signed_publisher_time_claim,
            "integrity_note": self._integrity_note,
            "trust_config_digest": self._trust_config_digest,
        }

    @classmethod
    def _fail(cls, reason_code: str, detail: str = "") -> "TrustVerificationResult":
        return cls(allowed=False, reason_code=reason_code, detail=detail)


# ---------------------------------------------------------------------------
# PublisherTrustVerifier
# ---------------------------------------------------------------------------

class PublisherTrustVerifier:
    """Fail-closed publisher trust verifier.

    Verification steps (all must pass for allowed=True):
      1.  Verify the ``cryptography`` back-end is available; if not -> VERIFIER_UNAVAILABLE.
      2.  Parse the manifest JSON; reject duplicate keys and unsupported schemas.
      3.  Verify all required manifest fields are present.
      4.  Look up the publisher/key-id pair in the *local* trust config.
      5.  Check the trust anchor's key validity window at ``verification_time``.
      6.  Confirm the key is not revoked.
      7.  Verify the artifact digest matches ``original_bytes``.
      8.  Verify the cryptographic signature over the canonical payload.
      9.  Check artifact type and provider are in the permitted sets.
     10.  Parse and validate effective_from / effective_until (timezone-aware,
          not naive, consistent order).
     11.  Check rights_reference is non-empty.
     12.  Optionally (when ``required_scope`` is supplied), confirm the manifest
          scope matches the caller's expected provider/exchange/segment/instrument.

    A manifest CANNOT be self-verifying: the trust anchor comes exclusively
    from the ``trust_config`` argument, not from any field in the manifest.
    """

    def __init__(self, trust_config: TrustAnchorConfig) -> None:
        self._config = trust_config

    def verify(
        self,
        manifest_json,
        original_bytes: bytes,
        verification_time=None,
        required_scope=None,
    ) -> TrustVerificationResult:
        """Verify a signed publisher manifest against ``original_bytes``.

        Args:
            manifest_json:      The JSON-encoded manifest string or bytes.
            original_bytes:     The raw artifact bytes the manifest covers.
            verification_time:  Point-in-time for key-validity and effective-date
                                checks.  Defaults to utcnow(). Must be
                                timezone-aware if supplied.
            required_scope:     Optional dict with any of: provider, exchange,
                                market_segment, instrument_scope.  Each
                                present key must match the manifest exactly.

        Returns:
            TrustVerificationResult (allowed=True only on full success).
        """
        try:
            vtime = self._resolve_verification_time(verification_time)
        except _VerificationError as exc:
            return TrustVerificationResult._fail(exc.reason_code, exc.detail)
        try:
            return self._verify_inner(manifest_json, original_bytes, vtime, required_scope)
        except _VerificationError as exc:
            return TrustVerificationResult._fail(exc.reason_code, exc.detail)
        except (ValueError,TypeError,KeyError,ArithmeticError):
            return TrustVerificationResult._fail(REASON_MALFORMED_MANIFEST, "Malformed verification input.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_verification_time(t) -> datetime:
        if t is None:
            return datetime.now(timezone.utc)
        if t.utcoffset() is None:
            raise _VerificationError(
                REASON_NAIVE_TIMESTAMP,
                "verification_time must be timezone-aware; naive datetimes are ambiguous.",
            )
        return t.astimezone(timezone.utc)

    def _verify_inner(
        self, manifest_json, original_bytes: bytes, vtime: datetime, required_scope
    ) -> TrustVerificationResult:

        # Step 1: back-end availability
        if not _CRYPTO_AVAILABLE:
            return TrustVerificationResult._fail(
                REASON_VERIFIER_UNAVAILABLE,
                (
                    "The 'cryptography' package is required for Ed25519 signature "
                    "verification but is not installed.  "
                    "Install with: pip install 'cryptography>=42'.  "
                    "All verification code is implemented and will activate "
                    "when the dependency is available.  "
                    "This is not a substitution with HMAC or custom crypto."
                ),
            )

        # Step 2: parse manifest
        if isinstance(manifest_json, (bytes, bytearray)):
            try:
                manifest_json = manifest_json.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise _VerificationError(
                    REASON_MALFORMED_MANIFEST, f"Manifest is not valid UTF-8: {exc}"
                ) from exc
        try:
            manifest = json.loads(manifest_json, object_pairs_hook=_strict_json_object)
        except _VerificationError:
            raise
        except (ValueError, RecursionError) as exc:
            raise _VerificationError(
                REASON_MALFORMED_MANIFEST, f"Manifest JSON parse error: {exc}"
            ) from exc
        if not isinstance(manifest, dict):
            raise _VerificationError(
                REASON_MALFORMED_MANIFEST, "Manifest must be a JSON object."
            )

        # Step 3: schema + required fields
        schema = manifest.get("schema_version")
        if schema not in SUPPORTED_MANIFEST_SCHEMAS:
            raise _VerificationError(
                REASON_UNSUPPORTED_ARTIFACT_SCHEMA,
                f"Unsupported manifest schema {schema!r}; "
                f"supported: {sorted(SUPPORTED_MANIFEST_SCHEMAS)}.",
            )
        missing = sorted(REQUIRED_MANIFEST_FIELDS - set(manifest))
        if missing:
            raise _VerificationError(
                REASON_MISSING_MANIFEST_FIELD,
                f"Required manifest fields missing: {missing}.",
            )
        sig_algorithm = manifest["signature_algorithm"]
        if sig_algorithm != SUPPORTED_SIG_ALGORITHM:
            raise _VerificationError(
                REASON_UNSUPPORTED_SIG_ALGORITHM,
                f"Unsupported signature algorithm {sig_algorithm!r}; "
                f"only {SUPPORTED_SIG_ALGORITHM} is supported.",
            )

        publisher_id = manifest["publisher_id"]
        key_id = manifest["key_id"]
        if not isinstance(publisher_id, str) or not publisher_id:
            raise _VerificationError(
                REASON_UNKNOWN_PUBLISHER, "publisher_id must be a non-empty string."
            )
        if not isinstance(key_id, str) or not key_id:
            raise _VerificationError(
                REASON_MISSING_TRUST_ANCHOR, "key_id must be a non-empty string."
            )

        # Step 4: look up trust anchor (from local config only)
        anchor = self._config.find_anchor(publisher_id, key_id)
        if anchor is None:
            raise _VerificationError(
                REASON_MISSING_TRUST_ANCHOR,
                f"No trusted anchor found for publisher_id={publisher_id!r}, "
                f"key_id={key_id!r}.",
            )

        # Step 5: key validity window
        not_before = _parse_utc(anchor["not_before"], f"anchor[{key_id}].not_before")
        not_after  = _parse_utc(anchor["not_after"],  f"anchor[{key_id}].not_after")
        if vtime < not_before:
            raise _VerificationError(
                REASON_TRUST_ANCHOR_NOT_VALID,
                f"Key {key_id!r} is not yet valid at verification time "
                f"{vtime.isoformat()}; not_before={not_before.isoformat()}.",
            )
        if vtime > not_after:
            raise _VerificationError(
                REASON_TRUST_ANCHOR_NOT_VALID,
                f"Key {key_id!r} expired at {not_after.isoformat()}; "
                f"verification time {vtime.isoformat()}.",
            )

        # Step 6: revocation
        if anchor["revoked"]:
            raise _VerificationError(
                REASON_REVOKED_KEY,
                f"Key {key_id!r} for publisher {publisher_id!r} has been revoked.",
            )

        # Step 7: artifact digest
        if not isinstance(original_bytes, (bytes, bytearray)):
            raise _VerificationError(REASON_DIGEST_MISMATCH, "original_bytes must be bytes.")
        actual_digest = hashlib.sha256(original_bytes).hexdigest()
        declared_digest = manifest.get("artifact_digest_sha256", "")
        if not isinstance(declared_digest, str) or declared_digest != actual_digest:
            raise _VerificationError(
                REASON_DIGEST_MISMATCH,
                "artifact_digest_sha256 in manifest does not match SHA-256 of "
                "original_bytes.",
            )

        # Step 8: cryptographic signature
        raw_sig_b64 = manifest.get("signature", "")
        if not isinstance(raw_sig_b64, str) or not raw_sig_b64:
            raise _VerificationError(
                REASON_INVALID_SIGNATURE,
                "Manifest 'signature' field is missing or empty.",
            )
        try:
            sig_bytes = base64.b64decode(raw_sig_b64)
        except Exception as exc:
            raise _VerificationError(
                REASON_INVALID_SIGNATURE, f"Signature is not valid base64: {exc}"
            ) from exc

        try:
            der = base64.b64decode(anchor["public_key_der_b64"])
            pub_key = load_der_public_key(der)  # type: ignore[name-defined]
            if not isinstance(pub_key, Ed25519PublicKey):  # type: ignore[arg-type]
                raise _VerificationError(
                    REASON_UNSUPPORTED_SIG_ALGORITHM,
                    "Trust anchor key is not an Ed25519 public key.",
                )
        except _VerificationError:
            raise
        except Exception as exc:
            raise _VerificationError(
                REASON_MISSING_TRUST_ANCHOR,
                f"Failed to load public key from trust anchor: {exc}",
            ) from exc

        signed_payload = canonical_signed_payload(manifest)
        try:
            pub_key.verify(sig_bytes, signed_payload)
        except InvalidSignature:  # type: ignore[misc]
            raise _VerificationError(
                REASON_INVALID_SIGNATURE,
                "Cryptographic signature verification failed: the manifest bytes do "
                "not match the signature under the trusted public key.",
            )

        # Step 9: permitted artifact type and provider
        artifact_type = manifest.get("artifact_type", "")
        provider      = manifest.get("provider", "")
        if not self._config.is_permitted_artifact_type(artifact_type):
            raise _VerificationError(
                REASON_UNSUPPORTED_ARTIFACT_SCHEMA,
                f"Artifact type {artifact_type!r} is not in the permitted set for "
                "this trust config.",
            )
        if not self._config.is_permitted_provider(provider):
            raise _VerificationError(
                REASON_UNKNOWN_PUBLISHER,
                f"Provider {provider!r} is not in the permitted set for this trust config.",
            )

        # Step 10: effective dates (must be timezone-aware, in order)
        eff_from  = _parse_utc(manifest["effective_from"],  "effective_from")
        eff_until = _parse_utc(manifest["effective_until"], "effective_until")
        if eff_from >= eff_until:
            raise _VerificationError(
                REASON_OUTSIDE_EFFECTIVE_DATE,
                f"effective_from ({eff_from.isoformat()}) must be strictly before "
                f"effective_until ({eff_until.isoformat()}).",
            )
        published = _parse_utc(manifest["publisher_publication_time"],"publisher_publication_time")
        captured = _parse_utc(manifest["capture_observation_time"],"capture_observation_time")
        if published>captured or captured>vtime:
            raise _VerificationError(REASON_OUTSIDE_EFFECTIVE_DATE,"Publication/capture time is future or reversed.")

        # Step 11: rights reference
        rights = manifest.get("rights_reference", "")
        if not isinstance(rights, str) or not rights.strip():
            raise _VerificationError(
                REASON_MISSING_RIGHTS,
                "rights_reference must be a non-empty string documenting the "
                "licence or entitlement.",
            )

        # Step 12: optional scope match
        if required_scope:
            for field in ("provider", "exchange", "market_segment", "instrument_scope"):
                if field not in required_scope:
                    continue
                expected = required_scope[field]
                actual   = manifest.get(field)
                if actual != expected:
                    raise _VerificationError(
                        REASON_SCOPE_MISMATCH,
                        f"Scope field {field!r}: expected {expected!r}, manifest "
                        f"contains {actual!r}.",
                    )

        # All checks passed
        return TrustVerificationResult(
            allowed=True,
            reason_code="PUBLISHER_TRUST_VERIFIED",
            detail=(
                "Signature verified; effective dates and scope are within the signed "
                "coverage.  Publisher-signed timestamps are signed claims, not "
                "independently timestamp-verified facts."
            ),
            trust_policy_version=self._config.policy_version,
            publisher_id=publisher_id,
            key_id=key_id,
            effective_from=eff_from.isoformat(),
            effective_until=eff_until.isoformat(),
            signed_artifact_digest=actual_digest,
            signature_algorithm=sig_algorithm,
            signed_publisher_time_claim=manifest.get("publisher_publication_time"),
            trust_config_digest=self._config.fingerprint,
        )


# ---------------------------------------------------------------------------
# Utility: generate a test-only signed manifest (never for production use)
# ---------------------------------------------------------------------------

def _generate_test_manifest(
    *,
    artifact_bytes: bytes,
    publisher_id: str,
    key_id: str,
    private_key_der_b64: str,
    effective_from: str,
    effective_until: str,
    provider: str = "test_provider",
    exchange: str = "NSE",
    market_segment: str = "NSE_EQUITY_INTRADAY",
    instrument_scope: str = "ALL",
    record_coverage: str = "TEST_FIXTURE",
    artifact_type: str = "instrument-master",
    artifact_schema_version: str = "tradepulse.instrument-master.v1",
    capture_time: str = "2026-01-01T00:00:00+00:00",
    pub_time: str = "2026-01-01T00:00:00+00:00",
    rights_reference: str = "TEST_ONLY_NO_RIGHTS",
) -> str:
    """Return a JSON-encoded signed manifest for ISOLATED TESTS ONLY.

    This function exists solely to support test cases that need a validly
    signed manifest with a synthetic key.  It MUST NOT be used outside test
    code, and keys generated for tests MUST NOT be installed in the production
    trust store.

    Requires the ``cryptography`` package.  Raises ImportError if absent.
    """
    if not _CRYPTO_AVAILABLE:
        raise ImportError(
            "Cannot generate test manifest: 'cryptography' package is not installed."
        )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import]
        Ed25519PrivateKey,
    )
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    manifest = {
        "schema_version": "tradepulse.publisher-manifest.v1",
        "publisher_id": publisher_id,
        "key_id": key_id,
        "artifact_type": artifact_type,
        "artifact_schema_version": artifact_schema_version,
        "artifact_digest_sha256": digest,
        "provider": provider,
        "exchange": exchange,
        "market_segment": market_segment,
        "instrument_scope": instrument_scope,
        "record_coverage": record_coverage,
        "publisher_publication_time": pub_time,
        "capture_observation_time": capture_time,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "rights_reference": rights_reference,
        "signature_algorithm": SUPPORTED_SIG_ALGORITHM,
        "signature": "",  # placeholder, replaced below
    }
    payload = canonical_signed_payload(manifest)
    priv_raw = base64.b64decode(private_key_der_b64)
    priv_key = Ed25519PrivateKey.from_private_bytes(priv_raw)
    sig = priv_key.sign(payload)
    manifest["signature"] = base64.b64encode(sig).decode("ascii")
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"))


def _generate_test_keypair():
    """Return (private_key_b64, public_key_der_b64) for ISOLATED TESTS ONLY.

    The private key is returned as the raw 32-byte seed encoded as base64.
    The public key is returned as DER SubjectPublicKeyInfo encoded as base64.
    These keys are synthetic and must never be installed in a production trust store.

    Requires the ``cryptography`` package.  Raises ImportError if absent.
    """
    if not _CRYPTO_AVAILABLE:
        raise ImportError(
            "Cannot generate test keypair: 'cryptography' package is not installed."
        )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import]
        Ed25519PrivateKey,
    )
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        Encoding.Raw, PublicFormat.Raw, None  # type: ignore[name-defined]
    )
    priv_b64 = base64.b64encode(priv_raw).decode("ascii")
    pub_der  = priv.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo  # type: ignore[name-defined]
    )
    pub_b64  = base64.b64encode(pub_der).decode("ascii")
    return priv_b64, pub_b64

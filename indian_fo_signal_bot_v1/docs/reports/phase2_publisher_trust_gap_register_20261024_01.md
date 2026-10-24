# TRADEPULSE AI — PHASE 2 PUBLISHER TRUST, SOURCE AUTHORITY & RIGHTS GAP REGISTER

**Stage:** `p2p3_acceptance_20261024_01`  
**Date:** 2026-10-24  
**Workstream:** Workstream A (Phase 2 Historical Source Authority & Qualification)  
**Modules Audited:** `publisher_trust.py`, `source_qualification.py`, `instrument_archive.py`, `readiness_policy.py`, `historical_data.py`  
**Canonical Tests:** `test_publisher_trust.py` (14-case matrix), `test_market_data_contract.py`  

---

## 1. Executive Summary & Verification Verdict

The offline cryptographic and policy verification mechanisms for Phase 2 historical data are **fully implemented and verified in source code**. All 14 test cases in the cryptographic and trust policy matrix pass under the active Python runtime (`cryptography >= 44.0.2` with native Ed25519 asymmetric signature verification).

However, **authentic empirical historical data acceptance remains strictly BLOCKED (`BLOCKED_BY_EXTERNAL_DEPENDENCY`)** due to the absence of:
1. Production publisher trust anchors (trusted root public keys configured in local operator trust stores).
2. Publisher-detached Ed25519 signatures and manifests for authentic cash equity and F&O datasets.
3. Signed legal research/distribution rights agreements from exchange-authorized market data vendors.
4. Continuous, unbroken multi-month historical OHLCV archives for declared study intervals.

In strict compliance with TradePulse AI safety and integrity directives, synthetic fixtures and mock records are never promoted to authorize empirical performance claims. The historical replay execution gate remains **fail-closed**.

---

## 2. Cryptographic & Source Authority Architecture

### 2.1 The Trust Path
The end-to-end qualification and execution gate follows a strict unidirectional verification pipeline:
```
[Raw Artifact Bytes] + [Detached Publisher Manifest]
               │
               ▼
   publisher_trust.py (Ed25519 Signature Verification & Digest Match)
               │
               ▼
   source_qualification.py (Scope, Effective Dates, Calendar & Rights Verification)
               │
               ▼
   instrument_archive.py (Immutable Archive Packaging & Metadata Digesting)
               │
               ▼
   readiness_policy.py (Execution Gate Enforcement: Caller claims ignored)
               │
               ▼
   historical_data.py / backtest_engine.py (Replay Execution or Fail-Closed Rejection)
```

### 2.2 Replay Gate Integrity (Caller Claims Rejected)
Replay execution enforces that:
- A caller-supplied `"verified": True` boolean field is strictly ignored.
- A caller-supplied HTTP URL, recomputed JSON hash, or self-asserted signature claim cannot independently authorize historical use.
- The gate inspects the verified artifact provenance directly via `assess_source_evidence()` and `PublisherTrustVerifier.verify()`.
- If an unverified or synthetic fixture is supplied to `DeterministicBacktestEngine`, the backtest terminates with:
  - `status: "COMPLETED"` (for fixture simulation testing only),
  - `research_eligible: False`,
  - `empirical_performance_claim_allowed: False`,
  - `reason: "RESEARCH_ELIGIBILITY_BLOCKED_UNQUALIFIED_DATASET"`.

---

## 3. Mandatory 14-Case Cryptographic Matrix Verification

The 14 mandatory test cases in `test_publisher_trust.py` verify that cryptographic verification behaves deterministically and fails closed across all edge and corruption scenarios:

| Case # | Scenario Tested | Code Path & Policy | Verification Result |
| :---: | :--- | :--- | :--- |
| **01** | Valid Ed25519 key/signature pair | `PublisherTrustVerifier.verify()` | **PASS (VERIFIED)** |
| **02** | Altered artifact bytes (tamper resistance) | Digest mismatch detection | **PASS (`ARTIFACT_DIGEST_MISMATCH`)** |
| **03** | Wrong public key / signature mismatch | Ed25519 cryptographic check | **PASS (`INVALID_SIGNATURE`)** |
| **04** | Missing trust anchor (unknown publisher) | Trust store lookup | **PASS (`MISSING_TRUST_ANCHOR`)** |
| **05** | Unknown/untrusted publisher ID | Publisher registry validation | **PASS (`UNKNOWN_PUBLISHER`)** |
| **06** | Unsupported signature algorithm | Algorithm validation (`!= Ed25519`) | **PASS (`UNSUPPORTED_SIGNATURE_ALGORITHM`)** |
| **07** | Revoked publisher key | Revocation timestamp check | **PASS (`REVOKED_KEY`)** |
| **08** | Trust anchor expired / not yet valid | Validity interval bounds | **PASS (`TRUST_ANCHOR_NOT_VALID`)** |
| **09** | Unsupported artifact schema version | Manifest schema parser | **PASS (`UNSUPPORTED_ARTIFACT_SCHEMA`)** |
| **10** | Replay date outside effective dates | Effective date interval check | **PASS (`OUTSIDE_EFFECTIVE_DATE_RANGE`)** |
| **11** | Missing distribution/research rights | Rights reference presence | **PASS (`MISSING_RIGHTS_EVIDENCE`)** |
| **12** | Unavailable cryptography backend | Fail-closed import guard | **PASS (`VERIFIER_UNAVAILABLE`)** |
| **13** | Timezone-naive or ambiguous timestamp | ISO 8601 UTC parser | **PASS (`NAIVE_OR_AMBIGUOUS_TIMESTAMP`)** |
| **14** | Duplicate keys / malformed manifest JSON | Strict non-duplicate JSON parser | **PASS (`DUPLICATE_MANIFEST_KEY` / `MALFORMED_MANIFEST`)** |

---

## 4. Audit of Documented Workspace Artifacts

A forensic scan of the local repository workspace was conducted to identify existing historical datasets:
- `.local/` directory: Contains development diagnostic and probe captures (`master.original.json` from Angel One TLS captures).
- Scrip Masters: The captured instrument masters (`OpenAPIScripMaster.json`) contain instrument mappings and exchange metadata. However, as established in the research protocol: **an instrument master is NOT a historical price dataset**.
- Authentic historical 5-minute OHLCV cash equity observations: **NONE PRESENT in repository**.
- Authentic historical option premium ticks/bars: **NONE PRESENT in repository**.
- Signed publisher manifests (`tradepulse.publisher-manifest.v1`): **NONE PRESENT**.

---

## 5. Formal Gap Register & Resolution Roadmap

| Gap ID | Description | Impact | Classification | Actionable Prerequisite for Operator |
| :--- | :--- | :--- | :--- | :--- |
| **GAP-P2-01** | Production Publisher Trust Root Public Key | Cannot verify production publisher manifests | `BLOCKED_BY_EXTERNAL_DEPENDENCY` | Operator must obtain and configure authorized publisher Ed25519 public key in local trust store. |
| **GAP-P2-02** | Publisher Detached Manifests & Signatures | Cannot establish cryptographic integrity of historical bars | `BLOCKED_BY_EXTERNAL_DEPENDENCY` | Vendor must supply RFC 8032 Ed25519 signatures matching artifact SHA-256 digests. |
| **GAP-P2-03** | Multi-Month Continuous Cash OHLCV Archive | Cannot run statistically valid empirical walk-forward cash study | `BLOCKED_BY_EXTERNAL_DEPENDENCY` | Acquire authorized 1–3 year 1-minute / 5-minute NSE cash equity historical data. |
| **GAP-P2-04** | Formal Research & Distribution Rights Contract | Use of data for automated commercial research unapproved | `BLOCKED_BY_EXTERNAL_DEPENDENCY` | Execute data distribution and non-display research agreement with NSE Data & Analytics / licensed vendor. |

---

## 6. Workstream A Conclusion

The software engineering for Phase 2 publisher trust and source qualification is **complete, verified, and locked**. No additional code refactoring is required. The empirical acceptance gate correctly remains fail-closed until authentic, signed, and licensed market archives are delivered by the operator.

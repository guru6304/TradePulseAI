"""Offline historical-study evidence, operator rights policy and frozen evaluation.

No roots, rights approvals, downloads or profitable strategies are supplied here.
Operator approval records are assertions retained with the actual rights document;
they do not cryptographically prove a licence or independently authenticate a source.
Publisher identity still requires the existing genuine Ed25519 verifier.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path

from instrument_identity import digest
from publisher_trust import PublisherTrustVerifier
from strategies import IST

VERSION = "historical-study-v1"
MAX_BYTES = 64 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def aware(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("An aware evidence timestamp is required.")
    return stamp.astimezone(IST)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate evidence field.")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite evidence value.")))


def evidence_identity(artifacts, metadata):
    record = dict(schema_version=VERSION, artifacts={k: sha(v) for k, v in artifacts.items()},
        metadata=deepcopy(metadata))
    return "history_" + digest(record), record


class HistoricalEvidenceArchive:
    """Immutable content-addressed original bytes in the existing SQLite store.

    The byte digest proves local integrity only. Loading never restores old trust or
    rights authority. Use qualify_artifact again with current operator policy.
    """
    def __init__(self, store):
        self.store = store
        with store._db_lock:
            conn = store._get_connection()
            try:
                with conn:
                    conn.execute("CREATE TABLE IF NOT EXISTS historical_evidence_bytes "
                        "(sha256 TEXT PRIMARY KEY, original_bytes BLOB NOT NULL)")
                    conn.execute("CREATE TABLE IF NOT EXISTS historical_evidence_records "
                        "(evidence_id TEXT PRIMARY KEY, record_json TEXT NOT NULL)")
            finally:
                store._close_if_file(conn)

    def retain(self, artifacts, metadata):
        if (not isinstance(artifacts, dict) or not artifacts or
                any(not isinstance(k, str) or not k or not isinstance(v, bytes)
                    or not v or len(v) > MAX_BYTES for k, v in artifacts.items())):
            raise ValueError("Named bounded original evidence bytes are required.")
        evidence_id, record = evidence_identity(artifacts, metadata)
        raw_record = encode(record).decode()
        with self.store._db_lock:
            conn = self.store._get_connection()
            try:
                with conn:
                    for raw in artifacts.values():
                        old = conn.execute("SELECT original_bytes FROM historical_evidence_bytes WHERE sha256=?",
                            (sha(raw),)).fetchone()
                        if old is not None and bytes(old[0]) != raw:
                            raise ValueError("Stored historical evidence integrity failure.")
                        conn.execute("INSERT OR IGNORE INTO historical_evidence_bytes VALUES (?,?)", (sha(raw), raw))
                    old = conn.execute("SELECT record_json FROM historical_evidence_records WHERE evidence_id=?",
                        (evidence_id,)).fetchone()
                    if old is not None and old[0] != raw_record:
                        raise ValueError("Stored historical evidence record integrity failure.")
                    conn.execute("INSERT OR IGNORE INTO historical_evidence_records VALUES (?,?)",
                        (evidence_id, raw_record))
            finally:
                self.store._close_if_file(conn)
        return evidence_id

    def load(self, evidence_id):
        with self.store._db_lock:
            conn = self.store._get_connection()
            try:
                row = conn.execute("SELECT record_json FROM historical_evidence_records WHERE evidence_id=?",
                    (evidence_id,)).fetchone()
                if row is None:
                    raise ValueError("Historical evidence does not exist.")
                record = strict_json(row[0])
                if "history_" + digest(record) != evidence_id:
                    raise ValueError("Stored historical evidence record changed.")
                artifacts = {}
                for name, checksum in record["artifacts"].items():
                    data = conn.execute("SELECT original_bytes FROM historical_evidence_bytes WHERE sha256=?",
                        (checksum,)).fetchone()
                    if data is None or sha(bytes(data[0])) != checksum:
                        raise ValueError("Stored historical original bytes missing or changed.")
                    artifacts[name] = bytes(data[0])
                return dict(evidence_id=evidence_id, record=record, artifacts=artifacts)
            finally:
                self.store._close_if_file(conn)


def option_request_artifacts(request):
    """Retain the exact embedded source/manifest text, plus the replay envelope."""
    artifacts = {"request": encode(request)}
    for key in ("master_json", "dataset_json", "master_manifest", "dataset_manifest"):
        if key in request:
            if not isinstance(request[key], str):
                raise ValueError("Option source and manifest fields must be original text.")
            artifacts[key] = request[key].encode()
    return artifacts


class OperatorRightsPolicy:
    """Explicit locally controlled approvals; never construct this from a request.

    Each grant binds a retained document, publisher/provider, exact dataset hashes,
    symbols, permitted uses and temporal scope. Revocation is checked every time.
    The operator must independently review authenticity and contractual permission.
    """
    def __init__(self, grants=(), documents=None):
        self.grants = deepcopy(list(grants))
        self.documents = dict(documents or {})

    @property
    def fingerprint(self):
        return digest(dict(grants=self.grants,
            documents={key: sha(value) for key, value in self.documents.items()}))

    def assess(self, manifest, checksum, symbol, first, last, now):
        reference = manifest.get("rights_reference")
        matches = [g for g in self.grants if g.get("rights_reference") == reference]
        reason = "RIGHTS_APPROVAL_NOT_SUPPLIED"
        if len(matches) == 1:
            grant = matches[0]
            raw = self.documents.get(grant.get("document_sha256"))
            try:
                allowed = (grant.get("revoked") is False and isinstance(raw, bytes) and bool(raw)
                    and sha(raw) == grant.get("document_sha256")
                    and grant.get("publisher_id") == manifest["publisher_id"]
                    and grant.get("provider") == manifest["provider"]
                    and checksum in grant["artifact_sha256s"] and symbol in grant["symbols"]
                    and "HISTORICAL_RESEARCH" in grant["allowed_uses"]
                    and aware(grant["effective_from"]) <= first <= last <= aware(grant["effective_until"])
                    and aware(grant["approved_at"]) <= now <= aware(grant["review_due_at"])
                    and bool(grant.get("approved_by", "").strip())
                    and bool(grant.get("approval_reference", "").strip()))
            except (ValueError, KeyError, TypeError, AttributeError):
                allowed = False
            if allowed:
                return dict(allowed=True, reason_code="OPERATOR_DOCUMENTED_RIGHTS_SCOPE_MATCH",
                    rights_reference=reference, document_sha256=grant["document_sha256"],
                    approval_reference=grant["approval_reference"], policy_digest=self.fingerprint,
                    authority="OPERATOR_REVIEWED_DOCUMENT_NOT_INDEPENDENT_LEGAL_VERIFICATION")
            reason = "RIGHTS_REVOKED_EXPIRED_OR_SCOPE_DOCUMENT_MISMATCH"
        return dict(allowed=False, reason_code=reason, policy_digest=self.fingerprint)


def qualify_artifact(raw, manifest_json, *, trust_config, rights_policy, provider,
                     exchange, segment, symbol, artifact_type, schema_version,
                     coverage_start, coverage_end, verification_time):
    """Combine real publisher verification and separate current rights evidence."""
    result = dict(allowed=False, status="BLOCKED", artifact_sha256=sha(raw),
        required_use="HISTORICAL_RESEARCH", missing_evidence=[])
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise ValueError("Bounded original artifact bytes required.")
    first, last, now = map(aware, (coverage_start, coverage_end, verification_time))
    if first > last or last > now:
        raise ValueError("Invalid or future historical coverage.")
    if trust_config is None:
        result["missing_evidence"].append("APPROVED_PUBLISHER_TRUST_ROOTS_NOT_SUPPLIED")
        return result
    trust = PublisherTrustVerifier(trust_config).verify(manifest_json, raw,
        verification_time=now, required_scope=dict(provider=provider, exchange=exchange,
            market_segment=segment, instrument_scope=symbol))
    result["publisher_verification"] = trust.as_dict()
    if not trust.allowed:
        result["missing_evidence"].append("PUBLISHER_AUTHENTICATION_" + trust.reason_code)
        return result
    manifest = strict_json(manifest_json)
    if (manifest["artifact_type"] != artifact_type or manifest["artifact_schema_version"] != schema_version
            or not aware(trust.effective_from) <= first <= last <= aware(trust.effective_until)):
        result["missing_evidence"].append("SIGNED_SCHEMA_OR_COVERAGE_MISMATCH")
        return result
    payload = strict_json(raw)
    if not isinstance(payload, dict) or payload.get("schema_version") != schema_version:
        result["missing_evidence"].append("SOURCE_PAYLOAD_SCHEMA_MISMATCH")
        return result
    if (isinstance(payload, dict) and (payload.get("evidence_class") == "SYNTHETIC_FIXTURE"
            or payload.get("is_simulated") is True or payload.get("data_mode") == "SIMULATED")):
        result["missing_evidence"].append("SYNTHETIC_FIXTURE_IS_NOT_AUTHENTIC_DATA")
        return result
    if rights_policy is None:
        result["missing_evidence"].append("RIGHTS_DOCUMENT_AND_OPERATOR_APPROVAL_NOT_SUPPLIED")
        return result
    rights = rights_policy.assess(manifest, sha(raw), symbol, first, last, now)
    result["rights"] = rights
    if not rights["allowed"]:
        result["missing_evidence"].append(rights["reason_code"])
        return result
    result.update(allowed=True, status="QUALIFIED_FOR_BOUNDED_HISTORICAL_RESEARCH",
        source_timestamps=dict(publication=manifest["publisher_publication_time"],
            acquisition=manifest["capture_observation_time"]),
        scope=dict(provider=provider, exchange=exchange, segment=segment, symbol=symbol,
            schema_version=schema_version, coverage_start=coverage_start, coverage_end=coverage_end))
    return result


def walk_forward_plan(session_dates, *, training_sessions, test_sessions, step_sessions=None):
    """Expanding training prefixes with disjoint future tests; no tuning callback."""
    sessions = list(session_dates)
    if not sessions or sessions != sorted(set(sessions)):
        raise ValueError("Distinct chronologically ordered sessions required.")
    for item in sessions:
        if date.fromisoformat(item).isoformat() != item:
            raise ValueError("Canonical session date required.")
    step = test_sessions if step_sessions is None else step_sessions
    if any(type(n) is not int or n < 1 for n in (training_sessions, test_sessions, step)) or step < test_sessions:
        raise ValueError("Positive fold sizes and nonoverlapping test windows required.")
    folds = []
    for index in range(training_sessions, len(sessions) - test_sessions + 1, step):
        folds.append(dict(train_sessions=sessions[:index], test_sessions=sessions[index:index + test_sessions]))
    if not folds:
        raise ValueError("Insufficient sessions for a complete chronological fold.")
    return dict(schema_version=VERSION, selection_policy="FROZEN_PARAMETERS_NO_TEST_PERIOD_TUNING",
        folds=folds, sessions_not_scored_out_of_sample=[s for s in sessions if not any(s in f["test_sessions"] for f in folds)],
        train_test_overlap=False)


def source_fingerprint():
    base = Path(__file__).resolve().parent
    sources = [p for p in base.glob("*.py") if not p.name.startswith("test_")]
    sources.append(base / "requirements.txt")
    return {path.name: sha(path.read_bytes()) for path in sorted(sources)}


def run_frozen_study(engine, *, strategy_id, symbol, provider, backtest_config, plan,
                     candles=None, option_request=None, data_mode="SIMULATED", cash_source=None,
                     rights_policy=None, instrument_token=None):
    """Run the existing engine with one frozen config and disjoint future windows.

    LIVE cash source is exact JSON ``tradepulse.cash-observations.v1`` containing
    ``candles``, plus detached ``manifest_json``. LIVE option requests require both
    publisher manifests and rights approvals. Archive original inputs and plan
    before evaluation. No optimizer or market access exists in this runner.
    """
    if engine.store is None:
        raise ValueError("Durable study evidence store required.")
    if data_mode not in ("SIMULATED", "LIVE"):
        raise ValueError("Explicit study mode required.")
    frozen_plan = deepcopy(plan)
    folds = frozen_plan.get("folds", [])
    tested = set()
    if frozen_plan.get("schema_version") != VERSION or not folds:
        raise ValueError("Frozen chronological study plan required.")
    for fold in folds:
        train, test = fold["train_sessions"], fold["test_sessions"]
        if (not train or not test or train != sorted(set(train)) or test != sorted(set(test))
                or max(train) >= min(test) or tested.intersection(test)):
            raise ValueError("Overlapping or nonchronological study plan.")
        tested.update(test)
    if option_request is not None:
        artifacts = option_request_artifacts(option_request)
        observations = strict_json(option_request["dataset_json"])
        bars = observations["underlying_candles"]
        segment, exchange = "NSE_FO_INDEX", "NFO"
    else:
        if not isinstance(instrument_token, str) or not instrument_token:
            raise ValueError("Explicit canonical cash instrument identifier required.")
        bars = deepcopy(candles)
        segment, exchange = "NSE_EQUITY_INTRADAY", "NSE"
        artifacts = {"cash_dataset": encode(dict(schema_version="tradepulse.cash-observations.v1", candles=bars))}
        if cash_source is not None:
            artifacts.update(cash_dataset=cash_source["original_bytes"],
                cash_manifest=cash_source["manifest_json"].encode())
            supplied = strict_json(cash_source["original_bytes"])
            if supplied != dict(schema_version="tradepulse.cash-observations.v1", candles=bars):
                raise ValueError("Cash replay candles differ from original source bytes.")
        archive_id = backtest_config.historical_instrument_archive_id
        if archive_id is not None:
            master = engine.store.get_instrument_master_archive(archive_id, include_original=True)
            artifacts["cash_master"] = master["original_bytes"]
            master_manifest = (engine.publisher_manifests or {}).get(archive_id)
            if master_manifest is not None:
                artifacts["cash_master_manifest"] = master_manifest.encode()
    available_sessions = sorted({aware(b["timestamp"]).date().isoformat() for b in bars})
    if any(s not in available_sessions for f in folds for s in f["train_sessions"] + f["test_sessions"]):
        raise ValueError("Study plan references missing source sessions.")
    first = min(aware(b["timestamp"]) for b in bars)
    last = max(aware(b["timestamp"]) for b in bars) + timedelta(minutes=5)
    qualifications = []
    blockers = []
    quality_audit = None
    if option_request is None:
        from historical_data import validate_and_prepare_historical_dataset
        quality_audit = validate_and_prepare_historical_dataset(candles=deepcopy(bars), symbol=symbol,
            segment=segment, exchange=exchange, provider=provider, instrument_token=instrument_token,
            data_mode=data_mode, interval_min=5, reference_time_ist=engine.clock(),
            retrieved_at_ist=engine.clock(), configured_holidays=engine.bot_config.configured_holidays,
            allow_identical_duplicates=False, sort_chronologically=False, reject_forming_candles=True,
            session_start_ist=engine.bot_config.session_start_ist,
            session_end_ist=engine.bot_config.session_end_ist)["manifest"]
        # Acquisition time is a local receipt; retain it separately from the
        # reproducible dataset/source/configuration fingerprint.
        quality_audit.pop("retrieved_at_ist", None)
        if quality_audit["quality_status"] != "COMPLETE_VERIFIED":
            blockers.append("CASH_QUALITY_" + quality_audit["quality_status"])
    if data_mode == "LIVE":
        if backtest_config.execution_scope != "HISTORICAL_RESEARCH":
            raise ValueError("Real study requires explicit historical research scope.")
        checks = ([("master_json", "master_manifest", "instrument-master", "tradepulse.instrument-master.v1"),
                   ("dataset_json", "dataset_manifest", "option-observations", "tradepulse.option-observations.v1")]
                  if option_request is not None else
                  [("cash_dataset", "cash_manifest", "cash-observations", "tradepulse.cash-observations.v1"),
                   ("cash_master", "cash_master_manifest", "instrument-master", "tradepulse.instrument-master.v1")])
        for key, manifest_key, kind, schema in checks:
            if key not in artifacts or manifest_key not in artifacts:
                blockers.append("AUTHENTIC_" + kind.upper() + "_AND_DETACHED_MANIFEST_NOT_SUPPLIED")
                continue
            assessed = qualify_artifact(artifacts[key], artifacts[manifest_key].decode(),
                trust_config=engine.publisher_trust_config, rights_policy=rights_policy,
                provider=provider, exchange=exchange, segment=segment, symbol=symbol,
                artifact_type=kind, schema_version=schema, coverage_start=first.isoformat(),
                coverage_end=last.isoformat(), verification_time=engine.clock().isoformat())
            qualifications.append(assessed)
            blockers.extend(assessed["missing_evidence"])
        if rights_policy is not None:
            for checksum, raw in rights_policy.documents.items():
                artifacts["rights_document_" + checksum] = raw
    else:
        blockers.append("SIMULATED_FIXTURES_ARE_NOT_REAL_HISTORICAL_STUDY_EVIDENCE")
    frozen = dict(version=VERSION, strategy_id=strategy_id, symbol=symbol, provider=provider,
        data_mode=data_mode, instrument_token=instrument_token, config=asdict(backtest_config), plan=frozen_plan,
        input_artifact_sha256s={key: sha(raw) for key, raw in artifacts.items()},
        quality_audit=quality_audit,
        source_fingerprint=source_fingerprint(), qualifications=qualifications,
        rights_policy_digest=rights_policy.fingerprint if rights_policy is not None else None)
    from candle_lineage import runtime_profile
    frozen["runtime_profile"] = runtime_profile(engine.bot_config)
    frozen["trust_config_digest"] = (engine.publisher_trust_config.fingerprint
        if engine.publisher_trust_config is not None else None)
    artifacts["frozen_plan"] = encode(frozen)
    archive = HistoricalEvidenceArchive(engine.store)
    evidence_id = archive.retain(artifacts, dict(kind="FROZEN_STUDY_INPUTS", frozen_plan_sha256=sha(artifacts["frozen_plan"])))
    result = dict(study_id="study_" + digest(frozen), input_evidence_id=evidence_id,
        implementation_status="IMPLEMENTED_OFFLINE", real_historical_study_status="BLOCKED",
        missing_evidence=sorted(set(blockers)), configuration_frozen_before_evaluation=True,
        source_fingerprint=frozen["source_fingerprint"], folds=[], empirical_performance_claim_allowed=False)
    result["quality_audit"] = quality_audit
    if data_mode == "LIVE" and blockers:
        return result
    for index, fold in enumerate(folds):
        cfg = deepcopy(backtest_config)
        cfg.period_type = "OUT_OF_SAMPLE"
        cfg.evaluation_start_date = min(fold["test_sessions"])
        cfg.evaluation_end_date = max(fold["test_sessions"])
        # Exclude all future fold source observations from the evaluator input.
        prefix = [b for b in bars if aware(b["timestamp"]).date().isoformat() <= cfg.evaluation_end_date]
        if option_request is not None:
            request = deepcopy(option_request)
            # Exact signed originals stay intact: the existing option engine enforces
            # evaluation windows and point-in-time prefixes without rewriting bytes.
            run = engine.run_backtest(strategy_id, symbol, provider=provider, data_mode=data_mode,
                backtest_config=cfg, option_execution_request=request)
        else:
            run = engine.run_backtest(strategy_id, symbol, candles=prefix, provider=provider,
                data_mode=data_mode, backtest_config=cfg, instrument_token=instrument_token)
        result["folds"].append(dict(fold=index, train_sessions=fold["train_sessions"],
            test_sessions=fold["test_sessions"], run=run))
    if source_fingerprint() != frozen["source_fingerprint"]:
        raise ValueError("Study source changed during evaluation; no result acceptance issued.")
    if (runtime_profile(engine.bot_config) != frozen["runtime_profile"]
            or (engine.publisher_trust_config.fingerprint if engine.publisher_trust_config is not None else None)
                != frozen["trust_config_digest"]
            or (rights_policy.fingerprint if rights_policy is not None else None) != frozen["rights_policy_digest"]):
        raise ValueError("Study runtime, trust or rights policy changed during evaluation.")
    if data_mode == "LIVE" and all(
            (f["run"].get("status") == "COMPLETED" and f["run"].get("research_eligible", False)
             if option_request is not None else
             f["run"].get("execution_scope") == "HISTORICAL_RESEARCH" and
             f["run"].get("dataset_quality_status") == "COMPLETE_VERIFIED") for f in result["folds"]):
        result["real_historical_study_status"] = "QUALIFIED_REPRODUCIBLE_BOUNDED_STUDY"
    result["result_evidence_id"] = archive.retain({"study_result": encode(result)},
        dict(kind="FROZEN_STUDY_RESULT", input_evidence_id=evidence_id))
    return result

"""Local native NSE contract observations and an atomic inspection cache.

No download, activation, effective-date inference or source authentication. Native
schema follows the public Upstox instrument-file documentation; retained bytes and
all terms remain unqualified until independently accepted by an operator policy.
"""
from datetime import datetime
from decimal import Decimal
import json
import re

from instrument_identity import _contract_identifier, positive_integer, reject
from instrument_identity import INDICES
from strategies import IST, parse_ist_timestamp
from candle_lineage import digest


def inspect_upstox_native_contracts(rows):
    if not isinstance(rows, list) or not rows or len(rows) > 250000 or any(not isinstance(r, dict) for r in rows):
        reject("INVALID_NATIVE_MASTER", "A bounded native JSON row list is required.")
    spots = {}
    for row in rows:
        segment, kind = row.get("segment"), row.get("instrument_type")
        if (segment, kind) not in (("NSE_EQ", "EQ"), ("NSE_INDEX", "INDEX")):
            continue
        key = _contract_identifier(row.get("instrument_key"), "upstox", "EQ" if kind=="EQ" else "INDEX_SPOT")
        if row.get("exchange") != "NSE" or key in spots:
            reject("CONFLICTING_UNDERLYING", "Native underlying identity is duplicated or inconsistent.")
        symbol = row.get("trading_symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            reject("MISSING_UNDERLYING_IDENTITY", "An explicit underlying label is required.")
        spots[key] = ("EQUITY" if kind=="EQ" else "INDEX", symbol)
    facts, identifiers, terms, pairs = [], set(), set(), {}
    months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    for row in rows:
        if row.get("segment") != "NSE_FO":
            continue
        side, underlying = row.get("instrument_type"), row.get("underlying_symbol")
        if side not in ("FUT", "CE", "PE") or row.get("exchange") != "NSE":
            reject("UNSUPPORTED_NATIVE_CONTRACT", "Only explicit NSE futures and CE/PE observations are supported.")
        if not isinstance(underlying, str) or not re.fullmatch(r"[A-Z0-9&._-]+", underlying):
            reject("INVALID_UNDERLYING", "A canonical explicit underlying is required.")
        key, underlying_key = row.get("instrument_key"), row.get("underlying_key")
        index = row.get("underlying_type") == "INDEX"
        native_type = "INDEX" if index else "EQUITY"
        if (row.get("underlying_type") != native_type or underlying_key not in spots
                or spots[underlying_key][0] != native_type
                or (not index and spots[underlying_key][1] != underlying)):
            reject("MISSING_UNDERLYING_IDENTITY", "Exact underlying type and key must bind to the same retained file.")
        if index and ((underlying in INDICES and INDICES[underlying]["upstox_key"]!=underlying_key)
                      or underlying not in INDICES and spots[underlying_key][1].upper()!=underlying):
            reject("CONFLICTING_INDEX_UNDERLYING", "Index aliases require an exact supported key or matching explicit label.")
        kind = ("FUT" if side=="FUT" else "OPT") + ("IDX" if index else "STK")
        key = _contract_identifier(key, "upstox", kind)
        if key in identifiers or key.split("|", 1)[1] != str(row.get("exchange_token")):
            reject("DUPLICATE_OR_CONFLICTING_NATIVE_IDENTIFIER", "Native derivative key and token must agree and be unique.")
        identifiers.add(key)
        expiry_ms = row.get("expiry")
        if type(expiry_ms) is not int or not 946684800000 <= expiry_ms <= 4102444800000:
            reject("INVALID_CONTRACT_DATE", "Expiry requires the documented millisecond epoch value.")
        expiry = datetime.fromtimestamp(expiry_ms/1000, IST).date()
        lot = positive_integer(row.get("lot_size"), "lot_size")
        if "minimum_lot" in row and positive_integer(row["minimum_lot"], "minimum_lot") != lot:
            reject("CONFLICTING_QUANTITY_MODEL", "Minimum lot and lot size disagree.")
        strike = row.get("strike_price")
        try:
            if isinstance(strike, bool) or not isinstance(strike, (int, float)):
                raise ValueError()
            strike = Decimal(str(strike))
            if not strike.is_finite() or (strike != 0 if side=="FUT" else strike <= 0):
                raise ValueError()
        except (ValueError, ArithmeticError):
            reject("INVALID_NATIVE_STRIKE", "Futures require zero strike; options require a finite positive strike.")
        label = row.get("trading_symbol")
        date_label = f"{expiry.day:02d} {months[expiry.month-1]} {expiry.year%100:02d}"
        pattern = re.escape(underlying) + (r" FUT " if side=="FUT" else r" ([0-9]+(?:\.[0-9]+)?) "+side+" ") + re.escape(date_label)
        match = re.fullmatch(pattern, label) if isinstance(label, str) else None
        if not match or (side!="FUT" and Decimal(match[1]) != strike):
            reject("NATIVE_LABEL_TERMS_CONFLICT", "Label, strike, side and expiry must agree exactly.")
        term = (kind, underlying_key, expiry.isoformat(), strike if side!="FUT" else None, side)
        if term in terms:
            reject("AMBIGUOUS_CONTRACT", "Multiple keys claim the same native contract.")
        terms.add(term)
        pair = (underlying_key, expiry.isoformat(), strike)
        if side!="FUT" and pair in pairs and pairs[pair] != lot:
            reject("CONFLICTING_OPTION_PAIR", "Observed CE/PE lot sizes disagree.")
        if side!="FUT":
            pairs[pair] = lot
        fact = dict(provider="upstox", symbol=label, identifier=key, exchange="NFO",
            segment="NSE_FO_INDEX" if index else "NSE_FO_STOCK", instrument_type=kind,
            underlying=underlying, underlying_identifier=underlying_key, expiry=expiry.isoformat(),
            expiry_epoch_ms=expiry_ms, lot_size=lot, price_unit="INR", quantity_unit="UNDERLYING_UNITS",
            valid_from=None, valid_to=None, historical_validity="NOT_ESTABLISHED",
            source="UPSTOX_NATIVE_SNAPSHOT_UNQUALIFIED")
        if side!="FUT":
            fact.update(strike=float(strike), option_type=side)
        facts.append(fact)
    if not facts:
        reject("EMPTY_SUPPORTED_NATIVE_SCOPE", "No NSE derivative observations were supplied.")
    return sorted(facts, key=lambda r: (r["underlying"], r["expiry"], r["identifier"]))


def create_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS contract_master_cache (
        provider TEXT PRIMARY KEY, master_id TEXT NOT NULL REFERENCES contract_master_candidates(master_id),
        payload_json TEXT NOT NULL, content_digest TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS contract_master_refreshes (
        attempt_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
        master_id TEXT NOT NULL REFERENCES contract_master_candidates(master_id),
        status TEXT NOT NULL, reason_code TEXT NOT NULL, observed_at TEXT NOT NULL)""")


def _freshness(captured, now):
    if captured is None:
        return "MISSING_CAPTURE_TIME"
    stamp = parse_ist_timestamp(captured)
    if stamp > now:
        return "FUTURE_CAPTURE"
    if stamp.date() != now.date() or (now-stamp).total_seconds() > 86400:
        return "STALE_CAPTURE"
    return None


def refresh_cache(store, raw_bytes, *, provider, source_reference, source_version, captured_at, now=None):
    from instrument_identity import prepare_contract_master
    reference = parse_ist_timestamp(now or datetime.now(IST))
    candidate = prepare_contract_master(raw_bytes, provider=provider, source_reference=source_reference,
        source_version=source_version, captured_at=captured_at)
    records = candidate.get("observed_records", [])
    reason = (candidate["validation"] or {}).get("reason_code") if candidate["status"]=="REJECTED" else None
    reason = reason or _freshness(candidate["metadata"]["captured_at"], reference)
    if not reason and not any(r["expiry"] >= reference.date().isoformat() for r in records):
        reason = "NO_UNEXPIRED_NATIVE_OBSERVATIONS"
    payload = {k: v for k, v in candidate.items() if k!="original_bytes"}
    with store.paper_transaction() as conn:
        conn.execute("INSERT OR IGNORE INTO contract_master_candidates VALUES (?,?,?,?)", (
            candidate["master_id"], provider, raw_bytes, json.dumps(payload, sort_keys=True, allow_nan=False)))
        previous = conn.execute("SELECT payload_json,content_digest FROM contract_master_cache WHERE provider=?", (provider,)).fetchone()
        if previous:
            old = json.loads(previous[0])
            if digest(old) != previous[1]:
                raise ValueError("CONTRACT_CACHE_INTEGRITY_FAILURE")
            if not reason and parse_ist_timestamp(captured_at) < parse_ist_timestamp(old["captured_at"]):
                reason = "OLDER_THAN_LAST_GOOD_CAPTURE"
            if (not reason and parse_ist_timestamp(captured_at) == parse_ist_timestamp(old["captured_at"])
                    and candidate["master_id"] != old["master_id"]):
                reason = "CONFLICTING_SAME_CAPTURE_REFRESH"
        status = "FAIL" if reason else "PASS"
        reason = reason or "LOCAL_INSPECTION_CACHE_UPDATED_UNQUALIFIED"
        attempt = digest([candidate["master_id"], reference.isoformat(), status, reason])
        conn.execute("INSERT OR IGNORE INTO contract_master_refreshes VALUES (?,?,?,?,?,?)", (
            attempt, provider, candidate["master_id"], status, reason, reference.isoformat()))
        if status=="PASS":
            body = dict(provider=provider, master_id=candidate["master_id"], captured_at=candidate["metadata"]["captured_at"],
                        refreshed_at=reference.isoformat(), scope="INSPECTION_ONLY_UNQUALIFIED")
            conn.execute("INSERT OR REPLACE INTO contract_master_cache VALUES (?,?,?,?)", (
                provider, candidate["master_id"], json.dumps(body, sort_keys=True), digest(body)))
        store._contract_cache_checkpoint("before_contract_cache_commit")
    return dict(status=status, master_id=candidate["master_id"], reason_code=reason,
                eligible=False, historical_replay_allowed=False, observed_record_count=len(records))


def cache_status(store, provider, now=None):
    reference = parse_ist_timestamp(now or datetime.now(IST))
    with store.paper_transaction(write=False) as conn:
        row = conn.execute("SELECT * FROM contract_master_cache WHERE provider=?", (provider,)).fetchone()
    base = dict(provider=provider, eligible=False, historical_replay_allowed=False)
    if row is None:
        return dict(base, status="NOT_CONFIGURED")
    body = json.loads(row["payload_json"])
    if digest(body) != row["content_digest"] or body["master_id"] != row["master_id"] or body["provider"] != provider:
        raise ValueError("CONTRACT_CACHE_INTEGRITY_FAILURE")
    candidate = store.get_contract_master_candidate(row["master_id"], include_original=True)
    if candidate["metadata"]["captured_at"] != body["captured_at"]:
        raise ValueError("CONTRACT_CACHE_CAPTURE_CONFLICT")
    reason = _freshness(body["captured_at"], reference)
    return dict(base, **{k:v for k,v in body.items() if k!="provider"},
        status="STALE" if reason else "PASS", reason_code=reason or "UNQUALIFIED_NATIVE_OBSERVATIONS",
        observed_record_count=candidate.get("observed_record_count", 0))


def inspect_cached(store, provider, *, now=None, **request):
    from instrument_identity import resolve_contract_identity
    reference = parse_ist_timestamp(now or datetime.now(IST))
    status = cache_status(store, provider, reference)
    if status["status"]!="PASS":
        return status
    candidate = store.get_contract_master_candidate(status["master_id"], include_original=True)
    return resolve_contract_identity(candidate, provider=provider, as_of=reference, **request)


def main(argv=None):
    import argparse
    import gzip
    from pathlib import Path
    from instrument_identity import MAX_CONTRACT_MASTER_BYTES
    from storage import SQLitePersistenceStore
    parser = argparse.ArgumentParser(description="Import local Upstox native JSON for unqualified offline inspection only.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--source-reference", required=True)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args(argv)
    try:
        opener = gzip.open if args.file.suffix==".gz" else open
        with opener(args.file, "rb") as source:
            raw = source.read(MAX_CONTRACT_MASTER_BYTES+1)
        with SQLitePersistenceStore(args.database) as store:
            result = refresh_cache(store, raw, provider="upstox", source_reference=args.source_reference,
                source_version=args.source_version, captured_at=args.captured_at)
        print(json.dumps(result))
        return 0 if result["status"]=="PASS" else 1
    except Exception as exc:
        print(json.dumps(dict(status="FAIL", eligible=False, reason_code=type(exc).__name__)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

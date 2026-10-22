"""Bounded, chronological SQLite history snapshots; hashes are local integrity."""
import base64
from datetime import timedelta
import hashlib
import json
import re

from strategies import format_ist_timestamp, parse_ist_timestamp

MAX_REPLAY_BARS = 250000


def _scope(symbol, interval_min=5, data_mode="LIVE", provider=None, start_time_ist=None,
           end_time_ist=None, decision_time_ist=None):
    if (not isinstance(symbol, str) or not symbol.strip() or len(symbol)>64
            or type(interval_min) is not int or interval_min<=0 or data_mode not in ("LIVE", "SIMULATED")):
        raise ValueError("INVALID_HISTORY_SCOPE")
    return dict(symbol=symbol.strip().upper(), interval_min=interval_min, data_mode=data_mode,
        provider=str(provider).strip().lower() if provider is not None else None,
        start_time_ist=format_ist_timestamp(start_time_ist) if start_time_ist else None,
        end_time_ist=format_ist_timestamp(end_time_ist) if end_time_ist else None,
        decision_time_ist=format_ist_timestamp(decision_time_ist) if decision_time_ist is not None else None)


def _where(scope):
    clauses, args = ["symbol=?", "interval_min=?", "data_mode=?"], [scope["symbol"], scope["interval_min"], scope["data_mode"]]
    for field, column, operator in (("provider", "provider", "="), ("start_time_ist", "candle_timestamp", ">="),
                                    ("end_time_ist", "candle_timestamp", "<=")):
        if scope[field] is not None:
            clauses.append(column+operator+"?")
            args.append(scope[field])
    if scope["decision_time_ist"] is not None:
        clauses.extend(("candle_timestamp<=?", "is_complete=1"))
        args.append(format_ist_timestamp(parse_ist_timestamp(scope["decision_time_ist"])-timedelta(minutes=scope["interval_min"])))
    return " AND ".join(clauses), args


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _row(record):
    data = dict(record)
    data["timestamp"] = data.pop("candle_timestamp")
    data["transformations"] = json.loads(data.pop("transformations_json") or "[]")
    data["is_complete"], data["is_simulated"] = bool(data["is_complete"]), bool(data["is_simulated"])
    return data


def _scan(conn, where, args, through, *, collect=False, page_size=1000):
    cursor = conn.execute("SELECT * FROM historical_candles WHERE "+where+
                          " AND id<=? ORDER BY candle_timestamp,id", (*args, through))
    count, pages, checksum, items = 0, 0, hashlib.sha256(), []
    while True:
        page = cursor.fetchmany(page_size)
        if not page:
            break
        pages += 1
        for record in page:
            item = _row(record)
            checksum.update(_encoded(item)+b"\n")
            count += 1
            if collect:
                if count>MAX_REPLAY_BARS:
                    raise ValueError("HISTORICAL_REPLAY_RESOURCE_LIMIT")
                items.append(item)
    return count, checksum.hexdigest(), pages, items


def query_page(store, symbol, *, limit=1000, cursor=None, **scope_args):
    if type(limit) is not int or not 1<=limit<=10000:
        raise ValueError("INVALID_HISTORY_PAGE_LIMIT")
    scope = _scope(symbol, **scope_args)
    token = None
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or not cursor or len(cursor)>4096:
                raise ValueError()
            token = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if (token["v"]!=1 or token["scope"]!=scope or type(token["through"]) is not int or token["through"]<0
                    or type(token["count"]) is not int or token["count"]<0
                    or not re.fullmatch(r"[0-9a-f]{64}", token["digest"])
                    or not isinstance(token["after"], list) or len(token["after"])!=2
                    or type(token["after"][1]) is not int or not 0<token["after"][1]<=token["through"]
                    or format_ist_timestamp(token["after"][0])!=token["after"][0]):
                raise ValueError()
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ValueError("INVALID_HISTORY_CURSOR") from None
    where, args = _where(scope)
    with store.paper_transaction(write=False) as conn:
        through = token["through"] if token else conn.execute(
            "SELECT COALESCE(MAX(id),0) FROM historical_candles WHERE "+where, args).fetchone()[0]
        count, checksum, _, _ = _scan(conn, where, args, through)
        if token and (token["count"]!=count or token["digest"]!=checksum):
            raise ValueError("HISTORICAL_SNAPSHOT_CHANGED")
        extra, values = "", []
        if token:
            extra = " AND (candle_timestamp>? OR (candle_timestamp=? AND id>?))"
            values = [token["after"][0], token["after"][0], token["after"][1]]
        rows = conn.execute("SELECT * FROM historical_candles WHERE "+where+" AND id<=?"+extra+
            " ORDER BY candle_timestamp,id LIMIT ?", (*args, through, *values, limit+1)).fetchall()
        items, more = [_row(r) for r in rows[:limit]], len(rows)>limit
    next_cursor = None
    if more:
        next_cursor = base64.urlsafe_b64encode(_encoded(dict(v=1, scope=scope, through=through,
            count=count, digest=checksum, after=[items[-1]["timestamp"], items[-1]["id"]]))).decode("ascii")
    return dict(status="OK", scope=scope, total_count=count, snapshot_digest=checksum,
                through_id=through, limit=limit, next_cursor=next_cursor, items=items)


def read_snapshot(store, symbol, *, page_size=1000, **scope_args):
    if type(page_size) is not int or not 1<=page_size<=10000:
        raise ValueError("INVALID_HISTORY_PAGE_LIMIT")
    scope = _scope(symbol, **scope_args)
    where, args = _where(scope)
    with store.paper_transaction(write=False) as conn:
        through = conn.execute("SELECT COALESCE(MAX(id),0) FROM historical_candles WHERE "+where, args).fetchone()[0]
        count, checksum, pages, items = _scan(conn, where, args, through, collect=True, page_size=page_size)
    return dict(status="OK", scope=scope, total_count=count, snapshot_digest=checksum,
                through_id=through, pages_read=pages, items=items)

"""Explicit local preflight and bounded read-only Dhan streaming probe.

Importing this module opens no socket and changes no selected broker. Secrets are
consumed only by the transport and are never included in a returned report.
"""
import argparse
import importlib.metadata
import json
import time
from datetime import datetime, timezone


def preflight(config):
    result = dict(scope="LOCAL_DHAN_FEED_CONFIGURATION_ONLY", status="BLOCKED",
                  live_requests=False, authentication="NOT_TESTED", live_feed_accepted=False,
                  instrument_count=0, blockers=[])
    try:
        config.validate(require_live_credentials=False)
    except Exception:
        result["blockers"].append("CONFIGURATION_INVALID")
        return result
    if config.telegram_dry_run is not True or config.enable_background_scheduler is not False:
        result["blockers"].append("SAFE_RUNTIME_FLAGS_REQUIRED")
    if not config.is_broker_credentials_configured("dhan"):
        result["blockers"].append("DHAN_SPECIFIC_CREDENTIALS_MISSING_OR_PLACEHOLDER")
    scope = config.dhan_feed_instruments or []
    result["instrument_count"] = len(scope)
    if not scope:
        result["blockers"].append("EXPLICIT_VERIFIED_DHAN_INSTRUMENT_SCOPE_REQUIRED")
    elif len(scope) != 1:
        result["blockers"].append("SMOKE_REQUIRES_EXACTLY_ONE_INSTRUMENT")
    try:
        if importlib.metadata.version("websockets") != "15.0.1":
            result["blockers"].append("PINNED_WEBSOCKET_RUNTIME_REQUIRED")
    except importlib.metadata.PackageNotFoundError:
        result["blockers"].append("PINNED_WEBSOCKET_RUNTIME_REQUIRED")
    result["status"] = "PASS" if not result["blockers"] else "BLOCKED"
    return result


def smoke(config, seconds=15):
    """One configured instrument; no order/profile/token-refresh/REST calls."""
    report = preflight(config)
    report["scope"] = "READ_ONLY_DHAN_FEED_SMOKE"
    if type(seconds) is not int or not 1 <= seconds <= 30:
        return dict(report, status="BLOCKED", blockers=["SMOKE_DURATION_MUST_BE_1_TO_30_SECONDS"])
    if report["status"] != "PASS":
        return report
    # Never expand scope. A longer explicitly configured list must first be narrowed.
    if report["instrument_count"] != 1:
        return dict(report, status="BLOCKED", blockers=["SMOKE_REQUIRES_EXACTLY_ONE_INSTRUMENT"])
    from dhan_feed import DhanLiveFeed
    from storage import SQLitePersistenceStore
    store = SQLitePersistenceStore(":memory:")
    feed = None
    report.update(status="FAIL", live_requests=True, started_at=datetime.now(timezone.utc).isoformat())
    try:
        feed = DhanLiveFeed(config, store, instruments=config.dhan_feed_instruments)
        feed.connect()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            feed.poll_once()
        report["feed"] = feed.status()
        # A short quote probe cannot establish completed-candle/operational acceptance.
        report["status"] = "OBSERVED" if report["feed"].get("last_event_at") else "INCOMPLETE"
        report["authentication"] = "VERIFIED_BY_SCOPED_MARKET_PACKET" if report["feed"].get("last_event_at") else "NOT_VERIFIED"
        report["blockers"] = ["COMPLETED_CANDLE_AND_OPERATIONAL_ACCEPTANCE_NOT_ESTABLISHED"]
    except Exception:
        report.update(status="FAIL", blockers=["DHAN_FEED_SMOKE_FAILED_SEE_SANITIZED_FEED_STATUS"])
        if feed is not None:
            report["feed"] = feed.status()
    finally:
        clean = True
        try:
            if feed is not None:
                feed.stop()
        except Exception:
            clean = False
            report.update(status="FAIL", blockers=["DHAN_FEED_SHUTDOWN_REQUIRES_INSPECTION"])
        finally:
            store.close()
        report["ended_at"] = datetime.now(timezone.utc).isoformat()
        report["clean_shutdown"] = clean
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Explicit authorized read-only socket probe")
    parser.add_argument("--seconds", type=int, default=15)
    args = parser.parse_args(argv)
    from config import BotConfig
    try:
        cfg = BotConfig()
        report = smoke(cfg, args.seconds) if args.smoke else preflight(cfg)
    except Exception:
        report = dict(scope="LOCAL_DHAN_FEED_CONFIGURATION_ONLY", status="BLOCKED",
                      live_requests=False, blockers=["CONFIGURATION_INITIALIZATION_FAILED"])
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["status"] in ("PASS", "OBSERVED") else 1


if __name__ == "__main__":
    raise SystemExit(main())

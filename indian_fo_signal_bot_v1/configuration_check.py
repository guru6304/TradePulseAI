"""Local configuration-only check. No broker, store, scheduler or delivery startup."""
import json


def check_configuration():
    result = dict(status="BLOCKED", configuration_ready=False, scope="LOCAL_CONFIGURATION_ONLY",
        authentication="NOT_TESTED", quote="NOT_TESTED", candles="NOT_TESTED",
        data_persisted=False, readiness_receipt_issued=False, live_requests=False)
    try:
        import config
        cfg = config.BotConfig()
        cfg.validate(require_live_credentials=True)
        if cfg.telegram_dry_run is not True or cfg.enable_background_scheduler is not False:
            return dict(result, reason_code="SAFE_RUNTIME_FLAGS_REQUIRED", line_number=None)
        return dict(result, status="PASS", configuration_ready=True, reason_code="LOCAL_CONFIGURATION_VALID",
            line_number=None, active_broker=str(cfg.active_broker).strip().lower(),
            telegram_dry_run=True, enable_background_scheduler=False)
    except Exception as exc:
        # Only controlled metadata from our parser is allowed across this boundary.
        reason = getattr(exc, "reason_code", "CONFIGURATION_INITIALIZATION_FAILED")
        allowed = {"CONFIGURATION_INVALID", "DOTENV_ASSIGNMENT_MISSING_EQUALS", "DOTENV_KEY_INVALID",
                   "DOTENV_NUL_BYTE", "DOTENV_QUOTE_UNTERMINATED"}
        line = getattr(exc, "line_number", None)
        return dict(result, reason_code=reason if reason in allowed else "CONFIGURATION_INITIALIZATION_FAILED",
                    line_number=line if type(line) is int and line > 0 else None)


def main():
    result = check_configuration()
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["configuration_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

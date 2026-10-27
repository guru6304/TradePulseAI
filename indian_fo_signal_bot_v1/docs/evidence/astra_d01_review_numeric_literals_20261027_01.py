"""Pure authored native-JSON numeric diagnostic, never provider evidence."""
import hashlib
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP))
from test_option_observations import TestOptionObservations


def source_hashes():
    return {name: hashlib.sha256((APP / name).read_bytes()).hexdigest()
            for name in ("option_observations.py", "benchmark_observations.py", "test_option_observations.py")}


def main():
    output = Path(sys.argv[1])
    if output.exists():
        raise RuntimeError("Evidence path already exists")
    before = source_hashes()
    fixture = TestOptionObservations()
    fixture.setUp()
    cases = []
    for name, section, field, token, should_accept in (
            ("nonzero_iv_underflow", "option_greeks", "iv", "1e-999", False),
            ("fractional_volume_rounded_to_one", "market_data", "volume", "1.00000000000000001", False),
            ("large_fractional_oi_rounded_to_integer", "market_data", "oi", "9007199254740990.5", False),
            ("native_float_overflow", "option_greeks", "iv", "1e309", False),
            ("ordinary_decimal_control", "option_greeks", "iv", "0.1", True),
            ("smallest_positive_float_control", "option_greeks", "iv", "5e-324", True)):
        payload = fixture.chain()
        payload["data"][0]["call_options"][section][field] = "NATIVE_NUMERIC_LITERAL"
        raw = json.dumps(payload).replace('"NATIVE_NUMERIC_LITERAL"', token).encode()
        result = dict(name=name, field=field, native_json_numeric_literal=token,
                      expected_acceptance=should_accept, raw_sha256=hashlib.sha256(raw).hexdigest())
        try:
            capture = fixture.parse(raw=raw)
            call = next(row for row in capture["observations"] if row["identity"]["option_type"] == "CE")
            result.update(accepted=True, observed_field=call["fields"][field],
                          actionable=capture["actionable"], eligible=capture["eligible"])
        except Exception as exc:
            result.update(accepted=False, exception_type=type(exc).__name__, error_code=getattr(exc, "code", None))
        result["expected_behavior"] = (result["accepted"] == should_accept and
            (result["accepted"] or result["exception_type"] == "ObservationError"))
        cases.append(result)
    after = source_hashes()
    receipt = dict(schema_version="tradepulse.authored-numeric-diagnostic.v1",
        scope="SYNTHETIC_FIXTURE_ONLY_NOT_PROVIDER_OR_EXECUTION_ACCEPTANCE",
        reviewer_authored_option_tests=True, reviewer_authored_production_modules=False,
        source_sha256_before=before, source_sha256_after=after, source_unchanged=before == after,
        cases=cases, expected_behavior_count=sum(row["expected_behavior"] for row in cases),
        case_count=len(cases), status="PASS" if before == after and all(row["expected_behavior"] for row in cases) else "FAIL")
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(status=receipt["status"], expected_behavior_count=receipt["expected_behavior_count"],
                          case_count=receipt["case_count"], source_unchanged=receipt["source_unchanged"])))


if __name__ == "__main__":
    main()

"""Execute the real CLI with a temporary explicitly synthetic option request."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP))
import test_bot
from test_option_execution import TestOptionExecution
fixture=TestOptionExecution()
fixture.setUp()
try:
    with tempfile.TemporaryDirectory(prefix="tradepulse_option_cli_") as directory:
        request=Path(directory)/"fixture.json"
        request.write_text(json.dumps(fixture.request()),encoding="utf-8")
        command=[sys.executable,"-B","backtest_engine.py","--strategy","strat_3_option_apex_oi",
            "--symbol","NIFTY","--data-mode","SIMULATED","--provider","upstox",
            "--execution-scope","SIMULATED_TEST","--option-request",str(request),"--json"]
        result=subprocess.run(command,cwd=APP,env=dict(os.environ,**test_bot._test_config_defaults),
            capture_output=True,text=True,encoding="utf-8",timeout=30)
        assert result.returncode==0, (result.returncode,result.stderr)
        data=json.loads(result.stdout)
        assert data["status"]=="COMPLETED" and len(data["trades"])==1
        assert data["trades"][0]["exit_price"]==27.0 and data["ledger"]["reconciliation"]=="OK"
        assert data["empirical_performance_claim_allowed"] is False
        print(json.dumps(dict(status="PASS",process_exit_code=result.returncode,
            command=command[:-2]+["TEMPORARY_SYNTHETIC_REQUEST.json","--json"],
            trades=1,observed_exit_bid=data["trades"][0]["raw_exit_bid"],modeled_exit_fill=data["trades"][0]["exit_price"],
            ledger_reconciliation=data["ledger"]["reconciliation"],scope="OFFLINE_CLI_FIXTURE_ONLY")))
finally:
    fixture.doCleanups()

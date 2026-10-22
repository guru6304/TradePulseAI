"""OFFLINE contract/premium/OI fixtures; no real publisher or performance evidence."""
import copy
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

import test_bot
from backtest_engine import BacktestConfig,BacktestEligibilityError,DeterministicBacktestEngine
from config import BotConfig
from instrument_archive import prepare_archive,SCHEMA
from instrument_identity import digest
from strategies import IST
from storage import SQLitePersistenceStore


class TestOptionExecution(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,16,16,tzinfo=IST)
        self.store=SQLitePersistenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.engine=DeterministicBacktestEngine(BotConfig(active_broker="paper_sim",telegram_dry_run=True,
            enable_background_scheduler=False),self.store,clock=lambda:self.now)
        self.master=dict(schema_version=SCHEMA,provider="upstox",evidence_class="SYNTHETIC_FIXTURE",records=[
            dict(symbol="NIFTY",underlying="NIFTY",identifier="NSE_FO|"+str(n),exchange="NFO",instrument_type="OPTIDX",
                expiry="2026-10-29",strike=10000,option_type=side,lot_size=25,tick_size=.05,multiplier=1,
                valid_from="2026-10-01",valid_to="2026-10-29") for n,side in ((1001,"CE"),(1002,"PE"))])
        self.data=dict(schema_version="tradepulse.option-observations.v1",symbol="NIFTY",provider="upstox",
            data_mode="SIMULATED",is_simulated=True,evidence_class="SYNTHETIC_FIXTURE",premiums=[],underlying_candles=[],chains=[])
        archive=prepare_archive(json.dumps(self.master).encode(),"upstox","option-master.json","OPTION_REQUEST_ORIGINAL_BYTES")
        contracts={r["identifier"]:r for r in archive["records"]}
        first=datetime(2026,10,16,9,15,tzinfo=IST)
        for index in range(17):
            stamp=first+timedelta(minutes=index*5)
            self.data["underlying_candles"].append(dict(timestamp=stamp.isoformat(),open=100,high=101,low=99,
                close=100.5,volume=1000,is_complete=True,data_mode="SIMULATED",is_simulated=True))
            for contract in contracts.values():
                price=30 if index==16 else 20
                self.data["premiums"].append(dict(identifier=contract["identifier"],contract_digest=digest(contract),
                    timestamp=stamp.isoformat(),available_at=(stamp+timedelta(minutes=5)).isoformat(),is_complete=True,
                    data_mode="SIMULATED",is_simulated=True,bid_open=price,bid_high=price+1,bid_low=price-1,bid_close=price,
                    ask_open=price+.1,ask_high=price+1.1,ask_low=price-.9,ask_close=price+.1,
                    bid_size_units=10000,ask_size_units=10000,depth_observed_at=stamp.isoformat(),volume_units=10000))
        self.data["chains"].append(dict(known_at=(first+timedelta(minutes=75)).isoformat(),
            baseline_observed_at="2026-10-15T15:30:00+05:30",baseline_kind="CLOSING_BASELINE",symbol="NIFTY",
            data_mode="SIMULATED",is_simulated=True,expiry="2026-10-29",atm_strike=10000,pcr=1.5,
            strikes=[dict(strike=10000,ce_ltp=20,pe_ltp=20,ce_oi=1000,pe_oi=1500,ce_prev_oi=1200,pe_prev_oi=1200,
                ce_oi_change=-200,pe_oi_change=300)]))
        self.config=BacktestConfig(instrument_type="OPTIDX",execution_scope="SIMULATED_TEST")

    def request(self):
        return dict(schema_version="tradepulse.option-request.v1",master_json=json.dumps(self.master),dataset_json=json.dumps(self.data))

    def replay(self,**kwargs):
        return self.engine.run_backtest("strat_3_option_apex_oi","NIFTY",provider="upstox",data_mode="SIMULATED",
            backtest_config=self.config,option_execution_request=self.request(),**kwargs)

    def bad(self, action):
        action()
        with self.assertRaises((BacktestEligibilityError,ValueError,KeyError)):
            self.replay()

    def test_real_strategy_next_option_open_then_target_and_persistence_are_deterministic(self):
        result=self.replay(persist_run=True)
        self.assertEqual((result["status"],len(result["trades"])),("COMPLETED",1))
        trade=result["trades"][0]
        self.assertEqual(trade["signal_known_at"],trade["entry_timestamp_ist"])
        self.assertEqual(trade["entry_timestamp_ist"],"2026-10-16T10:30:00+05:30")
        self.assertGreater(trade["entry_price"],20.1)
        self.assertGreater(trade["charges_inr"],0)
        self.assertEqual(trade["raw_exit_bid"],30)
        self.assertLess(trade["exit_price"],trade["raw_exit_bid"])
        self.assertEqual(trade["stop_loss"],15.6)
        self.assertEqual(trade["target_price"],27.05)
        self.assertEqual(trade["exit_price"],27.0)
        self.assertEqual(trade["quantity"]%25,0)
        self.assertEqual(result,self.replay())
        self.assertFalse(result["research_eligible"])
        self.assertFalse(result["empirical_performance_claim_allowed"])
        self.assertEqual(result["ledger"]["reconciliation"],"OK")
        self.assertEqual(self.store.query_backtest_runs()["total_count"],1)

    def test_contract_token_underlying_strike_side_lot_and_tick_conflicts_fail(self):
        for field,value in (("identifier","WRONG"),("underlying","BANKNIFTY"),("strike",10100),
                            ("option_type","PE"),("lot_size",50),("tick_size",.2),("expiry","2026-10-01")):
            with self.subTest(field=field):
                original=copy.deepcopy(self.master)
                self.master["records"][0][field]=value
                with self.assertRaises(BacktestEligibilityError): self.replay()
                self.master=original

    def test_no_lookahead_future_option_bar_changes_do_not_change_candidate_or_entry(self):
        first=self.replay()
        for row in self.data["premiums"][-2:]:
            row["bid_high"]+=10;row["ask_high"]+=10
        second=self.replay()
        for key in ("entry_price","entry_timestamp_ist","quantity","signal_known_at"):
            self.assertEqual(first["trades"][0][key],second["trades"][0][key])

    def test_missing_next_open_rejects_instead_of_using_later_observation(self):
        self.data["premiums"]=[r for r in self.data["premiums"] if r["timestamp"]!="2026-10-16T10:30:00+05:30"]
        result=self.replay()
        self.assertFalse(result["trades"])
        self.assertIn("NEXT_ELIGIBLE_OPTION_OPEN_MISSING",str(result["rejected_signals"]))

    def test_open_position_missing_exit_retains_reservation_without_fake_settlement(self):
        self.data["premiums"]=self.data["premiums"][:-2]
        result=self.replay()
        self.assertEqual(result["status"],"UNRESOLVED")
        self.assertGreater(result["ledger"]["reserved_premium_inr"],0)
        self.assertFalse(result["trades"])

    def test_gap_through_stop_uses_observed_open_and_honors_actual_liquidity(self):
        for row in self.data["premiums"][-2:]:
            for side in ("bid","ask"):
                shift=20 if side=="bid" else 20
                for field in ("open","high","low","close"): row[side+"_"+field]=round(row[side+"_"+field]-shift,2)
        result=self.replay()
        self.assertEqual(result["trades"][0]["exit_reason"],"GAP_THROUGH_STOP")
        self.assertLess(result["trades"][0]["exit_price"],10)
        self.data["premiums"][-2]["bid_size_units"]=0
        self.assertEqual(self.replay()["status"],"UNRESOLVED")

    def test_intrabar_collision_does_not_award_target_or_invent_trigger_liquidity(self):
        row=self.data["premiums"][-2]
        row.update(bid_open=20,bid_low=10,bid_high=40,bid_close=20,ask_open=20.1,ask_low=10.1,ask_high=40.1,ask_close=20.1)
        result=self.replay()
        self.assertEqual(result["status"],"UNRESOLVED")
        self.assertFalse(result["trades"])

    def test_unknown_depth_crossed_spread_bad_tick_and_future_or_naive_time_reject(self):
        for field,value in (("ask_size_units",None),("bid_open",21),("bid_open",20.001),
            ("timestamp","2026-10-16T09:15:00"),("available_at","2026-10-17T12:00:00+05:30"),
            ("is_complete",False),("contract_digest","changed"),("data_mode","LIVE")):
            with self.subTest(field=field):
                original=copy.deepcopy(self.data)
                self.data["premiums"][0][field]=value
                with self.assertRaises(BacktestEligibilityError): self.replay()
                self.data=original

    def test_entry_risk_capital_and_opening_liquidity_constraints(self):
        self.config.starting_capital_inr=100
        self.assertFalse(self.replay()["trades"])
        self.config.starting_capital_inr=100000
        self.data["premiums"][-4]["ask_size_units"]=0
        result=self.replay()
        self.assertFalse(result["trades"])
        self.assertIn("LIQUIDITY",str(result["rejected_signals"]))

    def test_bad_oi_baseline_or_changed_previous_close_is_rejected(self):
        for change in (dict(baseline_kind="INTRADAY"),dict(baseline_observed_at="2026-10-16T09:15:00+05:30")):
            original=copy.deepcopy(self.data)
            self.data["chains"][0].update(change)
            with self.assertRaises(BacktestEligibilityError): self.replay()
            self.data=original
        self.data["chains"][0]["strikes"][0]["ce_prev_oi"]+=1
        with self.assertRaises(BacktestEligibilityError): self.replay()
        self.data["chains"][0]["strikes"][0]["ce_prev_oi"]-=1
        self.data["chains"][0]["strikes"][0]["ce_oi_change"]=-200.4
        with self.assertRaises(BacktestEligibilityError): self.replay()

    def test_unsigned_live_mode_and_caller_qualification_flags_do_not_enable_research(self):
        request=self.request()
        request["qualified"]=True
        with self.assertRaises(BacktestEligibilityError):
            self.engine.run_backtest("strat_3_option_apex_oi","NIFTY",provider="upstox",data_mode="LIVE",
                option_execution_request=request,backtest_config=BacktestConfig(instrument_type="OPTIDX",execution_scope="HISTORICAL_RESEARCH"))

    def test_timezone_offsets_represent_same_instant_and_derived_fills_are_labelled(self):
        first=self.replay()
        for row in self.data["premiums"]:
            for field in ("timestamp","available_at","depth_observed_at"):
                from datetime import timezone
                row[field]=datetime.fromisoformat(row[field]).astimezone(timezone.utc).isoformat()
        result=self.replay()
        self.assertEqual(result["trades"][0]["entry_price"],first["trades"][0]["entry_price"])
        self.assertEqual(result["trades"][0]["fill_classification"],"SIMULATED_FIXTURE_EXECUTION")

    def test_readiness_gate_validates_explicit_option_input_and_cannot_accept_flags(self):
        from readiness_policy import execution_gate
        args=dict(config=self.engine.bot_config,store=self.store,provider="upstox",symbol="NIFTY",
            strategy_id="strat_3_option_apex_oi",data_mode="SIMULATED",execution_scope="SIMULATED_TEST",now=self.now)
        self.assertTrue(execution_gate(**args,option_execution_request=self.request())["allowed"])
        request=self.request();request["qualified"]=True
        self.assertFalse(execution_gate(**args,option_execution_request=request)["allowed"])

    def test_expiry_observed_eod_exit_and_missing_eod_never_settle_at_zero(self):
        for record in self.master["records"]:
            record.update(expiry="2026-10-16",valid_to="2026-10-16")
        archive=prepare_archive(json.dumps(self.master).encode(),"upstox","option-master.json","OPTION_REQUEST_ORIGINAL_BYTES")
        contracts={r["identifier"]:r for r in archive["records"]}
        self.data["chains"][0]["expiry"]="2026-10-16"
        for row in self.data["premiums"]:
            row["contract_digest"]=digest(contracts[row["identifier"]])
            for side,base in (("bid",20),("ask",20.1)):
                row.update({side+"_open":base,side+"_high":round(base+1,2),side+"_low":round(base-1,2),side+"_close":base})
        while datetime.fromisoformat(self.data["underlying_candles"][-1]["timestamp"]).time().isoformat()<"15:20:00":
            bar=copy.deepcopy(self.data["underlying_candles"][-1])
            stamp=datetime.fromisoformat(bar["timestamp"])+timedelta(minutes=5)
            bar["timestamp"]=stamp.isoformat();self.data["underlying_candles"].append(bar)
            for row in copy.deepcopy(self.data["premiums"][-2:]):
                row.update(timestamp=stamp.isoformat(),depth_observed_at=stamp.isoformat(),available_at=(stamp+timedelta(minutes=5)).isoformat())
                self.data["premiums"].append(row)
        result=self.replay()
        self.assertEqual(result["trades"][0]["exit_reason"],"EXPIRY_PRE_CLOSE")
        self.data["premiums"]=self.data["premiums"][:-2]
        unresolved=self.replay()
        self.assertEqual(unresolved["status"],"UNRESOLVED")
        self.assertGreater(unresolved["ledger"]["reserved_premium_inr"],0)
        with self.assertRaises(BacktestEligibilityError): self.replay(persist_run=True)

    def test_bearish_strategy_selects_exact_put_instead_of_call_or_underlying(self):
        self.data["underlying_candles"][14]["close"]=99.5
        row=self.data["chains"][0]["strikes"][0]
        row.update(ce_oi=1500,pe_oi=1000,ce_oi_change=300,pe_oi_change=-200)
        self.data["chains"][0]["pcr"]=1000/1500
        result=self.replay()
        self.assertEqual(result["trades"][0]["contract"]["option_type"],"PE")
        self.assertEqual(result["trades"][0]["contract"]["identifier"],"NSE_FO|1002")

    def test_actual_local_http_option_request_returns_persisted_option_ledger(self):
        import http.client
        import threading
        from types import SimpleNamespace
        from server import DashboardRequestHandler,create_http_server
        engine=SimpleNamespace(config=self.engine.bot_config,store=self.store,clock=lambda:self.now,get_broker_status=lambda:{})
        handler=type("OfflineOptionHTTP",(DashboardRequestHandler,),dict(engine=engine,scheduler=object(),
            evidence_scope="OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE"))
        server=create_http_server("127.0.0.1",0,handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            conn=http.client.HTTPConnection(*server.server_address,timeout=15)
            try:
                conn.request("POST","/api/backtest",json.dumps(dict(strategy_id="strat_3_option_apex_oi",symbol="NIFTY",
                    data_mode="SIMULATED",provider="upstox",instrument_type="OPTIDX",execution_scope="SIMULATED_TEST",
                    option_execution_request=self.request())),{"Content-Type":"application/json"})
                response=conn.getresponse();payload=json.loads(response.read())
            finally: conn.close()
            self.assertEqual(response.status,200,payload)
            self.assertEqual(payload["ledger"]["reconciliation"],"OK")
            self.assertEqual(payload["evidence_scope"],"OFFLINE_FIXTURE_NOT_LIVE_ACCEPTANCE")
            self.assertEqual(payload["trades"][0]["contract"]["identifier"],"NSE_FO|1001")
        finally:
            server.shutdown();thread.join(5);server.server_close()

    def test_real_signature_gate_on_live_shaped_fixture_rechecks_revocation_and_changed_bytes(self):
        # TEST-ONLY roots in this object; no production root or dataset installed.
        from test_publisher_trust import TestPublisherTrustMatrix
        helper=TestPublisherTrustMatrix();helper.setUp();self.addCleanup(helper.doCleanups)
        anchor=helper._build_trust_config()._anchors[0];anchor["publisher_id"]="upstox"
        self.engine.publisher_trust_config=helper._build_trust_config(anchors=[anchor])
        self.master.pop("evidence_class")
        self.data.pop("evidence_class")
        self.data.update(data_mode="LIVE",is_simulated=False)
        for collection in ("premiums","underlying_candles","chains"):
            for row in self.data[collection]: row.update(data_mode="LIVE",is_simulated=False)
        request=self.request()
        common=dict(publisher_id="upstox",provider="upstox",exchange="NFO",market_segment="NSE_FO_INDEX")
        request["master_manifest"]=json.dumps(helper._build_manifest(request["master_json"].encode(),**common))
        request["dataset_manifest"]=json.dumps(helper._build_manifest(request["dataset_json"].encode(),**common,
            artifact_type="option-observations",artifact_schema_version=self.data["schema_version"],instrument_scope="NIFTY"))
        cfg=BacktestConfig(instrument_type="OPTIDX",execution_scope="HISTORICAL_RESEARCH")
        def run():
            return self.engine.run_backtest("strat_3_option_apex_oi","NIFTY",provider="upstox",data_mode="LIVE",
                option_execution_request=request,backtest_config=cfg)
        result=run()
        self.assertTrue(result["research_eligible"])
        self.assertFalse(result["empirical_performance_claim_allowed"])
        self.engine.publisher_trust_config._anchors[0]["revoked"]=True
        with self.assertRaises(BacktestEligibilityError): run()
        self.engine.publisher_trust_config._anchors[0]["revoked"]=False
        request["dataset_json"]+=" "
        with self.assertRaises(BacktestEligibilityError): run()

    def test_duplicate_premiums_or_future_chain_baseline_and_aliases_fail(self):
        self.data["premiums"].insert(1,copy.deepcopy(self.data["premiums"][0]))
        with self.assertRaises(BacktestEligibilityError):self.replay()
        self.data["premiums"].pop(1)
        self.master["records"][0]["symbol"]="NIFTY 50"
        with self.assertRaises(BacktestEligibilityError):self.replay()


if __name__=="__main__": unittest.main(verbosity=2)

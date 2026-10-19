"""Continuous acceptance: explicitly OFFLINE / MOCKED, never broker evidence."""
import copy
import gzip
import hashlib
import http.client
import io
import json
import os
import sys
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

if "test_bot" not in sys.modules and not hasattr(sys.modules.get("__main__"), "_test_config_defaults"):
    import test_bot
_fixtures = sys.modules.get("test_bot") or sys.modules["__main__"]


def setUpModule():
    guard = patch.dict(os.environ, _fixtures._test_config_defaults)
    guard.start()
    unittest.addModuleCleanup(guard.stop)


from diagnostics import run_angelone_market_data_diagnostics
from paper_portfolio import PaperPortfolio, PaperPortfolioError, _encode, _hash
from server import DashboardRequestHandler, create_http_server
from storage import PersistenceValidationError
from strategies import IST


class TestIsolatedAngelAcceptance(unittest.TestCase):
    def setUp(self):
        from test_angel_market_data import TestAngelMarketDataDiagnostics
        self.f = TestAngelMarketDataDiagnostics()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.cfg.active_broker = "upstox"
        self.f.cfg.upstox_access_token = ""

    def run_diagnostic(self, **changes):
        return run_angelone_market_data_diagnostics(self.f.cfg, self.f.adapter, symbol="RELIANCE",
            clock=lambda: self.f.now, isolated_provider=True, **changes)

    def test_isolated_preflight_uses_only_angel_credentials_without_provider_mutation(self):
        with patch("diagnostics.AngelOneSmartAPIAdapter", side_effect=AssertionError("No adapter")), \
             patch("diagnostics.SQLitePersistenceStore", side_effect=AssertionError("No database")):
            result = self.run_diagnostic(config_only=True)
        self.assertTrue(result["configuration_ready"])
        self.assertEqual(result["overall_status"], "NOT_TESTED")
        self.assertEqual(result["effective_configuration"]["active_broker"], "upstox")
        self.assertEqual(self.f.cfg.active_broker, "upstox")
        self.assertFalse(self.f.requests)
        self.assertFalse(result["application_provider_changed"])
        self.assertEqual(run_angelone_market_data_diagnostics(self.f.cfg, symbol="RELIANCE", config_only=True)["checks"]["configuration"]["status"], "BLOCKED")

    def test_mocked_isolated_session_uses_login_quote_candles_only(self):
        self.f.adapter.jwt_token = None
        self.f.responses = [dict(status=True, data=dict(jwtToken="OFFLINE_SESSION")),self.f._quote_response(),self.f._candles()]
        report = self.run_diagnostic()
        self.assertEqual(report["overall_status"], "PASS")
        self.assertEqual(len(self.f.requests),3)
        self.assertTrue(self.f.adapter.session_recovery_enabled)
        self.assertFalse(report["readiness_receipt_issued"])
        self.assertFalse(report["historical_replay_allowed"])
        self.assertFalse(report["data_persisted"])

    def test_diagnostic_401_does_not_refresh_or_attempt_second_login(self):
        error, stream = self.f._http_error(401)
        self.f.responses = [error]
        with patch.object(self.f.adapter,"_recover_session",side_effect=AssertionError("Recovery forbidden")) as recovery:
            report = self.run_diagnostic()
        recovery.assert_not_called()
        self.assertEqual(len(self.f.requests),1)
        self.assertTrue(stream.closed)
        self.assertEqual(report["checks"]["quote"]["http_status"],401)
        self.assertEqual(report["checks"]["candles"]["status"],"NOT_TESTED")
        self.assertTrue(self.f.adapter.session_recovery_enabled)

    def test_403_is_not_reported_as_a_proven_rate_limit_cause(self):
        error, stream = self.f._http_error(403)
        self.f.responses = [error]
        report = self.run_diagnostic()
        self.assertEqual(report["checks"]["quote"]["error_category"],"ACCESS_DENIED")
        self.assertEqual(report["checks"]["quote"]["provider_cause"],"NOT_ESTABLISHED")
        self.assertTrue(stream.closed)
        self.assertEqual(len(self.f.requests),1)

    def test_missing_fields_and_unsafe_flags_block_without_leaking_values(self):
        self.f.cfg.angel_api_key=""
        report=self.run_diagnostic(config_only=True)
        self.assertEqual(report["checks"]["configuration"]["missing_configuration_fields"],["ANGEL_API_KEY"])
        self.assertNotIn(self.f.cfg.angel_pin,json.dumps(report))
        self.f.cfg.angel_api_key="OFFLINE_KEY"
        for name,value in (("telegram_dry_run",False),("enable_background_scheduler",True)):
            old=getattr(self.f.cfg,name)
            try:
                setattr(self.f.cfg,name,value)
                self.assertFalse(self.run_diagnostic(config_only=True)["configuration_ready"])
            finally:
                setattr(self.f.cfg,name,old)
        self.assertFalse(self.f.requests)

    def test_cli_requires_explicit_narrow_mode_and_remains_offline(self):
        from diagnostics import main
        output=io.StringIO()
        with patch("diagnostics.BotConfig",return_value=self.f.cfg),patch("sys.stdout",output), \
             patch("diagnostics.run_angelone_diagnostics",side_effect=AssertionError("No legacy workflow")):
            self.assertEqual(main(["--market-data-only","--symbol","RELIANCE","--isolated-provider","--check-config","--json"]),0)
        self.assertTrue(json.loads(output.getvalue())["isolated_provider"])
        with patch("sys.stderr",io.StringIO()),self.assertRaises(SystemExit) as raised:
            main(["--isolated-provider","--offline"])
        self.assertEqual(raised.exception.code,2)
        self.assertFalse(self.f.requests)


class TestPaperOperationalAcceptance(unittest.TestCase):
    def setUp(self):
        from test_phase5c_recovery import TestPhase5CRecovery
        self.f=TestPhase5CRecovery()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.store=self.f.store

    def test_freeze_and_denied_late_repair_are_audited_without_financial_effects(self):
        paper,result,candidate,bar=self.f.eod_entry(cost_model_json="{}")
        self.f.f._set_time("16:00")
        before=paper.snapshot()
        original_hash=paper.config.config_hash
        decision=paper.review_unresolved_eod(result["position_id"],"freeze")
        self.assertEqual(decision["status"],"FROZEN")
        self.assertTrue(self.f.restart(paper).review_unresolved_eod(result["position_id"],"freeze")["idempotent"])
        denied=paper.review_unresolved_eod(result["position_id"],"late",requested_action="REQUEST_LATE_HISTORICAL_REPAIR",observation_sha256="a"*64)
        self.assertEqual(denied["status"],"BLOCKED_POLICY_APPROVAL_REQUIRED")
        self.assertFalse(denied["financial_mutations"])
        self.assertEqual(paper.snapshot(),before)
        self.assertEqual(paper.config.config_hash,original_hash)
        self.assertEqual(len(self.store.query_paper_ledger("eod","recovery_decisions")["items"]),2)
        self.f.assert_code("EVENT_IDEMPOTENCY_CONFLICT",lambda:paper.review_unresolved_eod(result["position_id"],"freeze",observation_sha256="b"*64))
        self.f.assert_code("UNAPPROVED_FINANCIAL_RECOVERY_ACTION",lambda:paper.review_unresolved_eod(result["position_id"],"adjust",requested_action="FORCE_CLOSE"))

    def test_recovery_audit_insert_failure_rolls_back_and_retry_is_safe(self):
        import sqlite3
        paper,result,candidate,bar=self.f.eod_entry()
        self.f.f._set_time("16:00")
        before=paper.snapshot()
        with self.store.paper_transaction() as conn:
            conn.execute("CREATE TRIGGER audit_fault AFTER INSERT ON paper_recovery_decisions BEGIN SELECT RAISE(ABORT,'OFFLINE'); END")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                paper.review_unresolved_eod(result["position_id"],"audit")
        finally:
            with self.store.paper_transaction() as conn:
                conn.execute("DROP TRIGGER audit_fault")
        self.assertEqual(paper.snapshot(),before)
        self.assertEqual(self.store.query_paper_ledger("eod","recovery_decisions")["items"],[])
        paper.review_unresolved_eod(result["position_id"],"audit")
        self.assertEqual(self.f.restart(paper).snapshot(),before)

    def test_recovery_waits_until_publication_deadline_and_rejects_corrupt_audit(self):
        paper,result,candidate,bar=self.f.eod_entry()
        self.f.f.now=datetime(2026,10,16,15,21,tzinfo=IST)
        self.f.assert_code('EOD_RECOVERY_NOT_DUE',lambda:paper.review_unresolved_eod(result['position_id'],'freeze'))
        self.f.f.now+=timedelta(microseconds=1)
        decision=paper.review_unresolved_eod(result['position_id'],'freeze')
        changed=dict(decision,financial_mutations=True)
        with self.store.paper_transaction() as conn:
            conn.execute('UPDATE paper_recovery_decisions SET payload_json=? WHERE decision_id=?',(_encode(changed),decision['decision_id']))
        self.f.assert_code('RECONCILIATION_REQUIRED',lambda:paper.review_unresolved_eod(result['position_id'],'freeze'))

    def test_recovery_rejects_other_accounts_pre_eod_and_closed_positions(self):
        result,candidate=self.f.enter()
        paper=self.f.paper
        self.f.assert_code("EOD_RECOVERY_NOT_DUE",lambda:paper.review_unresolved_eod(result["position_id"],"early"))
        other=self.f.f._service(account_id="foreign")
        self.f.assert_code("POSITION_NOT_IN_ACCOUNT",lambda:other.review_unresolved_eod(result["position_id"],"foreign"))
        self.f.f._set_time("10:15")
        paper.process_bar(result["position_id"],self.f.f._bar(candidate,stamp="10:10",high=125,low=99,close=121),"exit")
        self.f.assert_code("POSITION_ALREADY_CLOSED",lambda:paper.review_unresolved_eod(result["position_id"],"closed"))

    def test_eod_statement_is_reproducible_and_excludes_later_session_pnl(self):
        paper,result,candidate,bar=self.f.eod_entry(cost_model_json="{}")
        self.f.assert_code("SESSION_NOT_ENDED",lambda:paper.session_statement("2026-10-16"))
        self.f.f._set_time("15:20")
        paper.process_bar(result["position_id"],bar,"eod")
        self.f.f._set_time("16:00")
        first=paper.session_statement("2026-10-16")
        self.assertEqual(first["eod_status"],"RECONCILED")
        self.assertEqual(first["accounting"]["reserved_capital_inr"],0)
        self.assertEqual(first,self.f.restart(paper).session_statement("2026-10-16"))
        self.f.f._set_time("10:10",date="2026-10-19")
        monday=self.f.f._candidate(paper).to_dict()
        monday["timestamp"]="2026-10-19 10:00:00"
        paper.enter(monday,self.f.f._bar(candidate,timestamp="2026-10-19T10:05:00+05:30"),"monday")
        self.assertEqual(paper.session_statement("2026-10-16"),first)
        self.assertEqual(self.store.get_paper_session_report("eod","2026-10-16",as_of=self.f.f.now),first)
        self.assertFalse(first["historical_replay_allowed"])

    def test_unresolved_export_keeps_real_mark_reservation_and_no_fabricated_exit(self):
        paper,result,candidate,bar=self.f.eod_entry(cost_model_json="{}")
        self.f.f._set_time("16:00")
        before=paper.snapshot()
        statement=paper.session_statement("2026-10-16")
        self.assertEqual(statement["eod_status"],"UNRESOLVED")
        self.assertEqual(statement["accounting"]["reserved_capital_inr"],before["accounting"]["reserved_capital_inr"])
        self.assertEqual(statement["accounting"]["fees_paid_inr_session"],0)
        self.assertEqual(statement["accounting"]["unrealized_net_pnl_inr"],before["accounting"]["unrealized_net_pnl_inr"])
        self.f.f._set_time("10:10",date="2026-10-19")
        paper.review_unresolved_eod(result["position_id"],"audit")
        self.assertEqual(paper.session_statement("2026-10-16"),statement)

    def test_empty_corrupt_and_invalid_session_exports_fail_safely(self):
        self.f.f._set_time("16:00")
        empty=self.f.paper.session_statement("2026-10-16")
        self.assertEqual(empty["accounting"]["equity_inr"],10000)
        self.assertEqual(empty["event_count"],0)
        for day in ("2026-10-17","20261016","invalid"):
            self.f.assert_code("INVALID_CONFIGURED_SESSION_DATE",lambda:self.f.paper.session_statement(day))
        self.f.f._set_time("10:10")
        result,candidate=self.f.enter()
        self.f.f._set_time("16:00")
        with self.store.paper_transaction() as conn:
            conn.execute("UPDATE paper_events SET payload_json='{' WHERE account_id='account'")
        report=self.f.paper.session_statement("2026-10-16")
        self.assertEqual(report["status"],"RECONCILIATION_REQUIRED")
        self.assertIsNone(report["accounting"])

    def test_inventory_has_bounded_stable_pages_and_cross_cursor_rejection(self):
        base=self.f.paper.config
        with self.store.paper_transaction() as conn:
            for i in range(220):
                cfg=replace(base,account_id=f"inventory{i}")
                conn.execute("INSERT INTO paper_accounts VALUES(?,?,?,?)",(cfg.account_id,cfg.config_hash,_encode(cfg.to_dict()),"2026-10-16 10:00:00"))
        self.assertEqual(len(self.store.list_paper_accounts()),200)
        first=self.store.query_paper_accounts(limit=17)
        self.f.f._service(account_id="appended")
        seen=first["accounts"][:]
        cursor=first["next_cursor"]
        while cursor:
            page=self.store.query_paper_accounts(limit=17,cursor=cursor)
            seen.extend(page["accounts"])
            cursor=page["next_cursor"]
        self.assertEqual(len(seen),221)
        self.assertEqual(len({row['account_id'] for row in seen}),221)
        self.assertNotIn("appended",[row['account_id'] for row in seen])
        with self.assertRaises(ValueError):
            self.store.query_paper_ledger("account",cursor=first["next_cursor"])

    def test_restart_does_not_rewrite_order_sequence_for_existing_events(self):
        self.f.enter()
        with self.store.paper_transaction(write=False) as conn:
            before=conn.execute("SELECT seq FROM sqlite_sequence WHERE name='paper_ledger_order'").fetchone()[0]
        self.f.restart()
        with self.store.paper_transaction(write=False) as conn:
            after=conn.execute("SELECT seq FROM sqlite_sequence WHERE name='paper_ledger_order'").fetchone()[0]
        self.assertEqual(after,before)

    def test_expired_queued_candidates_are_processed_in_bounded_chronological_batches(self):
        paper=self.f.paper
        candidate=self.f.f._candidate(paper)
        summary=self.f.h._summary(candidate)
        self.f.coordinator._queue(summary)
        original=paper.snapshot()["candidate_decisions"][0]
        dates=[]
        day=datetime(2026,10,1)
        while len(dates)<8:
            if day.weekday()<5: dates.append(day)
            day+=timedelta(days=1)
        with self.store.paper_transaction() as conn:
            for i in range(449):
                d=copy.deepcopy(original)
                key=_hash(["OFFLINE_BACKLOG",i])
                d.update(candidate_id=key,signal_key=key)
                d["candidate"]["timestamp"]=(dates[i//60].replace(hour=9,minute=15)+timedelta(minutes=(i%60)*5)).strftime("%Y-%m-%d %H:%M:%S")
                d["candidate_hash"]=_hash(d["candidate"])
                conn.execute("INSERT INTO paper_candidate_decisions VALUES(?,?,?,?,?)",(key,"account",key,summary['run_id'],_encode(d)))
        self.f.f._set_time("10:10",date="2026-10-19")
        first=self.f.coordinator.consume_scan(summary,{})
        self.assertEqual(first["status"],"PARTIAL")
        self.assertEqual(len(first["actions"]),200)
        self.assertEqual(first["pending_deferred_count"],250)
        self.f.coordinator.consume_scan(summary,{})
        self.f.coordinator.consume_scan(summary,{})
        with self.store.paper_transaction(write=False) as conn:
            pending,count=self.store.pending_paper_decisions(conn,"account")
            plan=[r[3] for r in conn.execute("EXPLAIN QUERY PLAN SELECT payload_json FROM paper_candidate_decisions WHERE account_id=? "
                "AND json_extract(CASE WHEN json_valid(payload_json) THEN payload_json ELSE '{}' END,'$.status')='QUEUED'",('account',))]
        self.assertEqual(count,0)
        self.assertTrue(any('idx_paper_pending' in line for line in plan))
        report=paper.snapshot()
        self.assertEqual(report['accounting']['reserved_capital_inr'],0)
        self.assertEqual(report['total_events'],0)

    def test_corrupt_offpage_decision_blocks_handoff_without_effects(self):
        candidate=self.f.f._candidate(self.f.paper)
        summary=self.f.h._summary(candidate)
        self.f.coordinator._queue(summary)
        with self.store.paper_transaction() as conn:
            conn.execute("INSERT INTO paper_candidate_decisions VALUES('corrupt','account','corrupt','OFFLINE','[]')")
        with self.assertRaises(PersistenceValidationError):
            self.f.coordinator.consume_scan(summary,{candidate.symbol:[self.f.f._bar(candidate)]})
        self.assertEqual(self.f.paper.snapshot()['status'],'RECONCILIATION_REQUIRED')
        with self.store.paper_transaction(write=False) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM paper_events WHERE account_id='account'").fetchone()[0],0)

    def test_oversized_identity_cannot_commit_a_record_its_own_reader_rejects(self):
        candidate=self.f.f._candidate(self.f.paper)
        bar=self.f.f._bar(candidate)
        bar['instrument_identity']['extra_fixture_metadata']='X'*524288
        with self.assertRaises(PaperPortfolioError):
            self.f.paper.enter(candidate,bar,'oversized')
        self.assertEqual(self.f.paper.snapshot()['total_events'],0)

    def test_wire_session_and_inventory_routes_are_bounded_and_read_only(self):
        self.f.f._set_time('16:00')
        engine=SimpleNamespace(store=self.store,_now_ist=lambda:self.f.f.now)
        handler=type('ContinuousOfflineHandler',(DashboardRequestHandler,),{'engine':engine,'scheduler':object()})
        server=create_http_server('127.0.0.1',0,handler_cls=handler)
        self.addCleanup(server.server_close)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        def stop():
            server.shutdown();thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.addCleanup(stop)
        before=self.f.paper.snapshot()
        for method,path,expected in (('GET','/api/paper-session?account_id=account&session_date=2026-10-16',200),
            ('HEAD','/api/v1/paper-session?account_id=account&session_date=2026-10-16',200),
            ('GET','/api/paper-session?account_id=account&session_date=2026-10-17',400),
            ('GET','/api/paper-accounts?limit=1',200),('GET','/api/paper-accounts?limit=0',400)):
            connection=http.client.HTTPConnection(*server.server_address,timeout=5)
            try:
                connection.request(method,path)
                response=connection.getresponse();body=response.read()
                self.assertEqual(response.status,expected)
                self.assertEqual(response.getheader('Cache-Control'),'no-store')
                if method=='HEAD':self.assertEqual(body,b'')
            finally:
                connection.close()
        self.assertEqual(self.f.paper.snapshot(),before)


class TestNativeContractObservation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parent/'docs'/'evidence'
        raw=gzip.decompress((root/'angel_public_master_20261019.json.gz').read_bytes())
        cls.capture=json.loads((root/'angel_public_master_20261019_capture.json').read_text())
        if hashlib.sha256(raw).hexdigest()!=cls.capture['original_sha256']:
            raise AssertionError('Retained public artifact digest mismatch')
        cls.raw=raw
        cls.rows=json.loads(raw)
        cls.spots=[r for r in cls.rows if r.get('exch_seg')=='NSE' and
            ((r.get('name')=='NIFTY' and r.get('instrumenttype')=='AMXIDX') or
             (r.get('name')=='RELIANCE' and r.get('symbol')=='RELIANCE-EQ'))]
        cls.derivatives=[]
        for kind in ('FUTIDX','FUTSTK','OPTIDX','OPTSTK'):
            underlying='NIFTY' if kind.endswith('IDX') else 'RELIANCE'
            cls.derivatives.append(next(r for r in cls.rows if r.get('exch_seg')=='NFO' and r.get('instrumenttype')==kind and r.get('name')==underlying))

    @classmethod
    def tearDownClass(cls):
        cls.raw=cls.rows=cls.spots=cls.derivatives=None

    def prepare(self,rows=None):
        from instrument_identity import prepare_contract_master
        raw=json.dumps(self.spots+self.derivatives if rows is None else rows).encode()
        return prepare_contract_master(raw,provider='angelone',source_reference='OFFLINE_DERIVED_SUBSET_UNQUALIFIED',
            source_version='NATIVE_FORMAT_TEST',captured_at=self.capture['captured_at'])

    def test_real_public_snapshot_parses_all_four_scoped_types_without_authority_promotion(self):
        from instrument_identity import prepare_contract_master
        result=prepare_contract_master(self.raw,provider='angelone',source_reference='PUBLIC_HTTPS_OBSERVATION_UNATTESTED',
            source_version='20261019',captured_at=self.capture['captured_at'])
        self.assertEqual(result['status'],'BLOCKED_NATIVE_MASTER_AUTHORITY_AND_EFFECTIVE_DATES')
        self.assertEqual(result['observed_record_count'],3059)
        self.assertEqual({r['instrument_type'] for r in result['observed_records']},{'FUTIDX','FUTSTK','OPTIDX','OPTSTK'})
        self.assertFalse(result['eligible'])
        self.assertFalse(result['historical_replay_allowed'])
        self.assertTrue(all(r['valid_from'] is None and r['valid_to'] is None for r in result['observed_records']))

    def test_native_strike_scaling_lot_and_symbol_mismatches_reject(self):
        variants=[]
        for changes in ({'lotsize':'0'},{'lotsize':True},{'strike':'NaN'},{'strike':'1'},{'expiry':'31FEB2026'},
                        {'quantity_unit':'CONTRACTS_UNKNOWN'},{'multiplier':2},{'symbol':'INVALID_LABEL'}):
            rows=copy.deepcopy(self.spots+self.derivatives)
            rows[-1].update(changes)
            variants.append(rows)
        for rows in variants:
            with self.subTest(change=rows[-1]):
                self.assertEqual(self.prepare(rows)['status'],'REJECTED')
        rows=copy.deepcopy(self.spots+self.derivatives)
        rows[2]['strike']='sNaN'
        self.assertEqual(self.prepare(rows)['status'],'REJECTED')

    def test_duplicate_and_ambiguous_native_contracts_reject(self):
        duplicate=copy.deepcopy(self.spots+self.derivatives)
        duplicate.append(copy.deepcopy(duplicate[-1]))
        self.assertEqual(self.prepare(duplicate)['validation']['reason_code'],'CONFLICTING_IDENTIFIER')
        duplicate[-1]['token']='987654321'
        self.assertEqual(self.prepare(duplicate)['validation']['reason_code'],'AMBIGUOUS_CONTRACT')

    def test_native_call_put_pair_with_conflicting_lots_rejects(self):
        selected=self.derivatives[2]
        counterpart=copy.deepcopy(next(r for r in self.rows if r.get('exch_seg')=='NFO' and
            r.get('instrumenttype')=='OPTIDX' and r.get('name')==selected['name'] and r.get('expiry')==selected['expiry']
            and r.get('strike')==selected['strike'] and r.get('symbol','')[-2:]!=selected['symbol'][-2:]))
        counterpart['lotsize']=str(int(counterpart['lotsize'])+1)
        result=self.prepare(copy.deepcopy(self.spots+self.derivatives)+[counterpart])
        self.assertEqual(result['validation']['reason_code'],'CONFLICTING_OPTION_PAIR')

    def test_rollover_requires_exact_expiry_stale_capture_and_expired_contract_reject(self):
        from instrument_identity import resolve_contract_identity
        rows=copy.deepcopy(self.spots+self.derivatives)
        alternative=next(r for r in self.rows if r.get('exch_seg')=='NFO' and r.get('instrumenttype')=='FUTIDX' and r.get('name')=='NIFTY' and r['expiry']!=self.derivatives[0]['expiry'])
        rows.append(alternative)
        master=self.prepare(rows)
        scope=dict(provider='angelone',instrument_type='FUTIDX',underlying='NIFTY',as_of='2026-10-19')
        self.assertEqual(resolve_contract_identity(master,**scope)['status'],'AMBIGUOUS_CONTRACT')
        chosen=resolve_contract_identity(master,**scope,identifier=self.derivatives[0]['token'])
        self.assertFalse(chosen['eligible'])
        self.assertIn('observed_contract',chosen)
        self.assertIsNone(chosen['identity'])
        self.assertEqual(resolve_contract_identity(master,**dict(scope,as_of='2026-10-20'))['status'],'STALE_OR_UNDATED_NATIVE_CAPTURE')
        expired=copy.deepcopy(self.spots+self.derivatives)
        expired[2].update(expiry='01OCT2026',symbol='NIFTY01OCT26FUT')
        self.assertEqual(resolve_contract_identity(self.prepare(expired),**scope)['status'],'EXPIRED_CONTRACT')

    def test_native_candidate_uses_existing_store_and_rejects_persisted_tamper(self):
        from storage import SQLitePersistenceStore
        from instrument_identity import IdentityValidationError
        store=SQLitePersistenceStore(':memory:')
        self.addCleanup(store.close)
        master=store.ingest_contract_master_bytes(json.dumps(self.spots+self.derivatives).encode(),provider='angelone',
            source_reference='OFFLINE_DERIVED_SUBSET_UNQUALIFIED',source_version='NATIVE_FORMAT_TEST',captured_at=self.capture['captured_at'])
        self.assertEqual(store.get_contract_master_candidate(master['master_id']),master)
        changed=copy.deepcopy(master)
        changed['observed_records'][0]['lot_size']+=1
        with store.paper_transaction() as conn:
            conn.execute('UPDATE contract_master_candidates SET candidate_json=? WHERE master_id=?',(_encode(changed),master['master_id']))
        with self.assertRaises(IdentityValidationError):
            store.get_contract_master_candidate(master['master_id'])

    def test_preexisting_rejected_native_candidate_keeps_its_parser_identity(self):
        from instrument_identity import prepare_contract_master,CONTRACT_MASTER_PARSER_VERSION
        from storage import SQLitePersistenceStore
        raw=json.dumps(self.spots+self.derivatives).encode()
        scope=dict(provider='angelone',source_reference='LEGACY_OFFLINE_NATIVE_SUBSET',source_version='LEGACY_TEST',
                   captured_at=self.capture['captured_at'])
        legacy=prepare_contract_master(raw,**scope,parser_version=CONTRACT_MASTER_PARSER_VERSION)
        self.assertEqual(legacy['status'],'REJECTED')
        retained=dict(legacy);retained.pop('original_bytes')
        store=SQLitePersistenceStore(':memory:')
        self.addCleanup(store.close)
        with store.paper_transaction() as conn:
            conn.execute('INSERT INTO contract_master_candidates VALUES(?,?,?,?)',
                         (legacy['master_id'],'angelone',raw,_encode(retained)))
        self.assertEqual(store.get_contract_master_candidate(legacy['master_id']),retained)
        observed=store.ingest_contract_master_bytes(raw,**scope)
        self.assertNotEqual(observed['master_id'],legacy['master_id'])
        self.assertEqual(observed['metadata']['parser_version'],'angel-native-observation-v1')
        self.assertFalse(observed['eligible'])
        self.assertEqual(store.get_contract_master_candidate(legacy['master_id']),retained)


class TestFrozenResearchAndSourceBindings(unittest.TestCase):
    def setUp(self):
        from test_phase5a_provenance import TestPhase5AHistoricalProvenance
        self.f=TestPhase5AHistoricalProvenance()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.archive=self.f._ingest(provider='upstox')
        self.bars=[dict(timestamp=f'2026-10-{day:02d} 09:15:00',session_date=f'2026-10-{day:02d}',open=100,high=102,
            low=99,close=101,volume=1000,data_mode='LIVE',is_simulated=False,provider='upstox') for day in (14,15,16)]

    def protocol(self,**changes):
        from research_protocol import StudyProtocol,dataset_digest
        values=dict(provider='upstox',symbol='RELIANCE',instrument_identifier='NSE_EQ|INE002A01018',instrument_archive_id=self.archive['archive_id'],
            dataset_sha256=dataset_digest(self.bars),train_sessions=('2026-10-14',),validation_sessions=('2026-10-15',),
            out_of_sample_sessions=('2026-10-16',),strategy_ids=('strat_1_order_block',),parameters_json='{}')
        values.update(changes)
        return StudyProtocol(**values)

    def engine(self):
        from backtest_engine import DeterministicBacktestEngine
        from config import BotConfig
        return DeterministicBacktestEngine(BotConfig(active_broker='paper_sim',angel_scrip_master_path=''),self.f.store,clock=lambda:self.f.now)

    def test_immutable_chronological_protocol_freezes_dates_costs_and_hash(self):
        protocol=self.protocol()
        self.assertEqual(protocol.protocol_sha256,self.protocol().protocol_sha256)
        self.assertEqual([phase for phase,_ in protocol.phases()],['TRAIN','VALIDATION','OUT_OF_SAMPLE'])
        for changes in (dict(train_sessions=('2026-10-14','2026-10-15')),
                        dict(validation_sessions=('2026-10-16',)),dict(out_of_sample_sessions=()),
                        dict(strategy_ids=('strat_3_option_apex',)),dict(parameters_json='{"evaluation_start_date":"2026-10-14"}')):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.protocol(**changes)

    def test_unqualified_history_never_runs_evaluator_or_reports_profitability(self):
        from research_protocol import run_qualified_study
        engine=self.engine()
        with patch.object(engine,'run_backtest',side_effect=AssertionError('Source gate must precede evaluation')) as run:
            result=run_qualified_study(engine,self.protocol(),self.bars)
        run.assert_not_called()
        self.assertEqual(result['status'],'BLOCKED_EXTERNAL_DEPENDENCY')
        self.assertEqual(result['signal_quality_status'],'NOT_TESTED')
        self.assertEqual(result['results'],[])

    def test_mocked_orchestration_bounds_prefixes_dates_and_frozen_cost_scenarios(self):
        # MOCKED CONTROL FLOW ONLY: these mocks cannot demonstrate accepted source
        # evidence or a successful real historical evaluation.
        from research_protocol import run_qualified_study
        engine=self.engine()
        protocol=self.protocol(cost_sensitivity_bps=(10,))
        with patch.object(engine.store,'qualify_instrument_master_archive',return_value={'historical_eligibility':{'allowed':True}}), \
             patch.object(engine,'run_backtest',return_value={'metrics':{'fixture':'MOCKED_NOT_MARKET_EVIDENCE'}}) as run:
            result=run_qualified_study(engine,protocol,self.bars)
        self.assertEqual(len(result['results']),6)
        self.assertEqual(run.call_count,6)
        for index,call in enumerate(run.call_args_list):
            kwargs=call.kwargs;cfg=kwargs['backtest_config']
            group=index//2
            self.assertEqual(len(kwargs['candles']),group+1)
            self.assertEqual(cfg.evaluation_start_date,f'2026-10-{14+group:02d}')
            self.assertEqual(cfg.evaluation_start_date,cfg.evaluation_end_date)
            self.assertEqual(cfg.execution_scope,'HISTORICAL_RESEARCH')
            self.assertEqual(kwargs['instrument_token'],'NSE_EQ|INE002A01018')
            self.assertFalse(kwargs['persist_run'])
        self.assertEqual(protocol.protocol_sha256,self.protocol(cost_sensitivity_bps=(10,)).protocol_sha256)

    def test_tampered_synthetic_mixed_or_missing_study_input_rejects(self):
        from research_protocol import run_qualified_study,dataset_digest
        engine=self.engine()
        bad=copy.deepcopy(self.bars);bad[0]['close']=100
        with self.assertRaises(ValueError):run_qualified_study(engine,self.protocol(),bad)
        for changes in (dict(data_mode='SIMULATED',is_simulated=True),dict(provider='dhan')):
            bad=copy.deepcopy(self.bars);bad[0].update(changes)
            with self.assertRaises(ValueError):
                run_qualified_study(engine,self.protocol(dataset_sha256=dataset_digest(bad)),bad)
        bad=self.bars[:-1]
        with self.assertRaises(ValueError):run_qualified_study(engine,self.protocol(dataset_sha256=dataset_digest(bad)),bad)

    def test_undeclared_intermediate_session_cannot_hide_inside_period_label(self):
        from research_protocol import run_qualified_study,dataset_digest
        bars=copy.deepcopy(self.bars)
        for day in (19,20):bars.append(dict(bars[-1],timestamp=f'2026-10-{day} 09:15:00',session_date=f'2026-10-{day}'))
        protocol=self.protocol(dataset_sha256=dataset_digest(bars),train_sessions=('2026-10-14','2026-10-16'),
                               validation_sessions=('2026-10-19',),out_of_sample_sessions=('2026-10-20',))
        with self.assertRaises(ValueError):run_qualified_study(self.engine(),protocol,bars)

    def test_bundle_verifies_bytes_and_declared_scope_without_source_authority(self):
        from source_qualification import verify_source_bundle_bindings
        archive=self.f.store.get_instrument_master_archive(self.archive['archive_id'],include_original=True)
        raw=archive.pop('original_bytes');candles=_encode(self.bars).encode()
        bundle=dict(schema_version='tradepulse.source-bundle.v1',archive_id=archive['archive_id'],provider='upstox',
            symbol='RELIANCE',identifier='NSE_EQ|INE002A01018',first_date='2026-10-14',last_date='2026-10-16',
            interval_min=5,
            master_original_sha256=hashlib.sha256(raw).hexdigest(),candles_original_sha256=hashlib.sha256(candles).hexdigest())
        scope=dict(provider='upstox',symbol='RELIANCE',identifier='NSE_EQ|INE002A01018',first_date='2026-10-14',last_date='2026-10-16')
        report=verify_source_bundle_bindings(archive,raw,candles,bundle,**scope)
        self.assertEqual(report['status'],'BINDINGS_MATCH_AUTHORITY_BLOCKED')
        self.assertFalse(report['historical_eligibility']['allowed'])
        for changed in (dict(bundle,provider='angelone'),dict(bundle,master_original_sha256='a'*64),
                        dict(bundle,first_date='2026-10-01'),dict(bundle,interval_min=15),dict(bundle,verified=True),dict(bundle,authorization='OFFLINE_FAKE_SECRET')):
            self.assertEqual(verify_source_bundle_bindings(archive,raw,candles,changed,**scope)['status'],'REJECTED')
        self.assertEqual(verify_source_bundle_bindings(archive,raw+b' ',candles,bundle,**scope)['status'],'REJECTED')


class TestPerformanceAcceptanceHarness(unittest.TestCase):
    def test_statistics_omit_unsupported_tail_claims_and_validate_values(self):
        from performance_acceptance import sample_statistics
        self.assertIsNone(sample_statistics([1,2,3])['p95_ms'])
        self.assertEqual(sample_statistics(list(range(1,21)))['p95_ms'],19)
        for values in ([],[True],[float('nan')],[-1]):
            with self.assertRaises(ValueError):sample_statistics(values)

    def test_bounded_actual_offline_benchmark_covers_scanner_paper_and_errors(self):
        from performance_acceptance import run_offline_benchmark
        with self.assertLogs('tradepulse.scanner',level='INFO'):
            result=run_offline_benchmark(samples=3,large_events=100)
        self.assertEqual(result['status'],'OFFLINE_MEASURED')
        self.assertEqual([r['symbols'] for r in result['scanner']],[1,5,15])
        self.assertEqual(result['provider_error_status'],'FAILED')
        self.assertEqual(result['signal_quality'],'NOT_TESTED')
        self.assertFalse(result['sla_accepted'])
        self.assertTrue(result['no_live_transport'])
        self.assertIn('paper.entry',result['timings'])
        self.assertEqual(result['timings']['startup.existing_store']['samples'],3)


if __name__=='__main__':
    unittest.main(verbosity=2)

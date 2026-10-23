"""Point-in-time long index-option replay. No orders, downloads or trust roots.

V1 supports one long CE/PE position, all-or-none observed opening depth, observed
bid/ask bars and modeled adverse tick-rounded fills. Missing exits retain real
reservations in the simulated ledger; no carry, exercise or settlement is invented.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, time, date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import math

from instrument_archive import prepare_archive, resolve_archive_declarations, resolve_archives
from instrument_identity import digest, IdentityValidationError
from strategies import IST, parse_ist_timestamp, format_ist_timestamp, evaluate_option_apex_oi_shift, validate_option_chain_for_strategy

VERSION = "option-execution-v1"
STRATEGY = "strat_3_option_apex_oi"
DELTA = timedelta(minutes=5)


def reject(reason):
    from backtest_engine import BacktestEligibilityError
    raise BacktestEligibilityError(reason, dict(eligible=False,strategy_id=STRATEGY,reason_code=reason))


def number(value, *, zero=False):
    if (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)
            or value<0 or not zero and value==0):
        reject("INVALID_OPTION_NUMBER")
    return value


def timestamp(value):
    # Never apply the legacy convenience parser's naive IST assumption to input.
    if not isinstance(value,str):
        reject("OPTION_TIMESTAMP_REQUIRES_OFFSET")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(IST)
    except ValueError:
        reject("OPTION_TIMESTAMP_REQUIRES_OFFSET")


def decode(raw):
    if not isinstance(raw,str) or not raw or len(raw.encode())>64*1024*1024:
        reject("INVALID_OPTION_DATASET_SIZE")
    def unique(pairs):
        result = {}
        for k,v in pairs:
            if k in result:
                reject("DUPLICATE_OPTION_JSON_KEY")
            result[k] = v
        return result
    try:
        return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:reject("NONFINITE_OPTION_DATA"))
    except (ValueError,TypeError):
        reject("MALFORMED_OPTION_JSON")


def _prepare(engine, request, mode, provider, symbol, config):
    if (not isinstance(request,dict) or request.get("schema_version")!="tradepulse.option-request.v1"
            or set(request)-{"schema_version","master_json","dataset_json","master_manifest","dataset_manifest"}):
        reject("OPTION_EXECUTION_INPUT_REQUIRED")
    dataset = decode(request.get("dataset_json"))
    master_raw = request.get("master_json")
    original_master=decode(master_raw)
    if not isinstance(original_master,dict) or any(not isinstance(r,dict) or r.get("symbol")!=symbol or r.get("underlying")!=symbol
            for r in original_master.get("records",[])):
        reject("OPTION_ALIASES_OR_WRONG_UNDERLYING")
    if (not isinstance(dataset,dict) or dataset.get("schema_version")!="tradepulse.option-observations.v1"
            or dataset.get("data_mode")!=mode or dataset.get("provider")!=provider
            or symbol not in ("NIFTY","BANKNIFTY") or dataset.get("symbol")!=symbol
            or mode not in ("SIMULATED","LIVE") or dataset.get("is_simulated") is not (mode=="SIMULATED")):
        reject("OPTION_DATASET_SCOPE_MISMATCH")
    if config.allow_overnight_carry or config.execution_scope not in (None,"SIMULATED_TEST","HISTORICAL_RESEARCH"):
        reject("UNSUPPORTED_OPTION_EXECUTION_SCOPE")
    if mode=="SIMULATED" and config.execution_scope not in (None,"SIMULATED_TEST"):
        reject("EXECUTION_SCOPE_MODE_MISMATCH")
    if mode=="LIVE" and config.execution_scope!="HISTORICAL_RESEARCH":
        reject("OPTIONS_REQUIRE_QUALIFIED_HISTORICAL_RESEARCH")
    archive = prepare_archive(master_raw.encode(),provider,"option-master.json","OPTION_REQUEST_ORIGINAL_BYTES")
    if archive["status"]!="ELIGIBLE_LOCAL_RESEARCH":
        reject("OPTION_MASTER_DECLARED_COVERAGE_REQUIRED")
    contracts = {}
    for record in archive["records"]:
        if (record["instrument_type"]!="OPTIDX" or record["symbol"]!=symbol
                or not record.get("tick_size") or record["multiplier"]!=1):
            reject("EXACT_OPTION_CONTRACT_REQUIRED")
        contracts[record["identifier"]] = record
    observations = dataset.get("premiums")
    underlying = dataset.get("underlying_candles")
    chains = dataset.get("chains")
    if not isinstance(observations,list) or not observations or not isinstance(underlying,list) or not underlying or not isinstance(chains,list) or not chains:
        reject("MISSING_OPTION_OBSERVATIONS")
    rows, last = {}, {}
    reference = timestamp(engine.clock().isoformat())
    start, end = time.fromisoformat(engine.bot_config.session_start_ist),time.fromisoformat(engine.bot_config.session_end_ist)
    for row in observations:
        identifier = row.get("identifier")
        contract = contracts.get(identifier)
        if not contract or row.get("contract_digest")!=digest(contract):
            reject("OPTION_CONTRACT_MISMATCH")
        stamp, available = timestamp(row.get("timestamp")),timestamp(row.get("available_at"))
        if (available!=stamp+DELTA or available>reference or stamp.weekday()>=5
                or stamp.date().isoformat() in engine.bot_config.configured_holidays
                or not start<=stamp.time()<end or available.time()>end
                or (stamp.hour*60+stamp.minute-start.hour*60-start.minute)%5 or stamp.second or stamp.microsecond
                or not contract["valid_from"]<=stamp.date().isoformat()<=min(contract["valid_to"],contract["expiry"])
                or row.get("is_complete") is not True or row.get("data_mode")!=mode
                or row.get("is_simulated") is not (mode=="SIMULATED")):
            reject("STALE_INCOMPLETE_OR_OUTSIDE_OPTION_SESSION")
        if identifier in last and stamp<=last[identifier]:
            reject("DUPLICATE_OR_OUT_OF_ORDER_OPTION_OBSERVATION")
        last[identifier] = stamp
        for side in ("bid","ask"):
            prices = [number(row.get(side+"_"+field)) for field in ("open","high","low","close")]
            if not prices[2]<=min(prices[0],prices[3])<=max(prices[0],prices[3])<=prices[1]:
                reject("INVALID_OPTION_OHLC")
            if any(Decimal(str(p))%Decimal(str(contract["tick_size"]))!=0 for p in prices):
                reject("OFF_TICK_OPTION_OBSERVATION")
        if any(row["bid_"+field]>row["ask_"+field] for field in ("open","high","low","close")):
            reject("CROSSED_OPTION_SPREAD")
        for field in ("bid_size_units","ask_size_units"):
            if type(row.get(field)) is not int or row[field]<0:
                reject("OPENING_QUOTE_DEPTH_REQUIRED")
        if timestamp(row.get("depth_observed_at"))!=stamp:
            reject("FUTURE_OPTION_LIQUIDITY")
        if type(row.get("volume_units")) is not int or row["volume_units"]<0:
            reject("OPTION_VOLUME_REQUIRED")
        rows[(identifier,stamp)] = row
    previous = None
    for bar in underlying:
        stamp = timestamp(bar.get("timestamp"))
        if (stamp+DELTA>reference or bar.get("is_complete") is not True or bar.get("data_mode")!=mode
                or bar.get("is_simulated") is not (mode=="SIMULATED")
                or not start<=stamp.time()<end or stamp.second or stamp.microsecond
                or (stamp.hour*60+stamp.minute-start.hour*60-start.minute)%5
                or stamp.weekday()>=5 or stamp.date().isoformat() in engine.bot_config.configured_holidays
                or previous is not None and (stamp<=previous or stamp.date()==previous.date() and stamp-previous!=DELTA)):
            reject("INVALID_UNDERLYING_CHRONOLOGY")
        o,h,l,c = [number(bar.get(k)) for k in ("open","high","low","close")]
        number(bar.get("volume"),zero=True)
        if not l<=min(o,c)<=max(o,c)<=h:
            reject("INVALID_UNDERLYING_OHLC")
        previous = stamp
    chain_map = {}
    underlying_ends={timestamp(b["timestamp"])+DELTA for b in underlying}
    for chain in chains:
        known = timestamp(chain.get("known_at"))
        if (known in chain_map or chain.get("data_mode")!=mode or chain.get("symbol")!=symbol
                or chain.get("is_simulated") is not (mode=="SIMULATED")
                or known not in underlying_ends):
            reject("OPTION_CHAIN_SCOPE_OR_DUPLICATE")
        baseline = timestamp(chain.get("baseline_observed_at"))
        from storage import resolve_prior_trading_session_date
        prior = resolve_prior_trading_session_date(known,engine.bot_config.configured_holidays)
        if baseline!=datetime.combine(prior,time(15,30),IST) or chain.get("baseline_kind")!="CLOSING_BASELINE":
            reject("PRIOR_CLOSING_OI_REQUIRED")
        try:
            _,_,strike_row = validate_option_chain_for_strategy(chain)
        except (ValueError,LookupError):
            reject("INVALID_OPTION_CHAIN")
        if number(chain["atm_strike"])!=int(chain["atm_strike"]):
            reject("FRACTIONAL_ATM_NOT_SUPPORTED")
        for side in ("ce","pe"):
            for key in (side+"_oi",side+"_prev_oi"):
                if type(chain["strikes"][0].get(key)) is not int or strike_row[key]<0:
                    reject("OBSERVED_OI_AND_BASELINE_REQUIRED")
            if (type(chain["strikes"][0].get(side+"_oi_change")) is not int
                    or strike_row[side+"_oi_change"]!=strike_row[side+"_oi"]-strike_row[side+"_prev_oi"]):
                reject("OI_BASELINE_CONFLICT")
        if abs(chain["pcr"]-strike_row["pe_oi"]/max(1,strike_row["ce_oi"]))>1e-9 or len(chain["strikes"])!=1:
            reject("V1_REQUIRES_EXACT_PAIRED_ATM_PCR")
        chain_map[known] = chain
    qualification = dict(allowed=False,reason_code="SIMULATED_FIXTURE_NOT_EMPIRICAL_EVIDENCE")
    if mode=="LIVE":
        if dataset.get("evidence_class")=="SYNTHETIC_FIXTURE" or dataset.get("is_simulated") is True:
            reject("SYNTHETIC_DATA_IS_NOT_EXTERNAL_SOURCE_EVIDENCE")
        archive["original_bytes"] = master_raw.encode()
        archive["metadata"]["publisher_manifest_json"] = request.get("master_manifest")
        for contract in contracts.values():
            dates = [stamp.date().isoformat() for identifier,stamp in rows if identifier==contract["identifier"]]
            if not dates:
                reject("MISSING_EXACT_CONTRACT_PREMIUM")
            resolve_archives([archive],provider,symbol,contract["identifier"],"NFO","OPTIDX",min(dates),max(dates),
                contract["lot_size"],trust_config=engine.publisher_trust_config,verification_time=reference)
        from publisher_trust import PublisherTrustVerifier
        if engine.publisher_trust_config is None:
            reject("MISSING_OPERATOR_TRUST_ROOTS")
        result = PublisherTrustVerifier(engine.publisher_trust_config).verify(request.get("dataset_manifest"),
            request["dataset_json"].encode(),verification_time=reference,
            required_scope=dict(provider=provider,exchange="NFO",market_segment="NSE_FO_INDEX",instrument_scope=symbol))
        if not result.allowed:
            reject("OPTION_PREMIUM_SOURCE_"+result.reason_code)
        envelope = decode(request["dataset_manifest"])
        if envelope["artifact_type"]!="option-observations" or envelope["artifact_schema_version"]!=dataset["schema_version"]:
            reject("WRONG_SIGNED_OPTION_ARTIFACT")
        effective_start,effective_end = timestamp(result.effective_from),timestamp(result.effective_until)
        if any(not effective_start<=stamp<stamp+DELTA<=effective_end for _,stamp in rows):
            reject("PREMIUM_DATES_OUTSIDE_SIGNED_COVERAGE")
        qualification = result.as_dict()
    return dataset,archive,contracts,rows,chain_map,qualification


def gate(engine, request, mode, provider, symbol, config):
    try:
        *_,qualification = _prepare(engine,request,mode,provider,symbol,config)
        return dict(allowed=True,reason_code="SIMULATED_OPTION_MECHANICS_ONLY" if mode=="SIMULATED" else "SIGNED_OPTION_RESEARCH_INPUTS",
                    source_qualification=qualification,execution_scope="SIMULATED_TEST" if mode=="SIMULATED" else "HISTORICAL_RESEARCH")
    except (IdentityValidationError,KeyError,TypeError,ValueError,AttributeError) as exc:
        return dict(allowed=False,reason_code=getattr(exc,"rejection",{}).get("reason_code","INVALID_OPTION_INPUT"))
    except Exception as exc:
        from backtest_engine import BacktestEligibilityError
        if isinstance(exc,BacktestEligibilityError):
            return dict(allowed=False,**exc.details)
        raise


def run(engine, request, config, symbol, provider, mode, persist=False):
    from backtest_engine import compute_backtest_metrics
    admission = gate(engine,request,mode,provider,symbol,config)
    if not admission["allowed"]:
        reject(admission["reason_code"])
    dataset,archive,contracts,rows,chains,qualification = _prepare(engine,request,mode,provider,symbol,config)
    cost = deepcopy(config.cost_model)
    # Spread/slippage/tick adjustments enter effective fills exactly once.
    slip = cost.slippage_bps_per_leg/10000
    cost.slippage_bps_per_leg = 0
    def tick_level(value,contract,up):
        tick = Decimal(str(contract["tick_size"]))
        return float((Decimal(str(value))/tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*tick)
    def fill(value,contract,buy):
        adjusted=Decimal(str(value))*(1+Decimal(str(slip)) if buy else 1-Decimal(str(slip)))
        return tick_level(adjusted,contract,buy)
    def charges(entry,exit,qty):
        return cost.compute_trade_costs(entry,exit,qty,"LONG",segment="NSE_FO_INDEX",instrument_type="OPTIDX",exchange="NFO")["charges_inr"]
    cash, pending, position = float(config.starting_capital_inr),None,None
    trades,rejected,events,marks,unresolved = [],[],[],[],[]
    sessions, daily = set(),{}
    for index,bar in enumerate(dataset["underlying_candles"]):
        stamp = timestamp(bar["timestamp"])
        day = stamp.date().isoformat()
        if config.evaluation_start_date and day<config.evaluation_start_date or config.evaluation_end_date and day>config.evaluation_end_date:
            continue
        sessions.add(day)
        daily.setdefault(day,0.0)
        if position and stamp.date()!=position["entry_dt"].date():
            unresolved.append("MISSING_REQUIRED_EOD_OBSERVATION")
            break
        if pending:
            signal,contract,known = pending
            pending = None
            row = rows.get((contract["identifier"],stamp))
            if (stamp!=known or not row or stamp.time()>=time.fromisoformat(config.last_entry_Cutoff_ist)):
                rejected.append(dict(reason="NEXT_ELIGIBLE_OPTION_OPEN_MISSING",timestamp=stamp.isoformat()))
            else:
                entry = fill(row["ask_open"],contract,True)
                stop = tick_level(signal.stop_loss,contract,True)
                target = tick_level(signal.target_1 if config.target_mode=="TARGET_1" else signal.target_2,contract,True)
                lot = contract["lot_size"]
                qty = int(min(cash/entry,cash*config.risk_per_trade_pct/100/max(entry-stop,0.01))//lot)*lot
                while qty>0 and (qty*(entry-stop)+charges(entry,stop,qty)>cash*config.risk_per_trade_pct/100
                                  or qty*entry+charges(entry,stop,qty)>cash):
                    qty-=lot
                reason = ("INVALID_NEXT_OPEN_STOP_TARGET" if not 0<stop<entry<target else
                          "RISK_OR_CAPITAL_INSUFFICIENT" if not qty else
                          "INSUFFICIENT_OBSERVED_OPENING_LIQUIDITY" if qty>row["ask_size_units"] else None)
                if reason:
                    rejected.append(dict(reason=reason,timestamp=stamp.isoformat()))
                else:
                    reserved = round(qty*entry,2)
                    cash = round(cash-reserved,2)
                    position = dict(contract=contract,quantity=qty,entry=entry,raw_entry=row["ask_open"],
                        entry_dt=stamp,known_at=known,stop=stop,target=target,reserved=reserved,
                        fees_reserve=charges(entry,stop,qty),signal=signal.to_dict(),last=stamp)
                    events.append(dict(kind="ENTRY",timestamp=stamp.isoformat(),reserved_inr=reserved,quantity=qty))
        if position:
            p = position
            contract = p["contract"]
            row = rows.get((contract["identifier"],stamp))
            if not row or stamp>p["last"]+DELTA:
                unresolved.append("MISSING_POSITION_PREMIUM_NO_FORWARD_FILL")
                break
            p["last"] = stamp
            # Opening quote depth is only used for opening fills. Intrabar
            # stop/limit liquidity is not inferred from full-bar volume.
            exit_price,reason = None,None
            if stamp>p["entry_dt"] and row["bid_open"]<=p["stop"]:
                exit_price,reason=row["bid_open"],"GAP_THROUGH_STOP"
            elif row["bid_low"]<=p["stop"]:
                # Unknown intrabar depth: retain an unresolved position rather
                # than inventing a stop fill at an unobserved liquid price.
                unresolved.append("INTRABAR_STOP_REQUIRES_OBSERVED_EXECUTABLE_QUOTE")
                break
            elif stamp>p["entry_dt"] and row["bid_open"]>=p["target"]:
                exit_price,reason=p["target"],"TARGET_AT_OBSERVED_OPEN"
            elif stamp.time()>=time.fromisoformat(config.eod_square_off_ist):
                exit_price,reason=row["bid_open"],"EXPIRY_PRE_CLOSE" if day==contract["expiry"] else "EOD_AT_OBSERVED_OPEN"
            if exit_price is not None:
                if row["bid_size_units"]<p["quantity"]:
                    unresolved.append("EXIT_LIQUIDITY_UNAVAILABLE_NO_PARTIAL_FILL")
                    break
                exit_fill=fill(exit_price,contract,False)
                fees=charges(p["entry"],exit_fill,p["quantity"])
                gross=round((exit_price-p["raw_entry"])*p["quantity"],2)
                slip_cost=round((p["entry"]-p["raw_entry"]+exit_price-exit_fill)*p["quantity"],2)
                net=round(gross-fees-slip_cost,2)
                cash=round(cash+p["reserved"]+net,2)
                daily[day]+=net
                trade=dict(trade_id=digest([p["signal"],p["entry_dt"].isoformat(),stamp.isoformat()]),
                    strategy_id=STRATEGY,symbol=symbol,segment="NSE_FO_INDEX",direction=p["signal"]["direction"],
                    position_side="LONG",instrument_label=contract["identifier"],quantity=p["quantity"],
                    entry_timestamp_ist=p["entry_dt"].isoformat(),exit_timestamp_ist=stamp.isoformat(),
                    signal_known_at=p["known_at"].isoformat(),contract=contract,entry_price=p["entry"],exit_price=exit_fill,
                    raw_entry_ask=p["raw_entry"],raw_exit_bid=row["bid_open"],model_exit_reference=exit_price,
                    reference_classification="OBSERVED_OPEN_BID_CAPPED_AT_MODELED_LIMIT" if reason=="TARGET_AT_OBSERVED_OPEN" else "OBSERVED_OPEN_BID",
                    stop_loss=p["stop"],target_price=p["target"],
                    exit_reason=reason,gross_pnl_inr=gross,net_pnl_inr=net,charges_inr=fees,
                    slippage_inr=slip_cost,total_costs_inr=round(fees+slip_cost,2),r_multiple=round(net/max(0.01,(p["entry"]-p["stop"])*p["quantity"]),6),
                    bars_held=int((stamp-p["entry_dt"])/DELTA)+1,entry_session_date=day,
                    fill_classification="MODELED_EXECUTION_FROM_OBSERVED_BID_ASK" if mode=="LIVE" else "SIMULATED_FIXTURE_EXECUTION",
                    authoritative_margin=False)
                trades.append(trade)
                events.append(dict(kind="EXIT",timestamp=stamp.isoformat(),released_inr=p["reserved"],net_pnl_inr=net))
                position=None
            else:
                marks.append(dict(timestamp=(stamp+DELTA).isoformat(),identifier=contract["identifier"],
                    bid_close=row["bid_close"],unrealized_pnl_inr=round((row["bid_close"]-p["entry"])*p["quantity"],2)))
        known=stamp+DELTA
        chain=chains.get(known)
        if not chain or position or stamp.time()>=time.fromisoformat(config.last_entry_Cutoff_ist):
            continue
        if index+1<15:
            rejected.append(dict(reason="INSUFFICIENT_OPTION_STRATEGY_WARMUP",timestamp=known.isoformat()))
            continue
        if config.max_daily_loss_inr is not None and daily[day]<=-config.max_daily_loss_inr or config.daily_profit_target_inr is not None and daily[day]>=config.daily_profit_target_inr:
            rejected.append(dict(reason="DAILY_PORTFOLIO_LIMIT",timestamp=known.isoformat()))
            continue
        atm,_,strike_row=validate_option_chain_for_strategy(chain)
        paired={}
        for side in ("CE","PE"):
            matching=[c for c in contracts.values() if c["expiry"]==chain.get("expiry") and c["strike"]==atm
                and c["option_type"]==side and c["valid_from"]<=day<=min(c["valid_to"],c["expiry"])]
            if len(matching)!=1:
                reject("AMBIGUOUS_OR_MISSING_EXACT_OPTION_SELECTION")
            c=matching[0]
            row=rows.get((c["identifier"],stamp))
            if not row or strike_row[side.lower()+"_ltp"]!=row["bid_close"]:
                reject("CHAIN_PREMIUM_NOT_BOUND_TO_KNOWN_CONTRACT_BAR")
            paired[side]=c
        if paired["CE"]["lot_size"]!=paired["PE"]["lot_size"]:
            reject("PAIRED_CONTRACT_LOT_CONFLICT")
        sig=evaluate_option_apex_oi_shift(symbol,dataset["underlying_candles"][:index+1],
            dict(chain,is_simulated=mode=="SIMULATED"),lot_size=paired["CE"]["lot_size"],capital_inr=cash,
            risk_pct=config.risk_per_trade_pct,now=known)
        if sig:
            pending=(sig,paired["CE" if sig.position_type=="LONG_CALL_OPTION" else "PE"],known)
    if pending:
        rejected.append(dict(reason="END_OF_DATASET_NO_NEXT_OPTION_OPEN"))
    if position and not unresolved:
        unresolved.append("MISSING_REQUIRED_EOD_OBSERVATION")
    closed_net=round(sum(t["net_pnl_inr"] for t in trades),2)
    reserved=position["reserved"] if position else 0.0
    if round(cash+reserved,2)!=round(config.starting_capital_inr+closed_net,2):
        reject("OPTION_LEDGER_RECONCILIATION_FAILURE")
    assumptions=dict(engine_version=VERSION,strategy_version="option-apex-pit-v1",configuration=asdict(config),
        master_archive_id=archive["archive_id"],master_original_sha256=archive["metadata"]["original_sha256"],
        dataset_sha256=hashlib.sha256(request["dataset_json"].encode()).hexdigest(),source_qualification=qualification,
        execution_model="LONG_PREMIUM_FULL_NOTIONAL_ALL_OR_NONE_OPEN_QUOTES",intrabar_stop_policy="UNRESOLVED_UNTIL_EXECUTABLE_OBSERVATION",
        synthetic_prices_are_observed=False,margin_authority="MODELED_FULL_PREMIUM_ONLY",calendar="CONFIGURED_WEEKDAYS_HOLIDAYS",
        spread="OBSERVED_BID_ASK",slippage="ADVERSE_TICK_ROUNDED_IN_FILL_ONCE",partial_fills="UNSUPPORTED",
        fees="EXISTING_VERSIONED_ESTIMATED_INDIAN_COST_SCHEDULE",excluded_rows=[],settlement="UNSUPPORTED_NO_INVENTED_EXIT")
    checksum=digest(assumptions)
    for trade in trades:
        trade.update(strategy_version="option-apex-pit-v1",exchange="NFO",signal_timestamp=trade["signal_known_at"],
            entry_timestamp=trade["entry_timestamp_ist"],exit_timestamp=trade["exit_timestamp_ist"],
            session_date=trade["entry_session_date"],realized_r_multiple=trade["r_multiple"],
            risk_amount_inr=round((trade["entry_price"]-trade["stop_loss"])*trade["quantity"],2),
            dataset_id=assumptions["dataset_sha256"],dataset_checksum=assumptions["dataset_sha256"],
            data_mode=mode,is_simulated=mode=="SIMULATED",provider=provider,
            cost_breakdown=dict(charges_inr=trade["charges_inr"],slippage_inr=trade["slippage_inr"],
                is_estimated_schedule=True),signal_metadata=dict(contract=trade["contract"],
                master_archive_id=archive["archive_id"],source_qualification=qualification,
                observed_entry_ask=trade["raw_entry_ask"],observed_exit_bid_open=trade["raw_exit_bid"],
                modeled_exit_reference=trade["model_exit_reference"],reference_classification=trade["reference_classification"]))
    metrics=compute_backtest_metrics(trades,config.starting_capital_inr,sorted(sessions),len(dataset["underlying_candles"]),
        rejected_signals=rejected)
    result=dict(run_id="bt_options_"+checksum[:24],engine_version=VERSION,strategy_id=STRATEGY,
        strategy_name="Option Apex OI Shift",strategy_version="option-apex-pit-v1",symbol=symbol,segment="NSE_FO_INDEX",exchange="NFO",
        interval_min=5,dataset_id=assumptions["dataset_sha256"],dataset_checksum=assumptions["dataset_sha256"],
        provider=provider,data_mode=mode,is_simulated=mode=="SIMULATED",period_type=config.period_type,
        from_timestamp_ist=dataset["underlying_candles"][0]["timestamp"],to_timestamp_ist=dataset["underlying_candles"][-1]["timestamp"],
        starting_capital_inr=config.starting_capital_inr,ending_capital_inr=round(cash+reserved,2),
        risk_per_trade_pct=config.risk_per_trade_pct,max_daily_loss_inr=config.max_daily_loss_inr,
        daily_profit_target_inr=config.daily_profit_target_inr,assumptions=assumptions,metrics=metrics,trades=trades,
        rejected_signals=rejected,events=events,marks=marks,unresolved=unresolved,
        ledger=dict(available_cash_inr=cash,reserved_premium_inr=reserved,closed_net_pnl_inr=closed_net,reconciliation="OK"),
        status="UNRESOLVED" if unresolved else "COMPLETED",research_eligible=mode=="LIVE" and not unresolved
            and not any(r["reason"] in ("NEXT_ELIGIBLE_OPTION_OPEN_MISSING","END_OF_DATASET_NO_NEXT_OPTION_OPEN") for r in rejected),
        empirical_performance_claim_allowed=False,current_live_acceptance=False,
        data_acceptance_status=admission["reason_code"],implementation_status="IMPLEMENTED_OFFLINE_ENGINEERING",
        run_label="SIMULATED OPTION FIXTURE" if mode=="SIMULATED" else "SIGNED HISTORICAL INPUTS; EXECUTION/COSTS MODELED",
        created_at_ist=format_ist_timestamp(engine.clock()))
    from historical_study import HistoricalEvidenceArchive, option_request_artifacts, evidence_identity
    original_artifacts = option_request_artifacts(request)
    input_metadata = dict(kind="OPTION_REPLAY_ORIGINAL_INPUTS", provider=provider,
        symbol=symbol,data_mode=mode,master_archive_id=archive["archive_id"])
    result["input_evidence_id"] = evidence_identity(original_artifacts,input_metadata)[0]
    if persist:
        if engine.store is None or unresolved:
            reject("COMPLETED_OPTION_RESULT_AND_STORE_REQUIRED_FOR_PERSISTENCE")
        HistoricalEvidenceArchive(engine.store).retain(original_artifacts,input_metadata)
        # Persistence is receipt state, not part of deterministic replay output.
        engine.store.save_backtest_run(result,trades)
    return result

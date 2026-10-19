"""Frozen chronological study orchestration. No network or source-policy override.

Real signal-quality results require the existing independent source qualification
and engine gates. A local protocol/hash is reproducibility evidence, never a
publisher credential. This module cannot issue receipts or enable Strategy 3.
"""
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date

from backtest_engine import BacktestConfig, DeterministicBacktestEngine, IndianCostModel


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def dataset_digest(candles):
    return hashlib.sha256(canonical(candles).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class StudyProtocol:
    provider: str
    symbol: str
    instrument_identifier: str
    instrument_archive_id: str
    dataset_sha256: str
    train_sessions: tuple
    validation_sessions: tuple
    out_of_sample_sessions: tuple
    strategy_ids: tuple
    parameters_json: str
    cost_sensitivity_bps: tuple = ()

    def __post_init__(self):
        import re
        if self.provider not in ('angelone','upstox','dhan') or not self.symbol:
            raise ValueError('Explicit real-provider and instrument scope required.')
        from instrument_identity import spot_identity
        field={'angelone':'angel_token','upstox':'upstox_key','dhan':'dhan_id'}[self.provider]
        spot_identity(dict(symbol=self.symbol,**{field:self.instrument_identifier}),self.provider)
        if not re.fullmatch(r'[a-f0-9]{64}',self.dataset_sha256) or not self.instrument_archive_id:
            raise ValueError('Frozen dataset and retained archive identity required.')
        groups=[]
        for name in ('train_sessions','validation_sessions','out_of_sample_sessions'):
            group=tuple(getattr(self,name))
            if not group or len(group)>10000 or tuple(sorted(set(group)))!=group:
                raise ValueError('Session groups must be nonempty, unique and chronological.')
            for day in group:
                if date.fromisoformat(day).isoformat()!=day:
                    raise ValueError('Canonical session dates required.')
            object.__setattr__(self,name,group)
            groups.append(group)
        if not groups[0][-1]<groups[1][0] or not groups[1][-1]<groups[2][0]:
            raise ValueError('Train, validation and out-of-sample periods must be disjoint and chronological.')
        supported={'strat_1_order_block','strat_2_vwap_pullback','strat_4_orb_filtered','strat_5_supertrend_pullback'}
        strategies=tuple(self.strategy_ids)
        if not strategies or len(set(strategies))!=len(strategies) or any(s not in supported for s in strategies):
            raise ValueError('Only implemented historical cash strategies are eligible; Strategy 3 remains blocked.')
        object.__setattr__(self,'strategy_ids',strategies)
        scenarios=tuple(self.cost_sensitivity_bps)
        if (len(scenarios)>5 or len(set(scenarios))!=len(scenarios) or any(isinstance(v,bool) or
                not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1000 for v in scenarios)):
            raise ValueError('Cost sensitivities must be explicit, finite, unique and bounded.')
        object.__setattr__(self,'cost_sensitivity_bps',scenarios)
        parameters=json.loads(self.parameters_json)
        if not isinstance(parameters,dict) or any(parameters.get(k) for k in ('evaluation_start_date','evaluation_end_date')):
            raise ValueError('The protocol, not a caller label, supplies study date ranges.')
        config=self._config(parameters)
        config.validate()
        if config.instrument_type!='EQ' or config.historical_instrument_identity is not None:
            raise ValueError('Initial study scope is archived cash identity only.')
        if (config.period_type!='FULL' or config.execution_scope not in (None,'HISTORICAL_RESEARCH')
                or config.historical_instrument_archive_id not in (None,self.instrument_archive_id)):
            raise ValueError('Protocol scope and frozen engine parameters disagree.')
        object.__setattr__(self,'parameters_json',canonical(asdict(config)))

    @staticmethod
    def _config(parameters):
        values=dict(parameters)
        values['cost_model']=IndianCostModel(**values.get('cost_model',{}))
        return BacktestConfig(**values)

    @property
    def protocol_sha256(self):
        return dataset_digest(asdict(self))

    def phases(self):
        return zip(('TRAIN','VALIDATION','OUT_OF_SAMPLE'),
                   (self.train_sessions,self.validation_sessions,self.out_of_sample_sessions))


def run_qualified_study(engine, protocol, candles):
    """Gate first, then use the real engine with enforced bounds and past warmup.

    No fitting/optimization is implemented. Parameters/costs remain frozen across
    phases. Each phase sees only bars through its last declared session, with
    earlier bars supplied solely for the engine's existing warmup convention.
    """
    if not isinstance(engine,DeterministicBacktestEngine) or not isinstance(protocol,StudyProtocol):
        raise ValueError('Existing historical engine and explicit frozen protocol required.')
    if not isinstance(candles,list) or dataset_digest(candles)!=protocol.dataset_sha256:
        raise ValueError('Frozen dataset digest mismatch.')
    if any(not isinstance(bar,dict) or bar.get('data_mode')!='LIVE' or bar.get('is_simulated') is not False
           or bar.get('provider')!=protocol.provider for bar in candles):
        raise ValueError('Real study input must have explicit, unmixed provider/source provenance.')
    sessions=tuple(sorted({str(bar.get('session_date') or str(bar.get('timestamp',''))[:10]) for bar in candles}))
    declared=protocol.train_sessions+protocol.validation_sessions+protocol.out_of_sample_sessions
    if any(day not in sessions for day in declared):
        raise ValueError('Declared study sessions are missing from the dataset.')
    # A range-based engine must never evaluate undeclared intermediate sessions.
    for _,group in protocol.phases():
        if tuple(day for day in sessions if group[0]<=day<=group[-1])!=group:
            raise ValueError('Declared phases must include every dataset session inside their bounds.')
    base=dict(protocol_sha256=protocol.protocol_sha256,dataset_sha256=protocol.dataset_sha256,
              provider=protocol.provider,symbol=protocol.symbol,signal_quality_status='NOT_TESTED',
              execution_mode='RESEARCH_ONLY',historical_strategy_3_allowed=False)
    if engine.store is None:
        return dict(base,status='BLOCKED_EXTERNAL_DEPENDENCY',reason_code='ARCHIVE_STORE_REQUIRED',results=[])
    qualification=engine.store.qualify_instrument_master_archive(protocol.instrument_archive_id)
    if not qualification['historical_eligibility']['allowed']:
        return dict(base,status='BLOCKED_EXTERNAL_DEPENDENCY',
                    reason_code='HISTORICAL_SOURCE_EVIDENCE_INSUFFICIENT',results=[],
                    missing_evidence=qualification['historical_eligibility']['missing_evidence'])
    output=[]
    for phase,days in protocol.phases():
        prefix=[bar for bar in candles if str(bar.get('session_date') or str(bar.get('timestamp',''))[:10])<=days[-1]]
        for strategy in protocol.strategy_ids:
            for slippage in (None,)+protocol.cost_sensitivity_bps:
                config=protocol._config(json.loads(protocol.parameters_json))
                config.period_type,config.evaluation_start_date,config.evaluation_end_date=phase,days[0],days[-1]
                config.execution_scope='HISTORICAL_RESEARCH'
                config.historical_instrument_archive_id=protocol.instrument_archive_id
                if slippage is not None:
                    config.cost_model.slippage_bps_per_leg=slippage
                config.validate()
                result=engine.run_backtest(strategy,protocol.symbol,candles=prefix,provider=protocol.provider,
                    instrument_token=protocol.instrument_identifier,segment='NSE_EQUITY_INTRADAY',exchange='NSE',interval_min=5,
                    data_mode='LIVE',backtest_config=config,persist_run=False)
                output.append(dict(phase=phase,strategy_id=strategy,start_date=days[0],end_date=days[-1],
                    scenario='BASE' if slippage is None else f'SLIPPAGE_{slippage}_BPS',result=result,
                    baseline=dict(name='NO_TRADE_CASH',net_pnl_inr=0,exposure_inr=0,trades=0,costs_inr=0)))
    return dict(base,status='COMPLETED',signal_quality_status='EVALUATED_QUALIFIED_HISTORY',results=output,
                limitation='Frozen-parameter evaluation; no fitting, empirical calibration or profitability acceptance implied.')

import React from 'react';
import { ModelTrainingIcon } from '../components/common/Icons';
import { StatusBadge } from '../components/common/StatusBadge';

interface StrategyCard {
  id: string;
  name: string;
  category: string;
  warmupBars: number;
  maturity: string;
  isBaseline: boolean;
  summary: string;
}

const STRATEGIES: StrategyCard[] = [
  {
    id: 'strat_1_order_block',
    name: 'Order Block / BOS / FVG',
    category: 'Institutional Market Structure',
    warmupBars: 30,
    maturity: 'OFFLINE_MECHANICS_TESTED',
    isBaseline: true,
    summary: 'Detects impulsive break-of-structure (BOS), unmitigated order blocks, and fair value gaps (FVG) in completed 5m candles.',
  },
  {
    id: 'strat_2_vwap_pullback',
    name: 'VWAP Pullback',
    category: 'Mean Reversion & Value',
    warmupBars: 35,
    maturity: 'OFFLINE_MECHANICS_TESTED',
    isBaseline: true,
    summary: 'Requires confirmed 09:15 IST opening candle. Validates intraday mean reversion entries toward volume-weighted average price.',
  },
  {
    id: 'strat_3_option_apex_oi',
    name: 'Option Apex OI Shift',
    category: 'Derivatives Open Interest',
    warmupBars: 1,
    maturity: 'OFFLINE_MECHANICS_TESTED',
    isBaseline: true,
    summary: 'Evaluates strike-level intraday call/put OI shifts and PCR trends. Prospective forward premium execution remains in gated research.',
  },
  {
    id: 'strat_4_orb_filtered',
    name: 'Opening Range Breakout',
    category: 'Volatility Breakout',
    warmupBars: 30,
    maturity: 'OFFLINE_MECHANICS_TESTED',
    isBaseline: true,
    summary: 'Defines opening range boundaries with relative volume and ATR filters. Avoids low-volatility false breakouts.',
  },
  {
    id: 'strat_5_supertrend_pullback',
    name: 'Supertrend Pullback',
    category: 'Trend Following',
    warmupBars: 200,
    maturity: 'OFFLINE_MECHANICS_TESTED',
    isBaseline: true,
    summary: 'Long-period volatility envelope tracking. Evaluates pullbacks to dynamic support/resistance with no trailing mutation.',
  },
  {
    id: 'strat_research_volume_breakout',
    name: 'Volume Expansion Breakout',
    category: 'Stage 1 Research Candidate',
    warmupBars: 50,
    maturity: 'RESEARCH_DISABLED',
    isBaseline: false,
    summary: 'RVOL + multi-candle consolidation expansion. Disabled in V1 terminal pending empirical out-of-sample audit.',
  },
  {
    id: 'strat_research_volume_retest',
    name: 'Volume Retest',
    category: 'Stage 1 Research Candidate',
    warmupBars: 50,
    maturity: 'RESEARCH_DISABLED',
    isBaseline: false,
    summary: 'Post-breakout low-volume retest validation. Disabled in V1 terminal pending empirical out-of-sample audit.',
  },
];

export const StrategiesView: React.FC = () => {
  return (
    <div className="p-space-md md:p-space-lg flex flex-col gap-space-md select-none">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between pb-space-xs border-b border-outline-variant/30 gap-space-sm">
        <div>
          <h2 className="font-headline-lg text-headline-lg font-bold text-on-surface flex items-center gap-2">
            <ModelTrainingIcon size={20} className="text-primary" />
            <span>Strategies & Research</span>
          </h2>
          <p className="font-body-sm text-body-sm text-on-surface-variant">
            Know the rules · Understand setup definitions, warmup requirements, and empirical limits
          </p>
        </div>

        <div className="flex items-center gap-space-sm font-mono text-xs">
          <StatusBadge variant="NEUTRAL" label="5 BASELINE · 2 RESEARCH" />
        </div>
      </div>

      {/* Grid of Strategy Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-space-md">
        {STRATEGIES.map((strat) => (
          <article
            key={strat.id}
            className={`rounded-xl border p-space-md flex flex-col justify-between shadow-sm ${
              strat.isBaseline
                ? 'bg-surface-container-low border-outline-variant/40'
                : 'bg-surface-container-lowest border-outline-variant/20 opacity-80'
            }`}
          >
            <div>
              <div className="flex items-center justify-between pb-space-xs mb-space-xs border-b border-outline-variant/30">
                <span className="text-[10px] font-mono uppercase text-outline">
                  {strat.category}
                </span>
                <StatusBadge
                  variant={strat.isBaseline ? 'QUALIFIED' : 'RADAR'}
                  label={strat.isBaseline ? 'BASELINE' : 'DISABLED'}
                />
              </div>

              <h3 className="font-headline-md text-headline-md font-bold text-on-surface mt-1">
                {strat.name}
              </h3>

              <div className="font-mono text-[11px] text-primary mt-0.5">
                {strat.id}
              </div>

              <p className="font-body-sm text-xs text-on-surface-variant mt-2 leading-relaxed">
                {strat.summary}
              </p>
            </div>

            <div className="mt-space-md pt-space-xs border-t border-outline-variant/20 font-mono text-[11px] text-outline flex items-center justify-between">
              <span>Warmup: {strat.warmupBars} bars (5m)</span>
              <span className="text-on-surface font-semibold">{strat.maturity}</span>
            </div>
          </article>
        ))}
      </div>

      {/* Scientific Transparency Notice */}
      <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 text-xs font-mono text-outline leading-relaxed">
        <strong>Integrity Safeguard:</strong> Setup quality scores represent deterministic indicator evaluations out of 100, NOT a statistical probability of profit. All research algorithms remain strictly disabled until explicit out-of-sample verification.
      </div>
    </div>
  );
};

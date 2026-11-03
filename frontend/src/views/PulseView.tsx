import React from 'react';
import { useTerminal, STRATEGY_NAMES } from '../context/TerminalContext';
import { StatusBadge } from '../components/common/StatusBadge';
import { ShieldIcon, SyncIcon, RadarIcon, ScheduleIcon, VerifiedIcon } from '../components/common/Icons';
import { formatInr, formatIstTime, formatInrCurrency } from '../utils/time';
import type { RankingRow } from '../types/api';

export const PulseView: React.FC = () => {
  const {
    ranks,
    rankingRows,
    rankingUiState,
    rankingMessage,
    health,
    paperPortfolio,
    filterQuery,
    selectCandidate,
    setRoute,
    refreshData,
    isRefreshing,
  } = useTerminal();

  // Filter rows by global search if present
  const qualifiedRows = rankingRows.filter((r) =>
    !filterQuery || r.symbol.toLowerCase().includes(filterQuery.toLowerCase())
  );

  const topThree = qualifiedRows.slice(0, 3);
  const isCurrent = rankingUiState === 'CURRENT' && qualifiedRows.length > 0;
  const snapshot = ranks?.snapshot;

  const getRankReason = (r: RankingRow) => {
    switch (r.rank_change_reason) {
      case 'NEWLY_QUALIFIED':
        return 'Newly qualified in the latest retained scan.';
      case 'SCORE_COMPONENT_CHANGED':
        return 'Its measured setup inputs changed.';
      case 'RELATIVE_ORDER_CHANGED':
        return 'Other qualified candidates changed order.';
      case 'UNCHANGED_PRIORITY':
        return 'Priority is unchanged from the previous snapshot.';
      default:
        return 'Priority follows retained rule quality and gross reward/risk.';
    }
  };

  return (
    <div className="flex flex-col w-full select-none">
      {/* Top Protocol Strip */}
      <div className="w-full bg-surface-container-lowest px-space-md md:px-space-lg py-space-sm border-b border-outline-variant/30 flex flex-wrap items-center justify-between gap-space-sm">
        <div className="flex items-center gap-space-sm min-w-0">
          <ShieldIcon size={18} className="text-tertiary shrink-0" />
          <StatusBadge variant="SYNTHETIC_DEMO" label="MANDATORY PROTOCOL" />
          <span className="font-mono text-label-numeric-sm text-on-surface truncate">
            SYNTHETIC DEMO ONLY · Research & Paper V1 Terminal · Deterministic Quality Ranking
          </span>
        </div>
        <div className="flex items-center gap-space-md font-mono text-label-numeric-sm text-outline">
          <span className="hidden sm:inline">ENGINE: DETERMINISTIC PIPELINE</span>
          <button
            type="button"
            onClick={() => refreshData()}
            disabled={isRefreshing}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-surface-container hover:bg-surface-bright text-primary transition-colors disabled:opacity-50"
          >
            <SyncIcon size={13} className={isRefreshing ? 'animate-spin' : ''} />
            <span>GET Snapshot</span>
          </button>
        </div>
      </div>

      <div className="p-space-md md:p-space-lg flex flex-col gap-space-lg">
        {/* KPI Metrics Strip */}
        <section aria-label="Terminal Quantitative Coverage" className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-space-sm">
          {/* 1. Qualified Setups */}
          <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col justify-between border border-outline-variant/30">
            <div className="flex items-center justify-between">
              <span className="font-label-badge text-label-badge text-outline uppercase tracking-wider">
                Setups Validated
              </span>
              <span className={`w-2 h-2 rounded-full ${rankingRows.length > 0 ? 'bg-primary-container' : 'bg-outline'}`} />
            </div>
            <div className="mt-space-sm flex items-baseline gap-space-xs">
              <span className="font-headline-xl text-headline-xl text-primary font-bold font-mono">
                {rankingRows.length}
              </span>
              <span className="font-label-numeric-sm text-label-numeric-sm text-on-surface-variant">
                Qualified Setups
              </span>
            </div>
            <span className="mt-1 font-label-numeric-sm text-label-numeric-sm text-outline">
              Deterministic Pass
            </span>
          </div>

          {/* 2. Surveillance / Radar */}
          <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col justify-between border border-outline-variant/30">
            <div className="flex items-center justify-between">
              <span className="font-label-badge text-label-badge text-outline uppercase tracking-wider">
                Surveillance Feed
              </span>
              <span className="w-2 h-2 rounded-full bg-tertiary" />
            </div>
            <div className="mt-space-sm flex items-baseline gap-space-xs">
              <span className="font-headline-xl text-headline-xl text-tertiary font-bold font-mono">
                0
              </span>
              <span className="font-label-numeric-sm text-label-numeric-sm text-on-surface-variant">
                Radar / Developing
              </span>
            </div>
            <span className="mt-1 font-label-numeric-sm text-label-numeric-sm text-outline">
              Not Actionable (No Feed)
            </span>
          </div>

          {/* 3. Scope Coverage */}
          <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col justify-between border border-outline-variant/30">
            <div className="flex items-center justify-between">
              <span className="font-label-badge text-label-badge text-outline uppercase tracking-wider">
                Scope Coverage
              </span>
              <RadarIcon size={16} className="text-outline" />
            </div>
            <div className="mt-space-sm flex items-baseline gap-space-xs">
              <span className="font-headline-xl text-headline-xl text-on-surface font-bold font-mono">
                {snapshot ? '198' : '—'}
              </span>
              <span className="font-label-numeric-sm text-label-numeric-sm text-outline">
                / NIFTY 200
              </span>
            </div>
            <span className="mt-1 font-label-numeric-sm text-label-numeric-sm text-outline">
              Cash Watchlist
            </span>
          </div>

          {/* 4. Snapshot Sync */}
          <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col justify-between border border-outline-variant/30">
            <div className="flex items-center justify-between">
              <span className="font-label-badge text-label-badge text-outline uppercase tracking-wider">
                Snapshot Sync
              </span>
              <ScheduleIcon size={16} className="text-primary" />
            </div>
            <div className="mt-space-sm flex flex-col">
              <span className="font-label-numeric-lg text-label-numeric-lg text-on-surface font-bold font-mono">
                {snapshot?.reference ? formatIstTime(snapshot.reference) : '—'}
              </span>
              <span className="font-label-numeric-sm text-label-numeric-sm text-outline font-mono truncate">
                {snapshot?.run_id ? `#${snapshot.run_id}` : 'No scan run'}
              </span>
            </div>
            <span className="mt-1 font-label-numeric-sm text-label-numeric-sm text-primary">
              Retained Evidence
            </span>
          </div>

          {/* 5. Data Pipeline */}
          <div className="bg-surface-container-low p-space-md rounded-lg flex flex-col justify-between border border-outline-variant/30 col-span-2 md:col-span-1">
            <div className="flex items-center justify-between">
              <span className="font-label-badge text-label-badge text-outline uppercase tracking-wider">
                Data Pipeline
              </span>
              <VerifiedIcon size={16} className="text-primary-container" />
            </div>
            <div className="mt-space-sm flex items-baseline gap-space-xs">
              <span className="font-headline-xl text-headline-xl text-on-surface font-bold font-mono">
                {snapshot ? '100%' : '0%'}
              </span>
              <span className="font-label-numeric-sm text-label-numeric-sm text-outline">
                Retained
              </span>
            </div>
            <span className="mt-1 font-label-numeric-sm text-label-numeric-sm text-primary font-mono text-xs">
              {rankingUiState}
            </span>
          </div>
        </section>

        {/* Section Heading */}
        <div className="flex items-center justify-between border-b border-outline-variant/30 pb-space-xs">
          <div>
            <h2 className="font-headline-lg text-headline-lg font-bold text-on-surface">
              The Opportunity Shortlist
            </h2>
            <p className="font-body-sm text-body-sm text-on-surface-variant">
              Qualified candidate evidence · never an automatic entry instruction
            </p>
          </div>
          <button
            type="button"
            onClick={() => setRoute('opportunities')}
            className="text-primary hover:underline font-label-numeric-sm text-label-numeric-sm flex items-center gap-1"
          >
            <span>View all ({rankingRows.length}) →</span>
          </button>
        </div>

        {/* Qualified Candidates or Waiting State */}
        {isCurrent ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-space-md">
            {topThree.map((candidate) => {
              const strategyName = STRATEGY_NAMES[candidate.strategy_id] || candidate.strategy_id;
              const ruleQuality = candidate.score_components?.rule_quality;
              const actualRr = candidate.score_components?.actual_target1_rr;

              return (
                <article
                  key={candidate.opportunity_key}
                  className="bg-surface-container-low rounded-xl border border-outline-variant/40 p-space-md flex flex-col justify-between hover:border-primary/50 transition-colors shadow-sm"
                >
                  <div>
                    <div className="flex items-center justify-between pb-space-xs mb-space-xs border-b border-outline-variant/30">
                      <span className="font-mono text-xs text-primary font-bold">
                        #{candidate.rank} PRIORITY
                      </span>
                      <StatusBadge
                        variant={candidate.direction === 'LONG' ? 'LONG' : 'SHORT'}
                        label={candidate.direction}
                      />
                    </div>

                    <h3 className="font-headline-md text-headline-md text-on-surface font-bold tracking-tight">
                      {candidate.symbol}
                    </h3>

                    <p className="font-body-sm text-body-sm text-on-surface-variant font-medium mt-0.5">
                      {strategyName}
                    </p>

                    <p className="font-body-sm text-xs text-outline mt-1 italic">
                      {getRankReason(candidate)}
                    </p>

                    <div className="grid grid-cols-2 gap-space-xs my-space-sm p-space-sm bg-surface-container-lowest rounded border border-outline-variant/30 font-mono">
                      <div>
                        <div className="text-[10px] text-outline uppercase">Setup Quality</div>
                        <div className="text-sm font-bold text-primary">
                          {formatInr(ruleQuality)}
                          <span className="text-[10px] text-outline font-normal"> / 100</span>
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-outline uppercase">Gross T1 R:R</div>
                        <div className="text-sm font-bold text-on-surface">
                          1:{formatInr(actualRr)}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="font-mono text-[11px] text-outline pb-space-xs">
                      Candle watermark: {formatIstTime(candidate.source_data_watermark)}
                    </div>

                    <button
                      type="button"
                      onClick={() => {
                        selectCandidate(candidate);
                        setRoute('opportunities');
                      }}
                      className="w-full py-1.5 px-space-sm rounded bg-surface-container-high hover:bg-surface-bright text-primary border border-outline-variant/40 font-label-numeric-sm text-label-numeric-sm font-semibold transition-colors flex items-center justify-center gap-1"
                    >
                      <span>Explore evidence ↗</span>
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="bg-surface-container-low border border-outline-variant/40 rounded-xl p-space-lg flex flex-col md:flex-row items-center justify-between gap-space-lg">
            <div className="max-w-xl">
              <StatusBadge
                variant="CAUTION"
                label={
                  filterQuery
                    ? 'SEARCH RESULTS'
                    : rankingUiState === 'EMPTY'
                    ? 'NO QUALIFIED SETUPS'
                    : health
                    ? 'WAITING FOR QUALIFIED EVIDENCE'
                    : 'NO SOURCE'
                }
              />
              <h3 className="font-headline-lg text-headline-lg font-bold text-on-surface mt-space-sm">
                {filterQuery
                  ? 'No qualified match for this search.'
                  : rankingUiState === 'EMPTY'
                  ? 'Patience is a position, too.'
                  : health
                  ? 'A clear signal starts with clear evidence.'
                  : 'Your market view is waiting for a source.'}
              </h3>
              <p className="font-body-md text-body-md text-on-surface-variant mt-space-xs">
                {filterQuery
                  ? 'Search filters only the retained qualified candidates in this snapshot. It does not broaden the watchlist or acquire unverified instruments.'
                  : rankingUiState === 'EMPTY'
                  ? 'The latest stored scan has no qualifying candidate. Nothing is promoted just to fill this space. Review strategy rules or inspect source status.'
                  : rankingMessage || 'Current candidate priority is unavailable. Inspect source health before interpreting setups.'}
              </p>
              <div className="flex items-center gap-space-sm mt-space-md">
                <button
                  type="button"
                  onClick={() => setRoute('health')}
                  className="px-3 py-1.5 rounded bg-primary-container text-on-primary-container font-label-numeric-sm text-label-numeric-sm font-semibold hover:bg-primary transition-colors"
                >
                  Inspect source →
                </button>
                <button
                  type="button"
                  onClick={() => setRoute('strategies')}
                  className="px-3 py-1.5 rounded bg-surface-container-high text-on-surface border border-outline-variant/50 font-label-numeric-sm text-label-numeric-sm hover:bg-surface-bright transition-colors"
                >
                  Explore the rules
                </button>
              </div>
            </div>
            <div className="text-6xl text-outline-variant/40 font-mono select-none">⌁</div>
          </div>
        )}

        {/* Lower Split: Movement vs Paper */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-space-md">
          {/* Left: What Changed */}
          <div className="bg-surface-container-low rounded-xl border border-outline-variant/30 p-space-md flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-space-xs border-b border-outline-variant/30 mb-space-sm">
                <h3 className="font-headline-md text-headline-md font-bold text-on-surface">
                  What Changed
                </h3>
                <span className="font-label-badge text-label-badge text-outline">
                  RANK MOVEMENT
                </span>
              </div>
              {topThree.length > 0 ? (
                <div className="flex flex-col divide-y divide-outline-variant/20">
                  {topThree.map((r) => (
                    <div key={r.opportunity_key} className="py-2 flex items-center justify-between text-xs">
                      <div>
                        <div className="font-bold text-on-surface">{r.symbol}</div>
                        <div className="text-outline text-[11px]">{getRankReason(r)}</div>
                      </div>
                      <div className="text-right font-mono">
                        <div className="text-primary font-bold">#{r.rank}</div>
                        <div className="text-[10px] text-outline">
                          Prior: {r.previous_rank !== null ? `#${r.previous_rank}` : 'None'}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="font-body-sm text-body-sm text-outline py-4">
                  No current rank transitions to interpret. Historical results remain separate from current opportunities.
                </p>
              )}
            </div>
            <div className="pt-space-xs text-[11px] text-outline border-t border-outline-variant/20">
              Rank order is governed by detector rule quality and gross target-1 reward/risk.
            </div>
          </div>

          {/* Right: Paper Portfolio Summary */}
          <div className="bg-surface-container-low rounded-xl border border-outline-variant/30 p-space-md flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-space-xs border-b border-outline-variant/30 mb-space-sm">
                <h3 className="font-headline-md text-headline-md font-bold text-on-surface">
                  Paper, With Perspective
                </h3>
                <button
                  type="button"
                  onClick={() => setRoute('paper')}
                  className="text-primary hover:underline font-label-numeric-sm text-xs"
                >
                  Paper portfolio →
                </button>
              </div>

              {paperPortfolio && paperPortfolio.reconciliation?.status === 'OK' ? (
                <div className="flex flex-col gap-2 py-1 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-on-surface-variant">Account ID</span>
                    <span className="font-mono text-on-surface font-semibold">{paperPortfolio.account_id}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-on-surface-variant">Open Positions</span>
                    <span className="font-mono text-primary font-bold">
                      {paperPortfolio.accounting?.open_positions ?? 0}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-on-surface-variant">Realized Net P&L</span>
                    <span
                      className={`font-mono font-bold ${
                        (paperPortfolio.accounting?.realized_net_pnl_inr ?? 0) >= 0
                          ? 'text-tp-long'
                          : 'text-tp-short'
                      }`}
                    >
                      {formatInrCurrency(paperPortfolio.accounting?.realized_net_pnl_inr ?? 0)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-on-surface-variant">Reconciliation</span>
                    <StatusBadge variant="PAPER_FILLED" label="OK" />
                  </div>
                </div>
              ) : (
                <div className="py-4">
                  <h4 className="font-bold text-on-surface text-sm">
                    {paperPortfolio ? 'Reconciliation Needs Attention' : 'No Paper Summary Available'}
                  </h4>
                  <p className="text-xs text-outline mt-1">
                    A missing report is not a zero balance. No virtual account or order is created by this read-only view.
                  </p>
                </div>
              )}
            </div>
            <div className="pt-space-xs text-[11px] text-outline border-t border-outline-variant/20">
              Simulated marks only. Real broker order controls are strictly disabled.
            </div>
          </div>
        </div>

        {/* Bottom Radar Notice */}
        <div className="bg-surface-container-lowest rounded-xl border border-outline-variant/30 p-space-md">
          <div className="flex items-center gap-space-sm mb-1">
            <RadarIcon size={16} className="text-outline" />
            <span className="font-bold text-xs uppercase tracking-wider text-outline">
              Market Radar (Non-Actionable)
            </span>
          </div>
          <p className="font-body-sm text-xs text-outline leading-relaxed">
            Breadth, sector participation, and raw movers are not inferred from the ranked shortlist. This area remains unavailable until an admissible source supplies them.
          </p>
        </div>
      </div>
    </div>
  );
};

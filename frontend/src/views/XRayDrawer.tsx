import React, { useEffect, useState } from 'react';
import { useTerminal, STRATEGY_NAMES } from '../context/TerminalContext';
import { apiClient } from '../api/client';
import { StatusBadge } from '../components/common/StatusBadge';
import { CloseIcon, ArrowBackIcon, CandlestickIcon, ShieldIcon } from '../components/common/Icons';
import { CandleChart } from './CandleChart';
import { formatInr, formatIstTime, sourceTime, stableStringify, istDayString } from '../utils/time';
import type { SignalItem, CashCandleItem, RankingRow } from '../types/api';

export const XRayDrawer: React.FC = () => {
  const {
    selectedCandidate,
    ranks,
    closeDetail,
    detailState,
    setDetailState,
  } = useTerminal();

  const [signal, setSignal] = useState<SignalItem | null>(null);
  const [candles, setCandles] = useState<CashCandleItem[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [chartErrorMessage, setChartErrorMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'evidence' | 'geometry' | 'diagnostics'>('evidence');

  const candidate = selectedCandidate;

  useEffect(() => {
    const currentCandidate = selectedCandidate;
    if (!currentCandidate) {
      setSignal(null);
      setCandles([]);
      setErrorMessage(null);
      setChartErrorMessage(null);
      return;
    }

    let isCancelled = false;
    setDetailState('LOADING');
    setSignal(null);
    setCandles([]);
    setErrorMessage(null);
    setChartErrorMessage(null);

    async function loadDetail(cand: RankingRow) {
      try {
        const identity = cand.instrument_identity;

        // 1. Fetch signal matching candidate exactly
        const signalData = await apiClient.getSignals({
          symbol: cand.symbol,
          strategy_id: cand.strategy_id,
          provider: identity.provider,
          segment: identity.segment,
          start_time: cand.source_data_watermark,
          end_time: cand.source_data_watermark,
          limit: 200,
          offset: 0,
        });

        if (isCancelled) return;

        const candidateWatermark = sourceTime(cand.source_data_watermark, { requireOffset: true });
        const matchedSignals = (signalData.items || []).filter((s) => {
          return (
            s.actionable === false &&
            s.dedup_key === cand.candidate_id &&
            (!s.candidate_evaluation || s.candidate_evaluation.candidate_id === cand.candidate_id) &&
            s.strategy_id === cand.strategy_id &&
            s.position_type === cand.position_type &&
            stableStringify(s.instrument_identity) === stableStringify(cand.instrument_identity) &&
            sourceTime(s.timestamp) === candidateWatermark
          );
        });

        if (matchedSignals.length !== 1) {
          setDetailState('UNAVAILABLE');
          setErrorMessage(
            'The selected rank could not be uniquely matched to retained signal identity and timestamp. No replacement price or chart is shown.'
          );
          return;
        }

        const exactSignal = matchedSignals[0];
        setSignal(exactSignal);
        setDetailState('CURRENT');

        // 2. Fetch candle lineage and cash candles
        const runId = ranks?.snapshot?.run_id;
        if (!runId) {
          setChartErrorMessage('Candle source locator unavailable (missing scan run ID).');
          return;
        }

        const lineage = await apiClient.getScanLineage(runId);
        if (isCancelled) return;

        const batches = (lineage.batches || []).filter(
          (b) => stableStringify(b.identity) === stableStringify(cand.instrument_identity) && b.interval_min === 5
        );

        if (lineage.run_id !== runId || lineage.status !== 'COMMITTED' || batches.length !== 1) {
          setChartErrorMessage('Exact candle identity batch unavailable for candidate.');
          return;
        }

        const batch = batches[0];
        if (!Number.isInteger(batch.candle_count) || batch.candle_count < 1) {
          setChartErrorMessage('Invalid candle locator count in lineage.');
          return;
        }

        const candleRes = await apiClient.getCashCandles({
          run_id: runId,
          batch_id: batch.batch_id,
          limit: 100,
          offset: Math.max(0, batch.candle_count - 100),
        });

        if (isCancelled) return;

        if (
          candleRes.run_id !== runId ||
          candleRes.batch_id !== batch.batch_id ||
          !Array.isArray(candleRes.items) ||
          candleRes.items.length === 0 ||
          candleRes.total_count !== batch.candle_count
        ) {
          setChartErrorMessage('Invalid candle page received.');
          return;
        }

        // Validate candles sequentially
        let previous = -Infinity;
        for (const bar of candleRes.items) {
          const stamp = sourceTime(bar.timestamp);
          if (
            !Number.isFinite(stamp) ||
            stamp <= previous ||
            stamp > candidateWatermark ||
            bar.is_complete !== true ||
            bar.interval_min !== 5 ||
            ![bar.open, bar.high, bar.low, bar.close].every((n) => typeof n === 'number' && Number.isFinite(n) && n > 0) ||
            bar.high < Math.max(bar.open, bar.close, bar.low) ||
            bar.low > Math.min(bar.open, bar.close, bar.high)
          ) {
            setChartErrorMessage('Invalid candle price geometry or timestamp ordering.');
            return;
          }

          if (Number.isFinite(previous) && istDayString(stamp) === istDayString(previous) && stamp - previous !== 300000) {
            setChartErrorMessage('Candle session gap detected within session.');
            return;
          }
          previous = stamp;
        }

        if (previous !== candidateWatermark || previous !== sourceTime(batch.last_timestamp)) {
          setChartErrorMessage('Candle watermark mismatch against batch.');
          return;
        }

        setCandles(candleRes.items);
      } catch (err: unknown) {
        if (isCancelled) return;
        const msg = err instanceof Error ? err.message : 'Retained evidence read failed.';
        setErrorMessage(msg);
        setDetailState('UNAVAILABLE');
      }
    }

    loadDetail(currentCandidate);

    return () => {
      isCancelled = true;
    };
  }, [candidate, ranks?.snapshot?.run_id, setDetailState]);

  // Handle Escape key to close modal
  useEffect(() => {
    if (!candidate) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeDetail();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [candidate, closeDetail]);

  if (!candidate) return null;

  const strategyName = STRATEGY_NAMES[candidate.strategy_id] || candidate.strategy_id;
  const paper = signal?.paper_decision;

  return (
    <>
      {/* Accessible Backdrop Overlay */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-xs z-50 transition-opacity"
        onClick={closeDetail}
        aria-hidden="true"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Opportunity X-Ray detail for ${candidate.symbol}`}
        className="fixed inset-y-0 right-0 z-50 w-full sm:w-[500px] lg:w-[540px] bg-surface-container-low border-l border-outline-variant shadow-2xl flex flex-col select-none animate-in slide-in-from-right duration-200"
      >
      {/* 1. Drawer Header */}
      <div className="h-14 px-space-md bg-surface-container-lowest border-b border-outline-variant/40 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-space-sm">
          <button
            type="button"
            onClick={closeDetail}
            className="p-1 rounded text-on-surface-variant hover:text-on-surface hover:bg-surface-container"
            aria-label="Back to Opportunities"
          >
            <ArrowBackIcon size={16} />
          </button>
          <div className="flex flex-col leading-tight">
            <div className="flex items-center gap-2">
              <span className="font-headline-md text-headline-md font-bold text-on-surface">
                {candidate.symbol}
              </span>
              <StatusBadge
                variant={candidate.direction === 'LONG' ? 'LONG' : 'SHORT'}
                label={candidate.direction}
              />
              <span className="font-mono text-xs font-bold text-primary">
                RANK #{candidate.rank}
              </span>
            </div>
            <span className="text-[11px] font-mono text-outline">
              {strategyName} · NSE CASH
            </span>
          </div>
        </div>

        <button
          type="button"
          onClick={closeDetail}
          className="p-1.5 rounded-lg text-outline hover:text-on-surface hover:bg-surface-container"
          aria-label="Close drawer"
        >
          <CloseIcon size={18} />
        </button>
      </div>

      {/* 2. Sub-strip: Provenance & Status */}
      <div className="px-space-md py-2 bg-surface-container border-b border-outline-variant/30 flex items-center justify-between text-[11px] font-mono">
        <div className="flex items-center gap-1.5 text-on-surface-variant truncate">
          <span className="w-1.5 h-1.5 rounded-full bg-primary-container" />
          <span>Watermark: {formatIstTime(candidate.source_data_watermark)}</span>
        </div>
        <span className="text-outline shrink-0">
          State: <strong className="text-primary">{detailState}</strong>
        </span>
      </div>

      {/* 3. Tab Selectors */}
      <div className="flex border-b border-outline-variant/30 bg-surface-container-lowest px-space-md text-xs font-mono">
        <button
          type="button"
          onClick={() => setActiveTab('evidence')}
          className={`py-2 px-3 border-b-2 font-semibold transition-colors ${
            activeTab === 'evidence'
              ? 'border-primary text-primary'
              : 'border-transparent text-outline hover:text-on-surface'
          }`}
        >
          5m Retained Evidence
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('geometry')}
          className={`py-2 px-3 border-b-2 font-semibold transition-colors ${
            activeTab === 'geometry'
              ? 'border-primary text-primary'
              : 'border-transparent text-outline hover:text-on-surface'
          }`}
        >
          Strategy Geometry
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('diagnostics')}
          className={`py-2 px-3 border-b-2 font-semibold transition-colors ${
            activeTab === 'diagnostics'
              ? 'border-primary text-primary'
              : 'border-transparent text-outline hover:text-on-surface'
          }`}
        >
          Paper & Lineage
        </button>
      </div>

      {/* 4. Drawer Body */}
      <div className="flex-1 overflow-y-auto p-space-md flex flex-col gap-space-md">
        {detailState === 'LOADING' && (
          <div className="py-12 text-center text-outline font-mono text-xs">
            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-2" />
            Reading exact retained setup, signal link, and candle lineage…
          </div>
        )}

        {errorMessage && (
          <div className="p-space-md rounded-xl bg-error-container/20 border border-error/40 text-error font-mono text-xs">
            <div className="font-bold mb-1 flex items-center gap-1">
              <ShieldIcon size={14} />
              <span>Exact Setup Link Unavailable</span>
            </div>
            <p className="text-[11px] text-on-surface-variant leading-relaxed">
              {errorMessage}
            </p>
          </div>
        )}

        {detailState === 'CURRENT' && signal && (
          <>
            {/* TAB 1: Evidence & Candlesticks */}
            {activeTab === 'evidence' && (
              <div className="flex flex-col gap-space-md">
                {/* Candlestick Section */}
                <div className="flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-xs text-on-surface flex items-center gap-1">
                      <CandlestickIcon size={16} className="text-primary" />
                      <span>Retained 5-Minute Candles</span>
                    </span>
                    <span className="text-[10px] font-mono text-outline uppercase">
                      ZERO LOOKAHEAD BIAS
                    </span>
                  </div>

                  {chartErrorMessage ? (
                    <div className="p-space-sm rounded bg-surface-container text-outline font-mono text-[11px] border border-outline-variant/30">
                      Chart withheld: {chartErrorMessage}
                    </div>
                  ) : (
                    <CandleChart bars={candles} watermarkIst={candidate.source_data_watermark} />
                  )}
                </div>

                {/* Setup Qualification Rationale */}
                <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 flex flex-col gap-1">
                  <span className="font-label-badge text-label-badge text-outline uppercase">
                    Setup Qualification Rationale
                  </span>
                  <p className="font-body-sm text-xs text-on-surface leading-relaxed">
                    {signal.rationale || 'Qualified through deterministic rule evaluator.'}
                  </p>
                  <div className="mt-2 text-[10px] font-mono text-outline border-t border-outline-variant/20 pt-1">
                    Missing components: {(candidate.missing_components || []).join(', ') || 'None'}
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: Strategy Geometry */}
            {activeTab === 'geometry' && (
              <div className="flex flex-col gap-space-md font-mono text-xs">
                <div className="grid grid-cols-2 gap-space-xs p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30">
                  <div className="p-2 bg-surface-container rounded">
                    <div className="text-[10px] text-outline uppercase">Decision Reference</div>
                    <div className="text-sm font-bold text-on-surface">₹{formatInr(signal.entry_price)}</div>
                  </div>
                  <div className="p-2 bg-surface-container rounded">
                    <div className="text-[10px] text-outline uppercase">Gross T1 R:R</div>
                    <div className="text-sm font-bold text-primary">
                      1:{formatInr(candidate.score_components?.actual_target1_rr)}
                    </div>
                  </div>
                  <div className="p-2 bg-surface-container rounded">
                    <div className="text-[10px] text-outline uppercase">Stop Loss</div>
                    <div className="text-sm font-bold text-tp-short">₹{formatInr(signal.stop_loss)}</div>
                  </div>
                  <div className="p-2 bg-surface-container rounded">
                    <div className="text-[10px] text-outline uppercase">Invalidation Level</div>
                    <div className="text-sm font-bold text-outline">₹{formatInr(signal.invalidation_level)}</div>
                  </div>
                  <div className="p-2 bg-surface-container rounded">
                    <div className="text-[10px] text-outline uppercase">Target 1</div>
                    <div className="text-sm font-bold text-tp-long">₹{formatInr(signal.target_1)}</div>
                  </div>
                  <div className="p-2 bg-surface-container rounded">
                    <div className="text-[10px] text-outline uppercase">Target 2</div>
                    <div className="text-sm font-bold text-tp-long">₹{formatInr(signal.target_2)}</div>
                  </div>
                </div>

                <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 flex flex-col gap-1">
                  <span className="font-label-badge text-label-badge text-outline uppercase">Entry Zone Bracket</span>
                  <div className="text-sm font-bold text-primary">
                    ₹{formatInr(signal.entry_zone_low)} — ₹{formatInr(signal.entry_zone_high)}
                  </div>
                  <p className="text-[10px] text-outline mt-1 font-sans">
                    Decision levels are a retained reference, not an active executable limit order.
                  </p>
                </div>
              </div>
            )}

            {/* TAB 3: Diagnostics & Paper Evidence */}
            {activeTab === 'diagnostics' && (
              <div className="flex flex-col gap-space-md font-mono text-xs">
                {/* Paper Decision Status */}
                <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 flex flex-col gap-2">
                  <span className="font-label-badge text-label-badge text-outline uppercase">
                    Paper Trigger Decision
                  </span>

                  {paper ? (
                    <div className="flex flex-col gap-1 text-[11px]">
                      <div className="flex items-center justify-between">
                        <span className="text-outline">Decision Status:</span>
                        <span className="font-bold text-on-surface">{paper.status || 'NOT_EVALUATED'}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-outline">Reason Code:</span>
                        <span
                          className={`font-bold ${
                            paper.reason_code === 'CONFLICTING_OPEN_POSITION' ? 'text-tp-caution' : 'text-primary'
                          }`}
                        >
                          {paper.reason_code || 'NONE'}
                        </span>
                      </div>
                      {paper.trigger_timestamp_ist && (
                        <div className="flex items-center justify-between">
                          <span className="text-outline">Trigger Timestamp:</span>
                          <span className="text-on-surface">{formatIstTime(paper.trigger_timestamp_ist)}</span>
                        </div>
                      )}
                      <div className="flex items-center justify-between">
                        <span className="text-outline">Recommendation:</span>
                        <span className="text-on-surface">{signal.recommendation_status || 'CANDIDATE_ONLY'}</span>
                      </div>
                    </div>
                  ) : (
                    <p className="text-[11px] text-outline">
                      No paper evaluation performed on this candidate.
                    </p>
                  )}
                </div>

                {/* Lineage & Checksum */}
                <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 flex flex-col gap-1 text-[11px]">
                  <span className="font-label-badge text-label-badge text-outline uppercase">
                    Cryptographic Source Lineage
                  </span>
                  <div className="truncate">
                    <span className="text-outline">Source Digest: </span>
                    <span className="text-primary font-mono">{candidate.source_digest.slice(0, 24)}…</span>
                  </div>
                  <div className="truncate">
                    <span className="text-outline">Opportunity Key: </span>
                    <span className="text-on-surface font-mono">{candidate.opportunity_key.slice(0, 24)}…</span>
                  </div>
                  <div className="text-[10px] text-outline mt-1 font-sans">
                    Digest verifies internal data integrity against scan execution reference.
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* 5. Sticky Bottom Action Bar (Read-only, no paper simulation or orders!) */}
      <div className="p-space-md bg-surface-container-lowest border-t border-outline-variant/40 flex items-center justify-between gap-space-sm text-xs font-mono shrink-0">
        <span className="text-[10px] text-outline">
          V1 Read-Only Terminal
        </span>
        <button
          type="button"
          onClick={closeDetail}
          className="px-4 py-1.5 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface border border-outline-variant font-semibold transition-colors"
        >
          Close Inspector
        </button>
      </div>
    </div>
    </>
  );
};

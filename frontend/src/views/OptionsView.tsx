import React, { useEffect, useState } from 'react';
import { useTerminal } from '../context/TerminalContext';
import { StatusBadge } from '../components/common/StatusBadge';
import { AnalyticsIcon, SyncIcon } from '../components/common/Icons';
import { apiGet } from '../api/client';
import { formatInr, formatIstTime } from '../utils/time';

interface OiSnapshotItem {
  id: number;
  index_symbol: string;
  expiry: string;
  spot: number;
  pcr: number;
  total_ce_oi: number;
  total_pe_oi: number;
  snapshot_timestamp: string;
  is_simulated: boolean;
  strikes: Array<{
    strike: number;
    ce_ltp: number;
    ce_oi: number;
    pe_ltp: number;
    pe_oi: number;
  }>;
}

export const OptionsView: React.FC = () => {
  const { isRefreshing, refreshData } = useTerminal();
  const [snapshots, setSnapshots] = useState<OiSnapshotItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadOi() {
      setLoading(true);
      setError(null);
      try {
        const res = await apiGet<{ items: OiSnapshotItem[] }>('/api/oi-snapshots', { limit: 10 });
        if (!cancelled) {
          setSnapshots(res.items || []);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Options observation feed unavailable');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadOi();
    return () => {
      cancelled = true;
    };
  }, []);

  const latest = snapshots[0];

  return (
    <div className="p-space-md md:p-space-lg flex flex-col gap-space-md select-none">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between pb-space-xs border-b border-outline-variant/30 gap-space-sm">
        <div>
          <h2 className="font-headline-lg text-headline-lg font-bold text-on-surface flex items-center gap-2">
            <AnalyticsIcon size={20} className="text-primary" />
            <span>Options Lab</span>
          </h2>
          <p className="font-body-sm text-body-sm text-on-surface-variant">
            Underlying ≠ Contract · Exact instruments, observable premiums, honest availability
          </p>
        </div>

        <div className="flex items-center gap-space-sm font-mono text-xs">
          <StatusBadge variant="NEUTRAL" label="DERIVATIVES OBSERVATION" />
          <button
            type="button"
            onClick={() => refreshData()}
            disabled={isRefreshing}
            className="px-2.5 py-1 rounded bg-surface-container-high hover:bg-surface-bright text-primary flex items-center gap-1 border border-outline-variant/40"
          >
            <SyncIcon size={12} className={isRefreshing ? 'animate-spin' : ''} />
            <span>GET OI Observation</span>
          </button>
        </div>
      </div>

      {/* Snapshot summary */}
      {latest ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-space-sm font-mono text-xs">
          <div className="bg-surface-container-low p-space-md rounded-xl border border-outline-variant/30">
            <div className="text-outline uppercase text-[10px]">Underlying Index</div>
            <div className="text-lg font-bold text-on-surface mt-1">{latest.index_symbol}</div>
            <div className="text-[10px] text-outline">Spot: ₹{formatInr(latest.spot)}</div>
          </div>
          <div className="bg-surface-container-low p-space-md rounded-xl border border-outline-variant/30">
            <div className="text-outline uppercase text-[10px]">Contract Expiry</div>
            <div className="text-lg font-bold text-primary mt-1">{latest.expiry}</div>
            <div className="text-[10px] text-outline">Dated Contract Master</div>
          </div>
          <div className="bg-surface-container-low p-space-md rounded-xl border border-outline-variant/30">
            <div className="text-outline uppercase text-[10px]">Put / Call Ratio (PCR)</div>
            <div className="text-lg font-bold text-tertiary mt-1">{formatInr(latest.pcr)}</div>
            <div className="text-[10px] text-outline">Observed OI Aggregate</div>
          </div>
          <div className="bg-surface-container-low p-space-md rounded-xl border border-outline-variant/30">
            <div className="text-outline uppercase text-[10px]">Observation Timestamp</div>
            <div className="text-sm font-bold text-on-surface mt-1">
              {formatIstTime(latest.snapshot_timestamp)}
            </div>
            <div className="text-[10px] text-outline">Retained Snapshot</div>
          </div>
        </div>
      ) : (
        <div className="p-space-lg rounded-xl bg-surface-container-low border border-outline-variant/30 text-center font-mono text-xs">
          {loading ? (
            <span className="text-outline">Reading retained OI observations…</span>
          ) : error ? (
            <span className="text-error">{error}</span>
          ) : (
            <span className="text-outline">No derivative OI snapshot records currently retained.</span>
          )}
        </div>
      )}

      {/* Contract Ladder */}
      {latest && latest.strikes && latest.strikes.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-outline-variant/40 bg-surface-container-low shadow-sm">
          <table className="w-full text-left border-collapse font-mono text-xs" aria-label="Options Strike Matrix">
            <thead>
              <tr className="border-b border-outline-variant/40 bg-surface-container-lowest text-[11px] text-outline uppercase">
                <th colSpan={2} className="py-2 px-3 text-center border-r border-outline-variant/30 bg-primary/5 text-primary">
                  CALL OPTIONS (CE)
                </th>
                <th className="py-2 px-3 text-center bg-surface-container-high">STRIKE</th>
                <th colSpan={2} className="py-2 px-3 text-center border-l border-outline-variant/30 bg-tertiary/5 text-tertiary">
                  PUT OPTIONS (PE)
                </th>
              </tr>
              <tr className="border-b border-outline-variant/30 bg-surface-container text-[10px] text-outline">
                <th scope="col" className="py-1 px-3 text-right">CE OI</th>
                <th scope="col" className="py-1 px-3 text-right border-r border-outline-variant/30">CE LTP</th>
                <th scope="col" className="py-1 px-3 text-center font-bold text-on-surface">STRIKE</th>
                <th scope="col" className="py-1 px-3 text-right border-l border-outline-variant/30">PE LTP</th>
                <th scope="col" className="py-1 px-3 text-right">PE OI</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/20">
              {latest.strikes.slice(0, 15).map((row) => (
                <tr key={row.strike} className="hover:bg-surface-container-high/40">
                  <td className="py-2 px-3 text-right text-outline">{formatInr(row.ce_oi)}</td>
                  <td className="py-2 px-3 text-right border-r border-outline-variant/30 text-tp-long font-medium">
                    ₹{formatInr(row.ce_ltp)}
                  </td>
                  <td className="py-2 px-3 text-center font-bold text-on-surface bg-surface-container-high/20">
                    {row.strike}
                  </td>
                  <td className="py-2 px-3 text-right border-l border-outline-variant/30 text-tp-short font-medium">
                    ₹{formatInr(row.pe_ltp)}
                  </td>
                  <td className="py-2 px-3 text-right text-outline">{formatInr(row.pe_oi)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Truthfulness Notice */}
      <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 text-xs font-mono text-outline leading-relaxed">
        <strong>Options Lab Truthfulness Protocol:</strong> Open Interest movements and strike depth do not prove institutional accumulation or predict option premium profits. Implied Volatility (IV) and Greeks are only displayed when provided by verified models. Contract fitness scores remain disabled (research phase).
      </div>
    </div>
  );
};

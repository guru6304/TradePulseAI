import React, { useEffect, useState } from 'react';
import { useTerminal } from '../context/TerminalContext';
import { SettingsIcon, SyncIcon } from '../components/common/Icons';
import { StatusBadge } from '../components/common/StatusBadge';
import { apiClient } from '../api/client';
import { formatIstTime } from '../utils/time';
import type { ScanItem } from '../types/api';

export const HealthView: React.FC = () => {
  const { health, isRefreshing, refreshData } = useTerminal();
  const [scans, setScans] = useState<ScanItem[]>([]);
  const [loadingScans, setLoadingScans] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function loadScans() {
      setLoadingScans(true);
      try {
        const res = await apiClient.getScans({ limit: 10 });
        if (!cancelled) setScans(res.items || []);
      } catch {
        if (!cancelled) setScans([]);
      } finally {
        if (!cancelled) setLoadingScans(false);
      }
    }
    loadScans();
    return () => {
      cancelled = true;
    };
  }, []);

  const broker = health?.broker;
  const scheduler = health?.scheduler;
  const lastScan = health?.last_scan;

  return (
    <div className="p-space-md md:p-space-lg flex flex-col gap-space-md select-none font-mono text-xs">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between pb-space-xs border-b border-outline-variant/30 gap-space-sm">
        <div>
          <h2 className="font-headline-lg text-headline-lg font-bold text-on-surface font-sans flex items-center gap-2">
            <SettingsIcon size={20} className="text-primary" />
            <span>Health & Diagnostics</span>
          </h2>
          <p className="font-body-sm text-body-sm text-on-surface-variant font-sans">
            Source & system · Operational detail, kept separate from your market decisions
          </p>
        </div>

        <div className="flex items-center gap-space-sm">
          <StatusBadge
            variant={health?.status === 'ok' ? 'QUALIFIED' : 'CAUTION'}
            label={`SYSTEM: ${health?.status?.toUpperCase() || 'UNKNOWN'}`}
          />
          <button
            type="button"
            onClick={() => refreshData()}
            disabled={isRefreshing}
            className="px-2.5 py-1 rounded bg-surface-container-high hover:bg-surface-bright text-primary flex items-center gap-1 border border-outline-variant/40"
          >
            <SyncIcon size={12} className={isRefreshing ? 'animate-spin' : ''} />
            <span>GET Diagnostics</span>
          </button>
        </div>
      </div>

      {/* Grid of Diagnostic Panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-space-md">
        {/* 1. Broker & Adapter Feed */}
        <div className="bg-surface-container-low rounded-xl border border-outline-variant/30 p-space-md flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-space-xs border-b border-outline-variant/30 mb-2">
              <span className="font-bold text-on-surface">Broker Adapter Status</span>
              <StatusBadge
                variant={broker?.is_simulated ? 'CAUTION' : 'QUALIFIED'}
                label={broker?.data_mode || 'UNKNOWN'}
              />
            </div>
            <div className="flex flex-col gap-1.5 text-[11px]">
              <div className="flex justify-between">
                <span className="text-outline">Active Broker:</span>
                <span className="text-on-surface font-bold">{broker?.active_broker || 'paper_sim'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-outline">Connection State:</span>
                <span className="text-primary">{broker?.connection_state || 'SIMULATED'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-outline">Connectivity Verified:</span>
                <span className="text-on-surface">{broker?.connectivity_verified ? 'YES' : 'NO'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-outline">Live Signals Allowed:</span>
                <span className="text-on-surface">{broker?.live_signals_allowed ? 'YES' : 'NO'}</span>
              </div>
            </div>
          </div>
          <div className="text-[10px] text-outline pt-2 border-t border-outline-variant/20">
            Last verified: {broker?.last_verified_at_ist ? formatIstTime(broker.last_verified_at_ist) : '—'}
          </div>
        </div>

        {/* 2. Scheduler Engine */}
        <div className="bg-surface-container-low rounded-xl border border-outline-variant/30 p-space-md flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-space-xs border-b border-outline-variant/30 mb-2">
              <span className="font-bold text-on-surface">Scheduler & Session</span>
              <StatusBadge
                variant={scheduler?.session_open ? 'QUALIFIED' : 'NEUTRAL'}
                label={scheduler?.session_state || 'SESSION'}
              />
            </div>
            <div className="flex flex-col gap-1.5 text-[11px]">
              <div className="flex justify-between">
                <span className="text-outline">Scheduler Running:</span>
                <span className="text-on-surface font-bold">{scheduler?.running ? 'RUNNING' : 'STOPPED'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-outline">Scan Interval:</span>
                <span className="text-primary">{scheduler?.scan_interval_seconds ?? 300}s</span>
              </div>
              <div className="flex justify-between">
                <span className="text-outline">Cycles Executed:</span>
                <span className="text-on-surface">{scheduler?.cycles_executed ?? 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-outline">Session Window:</span>
                <span className="text-on-surface">09:15 — 15:30 IST</span>
              </div>
            </div>
          </div>
          <div className="text-[10px] text-outline pt-2 border-t border-outline-variant/20">
            Configured holidays: {scheduler?.configured_holidays?.length ?? 0} dates
          </div>
        </div>

        {/* 3. Database & Last Scan */}
        <div className="bg-surface-container-low rounded-xl border border-outline-variant/30 p-space-md flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-space-xs border-b border-outline-variant/30 mb-2">
              <span className="font-bold text-on-surface">Database & Last Scan</span>
              <StatusBadge variant="QUALIFIED" label="SQLITE LOCAL" />
            </div>
            <div className="flex flex-col gap-1.5 text-[11px]">
              <div className="flex justify-between">
                <span className="text-outline">Last Scan Run ID:</span>
                <span className="text-primary font-bold truncate max-w-[150px]">
                  {lastScan?.run_id ? `#${lastScan.run_id}` : 'None'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-outline">Status:</span>
                <span className="text-on-surface">{lastScan?.scan_status || 'IDLE'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-outline">Signals Produced:</span>
                <span className="text-on-surface font-bold">{lastScan?.total_signals ?? 0}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-outline">Execution Duration:</span>
                <span className="text-on-surface">{lastScan?.duration_ms ? `${lastScan.duration_ms}ms` : '—'}</span>
              </div>
            </div>
          </div>
          <div className="text-[10px] text-outline pt-2 border-t border-outline-variant/20">
            Completed: {lastScan?.completed_at_ist ? formatIstTime(lastScan.completed_at_ist) : '—'}
          </div>
        </div>
      </div>

      {/* Recent Scans Table */}
      <div className="bg-surface-container-low rounded-xl border border-outline-variant/40 overflow-hidden shadow-sm">
        <div className="p-space-md border-b border-outline-variant/30 flex items-center justify-between">
          <h3 className="font-headline-md text-headline-md font-bold text-on-surface font-sans">
            Recent Scans Telemetry ({scans.length})
          </h3>
          <span className="text-outline text-xs">Retained scan execution receipts</span>
        </div>

        {loadingScans ? (
          <div className="p-space-lg text-center text-outline">Reading recent scans…</div>
        ) : scans.length === 0 ? (
          <div className="p-space-lg text-center text-outline">No scan records retained in SQLite.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs" aria-label="Recent Scans">
              <thead>
                <tr className="border-b border-outline-variant/30 bg-surface-container-lowest text-[11px] text-outline uppercase">
                  <th scope="col" className="py-2 px-3">Run ID</th>
                  <th scope="col" className="py-2 px-3">Started IST</th>
                  <th scope="col" className="py-2 px-3">Status</th>
                  <th scope="col" className="py-2 px-3 text-right">Duration</th>
                  <th scope="col" className="py-2 px-3 text-right">Signals</th>
                  <th scope="col" className="py-2 px-3">Broker / Mode</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/20">
                {scans.map((s) => (
                  <tr key={s.id} className="hover:bg-surface-container-high/40">
                    <td className="py-2 px-3 font-bold text-primary truncate max-w-[140px]">#{s.run_id}</td>
                    <td className="py-2 px-3 text-outline">{formatIstTime(s.started_at_ist)}</td>
                    <td className="py-2 px-3">
                      <StatusBadge
                        variant={s.status === 'COMPLETED' ? 'QUALIFIED' : 'CAUTION'}
                        label={s.status}
                      />
                    </td>
                    <td className="py-2 px-3 text-right">{s.duration_ms ? `${s.duration_ms}ms` : '—'}</td>
                    <td className="py-2 px-3 text-right font-bold text-on-surface">{s.total_signals}</td>
                    <td className="py-2 px-3 text-outline text-[11px]">{s.broker} ({s.data_mode})</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Truthfulness Notice */}
      <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 text-[11px] text-outline leading-relaxed font-sans">
        <strong>Telemetry Integrity:</strong> No external latency claims (e.g. 4.2ms) are asserted without validated server measurements. Configuration parameters above are sanitized and redacted. No mutation APIs exist for operational configuration.
      </div>
    </div>
  );
};

import React, { useEffect, useRef } from 'react';
import { useTerminal } from '../../context/TerminalContext';
import { SyncIcon, SearchIcon, MenuIcon } from '../common/Icons';
import { formatInrCurrency, formatIstTime } from '../../utils/time';

interface HeaderProps {
  onToggleMobileNav?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onToggleMobileNav }) => {
  const {
    health,
    isRefreshing,
    refreshData,
    filterQuery,
    setFilterQuery,
    paperPortfolio,
    route,
    setRoute,
  } = useTerminal();

  const searchInputRef = useRef<HTMLInputElement>(null);

  // Global '/' keyboard shortcut to focus search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.key === '/' &&
        !['INPUT', 'TEXTAREA', 'SELECT'].includes((document.activeElement as HTMLElement)?.tagName)
      ) {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const getSessionText = () => {
    if (!health) return 'Session unverified / IST';
    if (health.evidence_scope === 'DETERMINISTIC_OFFLINE_DEMO') return 'Synthetic demo / IST';
    const state = health.scheduler?.session_state;
    const known: Record<string, string> = {
      OPEN: 'Market open',
      MARKET_OPEN: 'Market open',
      CLOSED: 'Market closed',
      MARKET_CLOSED: 'Market closed',
      PRE_OPEN: 'Before market',
      POST_CLOSE: 'After market',
      WEEKEND: 'Weekend',
      HOLIDAY: 'Market holiday',
    };
    return `${(state && known[state]) || 'Session unverified'} / IST`;
  };

  const candleTimestamp = health?.broker?.last_candle_timestamp_ist;
  const scanTimestamp = health?.last_scan?.completed_at_ist;
  const timeText = candleTimestamp
    ? formatIstTime(candleTimestamp)
    : scanTimestamp
    ? formatIstTime(scanTimestamp)
    : 'Awaiting evidence';

  const hasAlerts = Boolean(health?.operations?.alerts && health.operations.alerts.length > 0);
  const netPnl = paperPortfolio?.accounting?.realized_net_pnl_inr ?? null;

  return (
    <>
      <header className="fixed top-0 left-0 md:left-56 right-0 h-11 bg-surface-container-low/95 backdrop-blur-md z-40 flex items-center justify-between px-space-md md:px-space-lg border-b border-outline-variant/35 select-none">
        {/* Left indicators */}
        <div className="flex items-center gap-space-sm md:gap-space-md">
          {/* Mobile hamburger menu button */}
          <button
            type="button"
            className="md:hidden p-1 text-on-surface-variant hover:text-on-surface focus:outline-none"
            onClick={onToggleMobileNav}
            aria-label="Toggle navigation menu"
          >
            <MenuIcon size={20} />
          </button>

          <span className="font-label-badge text-label-badge px-2 py-0.5 rounded bg-tertiary-container/20 text-tertiary font-bold tracking-wider uppercase flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-tertiary animate-pulse" />
            <span>RESEARCH / PAPER ONLY</span>
          </span>

          <div className="hidden sm:block h-4 w-px bg-outline-variant/60" />

          <div className="flex items-center gap-1.5 font-label-numeric-sm text-label-numeric-sm text-on-surface-variant">
            <span className={`w-1.5 h-1.5 rounded-full ${hasAlerts ? 'bg-amber-400' : 'bg-primary-container'}`} />
            <span className="tabular-nums font-mono">
              {getSessionText()} • {timeText}
            </span>
          </div>
        </div>

        {/* Right Search & Controls */}
        <div className="flex items-center gap-space-sm md:gap-space-md">
          <div className="relative flex items-center w-40 sm:w-60 md:w-72">
            <SearchIcon className="absolute left-2.5 text-outline pointer-events-none" size={15} />
            <input
              ref={searchInputRef}
              type="text"
              value={filterQuery}
              onChange={(e) => {
                setFilterQuery(e.target.value);
                if (route !== 'pulse' && route !== 'opportunities') {
                  setRoute('opportunities');
                }
              }}
              placeholder="Search (press '/' to filter)..."
              className="w-full h-7 pl-8 pr-space-sm bg-surface-container-lowest rounded font-body-sm text-body-sm text-on-surface placeholder:text-outline focus:outline-none focus:ring-1 focus:ring-primary border border-outline-variant/40"
              aria-label="Search candidates"
            />
          </div>

          <button
            type="button"
            onClick={() => refreshData()}
            disabled={isRefreshing}
            className="h-7 px-space-sm rounded bg-surface-container-high text-on-surface hover:bg-surface-bright flex items-center gap-1 font-label-numeric-sm text-label-numeric-sm transition-colors disabled:opacity-50"
            title="Read stored evidence (GET only)"
            aria-label="Refresh data"
          >
            <SyncIcon
              size={13}
              className={`text-primary ${isRefreshing ? 'animate-spin' : ''}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </button>

          <div className="hidden lg:block h-4 w-px bg-outline-variant/60" />

          <div className="hidden lg:flex items-center gap-space-sm">
            <div className="flex flex-col text-right leading-none">
              <span className="font-label-numeric-sm text-label-numeric-sm text-on-surface font-medium">
                Analyst / Paper Trader
              </span>
              <span className="font-label-badge text-label-badge text-outline">
                TIER 1 ACCESS
              </span>
            </div>
            <div className="w-7 h-7 rounded-full bg-primary-container flex items-center justify-center font-bold text-on-primary-container text-xs">
              AP
            </div>
          </div>
        </div>
      </header>

      {/* Sub-banner: Terminal Safety Protocol */}
      <div className="fixed top-11 left-0 md:left-56 right-0 h-6 bg-surface-container-lowest z-30 flex items-center justify-between px-space-md md:px-space-lg border-b border-outline-variant/25 select-none text-[11px]">
        <div className="flex items-center gap-space-sm truncate">
          <span className="font-label-badge text-[9px] px-1 py-0.5 rounded bg-surface-container-high text-outline uppercase shrink-0">
            TERMINAL STATUS
          </span>
          <span className="font-mono text-on-surface-variant truncate">
            SYNTHETIC DEMO ONLY · Read-Only V1 Terminal · Deterministic Quality Ranking
          </span>
        </div>
        <div className="hidden md:flex items-center gap-space-md font-mono text-outline shrink-0">
          <span>SEGMENT: NSE CASH</span>
          {netPnl !== null ? (
            <span className={netPnl >= 0 ? 'text-tp-long font-semibold' : 'text-tp-short font-semibold'}>
              PAPER P&L: {netPnl >= 0 ? '+' : ''}{formatInrCurrency(netPnl)}
            </span>
          ) : (
            <span className="text-outline">PAPER: UNRECONCILED</span>
          )}
        </div>
      </div>
    </>
  );
};

import React, { useState } from 'react';
import { useTerminal, STRATEGY_NAMES } from '../context/TerminalContext';
import { StatusBadge } from '../components/common/StatusBadge';
import { SearchIcon, SyncIcon, ArrowUpIcon, ArrowDownIcon } from '../components/common/Icons';
import { formatInr, formatIstTime } from '../utils/time';
import { XRayDrawer } from './XRayDrawer';

export const OpportunitiesView: React.FC = () => {
  const {
    ranks,
    rankingRows,
    rankingUiState,
    rankingMessage,
    filterQuery,
    setFilterQuery,
    filterDirection,
    setFilterDirection,
    filterStrategy,
    setFilterStrategy,
    filterStatus,
    setFilterStatus,
    selectedKey,
    selectCandidate,
    refreshData,
    isRefreshing,
  } = useTerminal();

  const [page, setPage] = useState<number>(0);
  const pageSize = 20;

  const snapshot = ranks?.snapshot;

  // Filter application over complete snapshot
  const filteredRows = rankingRows.filter((r) => {
    if (filterQuery && !r.symbol.toLowerCase().includes(filterQuery.toLowerCase())) {
      return false;
    }
    if (filterDirection && r.direction !== filterDirection) {
      return false;
    }
    if (filterStrategy && r.strategy_id !== filterStrategy) {
      return false;
    }
    if (filterStatus === 'QUALIFIED' && r.priority_scope !== 'QUALIFIED_SCANNER_CANDIDATE_ONLY') {
      return false;
    }
    return true;
  });

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const currentPage = Math.min(Math.max(0, page), totalPages - 1);
  const pagedRows = filteredRows.slice(currentPage * pageSize, currentPage * pageSize + pageSize);

  const longCount = rankingRows.filter((r) => r.direction === 'LONG').length;
  const shortCount = rankingRows.filter((r) => r.direction === 'SHORT').length;

  const handleResetFilters = () => {
    setFilterQuery('');
    setFilterDirection('');
    setFilterStrategy('');
    setFilterStatus('');
    setPage(0);
  };

  return (
    <div className="flex flex-col w-full relative select-none">
      {/* 1. System Run Ribbon / Snapshot Integrity */}
      <div className="w-full bg-surface-container-lowest px-space-md md:px-space-lg py-space-xs border-b border-outline-variant/30 flex flex-wrap items-center justify-between gap-space-sm text-xs font-mono">
        <div className="flex flex-wrap items-center gap-space-md">
          <div className="flex items-center gap-1.5 text-on-surface">
            <span className="w-1.5 h-1.5 rounded-full bg-primary" />
            <span className="text-outline uppercase">RUN ID:</span>
            <span className="text-primary font-medium">
              {snapshot?.run_id ? `#${snapshot.run_id}` : 'NO_RUN_RETAINED'}
            </span>
          </div>

          <div className="h-3 w-px bg-surface-variant hidden sm:block" />

          <div className="flex items-center gap-1 text-on-surface-variant">
            <span className="text-outline">SNAPSHOT TIME:</span>
            <span className="text-tertiary">
              {snapshot?.reference ? formatIstTime(snapshot.reference) : '—'}
            </span>
          </div>

          <div className="h-3 w-px bg-surface-variant hidden sm:block" />

          <div className="flex items-center gap-1 text-on-surface-variant">
            <span className="text-outline">CANDIDATES:</span>
            <span className="text-on-surface font-semibold">{rankingRows.length} Loaded</span>
            <span className="text-outline text-[10px] bg-surface-container-high px-1 py-0.5 rounded">
              (Complete Retained Run)
            </span>
          </div>
        </div>

        <div className="flex items-center gap-space-sm">
          <span className="px-2 py-0.5 rounded bg-surface-container text-on-surface-variant text-[11px] font-semibold border border-outline-variant/40">
            DETERMINISTIC RANK
          </span>
          <button
            type="button"
            onClick={() => refreshData()}
            disabled={isRefreshing}
            className="h-6 px-2 rounded bg-surface-container-high hover:bg-surface-bright text-primary flex items-center gap-1 transition-colors disabled:opacity-50"
          >
            <SyncIcon size={12} className={isRefreshing ? 'animate-spin' : ''} />
            <span>GET Stored Snapshot</span>
          </button>
        </div>
      </div>

      {/* 2. Filter & Control Matrix Bar */}
      <div className="w-full bg-surface-container-low px-space-md md:px-space-lg py-space-sm border-b border-outline-variant/30 flex flex-col gap-space-sm">
        <div className="flex flex-wrap items-center justify-between gap-space-md">
          {/* Search Input & Direction Toggles */}
          <div className="flex flex-wrap items-center gap-space-md flex-1 min-w-[280px]">
            <div className="relative flex items-center w-64 sm:w-72">
              <SearchIcon className="absolute left-2 text-outline pointer-events-none" size={15} />
              <input
                type="text"
                value={filterQuery}
                onChange={(e) => {
                  setFilterQuery(e.target.value);
                  setPage(0);
                }}
                placeholder="Filter snapshot (RELIANCE, SBIN)..."
                className="w-full h-8 pl-7 pr-space-sm bg-surface-container-lowest rounded font-mono text-xs text-on-surface placeholder:text-outline border border-outline-variant/40 focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>

            {/* Direction Segmented Toggles */}
            <div className="flex items-center bg-surface-container-lowest rounded p-0.5 border border-outline-variant/30 text-xs font-mono">
              <button
                type="button"
                onClick={() => {
                  setFilterDirection('');
                  setPage(0);
                }}
                className={`px-2.5 py-1 rounded transition-colors ${
                  filterDirection === '' ? 'bg-surface-container-high text-primary font-bold' : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                All ({rankingRows.length})
              </button>
              <button
                type="button"
                onClick={() => {
                  setFilterDirection('LONG');
                  setPage(0);
                }}
                className={`px-2.5 py-1 rounded flex items-center gap-1 transition-colors ${
                  filterDirection === 'LONG' ? 'bg-surface-container-high text-tp-long font-bold' : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <ArrowUpIcon size={12} className="text-tp-long" />
                <span>Long ({longCount})</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setFilterDirection('SHORT');
                  setPage(0);
                }}
                className={`px-2.5 py-1 rounded flex items-center gap-1 transition-colors ${
                  filterDirection === 'SHORT' ? 'bg-surface-container-high text-tp-short font-bold' : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <ArrowDownIcon size={12} className="text-tp-short" />
                <span>Short ({shortCount})</span>
              </button>
            </div>

            {/* Strategy Selector */}
            <div className="flex items-center gap-1">
              <span className="font-label-badge text-label-badge text-outline uppercase">Strategy:</span>
              <select
                value={filterStrategy}
                onChange={(e) => {
                  setFilterStrategy(e.target.value);
                  setPage(0);
                }}
                aria-label="Filter by Strategy"
                className="h-8 px-2 bg-surface-container-lowest text-on-surface font-mono text-xs rounded border border-outline-variant/40 focus:outline-none cursor-pointer"
              >
                <option value="">All Strategies</option>
                {Object.entries(STRATEGY_NAMES).map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </div>

            {/* Status Selector */}
            <div className="flex items-center gap-1">
              <span className="font-label-badge text-label-badge text-outline uppercase">Status:</span>
              <select
                value={filterStatus}
                onChange={(e) => {
                  setFilterStatus(e.target.value);
                  setPage(0);
                }}
                aria-label="Filter by Status"
                className="h-8 px-2 bg-surface-container-lowest text-on-surface font-mono text-xs rounded border border-outline-variant/40 focus:outline-none cursor-pointer"
              >
                <option value="">All Retained</option>
                <option value="QUALIFIED">QUALIFIED ({rankingRows.length})</option>
              </select>
            </div>

            {/* Reset Filters */}
            {(filterQuery || filterDirection || filterStrategy || filterStatus) && (
              <button
                type="button"
                onClick={handleResetFilters}
                className="text-xs text-outline hover:text-primary underline ml-1"
              >
                Reset
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 3. Main Ranking Content Area */}
      <div className="p-space-md md:p-space-lg flex flex-col gap-space-md">
        {/* Status notice */}
        <div
          id="ranking-status"
          role="status"
          tabIndex={-1}
          className="text-xs font-mono text-outline pb-1 flex items-center justify-between"
        >
          <span>{rankingMessage}</span>
          <span className="text-[11px] bg-surface-container px-1.5 py-0.5 rounded border border-outline-variant/30 uppercase">
            STATUS: {rankingUiState}
          </span>
        </div>

        {/* Candidate Table or Empty State */}
        {rankingRows.length === 0 ? (
          <div className="bg-surface-container-low border border-outline-variant/40 rounded-xl p-space-lg text-center my-4">
            <h3 className="font-headline-md text-headline-md font-bold text-on-surface">
              {rankingUiState === 'LOADING' ? 'Reading Retained Priority…' : 'No Qualified Candidates Retained'}
            </h3>
            <p className="font-body-sm text-body-sm text-outline mt-1 max-w-md mx-auto">
              {rankingMessage ||
                'This current snapshot has no qualifying candidates. Refresh only reads stored evidence from the server.'}
            </p>
            {rankingUiState !== 'LOADING' && (
              <button
                type="button"
                onClick={() => refreshData()}
                className="mt-space-md px-4 py-1.5 rounded bg-surface-container-high hover:bg-surface-bright text-primary border border-outline-variant text-xs font-mono font-semibold"
              >
                Retry stored evidence
              </button>
            )}
          </div>
        ) : filteredRows.length === 0 ? (
          <div className="bg-surface-container-low border border-outline-variant/40 rounded-xl p-space-lg text-center my-4">
            <h3 className="font-headline-md text-headline-md font-bold text-on-surface">
              No Candidates Match Current Filters
            </h3>
            <p className="font-body-sm text-body-sm text-outline mt-1">
              Try adjusting symbol search, direction, or strategy filters. Filters inspect the entire verified snapshot.
            </p>
            <button
              type="button"
              onClick={handleResetFilters}
              className="mt-space-md px-3 py-1.5 rounded bg-primary-container text-on-primary-container font-mono text-xs font-semibold"
            >
              Clear filters
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-outline-variant/40 bg-surface-container-low shadow-sm">
            <table className="w-full text-left border-collapse" aria-label="Opportunities ranking table">
              <thead>
                <tr className="border-b border-outline-variant/40 bg-surface-container-lowest text-[11px] font-mono text-outline uppercase tracking-wider">
                  <th scope="col" className="py-2.5 px-3">Rank / Change</th>
                  <th scope="col" className="py-2.5 px-3">Instrument</th>
                  <th scope="col" className="py-2.5 px-3">Strategy</th>
                  <th scope="col" className="py-2.5 px-3">Direction</th>
                  <th scope="col" className="py-2.5 px-3 text-right">Setup Quality</th>
                  <th scope="col" className="py-2.5 px-3 text-right">Gross T1 R:R</th>
                  <th scope="col" className="py-2.5 px-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/20 font-mono text-xs">
                {pagedRows.map((candidate) => {
                  const isSelected = selectedKey === candidate.opportunity_key;
                  const strategyName = STRATEGY_NAMES[candidate.strategy_id] || candidate.strategy_id;
                  const quality = candidate.score_components?.rule_quality;
                  const rr = candidate.score_components?.actual_target1_rr;

                  return (
                    <tr
                      key={candidate.opportunity_key}
                      className={`transition-colors cursor-pointer ${
                        isSelected
                          ? 'bg-surface-container-high border-l-4 border-l-primary'
                          : 'hover:bg-surface-container/60'
                      }`}
                      onClick={() => selectCandidate(candidate)}
                    >
                      {/* Rank & Change */}
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-primary">#{candidate.rank}</span>
                          <span className="text-[10px] text-outline">
                            {candidate.previous_rank !== null ? `(prior #${candidate.previous_rank})` : '(new)'}
                          </span>
                        </div>
                      </td>

                      {/* Instrument Symbol & Watermark */}
                      <td className="py-3 px-3">
                        <div className="flex flex-col">
                          <span className="font-bold text-on-surface text-sm">{candidate.symbol}</span>
                          <span className="text-[10px] text-outline">
                            {formatIstTime(candidate.source_data_watermark)}
                          </span>
                        </div>
                      </td>

                      {/* Strategy */}
                      <td className="py-3 px-3 font-sans text-on-surface-variant font-medium">
                        {strategyName}
                      </td>

                      {/* Direction */}
                      <td className="py-3 px-3">
                        <StatusBadge
                          variant={candidate.direction === 'LONG' ? 'LONG' : 'SHORT'}
                          label={candidate.direction}
                        />
                      </td>

                      {/* Setup Quality */}
                      <td className="py-3 px-3 text-right">
                        <span className="text-primary font-bold">{formatInr(quality)}</span>
                        <span className="text-outline text-[10px]"> / 100</span>
                      </td>

                      {/* Gross T1 R:R */}
                      <td className="py-3 px-3 text-right font-bold text-on-surface">
                        1:{formatInr(rr)}
                      </td>

                      {/* Action */}
                      <td className="py-3 px-3 text-center">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            selectCandidate(candidate);
                          }}
                          className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-colors border ${
                            isSelected
                              ? 'bg-primary text-on-primary border-primary'
                              : 'bg-surface-container-high text-primary border-outline-variant hover:bg-surface-bright'
                          }`}
                          aria-label={`Inspect ${candidate.symbol}`}
                        >
                          {isSelected ? 'Viewing' : 'Inspect'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* 4. Pagination Bar */}
        {filteredRows.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-space-sm pt-space-xs text-xs font-mono">
            <div className="flex items-center gap-space-sm">
              <button
                type="button"
                onClick={() => setPage(Math.max(0, currentPage - 1))}
                disabled={currentPage === 0}
                className="px-3 py-1 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface border border-outline-variant/40 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ← Previous
              </button>
              <button
                type="button"
                onClick={() => setPage(Math.min(totalPages - 1, currentPage + 1))}
                disabled={currentPage >= totalPages - 1}
                className="px-3 py-1 rounded bg-surface-container-high hover:bg-surface-bright text-on-surface border border-outline-variant/40 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Next →
              </button>
            </div>

            <div className="text-outline">
              Page <span className="text-on-surface font-bold">{currentPage + 1}</span> of{' '}
              <span className="text-on-surface font-bold">{totalPages}</span> ·{' '}
              <span className="text-primary font-bold">{filteredRows.length}</span> matching /{' '}
              <span>{rankingRows.length}</span> retained candidates
            </div>
          </div>
        )}

        {/* 5. Integrity & Regulatory Footnote */}
        <p className="text-[11px] text-outline font-mono leading-relaxed pt-space-xs border-t border-outline-variant/20">
          Setup Quality evaluates detector rules, not a win probability. Gross R:R reflects price level geometry; net executable reward requires dated spreads and broker cost models. Canonical rank order is strictly server-determined and immutable.
        </p>
      </div>

      {/* 6. X-Ray Detail Drawer */}
      <XRayDrawer />
    </div>
  );
};

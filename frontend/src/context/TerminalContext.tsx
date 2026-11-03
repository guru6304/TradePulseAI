import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import type {
  HealthResponse,
  ConfigResponse,
  RankingResponse,
  RankingRow,
  PaperPortfolioResponse,
} from '../types/api';
import { apiClient } from '../api/client';
import { collectRankingSnapshot } from '../api/snapshot-collector';

export type TerminalRoute =
  | 'pulse'
  | 'opportunities'
  | 'options'
  | 'strategies'
  | 'paper'
  | 'health'
  | 'admin-research';

export type RankingUiState =
  | 'LOADING'
  | 'CURRENT'
  | 'ARCHIVED'
  | 'EMPTY'
  | 'UNAVAILABLE'
  | 'ERROR';

export interface TerminalContextValue {
  route: TerminalRoute;
  setRoute: (route: TerminalRoute) => void;
  health: HealthResponse | null;
  config: ConfigResponse | null;
  ranks: RankingResponse | null;
  rankingRows: RankingRow[];
  rankingUiState: RankingUiState;
  rankingMessage: string;
  selectedCandidate: RankingRow | null;
  selectedKey: string | null;
  paperPortfolio: PaperPortfolioResponse | null;
  isRefreshing: boolean;
  filterQuery: string;
  setFilterQuery: (q: string) => void;
  filterDirection: string;
  setFilterDirection: (d: string) => void;
  filterStrategy: string;
  setFilterStrategy: (s: string) => void;
  filterStatus: string;
  setFilterStatus: (st: string) => void;
  selectCandidate: (candidate: RankingRow | null) => void;
  closeDetail: () => void;
  refreshData: () => Promise<void>;
  detailState: 'CLOSED' | 'LOADING' | 'CURRENT' | 'UNAVAILABLE';
  setDetailState: (state: 'CLOSED' | 'LOADING' | 'CURRENT' | 'UNAVAILABLE') => void;
}

const TerminalContext = createContext<TerminalContextValue | undefined>(undefined);

export const STRATEGY_NAMES: Record<string, string> = {
  strat_1_order_block: 'Order Block / BOS / FVG',
  strat_2_vwap_pullback: 'VWAP Pullback',
  strat_3_option_apex_oi: 'Option Apex OI Shift',
  strat_4_orb_filtered: 'Opening Range Breakout',
  strat_5_supertrend_pullback: 'Supertrend Pullback',
};

export const TerminalProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [route, setRouteState] = useState<TerminalRoute>('pulse');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [ranks, setRanks] = useState<RankingResponse | null>(null);
  const [rankingRows, setRankingRows] = useState<RankingRow[]>([]);
  const [rankingUiState, setRankingUiState] = useState<RankingUiState>('LOADING');
  const [rankingMessage, setRankingMessage] = useState<string>('Reading retained priority…');
  const [selectedCandidate, setSelectedCandidate] = useState<RankingRow | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [paperPortfolio, setPaperPortfolio] = useState<PaperPortfolioResponse | null>(null);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [detailState, setDetailState] = useState<'CLOSED' | 'LOADING' | 'CURRENT' | 'UNAVAILABLE'>('CLOSED');

  // Filters
  const [filterQuery, setFilterQuery] = useState<string>('');
  const [filterDirection, setFilterDirection] = useState<string>('');
  const [filterStrategy, setFilterStrategy] = useState<string>('');
  const [filterStatus, setFilterStatus] = useState<string>('');

  const generationRef = useRef<number>(0);
  const activeControllersRef = useRef<Set<AbortController>>(new Set());
  const expiryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync hash with route state
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace(/^#\/?/, '').split('?')[0];
      const validRoutes: TerminalRoute[] = [
        'pulse',
        'opportunities',
        'options',
        'strategies',
        'paper',
        'health',
        'admin-research',
      ];
      if (validRoutes.includes(hash as TerminalRoute)) {
        setRouteState(hash as TerminalRoute);
      } else {
        setRouteState('pulse');
        window.location.hash = '#/pulse';
      }
    };

    handleHashChange();
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const setRoute = useCallback((newRoute: TerminalRoute) => {
    window.location.hash = `#/${newRoute}`;
    setRouteState(newRoute);
  }, []);

  const selectCandidate = useCallback((candidate: RankingRow | null) => {
    setSelectedCandidate(candidate);
    setSelectedKey(candidate ? candidate.opportunity_key : null);
    if (candidate) {
      setDetailState('LOADING');
    } else {
      setDetailState('CLOSED');
    }
  }, []);

  const closeDetail = useCallback(() => {
    setSelectedCandidate(null);
    setSelectedKey(null);
    setDetailState('CLOSED');
  }, []);

  const refreshData = useCallback(async () => {
    const generation = ++generationRef.current;
    setIsRefreshing(true);

    if (expiryTimeoutRef.current) {
      clearTimeout(expiryTimeoutRef.current);
      expiryTimeoutRef.current = null;
    }

    // Cancel prior controllers
    for (const c of activeControllersRef.current) {
      c.abort();
    }
    activeControllersRef.current.clear();

    const controller = new AbortController();
    activeControllersRef.current.add(controller);

    try {
      // 1. Fetch Health and Config in parallel
      const [healthRes, configRes] = await Promise.allSettled([
        apiClient.getHealth({ signal: controller.signal }),
        apiClient.getConfig({ signal: controller.signal }),
      ]);

      if (generation !== generationRef.current) return;

      if (healthRes.status === 'fulfilled') {
        setHealth(healthRes.value);
        // If health has a paper account id, read paper portfolio
        const accountId = healthRes.value.paper_account_id;
        if (accountId) {
          try {
            const paperRes = await apiClient.getPaperPortfolio(accountId, { signal: controller.signal });
            if (generation === generationRef.current) {
              setPaperPortfolio(paperRes);
            }
          } catch {
            if (generation === generationRef.current) {
              setPaperPortfolio(null);
            }
          }
        } else {
          setPaperPortfolio(null);
        }
      }

      if (configRes.status === 'fulfilled') {
        setConfig(configRes.value);
      }

      // 2. Collect Opportunity Rankings Snapshot with strict verification
      setRankingUiState('LOADING');
      setRankingMessage('Reading retained candidate priority…');

      const snapshotResult = await collectRankingSnapshot({
        signal: controller.signal,
        currentGeneration: generation,
        getGeneration: () => generationRef.current,
      });

      if (generation !== generationRef.current || !snapshotResult) return;

      const { data, rows, deadline } = snapshotResult;
      setRanks(data);
      setRankingRows(rows);

      if (data.status === 'CURRENT_CANDIDATE_PRIORITY') {
        if (rows.length === 0) {
          setRankingUiState('EMPTY');
          setRankingMessage('The latest stored scan has no qualifying candidate.');
        } else {
          setRankingUiState('CURRENT');
          setRankingMessage(`Retained candidate priority · ${rows.length} qualified candidate(s)`);
        }

        // Re-evaluate selected candidate: preserve if present, invalidate if removed
        if (selectedKey) {
          const matched = rows.find((r) => r.opportunity_key === selectedKey);
          if (matched) {
            setSelectedCandidate(matched);
          } else {
            setSelectedCandidate(null);
            setSelectedKey(null);
            setDetailState('UNAVAILABLE');
          }
        }

        // Schedule expiry if deadline is finite
        if (deadline && Number.isFinite(deadline)) {
          const remainingMs = deadline - performance.now();
          if (remainingMs > 0) {
            expiryTimeoutRef.current = setTimeout(() => {
              if (generation === generationRef.current) {
                setRankingUiState('ARCHIVED');
                setRankingMessage('Snapshot lifetime expired · showing retained historical evidence.');
                // Invalidate selected X-Ray price evidence on expiry
                setDetailState('UNAVAILABLE');
              }
            }, remainingMs);
          } else {
            setRankingUiState('ARCHIVED');
            setRankingMessage('Retained priority snapshot is expired.');
          }
        }
      } else if (data.status === 'RANKING_UNAVAILABLE_NO_DURABLE_SCAN') {
        setRankingUiState('UNAVAILABLE');
        setRankingMessage('No durable candidate ranking scan is currently available.');
      } else {
        setRankingUiState('ARCHIVED');
        setRankingMessage(`Retained ranking is archived (${data.status}).`);
      }
    } catch (err: unknown) {
      if (generation !== generationRef.current) return;
      setRankingUiState('ERROR');
      const msg = err instanceof Error ? err.message : 'Priority could not be verified.';
      setRankingMessage(msg);
      setRanks(null);
      setRankingRows([]);
      if (selectedKey) {
        setSelectedCandidate(null);
        setSelectedKey(null);
        setDetailState('UNAVAILABLE');
      }
    } finally {
      if (generation === generationRef.current) {
        setIsRefreshing(false);
        activeControllersRef.current.delete(controller);
      }
    }
  }, [selectedKey]);

  // Initial load
  useEffect(() => {
    refreshData();
    return () => {
      if (expiryTimeoutRef.current) {
        clearTimeout(expiryTimeoutRef.current);
      }
      for (const c of activeControllersRef.current) {
        c.abort();
      }
    };
  }, []);

  return (
    <TerminalContext.Provider
      value={{
        route,
        setRoute,
        health,
        config,
        ranks,
        rankingRows,
        rankingUiState,
        rankingMessage,
        selectedCandidate,
        selectedKey,
        paperPortfolio,
        isRefreshing,
        filterQuery,
        setFilterQuery,
        filterDirection,
        setFilterDirection,
        filterStrategy,
        setFilterStrategy,
        filterStatus,
        setFilterStatus,
        selectCandidate,
        closeDetail,
        refreshData,
        detailState,
        setDetailState,
      }}
    >
      {children}
    </TerminalContext.Provider>
  );
};

export const useTerminal = (): TerminalContextValue => {
  const context = useContext(TerminalContext);
  if (!context) {
    throw new Error('useTerminal must be used within a TerminalProvider');
  }
  return context;
};

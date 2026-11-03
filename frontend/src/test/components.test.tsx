import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from '../App';
import { apiClient } from '../api/client';
import type {
  HealthResponse,
  RankingResponse,
  RankingRow,
  SignalListResponse,
  ScanLineageResponse,
  CashCandlesResponse,
  PaperPortfolioResponse,
} from '../types/api';

describe('React Terminal Components', () => {
  const dummySha = 'c'.repeat(64);
  const scope = {
    provider: 'paper_sim',
    data_mode: 'SIMULATED' as const,
    segment: 'NSE_EQUITY_INTRADAY',
    profile_digest: dummySha,
  };

  const mockHealth: HealthResponse = {
    status: 'ok',
    broker: {
      active_broker: 'paper_sim',
      connection_state: 'SIMULATED',
      data_mode: 'SIMULATED',
      is_simulated: true,
      connectivity_verified: true,
      last_verified_at_ist: '2026-10-31 09:15:00',
    },
    database: { status: 'ok' },
    scheduler: {
      running: true,
      session_open: true,
      session_state: 'OPEN',
      scan_interval_seconds: 300,
      cycles_executed: 5,
    },
    last_scan: {
      run_id: 'run_20261031_0915',
      scan_status: 'COMPLETED',
      started_at_ist: '2026-10-31 09:15:00',
      completed_at_ist: '2026-10-31 09:15:05',
      duration_ms: 120,
      total_signals: 2,
    },
    paper_account_id: 'paper_act_1',
    operations: {
      scope: 'LOCAL_OPERATIONAL_OBSERVATIONS',
      alerts: [],
      real_delivery_enabled: false,
    },
    live_acceptance: { accepted: false, by_symbol: {} },
    evidence_scope: 'DETERMINISTIC_OFFLINE_DEMO',
  };

  const mockRanking: RankingResponse = {
    status: 'CURRENT_CANDIDATE_PRIORITY',
    actionable: false,
    scope,
    as_of: '2026-10-31T09:15:05+05:30',
    current_rows: [
      {
        opportunity_key: 'key_rel_1',
        candidate_id: 'cand_rel_1',
        symbol: 'RELIANCE',
        strategy_id: 'strat_1_order_block',
        position_type: 'LONG_EQUITY_INTRADAY',
        direction: 'LONG',
        source_data_watermark: '2026-10-31T09:15:00+05:30',
        source_digest: dummySha,
        priority_scope: 'QUALIFIED_SCANNER_CANDIDATE_ONLY',
        instrument_identity: {
          provider: 'paper_sim',
          identifier: '2885',
          symbol: 'RELIANCE',
          exchange: 'NSE',
          segment: 'NSE_EQUITY_INTRADAY',
          instrument_type: 'EQ',
          is_index: false,
        },
        score_components: {
          rule_quality: 92,
          actual_target1_rr: 2.8,
        },
        component_versions: {
          rule_quality: 'EXISTING_EVALUATOR_V1',
          actual_target1_rr: 'PRICE_LEVEL_GEOMETRY_V1',
        },
        missing_components: ['RELATIVE_STRENGTH', 'SECTOR'],
        rank: 1,
        previous_rank: null,
        rank_change_reason: 'NEWLY_QUALIFIED',
        component_changes: {},
        actionable: false,
      },
    ],
    historical_rows: [],
    pagination: { offset: 0, limit: 100, total: 1 },
    snapshot: {
      policy: 'CASH_QUALITY_ACTUAL_RR_DIRECTION_ONE_SYMBOL_V2',
      rank_version: dummySha,
      previous_rank_version: null,
      valid_until: '2026-10-31T09:21:00+05:30',
      evidence_scope: 'DETERMINISTIC_OFFLINE_DEMO',
      run_id: 'run_20261031_0915',
      work_id: 'work_1',
      reference: '2026-10-31T09:15:00+05:30',
      scope,
      previous_snapshot: null,
      source_authenticity: 'NOT_ESTABLISHED',
      source_data_watermarks: ['2026-10-31T09:15:00+05:30'],
      source_data_watermark_count: 1,
      exclusions: [],
      exclusion_count: 0,
      removals: [],
      removal_count: 0,
      metadata_preview_limit: 100,
      exclusions_truncated: false,
      removals_truncated: false,
      source_data_watermarks_truncated: false,
    },
  };

  const mockSignals: SignalListResponse = {
    status: 'ok',
    total_count: 1,
    limit: 200,
    offset: 0,
    items: [
      {
        id: 101,
        dedup_key: 'cand_rel_1',
        symbol: 'RELIANCE',
        segment: 'NSE_EQUITY_INTRADAY',
        strategy_id: 'strat_1_order_block',
        strategy_name: 'Order Block / BOS / FVG',
        direction: 'LONG',
        position_type: 'LONG_EQUITY_INTRADAY',
        instrument_label: 'RELIANCE EQ',
        entry_price: 2845.5,
        entry_zone_low: 2820.0,
        entry_zone_high: 2845.5,
        stop_loss: 2810.0,
        invalidation_level: 2805.0,
        target_1: 2940.0,
        target_2: 3000.0,
        capital_risk_inr: 1500.0,
        est_charges_inr: 45.0,
        risk_reward: '1:2.8',
        rationale: 'Confirmed bullish Order Block and FVG mitigation in completed 5m candle.',
        timestamp: '2026-10-31 09:15:00',
        quality_score: 92,
        confidence_pct: 92,
        position_qty: 42,
        is_simulated: true,
        data_mode: 'SIMULATED',
        broker: 'paper_sim',
        created_at_ist: '2026-10-31 09:15:05',
        actionable: false,
        instrument_identity: {
          provider: 'paper_sim',
          identifier: '2885',
          symbol: 'RELIANCE',
          exchange: 'NSE',
          segment: 'NSE_EQUITY_INTRADAY',
          instrument_type: 'EQ',
          is_index: false,
        },
        score_breakdown: {},
        paper_decision: {
          status: 'REJECTED',
          reason_code: 'CONFLICTING_OPEN_POSITION',
          position_id: null,
          account_id: 'paper_act_1',
          candidate_id: 'cand_rel_1',
          trigger_contract: { rule_id: 'rule_ob_1' },
          trigger_timestamp_ist: '2026-10-31 09:15:02',
        },
        recommendation_status: 'PAPER_REJECTED',
      },
    ],
  };

  const mockLineage: ScanLineageResponse = {
    run_id: 'run_20261031_0915',
    status: 'COMMITTED',
    work_id: 'work_1',
    version: '1.0.0',
    reference: '2026-10-31 09:15:00',
    code_digest: dummySha,
    profile_digest: dummySha,
    source_authenticity: 'NOT_ESTABLISHED',
    historical_replay_allowed: false,
    current_live_acceptance: false,
    batches: [
      {
        batch_id: 'batch_rel_1',
        identity: {
          provider: 'paper_sim',
          identifier: '2885',
          symbol: 'RELIANCE',
          exchange: 'NSE',
          segment: 'NSE_EQUITY_INTRADAY',
          instrument_type: 'EQ',
          is_index: false,
        },
        interval_min: 5,
        candle_count: 2,
        first_timestamp: '2026-10-31 09:10:00',
        last_timestamp: '2026-10-31 09:15:00',
        validation: {},
        retrieved_at: '2026-10-31 09:15:01',
        source_observation_at: null,
      },
    ],
  };

  const mockCandles: CashCandlesResponse = {
    status: 'ok',
    run_id: 'run_20261031_0915',
    batch_id: 'batch_rel_1',
    total_count: 2,
    limit: 100,
    offset: 0,
    items: [
      {
        timestamp: '2026-10-31 09:10:00',
        open: 2830.0,
        high: 2842.0,
        low: 2825.0,
        close: 2838.0,
        volume: 12500,
        interval_min: 5,
        is_complete: true,
      },
      {
        timestamp: '2026-10-31 09:15:00',
        open: 2838.0,
        high: 2850.0,
        low: 2835.0,
        close: 2845.5,
        volume: 24000,
        interval_min: 5,
        is_complete: true,
      },
    ],
  };

  const mockPaperPortfolio: PaperPortfolioResponse = {
    status: 'OK',
    account_id: 'paper_primary',
    run_id: 'run_20261031_0915',
    config_hash: 'a'.repeat(64),
    provider: 'paper_sim',
    source_data_mode: 'SIMULATED',
    execution_mode: 'SIMULATED',
    fill_policy: 'NEXT_TICK',
    as_of_ist: '2026-10-31 09:15:00+05:30',
    reconciliation: {
      status: 'OK',
      errors: [],
    },
    accounting: {
      starting_capital_inr: 1000000,
      realized_net_pnl_inr: 12500,
      unrealized_net_pnl_inr: 3200,
      equity_inr: 1015700,
      reserved_capital_inr: 200000,
      available_capital_inr: 815700,
      gross_exposure_inr: 200000,
      fees_paid_inr: 120,
      slippage_paid_inr: 80,
      open_positions: 1,
      closed_positions: 2,
    },
    positions: [],
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    window.location.hash = '#/pulse';

    vi.spyOn(apiClient, 'getHealth').mockResolvedValue(mockHealth);
    vi.spyOn(apiClient, 'getConfig').mockResolvedValue({
      status: 'ok',
      config: {},
      broker_status: mockHealth.broker,
      scheduler: mockHealth.scheduler,
    });
    vi.spyOn(apiClient, 'getOpportunityRankings').mockResolvedValue(mockRanking);
    vi.spyOn(apiClient, 'getSignals').mockResolvedValue(mockSignals);
    vi.spyOn(apiClient, 'getScanLineage').mockResolvedValue(mockLineage);
    vi.spyOn(apiClient, 'getCashCandles').mockResolvedValue(mockCandles);
    vi.spyOn(apiClient, 'getPaperPortfolio').mockResolvedValue(mockPaperPortfolio);
  });

  it('renders application shell, security protocol banner, and Pulse view', async () => {
    render(<App />);

    expect(await screen.findByText(/RESEARCH \/ PAPER ONLY/i)).toBeInTheDocument();
    const demoBanners = await screen.findAllByText(/SYNTHETIC DEMO ONLY/i);
    expect(demoBanners.length).toBeGreaterThan(0);
    expect(screen.getByText(/The Opportunity Shortlist/i)).toBeInTheDocument();
    const relianceElements = await screen.findAllByText('RELIANCE');
    expect(relianceElements.length).toBeGreaterThan(0);
    expect(screen.getByText(/#1 PRIORITY/i)).toBeInTheDocument();
  });

  it('navigates to Opportunities view, lists qualified candidates, and opens X-Ray', async () => {
    render(<App />);

    await waitFor(async () => {
      const items = await screen.findAllByText('RELIANCE');
      expect(items.length).toBeGreaterThan(0);
    });

    // Switch hash to opportunities
    fireEvent.click(screen.getByRole('button', { name: /View all \(1\) →/i }));

    expect(await screen.findByRole('table', { name: /Opportunities ranking table/i })).toBeInTheDocument();
    expect(screen.getByText(/Rank \/ Change/i)).toBeInTheDocument();

    // Inspect RELIANCE
    const inspectBtn = screen.getByRole('button', { name: /Inspect RELIANCE/i });
    fireEvent.click(inspectBtn);

    // X-Ray dialog should open
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/Retained 5-Minute Candles/i)).toBeInTheDocument();
    expect(screen.getByText(/ZERO LOOKAHEAD BIAS/i)).toBeInTheDocument();

    // Switch to Strategy Geometry tab
    fireEvent.click(screen.getByRole('button', { name: /Strategy Geometry/i }));
    expect(screen.getByText(/Decision Reference/i)).toBeInTheDocument();
    expect(screen.getAllByText(/2,845/i).length).toBeGreaterThan(0);

    // Switch to Diagnostics tab and verify CONFLICTING_OPEN_POSITION reason
    fireEvent.click(screen.getByRole('button', { name: /Paper & Lineage/i }));
    expect(screen.getByText('CONFLICTING_OPEN_POSITION')).toBeInTheDocument();
  });

  it('displays UNAVAILABLE in X-Ray drawer when signal cannot be proven or joined', async () => {
    // When getSignals returns empty items (join cannot be proven)
    vi.spyOn(apiClient, 'getSignals').mockResolvedValue({
      status: 'ok',
      total_count: 0,
      limit: 200,
      offset: 0,
      items: [],
    });

    render(<App />);

    await waitFor(async () => {
      const items = await screen.findAllByText('RELIANCE');
      expect(items.length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByRole('button', { name: /View all \(1\) →/i }));
    const inspectBtn = await screen.findByRole('button', { name: /Inspect RELIANCE/i });
    fireEvent.click(inspectBtn);

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(
      await screen.findByText(/The selected rank could not be uniquely matched to retained signal identity/i)
    ).toBeInTheDocument();
  });

  it('displays truthful unconfigured paper portfolio notice when account_id is null', async () => {
    vi.spyOn(apiClient, 'getHealth').mockResolvedValue({
      ...mockHealth,
      paper_account_id: null,
    });
    vi.spyOn(apiClient, 'getPaperAccounts').mockResolvedValue({
      status: 'ok',
      execution_mode: 'SIMULATED',
      accounts: [],
      next_cursor: null,
      through_sequence: 0,
      truncated: false,
    });

    render(<App />);

    fireEvent.click(screen.getByRole('link', { name: /Paper Portfolio/i }));

    expect(await screen.findByText(/No Reconciled Paper Account/i)).toBeInTheDocument();
    expect(screen.getByText(/Virtual simulated trading requires a configured and reconciled paper account/i)).toBeInTheDocument();
  });

  it('closes X-Ray drawer with Escape key and backdrop click', async () => {
    render(<App />);

    await waitFor(async () => {
      const items = await screen.findAllByText('RELIANCE');
      expect(items.length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByRole('button', { name: /View all \(1\) →/i }));
    const inspectBtn = await screen.findByRole('button', { name: /Inspect RELIANCE/i });
    fireEvent.click(inspectBtn);

    expect(await screen.findByRole('dialog')).toBeInTheDocument();

    // Press Escape key to close
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    // Re-open and close with backdrop click
    fireEvent.click(inspectBtn);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();

    const backdrop = document.querySelector('.backdrop-blur-xs');
    expect(backdrop).toBeInTheDocument();
    if (backdrop) {
      fireEvent.click(backdrop);
    }

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('preserves strict server ranking order and scores without client recomputation', async () => {
    const multiRankResponse: RankingResponse = {
      ...mockRanking,
      pagination: { offset: 0, limit: 100, total: 3 },
      current_rows: [
        {
          ...mockRanking.current_rows[0],
          rank: 1,
          symbol: 'RELIANCE',
          instrument_identity: {
            ...mockRanking.current_rows[0].instrument_identity,
            symbol: 'RELIANCE',
            identifier: '2885',
          },
          score_components: { rule_quality: 92, actual_target1_rr: 2.34 },
        },
        {
          ...mockRanking.current_rows[0],
          opportunity_key: 'opp-tcs-002',
          candidate_id: 'cand-tcs-002',
          rank: 2,
          symbol: 'TCS',
          instrument_identity: {
            ...mockRanking.current_rows[0].instrument_identity,
            symbol: 'TCS',
            identifier: '11536',
          },
          score_components: { rule_quality: 85, actual_target1_rr: 1.85 },
        },
        {
          ...mockRanking.current_rows[0],
          opportunity_key: 'opp-infy-003',
          candidate_id: 'cand-infy-003',
          rank: 3,
          symbol: 'INFY',
          instrument_identity: {
            ...mockRanking.current_rows[0].instrument_identity,
            symbol: 'INFY',
            identifier: '1594',
          },
          score_components: { rule_quality: 78, actual_target1_rr: 1.45 },
        },
      ],
    };

    vi.spyOn(apiClient, 'getOpportunityRankings').mockResolvedValue(multiRankResponse);

    render(<App />);

    fireEvent.click(screen.getByRole('link', { name: /Opportunities/i }));

    expect(await screen.findByRole('table', { name: /Opportunities ranking table/i })).toBeInTheDocument();

    const rows = screen.getAllByRole('row');
    // Header is row 0; data rows are 1, 2, 3
    expect(rows[1]).toHaveTextContent('#1');
    expect(rows[1]).toHaveTextContent('RELIANCE');
    expect(rows[1]).toHaveTextContent('92');
    expect(rows[1]).toHaveTextContent('1:2.34');

    expect(rows[2]).toHaveTextContent('#2');
    expect(rows[2]).toHaveTextContent('TCS');
    expect(rows[2]).toHaveTextContent('85');
    expect(rows[2]).toHaveTextContent('1:1.85');

    expect(rows[3]).toHaveTextContent('#3');
    expect(rows[3]).toHaveTextContent('INFY');
    expect(rows[3]).toHaveTextContent('78');
    expect(rows[3]).toHaveTextContent('1:1.45');
  });

  it('verifies 20-row client pagination controls and boundary disabled states', async () => {
    // Generate 25 synthetic ranking rows with valid, unique identities
    const twentyFiveRows: RankingRow[] = Array.from({ length: 25 }, (_, i) => ({
      ...mockRanking.current_rows[0],
      opportunity_key: `opp-key-${i + 1}`,
      candidate_id: `cand-${i + 1}`,
      symbol: `SYM${i + 1}`,
      rank: i + 1,
      instrument_identity: {
        ...mockRanking.current_rows[0].instrument_identity,
        symbol: `SYM${i + 1}`,
        identifier: String(2000 + i + 1),
      },
    }));

    vi.spyOn(apiClient, 'getOpportunityRankings').mockResolvedValue({
      ...mockRanking,
      pagination: { offset: 0, limit: 100, total: 25 },
      current_rows: twentyFiveRows,
    });

    render(<App />);

    fireEvent.click(screen.getByRole('link', { name: /Opportunities/i }));

    expect(await screen.findByRole('table', { name: /Opportunities ranking table/i })).toBeInTheDocument();

    // On page 1: SYM1 is visible, SYM25 is not
    expect(screen.getByText('SYM1')).toBeInTheDocument();
    expect(screen.getByText('SYM20')).toBeInTheDocument();
    expect(screen.queryByText('SYM21')).not.toBeInTheDocument();

    const prevBtn = screen.getByRole('button', { name: /← Previous/i });
    const nextBtn = screen.getByRole('button', { name: /Next →/i });

    expect(prevBtn).toBeDisabled();
    expect(nextBtn).toBeEnabled();
    expect(screen.getByTestId('pagination-info')).toHaveTextContent('Page 1 of 2');

    // Click Next
    fireEvent.click(nextBtn);

    expect(screen.getByText('SYM21')).toBeInTheDocument();
    expect(screen.getByText('SYM25')).toBeInTheDocument();
    expect(screen.queryByText('SYM1')).not.toBeInTheDocument();
    expect(screen.getByTestId('pagination-info')).toHaveTextContent('Page 2 of 2');

    expect(prevBtn).toBeEnabled();
    expect(nextBtn).toBeDisabled();
  });

  it('verifies paper trading displays remain strictly read-only with zero order buttons', async () => {
    render(<App />);

    fireEvent.click(screen.getByRole('link', { name: /Paper Portfolio/i }));

    expect(await screen.findByRole('heading', { name: /Paper Portfolio/i })).toBeInTheDocument();
    expect(screen.getByText(/Starting Capital/i)).toBeInTheDocument();
    expect(screen.getByText(/Current Equity/i)).toBeInTheDocument();

    // Verify zero order or trading buttons
    const buttons = screen.getAllByRole('button');
    const forbiddenPatterns = [/buy/i, /sell/i, /order/i, /place order/i, /simulate paper entry/i, /execute/i];

    for (const btn of buttons) {
      const text = btn.textContent || '';
      for (const pattern of forbiddenPatterns) {
        expect(text).not.toMatch(pattern);
      }
    }
  });

  it('verifies responsive mobile navigation and more popover sheet', async () => {
    render(<App />);

    // Mobile bottom nav should have Pulse, Opps, Options, Paper, More
    const bottomNav = screen.getByRole('navigation', { name: /Mobile Bottom Navigation/i });
    expect(bottomNav).toBeInTheDocument();

    const moreBtn = screen.getByRole('button', { name: /More destinations/i });
    expect(moreBtn).toBeInTheDocument();

    // Open More popover
    fireEvent.click(moreBtn);

    // Popover contains Strategies, Health, Admin Research
    expect(await screen.findByRole('menuitem', { name: /Strategies & Research/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Health & Settings/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Admin Research/i })).toBeInTheDocument();
  });
});

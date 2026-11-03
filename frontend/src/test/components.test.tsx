import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from '../App';
import { apiClient } from '../api/client';
import type { HealthResponse, RankingResponse, SignalListResponse, ScanLineageResponse, CashCandlesResponse } from '../types/api';

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
    vi.spyOn(apiClient, 'getSignals').mockResolvedValueOnce({
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
    vi.spyOn(apiClient, 'getHealth').mockResolvedValueOnce({
      ...mockHealth,
      paper_account_id: null,
    });
    vi.spyOn(apiClient, 'getPaperAccounts').mockResolvedValueOnce({
      status: 'ok',
      execution_mode: 'SIMULATED',
      accounts: [],
      next_cursor: null,
      through_sequence: 0,
      truncated: false,
    });

    render(<App />);

    window.location.hash = '#/paper';
    fireEvent(window, new HashChangeEvent('hashchange'));

    expect(await screen.findByText(/No Reconciled Paper Account/i)).toBeInTheDocument();
    expect(screen.getByText(/Virtual simulated trading requires a configured and reconciled paper account/i)).toBeInTheDocument();
  });
});

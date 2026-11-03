import { describe, it, expect, vi, beforeEach } from 'vitest';
import { collectRankingSnapshot } from '../api/snapshot-collector';
import { apiClient } from '../api/client';
import type { RankingResponse, RankingRow } from '../types/api';

describe('collectRankingSnapshot', () => {
  const dummySha = 'a'.repeat(64);
  const scope = {
    provider: 'angel_one',
    data_mode: 'LIVE' as const,
    segment: 'NSE_EQUITY_INTRADAY',
    profile_digest: dummySha,
  };

  const createRow = (rank: number, symbol: string): RankingRow => ({
    opportunity_key: `key_${rank}_${symbol}`,
    candidate_id: `cand_${rank}_${symbol}`,
    symbol,
    strategy_id: 'strat_1_order_block',
    position_type: 'LONG_EQUITY_INTRADAY',
    direction: 'LONG',
    source_data_watermark: '2026-10-31T09:15:00+05:30',
    source_digest: dummySha,
    priority_scope: 'QUALIFIED_SCANNER_CANDIDATE_ONLY',
    instrument_identity: {
      provider: 'angel_one',
      identifier: `id_${symbol}`,
      symbol,
      exchange: 'NSE',
      segment: 'NSE_EQUITY_INTRADAY',
      instrument_type: 'EQ',
      is_index: false,
    },
    score_components: {
      rule_quality: 90 - rank,
      actual_target1_rr: 2.5,
    },
    component_versions: {
      rule_quality: 'EXISTING_EVALUATOR_V1',
      actual_target1_rr: 'PRICE_LEVEL_GEOMETRY_V1',
    },
    missing_components: [],
    rank,
    previous_rank: null,
    rank_change_reason: 'NEWLY_QUALIFIED',
    component_changes: {},
    actionable: false,
  });

  const createSnapshotResponse = (
    offset: number,
    limit: number,
    total: number,
    rows: RankingRow[]
  ): RankingResponse => ({
    status: 'CURRENT_CANDIDATE_PRIORITY',
    actionable: false,
    scope,
    as_of: '2026-10-31T09:15:05+05:30',
    current_rows: rows,
    historical_rows: [],
    pagination: { offset, limit, total },
    snapshot: {
      policy: 'CASH_QUALITY_ACTUAL_RR_DIRECTION_ONE_SYMBOL_V2',
      rank_version: dummySha,
      previous_rank_version: null,
      valid_until: '2026-10-31T09:21:00+05:30',
      evidence_scope: 'DETERMINISTIC_OFFLINE_DEMO',
      run_id: 'run_20261031_0915',
      work_id: 'work_123',
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
  });

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('collects multi-page rankings with limit=100 pinning run_id', async () => {
    // 120 items total: page 0 has 100 items, page 1 has 20 items
    const page0Rows = Array.from({ length: 100 }, (_, i) => createRow(i + 1, `SYM_${i + 1}`));
    const page1Rows = Array.from({ length: 20 }, (_, i) => createRow(100 + i + 1, `SYM_${100 + i + 1}`));

    const spy = vi.spyOn(apiClient, 'getOpportunityRankings')
      .mockResolvedValueOnce(createSnapshotResponse(0, 100, 120, page0Rows))
      .mockResolvedValueOnce(createSnapshotResponse(100, 100, 120, page1Rows));

    const result = await collectRankingSnapshot();

    expect(result).not.toBeNull();
    expect(result?.rows.length).toBe(120);
    expect(spy).toHaveBeenCalledTimes(2);

    // Verify second request pinned run_id
    expect(spy.mock.calls[1][0]).toEqual({
      limit: 100,
      offset: 100,
      run_id: 'run_20261031_0915',
    });
  });

  it('rejects collection larger than 512 total rows', async () => {
    vi.spyOn(apiClient, 'getOpportunityRankings').mockResolvedValueOnce(
      createSnapshotResponse(0, 100, 513, [])
    );

    await expect(collectRankingSnapshot()).rejects.toThrow('Invalid ranking page schema or parameters');
  });

  it('rejects inconsistent snapshot versions across pages', async () => {
    const page0Rows = Array.from({ length: 100 }, (_, i) => createRow(i + 1, `SYM_${i + 1}`));
    const page1Rows = Array.from({ length: 20 }, (_, i) => createRow(100 + i + 1, `SYM_${100 + i + 1}`));

    const res0 = createSnapshotResponse(0, 100, 120, page0Rows);
    const res1 = createSnapshotResponse(100, 100, 120, page1Rows);
    // Mutate rank_version on second page to simulate a race/inconsistency
    res1.snapshot!.rank_version = 'b'.repeat(64);

    vi.spyOn(apiClient, 'getOpportunityRankings')
      .mockResolvedValueOnce(res0)
      .mockResolvedValueOnce(res1);

    await expect(collectRankingSnapshot()).rejects.toThrow('Inconsistent ranking pages detected');
  });

  it('rejects duplicate symbols in ranking snapshot (one setup per symbol rule)', async () => {
    const pageRows = [
      createRow(1, 'RELIANCE'),
      createRow(2, 'RELIANCE'), // Duplicate symbol!
    ];

    vi.spyOn(apiClient, 'getOpportunityRankings').mockResolvedValueOnce(
      createSnapshotResponse(0, 100, 2, pageRows)
    );

    await expect(collectRankingSnapshot()).rejects.toThrow('Invalid ranking row identity or ordering');
  });

  it('handles non-current status cleanly without error', async () => {
    const nonCurrentRes = createSnapshotResponse(0, 100, 0, []);
    nonCurrentRes.status = 'RANKING_UNAVAILABLE_NO_DURABLE_SCAN';

    vi.spyOn(apiClient, 'getOpportunityRankings').mockResolvedValueOnce(nonCurrentRes);

    const result = await collectRankingSnapshot();
    expect(result).not.toBeNull();
    expect(result?.rows.length).toBe(0);
    expect(result?.data.status).toBe('RANKING_UNAVAILABLE_NO_DURABLE_SCAN');
  });
});

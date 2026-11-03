/**
 * Complete Snapshot Collection and Retained Ranking Validator
 *
 * Implements strict multi-page retrieval pinned to a single run_id,
 * invariant verification, uniqueness checks, and deadline enforcement.
 */

import { apiClient, RequestOptions } from './client';
import type { RankingResponse, RankingRow } from '../types/api';
import { sourceTime, stableStringify } from '../utils/time';

export interface CollectedSnapshot {
  data: RankingResponse;
  rows: RankingRow[];
  deadline: number;
  lifetimeMs: number;
}

const HEX_REGEX = /^[a-f0-9]{64}$/;

function isHexSha256(val: unknown): val is string {
  return typeof val === 'string' && HEX_REGEX.test(val);
}

function isTrimmedString(val: unknown, maxLen = 160): val is string {
  return typeof val === 'string' && val.length > 0 && val.length <= maxLen && val.trim() === val;
}

export async function collectRankingSnapshot(
  options: RequestOptions & { currentGeneration?: number; getGeneration?: () => number } = {}
): Promise<CollectedSnapshot | { data: RankingResponse; rows: []; deadline: null; lifetimeMs: null } | null> {
  const rows: RankingRow[] = [];
  const keys = new Set<string>();
  const candidates = new Set<string>();
  const symbols = new Set<string>();
  const identities = new Set<string>();

  let firstData: RankingResponse | undefined;
  let binding: string | undefined;
  let total = 0;
  let deadline = Infinity;

  const isObsolete = () => {
    if (options.currentGeneration !== undefined && options.getGeneration) {
      return options.getGeneration() !== options.currentGeneration;
    }
    return false;
  };

  for (let offset = 0; offset === 0 || offset < total; offset += 100) {
    const sentTime = performance.now();
    const data = await apiClient.getOpportunityRankings(
      {
        limit: 100,
        offset,
        ...(firstData ? { run_id: firstData.snapshot?.run_id } : {}),
      },
      options
    );

    if (isObsolete()) return null;

    if (offset === 0 && data.status !== 'CURRENT_CANDIDATE_PRIORITY') {
      return { data, rows: [], deadline: null, lifetimeMs: null };
    }

    const page = data.pagination || { offset: 0, limit: 0, total: 0 };
    const snapshot = data.snapshot;
    const scope = data.scope;

    if (!snapshot || !scope) {
      throw new Error('Ranking snapshot or scope missing from response');
    }

    const until = sourceTime(snapshot.valid_until, { requireOffset: true });
    const asOf = sourceTime(data.as_of, { requireOffset: true });
    const refStamp = sourceTime(snapshot.reference, { requireOffset: true });

    if (
      data.status !== 'CURRENT_CANDIDATE_PRIORITY' ||
      data.actionable !== false ||
      !isTrimmedString(snapshot.run_id) ||
      !isTrimmedString(snapshot.work_id) ||
      !isHexSha256(snapshot.rank_version) ||
      !Number.isFinite(until) ||
      !Number.isFinite(asOf) ||
      !Number.isFinite(refStamp) ||
      until < asOf ||
      !isTrimmedString(scope.provider) ||
      !['LIVE', 'SIMULATED'].includes(scope.data_mode) ||
      scope.segment !== 'NSE_EQUITY_INTRADAY' ||
      !isHexSha256(scope.profile_digest) ||
      stableStringify(scope) !== stableStringify(snapshot.scope) ||
      page.limit !== 100 ||
      page.offset !== offset ||
      !Number.isInteger(page.total) ||
      page.total < 0 ||
      page.total > 512 ||
      !Array.isArray(data.current_rows) ||
      data.current_rows.length !== Math.min(100, page.total - offset)
    ) {
      throw new Error('Invalid ranking page schema or parameters');
    }

    const currentBinding = stableStringify({
      run: snapshot.run_id,
      work: snapshot.work_id,
      version: snapshot.rank_version,
      scope,
      reference: snapshot.reference,
      until: snapshot.valid_until,
      policy: snapshot.policy,
    });

    if (firstData && (binding !== currentBinding || total !== page.total)) {
      throw new Error('Inconsistent ranking pages detected across snapshot read');
    }

    if (!firstData) {
      firstData = data;
      binding = currentBinding;
      total = page.total;
    }

    deadline = Math.min(deadline, sentTime + (until - asOf));

    for (const [index, row] of data.current_rows.entries()) {
      const id = row && row.instrument_identity;
      const expectedPositionType = row.direction === 'LONG' ? 'LONG_EQUITY_INTRADAY' : 'SHORT_EQUITY_INTRADAY';

      if (
        !row ||
        row.actionable !== false ||
        !isTrimmedString(row.symbol) ||
        !isTrimmedString(row.opportunity_key) ||
        !isTrimmedString(row.candidate_id) ||
        row.rank !== offset + index + 1 ||
        !isHexSha256(row.source_digest) ||
        !Number.isFinite(sourceTime(row.source_data_watermark, { requireOffset: true })) ||
        !['LONG', 'SHORT'].includes(row.direction) ||
        row.position_type !== expectedPositionType ||
        !id ||
        !isTrimmedString(id.identifier) ||
        id.symbol !== row.symbol ||
        id.provider !== scope.provider ||
        id.segment !== scope.segment ||
        id.exchange !== 'NSE' ||
        id.instrument_type !== 'EQ' ||
        id.is_index !== false ||
        !isTrimmedString(row.strategy_id) ||
        keys.has(row.opportunity_key) ||
        candidates.has(row.candidate_id) ||
        symbols.has(row.symbol)
      ) {
        throw new Error(`Invalid ranking row identity or ordering at index ${offset + index}`);
      }

      const identityKey = stableStringify([
        id.provider,
        id.identifier,
        id.exchange,
        id.segment,
        id.instrument_type,
      ]);

      if (identities.has(identityKey)) {
        throw new Error(`Duplicate instrument identity detected in snapshot: ${row.symbol}`);
      }

      keys.add(row.opportunity_key);
      candidates.add(row.candidate_id);
      symbols.add(row.symbol);
      identities.add(identityKey);
      rows.push(row);
    }
  }

  const lifetimeMs = deadline - performance.now();
  if (!Number.isFinite(lifetimeMs) || lifetimeMs < 0) {
    throw new Error('Ranking expired during snapshot collection');
  }

  return {
    data: firstData!,
    rows,
    deadline,
    lifetimeMs,
  };
}


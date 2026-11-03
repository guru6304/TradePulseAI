/**
 * TradePulse AI Typed API Client
 *
 * Requirements:
 * - Read-only GET/HEAD requests only (no mutations)
 * - same-origin credentials & loopback Host compliance
 * - no-store Cache-Control
 * - AbortController timeout & cancellation handling
 * - Explicit error reporting without fabricated fallbacks
 */

import type {
  HealthResponse,
  ConfigResponse,
  ScanListResponse,
  RankingResponse,
  SignalListResponse,
  ScanLineageResponse,
  CashCandlesResponse,
  PaperPortfolioResponse,
  PaperAccountsResponse,
} from '../types/api';

export class ApiError extends Error {
  status: number;
  statusText: string;
  payload: unknown;

  constructor(message: string, status = 0, statusText = '', payload: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.statusText = statusText;
    this.payload = payload;
  }
}

export interface RequestOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
}

export async function apiGet<T>(
  endpoint: string,
  params: Record<string, string | number | boolean | undefined | null> = {},
  options: RequestOptions = {}
): Promise<T> {
  const { timeoutMs = 8000, signal: callerSignal } = options;
  const controller = new AbortController();

  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  if (timeoutMs > 0) {
    timeoutId = setTimeout(() => {
      controller.abort(new ApiError(`Request timeout after ${timeoutMs}ms`, 408, 'Request Timeout'));
    }, timeoutMs);
  }

  // Link caller signal if provided
  if (callerSignal) {
    if (callerSignal.aborted) {
      controller.abort(callerSignal.reason);
    } else {
      callerSignal.addEventListener('abort', () => controller.abort(callerSignal.reason), { once: true });
    }
  }

  try {
    const url = new URL(endpoint, window.location.origin);
    for (const [key, val] of Object.entries(params)) {
      if (val !== undefined && val !== null && val !== '') {
        url.searchParams.set(key, String(val));
      }
    }

    const response = await fetch(url.toString(), {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal,
    });

    if (!response.ok) {
      let errorBody: unknown = null;
      try {
        errorBody = await response.json();
      } catch {
        // Body was not JSON
      }
      throw new ApiError(
        `API request failed with status ${response.status}`,
        response.status,
        response.statusText,
        errorBody
      );
    }

    const payload = await response.json();
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new ApiError('Malformed API response payload', response.status, response.statusText, payload);
    }

    return payload as T;
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
  }
}

export const apiClient = {
  getHealth(options?: RequestOptions): Promise<HealthResponse> {
    return apiGet<HealthResponse>('/api/health', {}, options);
  },

  getConfig(options?: RequestOptions): Promise<ConfigResponse> {
    return apiGet<ConfigResponse>('/api/config', {}, options);
  },

  getScans(params: { limit?: number; offset?: number; status?: string } = {}, options?: RequestOptions): Promise<ScanListResponse> {
    return apiGet<ScanListResponse>('/api/scans', params, options);
  },

  getOpportunityRankings(
    params: { run_id?: string; limit?: number; offset?: number } = {},
    options?: RequestOptions
  ): Promise<RankingResponse> {
    // server.py:558 strictly allows only {"run_id", "limit", "offset"}
    const cleanParams: { run_id?: string; limit?: number; offset?: number } = {};
    if (params.run_id !== undefined && params.run_id !== null) {
      const stripped = String(params.run_id).trim();
      if (stripped.length > 0 && stripped.length <= 160) {
        cleanParams.run_id = stripped;
      }
    }
    if (params.limit !== undefined && params.limit !== null) {
      cleanParams.limit = Math.max(1, Math.min(100, Number(params.limit)));
    }
    if (params.offset !== undefined && params.offset !== null) {
      cleanParams.offset = Math.max(0, Math.min(512, Number(params.offset)));
    }
    return apiGet<RankingResponse>('/api/opportunity-rankings', cleanParams, options);
  },

  getSignals(
    params: {
      symbol?: string;
      strategy_id?: string;
      provider?: string;
      segment?: string;
      start_time?: string;
      end_time?: string;
      direction?: string;
      data_mode?: string;
      state_context?: string;
      limit?: number;
      offset?: number;
    } = {},
    options?: RequestOptions
  ): Promise<SignalListResponse> {
    return apiGet<SignalListResponse>('/api/signals', params, options);
  },

  async getScanLineage(run_id: string, options?: RequestOptions): Promise<ScanLineageResponse> {
    const stripped = typeof run_id === 'string' ? run_id.trim() : '';
    if (!stripped || stripped.length > 160) {
      throw new ApiError(
        'Invalid or missing run_id for /api/scan-lineage',
        400,
        'Bad Request',
        { status: 'error', reason_code: 'INVALID_RUN_ID' }
      );
    }
    return apiGet<ScanLineageResponse>('/api/scan-lineage', { run_id: stripped }, options);
  },

  async getCashCandles(
    params: { run_id: string; batch_id: string; limit?: number; offset?: number },
    options?: RequestOptions
  ): Promise<CashCandlesResponse> {
    const run_id = typeof params.run_id === 'string' ? params.run_id.trim() : '';
    const batch_id = typeof params.batch_id === 'string' ? params.batch_id.trim() : '';
    if (!run_id || !batch_id) {
      throw new ApiError(
        'Both run_id and batch_id are required for /api/cash-candles',
        400,
        'Bad Request',
        { status: 'error', reason_code: 'MISSING_CANDLE_IDENTIFIERS' }
      );
    }
    return apiGet<CashCandlesResponse>(
      '/api/cash-candles',
      {
        run_id,
        batch_id,
        limit: params.limit !== undefined ? Math.max(1, Math.min(200, Number(params.limit))) : undefined,
        offset: params.offset !== undefined ? Math.max(0, Math.min(25000, Number(params.offset))) : undefined,
      },
      options
    );
  },

  getPaperAccounts(
    params: { limit?: number; cursor?: string } = {},
    options?: RequestOptions
  ): Promise<PaperAccountsResponse> {
    return apiGet<PaperAccountsResponse>('/api/paper-accounts', params, options);
  },

  async getPaperPortfolio(account_id: string, options?: RequestOptions): Promise<PaperPortfolioResponse> {
    const trimmed = typeof account_id === 'string' ? account_id.trim() : '';
    if (!trimmed || trimmed.length > 128 || !/^[A-Za-z0-9_.:-]+$/.test(trimmed)) {
      throw new ApiError(
        `Invalid or missing account_id for paper portfolio request: ${account_id}`,
        400,
        'Bad Request',
        { status: 'error', reason_code: 'INVALID_ACCOUNT_ID' }
      );
    }
    return apiGet<PaperPortfolioResponse>('/api/paper-portfolio', { account_id: trimmed }, options);
  },
};


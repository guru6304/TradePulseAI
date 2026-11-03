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
    return apiGet<RankingResponse>('/api/opportunity-rankings', params, options);
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
      limit?: number;
      offset?: number;
    } = {},
    options?: RequestOptions
  ): Promise<SignalListResponse> {
    return apiGet<SignalListResponse>('/api/signals', params, options);
  },

  getScanLineage(run_id: string, options?: RequestOptions): Promise<ScanLineageResponse> {
    return apiGet<ScanLineageResponse>('/api/scan-lineage', { run_id }, options);
  },

  getCashCandles(
    params: { run_id: string; batch_id: string; limit?: number; offset?: number },
    options?: RequestOptions
  ): Promise<CashCandlesResponse> {
    return apiGet<CashCandlesResponse>('/api/cash-candles', params, options);
  },

  getPaperPortfolio(account_id: string, options?: RequestOptions): Promise<PaperPortfolioResponse> {
    return apiGet<PaperPortfolioResponse>('/api/paper-portfolio', { account_id }, options);
  },
};

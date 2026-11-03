import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiGet, apiClient, ApiError } from '../api/client';

describe('apiClient and apiGet', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('performs GET request with same-origin, no-store and Accept json', async () => {
    const mockPayload = { status: 'ok', data_mode: 'SIMULATED' };
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => mockPayload,
    } as Response);

    const result = await apiGet<{ status: string }>('/api/health');

    expect(result).toEqual(mockPayload);
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const [calledUrl, options] = fetchSpy.mock.calls[0];
    const url = new URL(calledUrl as string);

    expect(url.pathname).toBe('/api/health');
    expect(options?.method).toBe('GET');
    expect(options?.cache).toBe('no-store');
    expect(options?.credentials).toBe('same-origin');
    expect(options?.headers).toEqual({ Accept: 'application/json' });
  });

  it('encodes query params and filters out undefined/null/empty', async () => {
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ status: 'ok', items: [] }),
    } as Response);

    await apiGet('/api/signals', {
      symbol: 'RELIANCE',
      strategy_id: 'strat_1_order_block',
      emptyParam: '',
      nullParam: null,
      undefinedParam: undefined,
      limit: 100,
    });

    const [calledUrl] = fetchSpy.mock.calls[0];
    const url = new URL(calledUrl as string);

    expect(url.searchParams.get('symbol')).toBe('RELIANCE');
    expect(url.searchParams.get('strategy_id')).toBe('strat_1_order_block');
    expect(url.searchParams.get('limit')).toBe('100');
    expect(url.searchParams.has('emptyParam')).toBe(false);
    expect(url.searchParams.has('nullParam')).toBe(false);
    expect(url.searchParams.has('undefinedParam')).toBe(false);
  });

  it('throws ApiError on non-200 HTTP response with status and parsed body', async () => {
    vi.spyOn(window, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({ status: 'error', message: 'Resource not found' }),
    } as Response);

    await expect(apiGet('/api/non-existent')).rejects.toThrow(ApiError);
  });

  it('throws ApiError on malformed non-object JSON response', async () => {
    vi.spyOn(window, 'fetch').mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ['not', 'an', 'object'],
    } as Response);

    await expect(apiGet('/api/health')).rejects.toThrow(ApiError);
  });

  describe('Strict production endpoint paths and parameter contracts', () => {
    it('calls /api/opportunity-rankings with run_id, limit, offset and never page', async () => {
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: 'CURRENT_CANDIDATE_PRIORITY', current_rows: [] }),
      } as Response);

      await apiClient.getOpportunityRankings({
        run_id: 'scan-run-123',
        limit: 100,
        offset: 0,
      });

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const url = new URL(fetchSpy.mock.calls[0][0] as string);
      expect(url.pathname).toBe('/api/opportunity-rankings');
      expect(url.searchParams.get('run_id')).toBe('scan-run-123');
      expect(url.searchParams.get('limit')).toBe('100');
      expect(url.searchParams.get('offset')).toBe('0');
      expect(url.searchParams.has('page')).toBe(false);
    });

    it('calls /api/cash-candles with required run_id and batch_id', async () => {
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: 'ok', items: [] }),
      } as Response);

      await apiClient.getCashCandles({
        run_id: 'scan-run-123',
        batch_id: 'batch-456',
        limit: 100,
        offset: 0,
      });

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const url = new URL(fetchSpy.mock.calls[0][0] as string);
      expect(url.pathname).toBe('/api/cash-candles');
      expect(url.searchParams.get('run_id')).toBe('scan-run-123');
      expect(url.searchParams.get('batch_id')).toBe('batch-456');
    });

    it('rejects getCashCandles when run_id or batch_id is missing', async () => {
      await expect(
        apiClient.getCashCandles({ run_id: '', batch_id: 'batch-456' })
      ).rejects.toThrow('Both run_id and batch_id are required for /api/cash-candles');

      await expect(
        apiClient.getCashCandles({ run_id: 'run-123', batch_id: '' })
      ).rejects.toThrow('Both run_id and batch_id are required for /api/cash-candles');
    });

    it('calls /api/scan-lineage with run_id and validates length', async () => {
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: 'COMMITTED', batches: [] }),
      } as Response);

      await apiClient.getScanLineage('scan-run-123');

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const url = new URL(fetchSpy.mock.calls[0][0] as string);
      expect(url.pathname).toBe('/api/scan-lineage');
      expect(url.searchParams.get('run_id')).toBe('scan-run-123');
    });

    it('rejects getScanLineage when run_id is missing or oversized', async () => {
      await expect(apiClient.getScanLineage('')).rejects.toThrow('Invalid or missing run_id');
      await expect(apiClient.getScanLineage('x'.repeat(161))).rejects.toThrow('Invalid or missing run_id');
    });

    it('calls /api/signals with exact filter parameters', async () => {
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: 'ok', items: [] }),
      } as Response);

      await apiClient.getSignals({
        symbol: 'INFY',
        strategy_id: 'strat_2_vwap_pullback',
        provider: 'upstox',
        segment: 'NSE_EQUITY_INTRADAY',
        start_time: '2026-11-03T09:15:00+05:30',
        end_time: '2026-11-03T09:15:00+05:30',
        limit: 200,
        offset: 0,
      });

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const url = new URL(fetchSpy.mock.calls[0][0] as string);
      expect(url.pathname).toBe('/api/signals');
      expect(url.searchParams.get('symbol')).toBe('INFY');
      expect(url.searchParams.get('strategy_id')).toBe('strat_2_vwap_pullback');
      expect(url.searchParams.get('limit')).toBe('200');
    });

    it('calls /api/paper-portfolio strictly with account_id', async () => {
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: 'OK', account_id: 'paper_test_1' }),
      } as Response);

      await apiClient.getPaperPortfolio('paper_test_1');

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const url = new URL(fetchSpy.mock.calls[0][0] as string);
      expect(url.pathname).toBe('/api/paper-portfolio');
      expect(url.searchParams.get('account_id')).toBe('paper_test_1');
    });

    it('rejects getPaperPortfolio when account_id is empty or invalid', async () => {
      await expect(apiClient.getPaperPortfolio('')).rejects.toThrow('Invalid or missing account_id');
      await expect(apiClient.getPaperPortfolio('invalid account with spaces')).rejects.toThrow(
        'Invalid or missing account_id'
      );
    });

    it('calls /api/paper-accounts for verified account discovery', async () => {
      const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: 'ok', accounts: [] }),
      } as Response);

      await apiClient.getPaperAccounts({ limit: 5 });

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const url = new URL(fetchSpy.mock.calls[0][0] as string);
      expect(url.pathname).toBe('/api/paper-accounts');
      expect(url.searchParams.get('limit')).toBe('5');
    });

    it('calls /api/health and /api/config without unexpected query strings', async () => {
      const fetchSpy = vi.spyOn(window, 'fetch')
        .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ status: 'ok' }) } as Response)
        .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ status: 'ok' }) } as Response);

      await apiClient.getHealth();
      await apiClient.getConfig();

      expect(fetchSpy).toHaveBeenCalledTimes(2);
      const url1 = new URL(fetchSpy.mock.calls[0][0] as string);
      const url2 = new URL(fetchSpy.mock.calls[1][0] as string);
      expect(url1.pathname).toBe('/api/health');
      expect(url1.search).toBe('');
      expect(url2.pathname).toBe('/api/config');
      expect(url2.search).toBe('');
    });
  });
});

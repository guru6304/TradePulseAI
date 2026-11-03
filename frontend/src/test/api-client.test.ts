import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiGet, ApiError } from '../api/client';

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
});

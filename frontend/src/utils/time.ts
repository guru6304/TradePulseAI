/**
 * Authoritative time and formatting utilities
 * Strictly matches terminal.js and test_terminal_clock.js
 */

export function sourceTime(value: unknown, options: { requireOffset?: boolean } = {}): number {
  if (typeof value !== 'string') return NaN;

  // Stored application timestamps use naive IST format: YYYY-MM-DD HH:MM:SS
  // Wire/feed/rank timestamps use offset-qualified ISO format.
  let fields = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?$/.exec(value);
  let zone = '+05:30';

  if (fields) {
    if (options.requireOffset) return NaN;
  } else {
    fields = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
    if (!fields) return NaN;
    zone = fields[8];
  }

  const [year, month, day, hour, minute, second] = fields.slice(1, 7).map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

  if (
    year < 1 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > days[month - 1] ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    return NaN;
  }

  let offset = 0;
  if (zone !== 'Z') {
    const hours = Number(zone.slice(1, 3));
    const minutes = Number(zone.slice(4, 6));
    if (hours > 23 || minutes > 59) return NaN;
    offset = (zone[0] === '+' ? 1 : -1) * (hours * 60 + minutes);
  }

  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, Number((fields[7] || '').padEnd(3, '0').slice(0, 3)));
  return date.getTime() - offset * 60000;
}

export function formatIstTime(value: unknown, options: { includeDate?: boolean; includeSeconds?: boolean } = {}): string {
  const parsed = typeof value === 'number' ? value : sourceTime(value);
  if (!Number.isFinite(parsed)) return 'Time unavailable';

  const date = new Date(parsed);
  const formatter = new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: options.includeDate ? '2-digit' : undefined,
    month: options.includeDate ? 'short' : undefined,
    hour: '2-digit',
    minute: '2-digit',
    second: options.includeSeconds ? '2-digit' : undefined,
    hour12: false,
  });

  return `${formatter.format(date)} IST`;
}

export function istDayString(timestampMs: number): string {
  return new Date(timestampMs + 330 * 60000).toISOString().slice(0, 10);
}

export function formatInr(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return value.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

export function formatInrCurrency(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return '₹' + value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * Stable, deterministic JSON serialization for object equality comparison
 */
export function stableStringify(obj: unknown): string {
  if (obj === null || typeof obj !== 'object') {
    return JSON.stringify(obj);
  }
  if (Array.isArray(obj)) {
    return '[' + obj.map(stableStringify).join(',') + ']';
  }
  const keys = Object.keys(obj as Record<string, unknown>).sort();
  return '{' + keys.map(k => JSON.stringify(k) + ':' + stableStringify((obj as Record<string, unknown>)[k])).join(',') + '}';
}


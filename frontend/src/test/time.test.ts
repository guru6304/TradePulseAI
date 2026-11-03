import { describe, it, expect } from 'vitest';
import { sourceTime, formatIstTime, istDayString, stableStringify } from '../utils/time';

describe('sourceTime and time utilities', () => {
  it('parses naive stored IST text with implicit +05:30 offset', () => {
    // 2026-10-31 09:15:00 IST = 2026-10-31 03:45:00 UTC
    const t = sourceTime('2026-10-31 09:15:00');
    expect(Number.isFinite(t)).toBe(true);

    const date = new Date(t);
    expect(date.getUTCFullYear()).toBe(2026);
    expect(date.getUTCMonth()).toBe(9); // 0-indexed month 9 is October
    expect(date.getUTCDate()).toBe(31);
    expect(date.getUTCHours()).toBe(3);
    expect(date.getUTCMinutes()).toBe(45);
  });

  it('parses ISO string with explicit offset and matches naive IST counterpart', () => {
    const naiveTime = sourceTime('2026-10-31 15:30:00');
    const isoTime = sourceTime('2026-10-31T15:30:00+05:30');
    const utcIsoTime = sourceTime('2026-10-31T10:00:00Z');

    expect(naiveTime).toBe(isoTime);
    expect(isoTime).toBe(utcIsoTime);
  });

  it('rejects naive IST string when requireOffset: true', () => {
    const naive = sourceTime('2026-10-31 09:15:00', { requireOffset: true });
    expect(Number.isNaN(naive)).toBe(true);

    const withOffset = sourceTime('2026-10-31T09:15:00+05:30', { requireOffset: true });
    expect(Number.isFinite(withOffset)).toBe(true);
  });

  it('rejects invalid or rolled over calendar dates', () => {
    expect(Number.isNaN(sourceTime('2026-02-29 09:15:00'))).toBe(true); // 2026 is not a leap year
    expect(Number.isNaN(sourceTime('2024-02-30 09:15:00'))).toBe(true); // Feb 30 does not exist
    expect(Number.isNaN(sourceTime('2026-13-01 09:15:00'))).toBe(true); // Month 13
    expect(Number.isNaN(sourceTime('2026-10-32 09:15:00'))).toBe(true); // Day 32
    expect(Number.isNaN(sourceTime('2026-10-31 25:00:00'))).toBe(true); // Hour 25
    expect(Number.isNaN(sourceTime('not-a-date'))).toBe(true);
    expect(Number.isNaN(sourceTime(null))).toBe(true);
    expect(Number.isNaN(sourceTime(12345))).toBe(true);
  });

  it('formats timestamp in Asia/Kolkata timezone with IST indicator', () => {
    // 2026-10-31T03:45:00Z -> 09:15:00 IST
    const t = Date.UTC(2026, 9, 31, 3, 45, 0);
    const formatted = formatIstTime(t);
    expect(formatted).toContain('IST');
    expect(formatted).toMatch(/09:15/);
  });

  it('calculates istDayString consistently', () => {
    const t = Date.UTC(2026, 9, 30, 20, 0, 0); // 20:00 UTC on 30 Oct is 01:30 IST on 31 Oct
    expect(istDayString(t)).toBe('2026-10-31');
  });

  it('produces deterministic stableStringify regardless of object key order', () => {
    const a = { z: 1, a: 2, m: { y: 'b', x: 'a' } };
    const b = { a: 2, z: 1, m: { x: 'a', y: 'b' } };
    expect(stableStringify(a)).toBe(stableStringify(b));
  });
});

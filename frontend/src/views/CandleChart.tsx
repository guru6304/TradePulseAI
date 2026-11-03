import React from 'react';
import type { CashCandleItem } from '../types/api';
import { formatInr, formatIstTime } from '../utils/time';

interface CandleChartProps {
  bars: CashCandleItem[];
  watermarkIst?: string;
}

export const CandleChart: React.FC<CandleChartProps> = ({ bars }) => {
  if (!bars || bars.length === 0) {
    return (
      <div className="h-48 bg-surface-container-lowest rounded-lg flex items-center justify-center text-outline font-mono text-xs border border-outline-variant/30">
        No candle data available
      </div>
    );
  }

  const low = Math.min(...bars.map((b) => b.low));
  const high = Math.max(...bars.map((b) => b.high));
  const range = high - low || 1;

  const width = 760;
  const height = 210;
  const paddingBottom = 20;
  const chartHeight = height - paddingBottom;

  const getY = (val: number) => {
    return chartHeight - ((val - low) / range) * (chartHeight - 20) - 10;
  };

  const step = (width - 40) / Math.max(1, bars.length);

  return (
    <div className="flex flex-col gap-space-sm">
      {/* SVG Canvas */}
      <div className="relative w-full h-56 bg-surface-container-lowest rounded-lg p-2 border border-outline-variant/30 overflow-hidden flex flex-col justify-between">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Retained completed 5-minute OHLC candlestick chart with ${bars.length} bars. Price range ₹${formatInr(low)} to ₹${formatInr(high)}.`}
          className="w-full h-full overflow-visible candle-chart"
        >
          {/* Subtle grid lines */}
          <line x1="20" y1={getY(high)} x2={width - 20} y2={getY(high)} stroke="#252a32" strokeDasharray="3 3" />
          <line x1="20" y1={getY((high + low) / 2)} x2={width - 20} y2={getY((high + low) / 2)} stroke="#252a32" strokeDasharray="3 3" />
          <line x1="20" y1={getY(low)} x2={width - 20} y2={getY(low)} stroke="#252a32" strokeDasharray="3 3" />

          {/* Candlesticks */}
          {bars.map((bar, i) => {
            const isBullish = bar.close >= bar.open;
            const color = isBullish ? '#10b981' : '#ef4444';
            const x = 25 + i * step;
            const wickY1 = getY(bar.high);
            const wickY2 = getY(bar.low);
            const bodyY = Math.min(getY(bar.open), getY(bar.close));
            const bodyHeight = Math.max(1, Math.abs(getY(bar.open) - getY(bar.close)));
            const bodyWidth = Math.max(2, step * 0.6);

            return (
              <g key={bar.timestamp}>
                {/* Wick */}
                <line
                  x1={x}
                  y1={wickY1}
                  x2={x}
                  y2={wickY2}
                  stroke={color}
                  strokeWidth="1.5"
                />
                {/* Body */}
                <rect
                  x={x - bodyWidth / 2}
                  y={bodyY}
                  width={bodyWidth}
                  height={bodyHeight}
                  fill={color}
                />
              </g>
            );
          })}
        </svg>

        {/* Legend / Range labels */}
        <div className="flex items-center justify-between text-[10px] font-mono text-outline pt-1 border-t border-outline-variant/20 px-2">
          <span>High: ₹{formatInr(high)}</span>
          <span>{bars.length} completed 5m bars</span>
          <span>Low: ₹{formatInr(low)}</span>
        </div>
      </div>

      {/* Accessible Collapsible OHLC Value Table */}
      <details className="text-xs font-mono group">
        <summary className="cursor-pointer text-primary hover:underline py-1 flex items-center gap-1 select-none">
          <span>Read raw OHLC bar values ({bars.length} bars)</span>
        </summary>
        <div className="mt-2 max-h-48 overflow-y-auto rounded border border-outline-variant/30 bg-surface-container-lowest">
          <table className="w-full text-left border-collapse text-[11px]" aria-label="Raw OHLC bar data">
            <thead>
              <tr className="border-b border-outline-variant/40 bg-surface-container text-outline">
                <th scope="col" className="py-1 px-2">Time IST</th>
                <th scope="col" className="py-1 px-2 text-right">Open</th>
                <th scope="col" className="py-1 px-2 text-right">High</th>
                <th scope="col" className="py-1 px-2 text-right">Low</th>
                <th scope="col" className="py-1 px-2 text-right">Close</th>
                <th scope="col" className="py-1 px-2 text-right">Volume</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/20">
              {bars.map((b) => (
                <tr key={b.timestamp} className="hover:bg-surface-container-high/40">
                  <td className="py-1 px-2 text-outline">{formatIstTime(b.timestamp)}</td>
                  <td className="py-1 px-2 text-right font-medium">{formatInr(b.open)}</td>
                  <td className="py-1 px-2 text-right text-tp-long">{formatInr(b.high)}</td>
                  <td className="py-1 px-2 text-right text-tp-short">{formatInr(b.low)}</td>
                  <td className="py-1 px-2 text-right font-bold text-on-surface">{formatInr(b.close)}</td>
                  <td className="py-1 px-2 text-right text-outline">{b.volume ? formatInr(b.volume) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
};

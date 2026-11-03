import React from 'react';

export type BadgeVariant =
  | 'QUALIFIED'
  | 'RADAR'
  | 'PENDING_ENTRY'
  | 'PAPER_FILLED'
  | 'INVALIDATED'
  | 'STALE'
  | 'BLOCKED_DATA'
  | 'SYNTHETIC_DEMO'
  | 'LONG'
  | 'SHORT'
  | 'NEUTRAL'
  | 'CAUTION';

interface StatusBadgeProps {
  variant?: BadgeVariant;
  label?: string;
  className?: string;
  children?: React.ReactNode;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  variant = 'NEUTRAL',
  label,
  className = '',
  children,
}) => {
  const content = children || label || variant;

  let styleClasses = 'bg-surface-container-high text-on-surface-variant border-outline-variant';

  switch (variant) {
    case 'QUALIFIED':
      styleClasses = 'bg-[#0284c7]/15 text-[#38bdf8] border-[#0284c7]/50';
      break;
    case 'RADAR':
      styleClasses = 'bg-[#6e7681]/15 text-[#8b949e] border-[#484f58]/50';
      break;
    case 'PENDING_ENTRY':
    case 'CAUTION':
      styleClasses = 'bg-[#f59e0b]/15 text-[#f59e0b] border-[#f59e0b]/50';
      break;
    case 'PAPER_FILLED':
      styleClasses = 'bg-[#10b981]/15 text-[#10b981] border-[#10b981]/50';
      break;
    case 'INVALIDATED':
      styleClasses = 'bg-[#ef4444]/15 text-[#ef4444] border-[#ef4444]/50';
      break;
    case 'STALE':
      styleClasses = 'bg-[#d97706]/15 text-[#fcd34d] border-[#d97706]/50';
      break;
    case 'BLOCKED_DATA':
      styleClasses = 'bg-[#93000a]/20 text-[#ffb4ab] border-[#ef4444]/60';
      break;
    case 'SYNTHETIC_DEMO':
      styleClasses = 'bg-tertiary-container/20 text-tertiary border-tertiary-container/40 font-bold';
      break;
    case 'LONG':
      styleClasses = 'bg-[#10b981]/15 text-[#10b981] border-[#10b981]/40 font-semibold';
      return (
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm border font-label-badge text-label-badge uppercase tracking-wider ${styleClasses} ${className}`}>
          <span>▲</span>
          <span>{content}</span>
        </span>
      );
    case 'SHORT':
      styleClasses = 'bg-[#ef4444]/15 text-[#ef4444] border-[#ef4444]/40 font-semibold';
      return (
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm border font-label-badge text-label-badge uppercase tracking-wider ${styleClasses} ${className}`}>
          <span>▼</span>
          <span>{content}</span>
        </span>
      );
    default:
      styleClasses = 'bg-surface-container-high text-on-surface-variant border-outline-variant';
      break;
  }

  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded-sm border font-label-badge text-label-badge uppercase tracking-wider ${styleClasses} ${className}`}
    >
      {content}
    </span>
  );
};

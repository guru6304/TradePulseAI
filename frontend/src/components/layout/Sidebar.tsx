import React from 'react';
import { useTerminal, TerminalRoute } from '../../context/TerminalContext';
import {
  MonitoringIcon,
  PulseChartIcon,
  RadarIcon,
  AnalyticsIcon,
  ModelTrainingIcon,
  WalletIcon,
  SettingsIcon,
  LockIcon,
} from '../common/Icons';

interface NavItem {
  key: TerminalRoute;
  label: string;
  icon: React.FC<{ size?: number; className?: string }>;
  isLocked?: boolean;
}

const PRIMARY_NAV: NavItem[] = [
  { key: 'pulse', label: 'Pulse', icon: PulseChartIcon },
  { key: 'opportunities', label: 'Opportunities', icon: RadarIcon },
  { key: 'options', label: 'Options Lab', icon: AnalyticsIcon },
  { key: 'strategies', label: 'Strategies & Research', icon: ModelTrainingIcon },
  { key: 'paper', label: 'Paper Portfolio', icon: WalletIcon },
];

export const Sidebar: React.FC = () => {
  const { route, setRoute } = useTerminal();

  return (
    <aside className="hidden md:flex fixed left-0 top-0 h-full w-56 bg-surface-container-low z-50 flex-col justify-between select-none border-r border-outline-variant/35 shadow-[1px_0_0_rgba(62,72,79,0.35)]">
      {/* Brand & Main Destinations */}
      <div className="flex flex-col">
        <div className="h-11 px-space-md flex items-center justify-between bg-surface-container-lowest/60 border-b border-outline-variant/30">
          <div className="flex items-center gap-space-sm">
            <div className="w-6 h-6 rounded bg-primary-container flex items-center justify-center">
              <MonitoringIcon size={16} className="text-on-primary-container" />
            </div>
            <div className="flex items-center leading-none">
              <span className="font-headline-md text-headline-md tracking-tight text-on-surface font-bold">
                TradePulse<span className="text-primary font-mono text-label-numeric-sm ml-0.5">AI</span>
              </span>
            </div>
          </div>
          <span className="font-label-badge text-label-badge px-1 py-0.5 rounded bg-surface-container-high text-on-surface-variant uppercase">
            V1.2
          </span>
        </div>

        <nav className="flex flex-col gap-0.5 px-space-xs py-space-sm" aria-label="Desktop Navigation">
          {PRIMARY_NAV.map((item) => {
            const Icon = item.icon;
            const isActive = route === item.key;
            return (
              <a
                key={item.key}
                href={`#/${item.key}`}
                onClick={(e) => {
                  e.preventDefault();
                  setRoute(item.key);
                }}
                className={`flex items-center gap-space-sm px-space-sm py-1.5 rounded transition-colors ${
                  isActive
                    ? 'bg-surface-container-high text-primary font-medium'
                    : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
                }`}
                aria-current={isActive ? 'page' : undefined}
              >
                <Icon size={18} className={isActive ? 'text-primary' : 'text-on-surface-variant'} />
                <span className="font-body-md text-body-md">{item.label}</span>
              </a>
            );
          })}
        </nav>
      </div>

      {/* Utilities & Admin */}
      <div className="flex flex-col gap-0.5 px-space-xs py-space-sm bg-surface-container-lowest/40 border-t border-outline-variant/30">
        <a
          href="#/health"
          onClick={(e) => {
            e.preventDefault();
            setRoute('health');
          }}
          className={`flex items-center gap-space-sm px-space-sm py-1.5 rounded transition-colors ${
            route === 'health'
              ? 'bg-surface-container-high text-primary font-medium'
              : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
          }`}
          aria-current={route === 'health' ? 'page' : undefined}
        >
          <SettingsIcon size={18} />
          <span className="font-body-md text-body-md">Health & Settings</span>
        </a>

        <a
          href="#/admin-research"
          onClick={(e) => {
            e.preventDefault();
            setRoute('admin-research');
          }}
          className={`flex items-center justify-between px-space-sm py-1.5 rounded transition-colors ${
            route === 'admin-research'
              ? 'bg-surface-container-high text-error font-medium'
              : 'text-outline hover:bg-surface-container hover:text-on-surface-variant'
          }`}
          aria-current={route === 'admin-research' ? 'page' : undefined}
        >
          <div className="flex items-center gap-space-sm">
            <LockIcon size={18} />
            <span className="font-body-md text-body-md">Admin Research</span>
          </div>
          <span className="font-label-badge text-label-badge px-1 py-0.5 rounded bg-error-container/30 text-error uppercase font-bold">
            Lock
          </span>
        </a>

        <div className="mt-space-xs pt-space-xs px-space-sm flex items-center justify-between text-on-surface-variant font-mono text-[10px]">
          <span className="text-outline">READ-ONLY LOCAL</span>
          <span className="text-primary font-semibold">GET ONLY</span>
        </div>
      </div>
    </aside>
  );
};

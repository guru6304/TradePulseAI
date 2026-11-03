import React, { useState } from 'react';
import { useTerminal, TerminalRoute } from '../../context/TerminalContext';
import {
  PulseChartIcon,
  RadarIcon,
  AnalyticsIcon,
  WalletIcon,
  MoreHorizIcon,
  ModelTrainingIcon,
  SettingsIcon,
  LockIcon,
  CloseIcon,
  MonitoringIcon,
} from '../common/Icons';

interface MobileNavProps {
  isDrawerOpen: boolean;
  onCloseDrawer: () => void;
}

export const MobileNav: React.FC<MobileNavProps> = ({ isDrawerOpen, onCloseDrawer }) => {
  const { route, setRoute } = useTerminal();
  const [isMoreOpen, setIsMoreOpen] = useState(false);

  const handleSelectRoute = (newRoute: TerminalRoute) => {
    setRoute(newRoute);
    setIsMoreOpen(false);
    onCloseDrawer();
  };

  return (
    <>
      {/* 1. Mobile Bottom Navigation Bar (Fixed bottom, visible ≤767px) */}
      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 h-14 bg-surface-container-low/95 backdrop-blur-md border-t border-outline-variant/35 z-40 flex items-center justify-around px-1 select-none"
        aria-label="Mobile Bottom Navigation"
      >
        <button
          type="button"
          onClick={() => handleSelectRoute('pulse')}
          className={`flex flex-col items-center justify-center flex-1 h-full py-1 ${
            route === 'pulse' ? 'text-primary font-semibold' : 'text-on-surface-variant hover:text-on-surface'
          }`}
          aria-current={route === 'pulse' ? 'page' : undefined}
        >
          <PulseChartIcon size={18} />
          <span className="text-[10px] mt-0.5">Pulse</span>
        </button>

        <button
          type="button"
          onClick={() => handleSelectRoute('opportunities')}
          className={`flex flex-col items-center justify-center flex-1 h-full py-1 ${
            route === 'opportunities' ? 'text-primary font-semibold' : 'text-on-surface-variant hover:text-on-surface'
          }`}
          aria-current={route === 'opportunities' ? 'page' : undefined}
        >
          <RadarIcon size={18} />
          <span className="text-[10px] mt-0.5">Opps</span>
        </button>

        <button
          type="button"
          onClick={() => handleSelectRoute('options')}
          className={`flex flex-col items-center justify-center flex-1 h-full py-1 ${
            route === 'options' ? 'text-primary font-semibold' : 'text-on-surface-variant hover:text-on-surface'
          }`}
          aria-current={route === 'options' ? 'page' : undefined}
        >
          <AnalyticsIcon size={18} />
          <span className="text-[10px] mt-0.5">Options</span>
        </button>

        <button
          type="button"
          onClick={() => handleSelectRoute('paper')}
          className={`flex flex-col items-center justify-center flex-1 h-full py-1 ${
            route === 'paper' ? 'text-primary font-semibold' : 'text-on-surface-variant hover:text-on-surface'
          }`}
          aria-current={route === 'paper' ? 'page' : undefined}
        >
          <WalletIcon size={18} />
          <span className="text-[10px] mt-0.5">Paper</span>
        </button>

        <button
          type="button"
          onClick={() => setIsMoreOpen(!isMoreOpen)}
          className={`flex flex-col items-center justify-center flex-1 h-full py-1 ${
            isMoreOpen || ['strategies', 'health', 'admin-research'].includes(route)
              ? 'text-primary font-semibold'
              : 'text-on-surface-variant hover:text-on-surface'
          }`}
          aria-expanded={isMoreOpen}
          aria-label="More destinations"
        >
          <MoreHorizIcon size={18} />
          <span className="text-[10px] mt-0.5">More</span>
        </button>
      </nav>

      {/* 2. 'More' Sheet Popup for secondary destinations */}
      {isMoreOpen && (
        <div className="md:hidden fixed inset-0 z-50 bg-black/60 flex flex-col justify-end" onClick={() => setIsMoreOpen(false)}>
          <div
            className="bg-surface-container-low border-t border-outline-variant p-space-md rounded-t-xl flex flex-col gap-2 pb-16"
            onClick={(e) => e.stopPropagation()}
            role="menu"
            aria-label="Additional Workspaces"
          >
            <div className="flex items-center justify-between pb-2 border-b border-outline-variant/30">
              <span className="font-headline-md text-headline-md text-on-surface">Additional Workspaces</span>
              <button
                type="button"
                onClick={() => setIsMoreOpen(false)}
                className="p-1 text-on-surface-variant hover:text-on-surface"
                aria-label="Close menu"
              >
                <CloseIcon size={18} />
              </button>
            </div>

            <button
              type="button"
              role="menuitem"
              onClick={() => handleSelectRoute('strategies')}
              className={`flex items-center gap-space-sm p-space-sm rounded ${
                route === 'strategies' ? 'bg-surface-container-high text-primary' : 'text-on-surface-variant'
              }`}
            >
              <ModelTrainingIcon size={18} />
              <div className="flex flex-col text-left">
                <span className="font-medium text-body-md">Strategies & Research</span>
                <span className="text-xs text-outline">5 Baseline Models + Research Candidates</span>
              </div>
            </button>

            <button
              type="button"
              role="menuitem"
              onClick={() => handleSelectRoute('health')}
              className={`flex items-center gap-space-sm p-space-sm rounded ${
                route === 'health' ? 'bg-surface-container-high text-primary' : 'text-on-surface-variant'
              }`}
            >
              <SettingsIcon size={18} />
              <div className="flex flex-col text-left">
                <span className="font-medium text-body-md">Health & Settings</span>
                <span className="text-xs text-outline">Feed Status, Storage, Operational Checks</span>
              </div>
            </button>

            <button
              type="button"
              role="menuitem"
              onClick={() => handleSelectRoute('admin-research')}
              className={`flex items-center justify-between p-space-sm rounded ${
                route === 'admin-research' ? 'bg-surface-container-high text-error' : 'text-outline'
              }`}
            >
              <div className="flex items-center gap-space-sm">
                <LockIcon size={18} />
                <div className="flex flex-col text-left">
                  <span className="font-medium text-body-md">Admin Research</span>
                  <span className="text-xs text-outline">Replay & Audit (Restricted)</span>
                </div>
              </div>
              <span className="font-label-badge text-label-badge px-1 py-0.5 rounded bg-error-container/30 text-error uppercase font-bold">
                Lock
              </span>
            </button>
          </div>
        </div>
      )}

      {/* 3. Hamburger Slide-over Drawer (≤767px) */}
      {isDrawerOpen && (
        <div className="md:hidden fixed inset-0 z-50 bg-black/70 flex" onClick={onCloseDrawer}>
          <div
            className="w-64 bg-surface-container-low h-full flex flex-col justify-between p-space-md shadow-2xl border-r border-outline-variant"
            onClick={(e) => e.stopPropagation()}
          >
            <div>
              <div className="flex items-center justify-between pb-space-md border-b border-outline-variant/30">
                <div className="flex items-center gap-space-sm">
                  <div className="w-6 h-6 rounded bg-primary-container flex items-center justify-center">
                    <MonitoringIcon size={16} className="text-on-primary-container" />
                  </div>
                  <span className="font-headline-md text-headline-md font-bold text-on-surface">
                    TradePulse<span className="text-primary font-mono text-xs ml-0.5">AI</span>
                  </span>
                </div>
                <button type="button" onClick={onCloseDrawer} className="p-1 text-on-surface-variant">
                  <CloseIcon size={18} />
                </button>
              </div>

              <div className="py-2 text-[10px] text-tertiary font-bold uppercase tracking-wider">
                Research & Paper Terminal
              </div>

              <nav className="flex flex-col gap-1 mt-2">
                {[
                  { key: 'pulse', label: 'Pulse', icon: PulseChartIcon },
                  { key: 'opportunities', label: 'Opportunities', icon: RadarIcon },
                  { key: 'options', label: 'Options Lab', icon: AnalyticsIcon },
                  { key: 'strategies', label: 'Strategies & Research', icon: ModelTrainingIcon },
                  { key: 'paper', label: 'Paper Portfolio', icon: WalletIcon },
                  { key: 'health', label: 'Health & Settings', icon: SettingsIcon },
                ].map((item) => {
                  const Icon = item.icon;
                  const isActive = route === item.key;
                  return (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => handleSelectRoute(item.key as TerminalRoute)}
                      className={`flex items-center gap-space-sm px-space-sm py-2 rounded text-left transition-colors ${
                        isActive
                          ? 'bg-surface-container-high text-primary font-medium'
                          : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
                      }`}
                    >
                      <Icon size={18} />
                      <span className="font-body-md text-body-md">{item.label}</span>
                    </button>
                  );
                })}

                <button
                  type="button"
                  onClick={() => handleSelectRoute('admin-research')}
                  className={`flex items-center justify-between px-space-sm py-2 rounded text-left transition-colors ${
                    route === 'admin-research' ? 'bg-surface-container-high text-error font-medium' : 'text-outline'
                  }`}
                >
                  <div className="flex items-center gap-space-sm">
                    <LockIcon size={18} />
                    <span className="font-body-md text-body-md">Admin Research</span>
                  </div>
                  <span className="font-label-badge text-label-badge px-1 py-0.5 rounded bg-error-container/30 text-error uppercase font-bold">
                    Lock
                  </span>
                </button>
              </nav>
            </div>

            <div className="pt-space-md border-t border-outline-variant/30 text-[10px] font-mono text-outline">
              <div>V1.2 · Loopback Mode</div>
              <div className="text-primary font-semibold">Deterministic Pipeline</div>
            </div>
          </div>
        </div>
      )}
    </>
  );
};


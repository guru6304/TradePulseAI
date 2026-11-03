import React from 'react';
import { LockIcon, ShieldIcon } from '../components/common/Icons';
import { StatusBadge } from '../components/common/StatusBadge';

export const AdminResearchView: React.FC = () => {
  return (
    <div className="p-space-md md:p-space-lg flex flex-col gap-space-md select-none font-mono text-xs">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between pb-space-xs border-b border-outline-variant/30 gap-space-sm">
        <div>
          <h2 className="font-headline-lg text-headline-lg font-bold text-on-surface font-sans flex items-center gap-2">
            <LockIcon size={20} className="text-error" />
            <span>Admin Research & Replay</span>
          </h2>
          <p className="font-body-sm text-body-sm text-on-surface-variant font-sans">
            Historical rank replay, no-lookahead audit, and ex-post outcome analysis
          </p>
        </div>

        <div className="flex items-center gap-space-sm">
          <StatusBadge variant="INVALIDATED" label="LOCKED · NOT AUTHORIZED" />
        </div>
      </div>

      {/* Security Barrier Card */}
      <div className="bg-surface-container-low border border-error/40 rounded-xl p-space-lg flex flex-col items-center justify-center text-center max-w-2xl mx-auto my-6">
        <div className="w-12 h-12 rounded-full bg-error-container/30 flex items-center justify-center text-error mb-3">
          <LockIcon size={24} />
        </div>

        <h3 className="font-headline-md text-headline-md font-bold text-on-surface font-sans">
          Server-Side Authentication Required
        </h3>

        <p className="font-body-sm text-body-sm text-on-surface-variant mt-2 leading-relaxed">
          The local loopback Python server does not implement role-based access control (RBAC). A client-side React route guard is not a security boundary; administrative replay endpoints cannot be exposed without verified server-side authorization.
        </p>

        <div className="w-full bg-surface-container-lowest p-space-md rounded-lg border border-outline-variant/30 mt-space-md text-left text-[11px] flex flex-col gap-1.5">
          <div className="font-bold text-outline uppercase tracking-wider mb-1 flex items-center gap-1">
            <ShieldIcon size={14} className="text-tertiary" />
            <span>V1 Blocking Backend Dependencies</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-on-surface-variant">1. Authenticated User Session & RBAC</span>
            <span className="text-error font-bold">NOT_IMPLEMENTED</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-on-surface-variant">2. Historical Rank Replay Handler (<code>/api/rank-history</code>)</span>
            <span className="text-error font-bold">NOT_ESTABLISHED</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-on-surface-variant">3. Point-in-time Ex-Post Benchmark Endpoint</span>
            <span className="text-error font-bold">PROPOSED_ONLY</span>
          </div>
        </div>

        <p className="text-[10px] text-outline mt-space-md">
          This workspace will remain securely locked until the backend API contract and authenticated authorization service are delivered and accepted.
        </p>
      </div>
    </div>
  );
};

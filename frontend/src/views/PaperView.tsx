import React from 'react';
import { useTerminal } from '../context/TerminalContext';
import { WalletIcon, SyncIcon, ShieldIcon } from '../components/common/Icons';
import { StatusBadge } from '../components/common/StatusBadge';
import { formatInr, formatInrCurrency } from '../utils/time';

export const PaperView: React.FC = () => {
  const { paperPortfolio, isRefreshing, refreshData } = useTerminal();

  const accounting = paperPortfolio?.accounting;
  const positions = paperPortfolio?.positions || [];
  const reconciliation = paperPortfolio?.reconciliation;

  return (
    <div className="p-space-md md:p-space-lg flex flex-col gap-space-md select-none">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between pb-space-xs border-b border-outline-variant/30 gap-space-sm">
        <div>
          <h2 className="font-headline-lg text-headline-lg font-bold text-on-surface flex items-center gap-2">
            <WalletIcon size={20} className="text-primary" />
            <span>Paper Portfolio</span>
          </h2>
          <p className="font-body-sm text-body-sm text-on-surface-variant">
            Simulation with a memory · From qualified setup to outcome, retained in SQLite
          </p>
        </div>

        <div className="flex items-center gap-space-sm font-mono text-xs">
          <StatusBadge
            variant={reconciliation?.status === 'OK' ? 'PAPER_FILLED' : 'CAUTION'}
            label={reconciliation?.status === 'OK' ? 'RECONCILED' : 'UNRECONCILED'}
          />
          <button
            type="button"
            onClick={() => refreshData()}
            disabled={isRefreshing}
            className="px-2.5 py-1 rounded bg-surface-container-high hover:bg-surface-bright text-primary flex items-center gap-1 border border-outline-variant/40"
          >
            <SyncIcon size={12} className={isRefreshing ? 'animate-spin' : ''} />
            <span>GET Stored Portfolio</span>
          </button>
        </div>
      </div>

      {/* Accounting Overview */}
      {paperPortfolio && accounting ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-space-sm font-mono text-xs">
            <div className="bg-surface-container-low p-space-md rounded-xl border border-outline-variant/30">
              <div className="text-outline uppercase text-[10px]">Starting Capital</div>
              <div className="text-lg font-bold text-on-surface mt-1">
                {formatInrCurrency(accounting.starting_capital_inr)}
              </div>
              <div className="text-[10px] text-outline">Virtual Allocation</div>
            </div>

            <div className="bg-surface-container-low p-space-md rounded-xl border border-outline-variant/30">
              <div className="text-outline uppercase text-[10px]">Current Equity</div>
              <div className="text-lg font-bold text-primary mt-1">
                {formatInrCurrency(accounting.equity_inr)}
              </div>
              <div className="text-[10px] text-outline">Available: {formatInrCurrency(accounting.available_capital_inr)}</div>
            </div>

            <div className="bg-surface-container-low p-space-md rounded-xl border border-outline-variant/30">
              <div className="text-outline uppercase text-[10px]">Realized Net P&L</div>
              <div
                className={`text-lg font-bold mt-1 ${
                  accounting.realized_net_pnl_inr >= 0 ? 'text-tp-long' : 'text-tp-short'
                }`}
              >
                {accounting.realized_net_pnl_inr >= 0 ? '+' : ''}
                {formatInrCurrency(accounting.realized_net_pnl_inr)}
              </div>
              <div className="text-[10px] text-outline">
                Unrealized: {formatInrCurrency(accounting.unrealized_net_pnl_inr)}
              </div>
            </div>

            <div className="bg-surface-container-low p-space-md rounded-xl border border-outline-variant/30">
              <div className="text-outline uppercase text-[10px]">Positions / Fees</div>
              <div className="text-sm font-bold text-on-surface mt-1">
                {accounting.open_positions} Open · {accounting.closed_positions} Closed
              </div>
              <div className="text-[10px] text-outline">
                Friction: {formatInrCurrency(accounting.fees_paid_inr + accounting.slippage_paid_inr)}
              </div>
            </div>
          </div>

          {/* Positions Table */}
          <div className="bg-surface-container-low rounded-xl border border-outline-variant/40 overflow-hidden shadow-sm">
            <div className="p-space-md border-b border-outline-variant/30 flex items-center justify-between">
              <h3 className="font-headline-md text-headline-md font-bold text-on-surface">
                Simulated Positions ({positions.length})
              </h3>
              <span className="font-mono text-xs text-outline">
                Account: <strong className="text-on-surface">{paperPortfolio.account_id}</strong>
              </span>
            </div>

            {positions.length === 0 ? (
              <div className="p-space-lg text-center font-mono text-xs text-outline">
                No active open positions in this paper account.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse font-mono text-xs" aria-label="Paper Positions">
                  <thead>
                    <tr className="border-b border-outline-variant/30 bg-surface-container-lowest text-[11px] text-outline uppercase">
                      <th scope="col" className="py-2.5 px-3">Position ID</th>
                      <th scope="col" className="py-2.5 px-3">Symbol</th>
                      <th scope="col" className="py-2.5 px-3">Side</th>
                      <th scope="col" className="py-2.5 px-3 text-right">Quantity</th>
                      <th scope="col" className="py-2.5 px-3 text-right">Entry Price</th>
                      <th scope="col" className="py-2.5 px-3 text-right">Current Price</th>
                      <th scope="col" className="py-2.5 px-3 text-right">Unrealized P&L</th>
                      <th scope="col" className="py-2.5 px-3 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-outline-variant/20">
                    {positions.map((pos) => (
                      <tr key={pos.position_id} className="hover:bg-surface-container-high/40">
                        <td className="py-2.5 px-3 text-outline text-[11px]">{pos.position_id}</td>
                        <td className="py-2.5 px-3 font-bold text-on-surface">{pos.symbol}</td>
                        <td className="py-2.5 px-3">
                          <StatusBadge
                            variant={pos.direction === 'LONG' ? 'LONG' : 'SHORT'}
                            label={pos.direction}
                          />
                        </td>
                        <td className="py-2.5 px-3 text-right">{pos.quantity}</td>
                        <td className="py-2.5 px-3 text-right">₹{formatInr(pos.entry_price)}</td>
                        <td className="py-2.5 px-3 text-right">
                          {pos.current_price ? `₹${formatInr(pos.current_price)}` : '—'}
                        </td>
                        <td
                          className={`py-2.5 px-3 text-right font-bold ${
                            (pos.unrealized_pnl_inr ?? 0) >= 0 ? 'text-tp-long' : 'text-tp-short'
                          }`}
                        >
                          {pos.unrealized_pnl_inr !== undefined
                            ? `${pos.unrealized_pnl_inr >= 0 ? '+' : ''}${formatInrCurrency(pos.unrealized_pnl_inr)}`
                            : '—'}
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <StatusBadge variant="PAPER_FILLED" label={pos.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="bg-surface-container-low border border-outline-variant/40 rounded-xl p-space-lg text-center font-mono text-xs my-4">
          <ShieldIcon size={24} className="text-outline mx-auto mb-2" />
          <h3 className="font-headline-md text-headline-md font-bold text-on-surface">
            No Reconciled Paper Account
          </h3>
          <p className="font-body-sm text-body-sm text-outline mt-1 max-w-md mx-auto">
            A missing account report is not a zero balance. Virtual simulated trading requires a configured and reconciled paper account in the backend. No orders or accounts are fabricated by this read-only terminal.
          </p>
        </div>
      )}

      {/* Safety & Invariant Notes */}
      <div className="p-space-md rounded-xl bg-surface-container-lowest border border-outline-variant/30 text-xs font-mono text-outline leading-relaxed">
        <strong>Paper Trading Safety Protocol:</strong> All simulated entries are evaluated atomically by the Python backend coordinator. Opposing positions for the same instrument are rejected under invariant <code>CONFLICTING_OPEN_POSITION</code>. Manual paper trade execution controls are strictly removed from V1.
      </div>
    </div>
  );
};

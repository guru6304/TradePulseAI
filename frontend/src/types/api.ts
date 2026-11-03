/**
 * Authoritative types derived directly from:
 * - TP_UI_API_CONTRACT_V1.md
 * - TP_STRATEGY_INTEGRATION_CONTRACT_V1.md
 * - server.py / opportunity_ranking.py / rank_history.py
 */

export interface InstrumentIdentity {
  provider: string;
  identifier: string;
  symbol: string;
  exchange: 'NSE';
  segment: 'NSE_EQUITY_INTRADAY' | 'NSE_FO_INDEX';
  instrument_type: string;
  is_index: boolean;
  [key: string]: unknown;
}

export interface ScoreComponents {
  rule_quality: number;
  actual_target1_rr: number;
}

export interface ComponentVersions {
  rule_quality: string;
  actual_target1_rr: string;
}

export type RankChangeReason =
  | 'NEWLY_QUALIFIED'
  | 'SCORE_COMPONENT_CHANGED'
  | 'RELATIVE_ORDER_CHANGED'
  | 'UNCHANGED_PRIORITY';

export interface RankingRow {
  opportunity_key: string;
  candidate_id: string;
  symbol: string;
  strategy_id: string;
  position_type: 'LONG_EQUITY_INTRADAY' | 'SHORT_EQUITY_INTRADAY' | string;
  direction: 'LONG' | 'SHORT';
  source_data_watermark: string;
  source_digest: string;
  priority_scope: 'QUALIFIED_SCANNER_CANDIDATE_ONLY';
  instrument_identity: InstrumentIdentity;
  score_components: ScoreComponents;
  component_versions: ComponentVersions;
  missing_components: string[];
  rank: number;
  previous_rank: number | null;
  rank_change_reason: RankChangeReason;
  component_changes: Record<string, { previous: number | null; current: number }>;
  actionable: false;
}

export interface RankingSnapshotScope {
  provider: string;
  data_mode: 'LIVE' | 'SIMULATED';
  segment: string;
  profile_digest: string;
}

export interface RankingSnapshot {
  policy: string;
  rank_version: string;
  previous_rank_version: string | null;
  valid_until: string;
  evidence_scope: string;
  run_id: string;
  work_id: string;
  reference: string;
  scope: RankingSnapshotScope;
  previous_snapshot: unknown | null;
  source_authenticity: string;
  source_data_watermarks: string[];
  source_data_watermark_count: number;
  exclusions: Array<{ candidate_id?: string; symbol?: string; reason_code: string }>;
  exclusion_count: number;
  removals: Array<{ opportunity_key: string; symbol: string; previous_rank: number; new_rank: null; reason_code: string }>;
  removal_count: number;
  metadata_preview_limit: number;
  exclusions_truncated: boolean;
  removals_truncated: boolean;
  source_data_watermarks_truncated: boolean;
}

export interface RankingPagination {
  offset: number;
  limit: number;
  total: number;
}

export type RankingStatus =
  | 'RANKING_UNAVAILABLE_NO_DURABLE_SCAN'
  | 'CURRENT_CANDIDATE_PRIORITY'
  | 'STALE_OR_FUTURE_SNAPSHOT'
  | 'ARCHIVED_DIFFERENT_RUNTIME_SCOPE'
  | 'ARCHIVED_DIFFERENT_CODE'
  | 'ARCHIVED_NON_CURRENT_SCAN';

export interface RankingResponse {
  status: RankingStatus | string;
  actionable: boolean;
  scope: RankingSnapshotScope;
  as_of: string;
  current_rows: RankingRow[];
  historical_rows: RankingRow[];
  pagination: RankingPagination;
  snapshot: RankingSnapshot | null;
  evidence_scope?: string;
}

export interface SignalItem {
  id: number;
  dedup_key: string;
  symbol: string;
  segment: string;
  strategy_id: string;
  strategy_name: string;
  direction: 'LONG' | 'SHORT' | string;
  position_type: string;
  instrument_label: string;
  entry_price: number;
  entry_zone_low: number;
  entry_zone_high: number;
  stop_loss: number;
  invalidation_level: number;
  target_1: number;
  target_2: number;
  capital_risk_inr: number;
  est_charges_inr: number;
  risk_reward: string;
  rationale: string;
  timestamp: string;
  quality_score: number;
  confidence_pct: number;
  position_qty: number;
  is_simulated: boolean;
  data_mode: string;
  broker: string;
  created_at_ist: string;
  actionable: false;
  instrument_identity: InstrumentIdentity;
  score_breakdown: Record<string, unknown>;
  strategy_evidence?: {
    maturity_state?: string;
    empirical_status?: string;
    paper_evidence_status?: string;
    out_of_sample_evidence_status?: string;
    rule_version?: string;
    score_semantics?: string;
    checks?: Array<{ rule_id: string; status: string; reason?: string; measurements?: Record<string, unknown> }>;
  };
  lineage?: {
    status: string;
    run_id?: string;
    batch_ids?: string[];
  };
  context?: Record<string, unknown>;
  context_alert_decision?: {
    status: string;
    reason_code: string;
  } | null;
  candidate_evaluation?: {
    candidate_id?: string;
  } | null;
  recommendation_status?: string;
  paper_decision?: {
    status?: string;
    reason_code?: string; // May be CONFLICTING_OPEN_POSITION
    position_id?: string | null;
    account_id?: string | null;
    candidate_id?: string | null;
    trigger_contract?: {
      rule_id?: string;
      [key: string]: unknown;
    } | null;
    trigger_timestamp_ist?: string | null;
  };
}

export interface SignalListResponse {
  status: string;
  total_count: number;
  limit: number;
  offset: number;
  items: SignalItem[];
  evidence_scope?: string;
}

export interface ScanLineageBatch {
  batch_id: string;
  identity: InstrumentIdentity;
  interval_min: number;
  candle_count: number;
  first_timestamp: string;
  last_timestamp: string;
  validation: Record<string, unknown>;
  retrieved_at: string;
  source_observation_at: string | null;
}

export interface ScanLineageResponse {
  run_id: string;
  status: string;
  work_id: string;
  version: string;
  reference: string;
  code_digest: string;
  profile_digest: string;
  source_authenticity: string;
  historical_replay_allowed: boolean;
  current_live_acceptance: boolean;
  batches: ScanLineageBatch[];
  evidence_scope?: string;
}

export interface CashCandleItem {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  interval_min: number;
  is_complete: boolean;
  instrument_identity?: InstrumentIdentity;
}

export interface CashCandlesResponse {
  status: string;
  run_id: string;
  batch_id: string;
  total_count: number;
  limit: number;
  offset: number;
  items: CashCandleItem[];
  evidence_scope?: string;
}

export interface BrokerStatus {
  active_broker?: string;
  broker_name?: string;
  connection_state?: string;
  is_simulated?: boolean;
  data_mode?: string;
  connectivity_verified?: boolean;
  last_verified_at_ist?: string | null;
  last_candle_timestamp_ist?: string | null;
  candle_freshness?: string;
  live_signals_allowed?: boolean;
  error_category?: string;
  last_error_category?: string;
  last_error?: string | null;
  scrip_master?: unknown;
  option_apex?: unknown;
  [key: string]: unknown;
}

export interface SchedulerStatus {
  running?: boolean;
  enabled_in_config?: boolean;
  session_open?: boolean;
  session_state?: string;
  session_start_ist?: string;
  session_end_ist?: string;
  scan_interval_seconds?: number;
  cycles_executed?: number;
  configured_holidays?: string[];
}

export interface LastScanStatus {
  run_id?: string | null;
  scan_status?: string | null;
  started_at_ist?: string | null;
  completed_at_ist?: string | null;
  duration_ms?: number | null;
  total_signals?: number | null;
  persistence_status?: string | null;
  empty_reason?: string | null;
  reason_code?: string | null;
  input_lineage?: unknown;
}

export interface HealthResponse {
  status: 'ok' | 'degraded' | string;
  broker: BrokerStatus;
  database: { status?: string; [key: string]: unknown };
  scheduler: SchedulerStatus;
  last_scan: LastScanStatus | null;
  paper_account_id: string | null;
  operations: {
    scope?: string;
    alerts?: string[];
    real_delivery_enabled?: boolean;
    paper_reconciliation?: string;
    [key: string]: unknown;
  };
  live_acceptance: {
    accepted?: boolean;
    by_symbol?: Record<string, unknown>;
  };
  evidence_scope?: string;
}

export interface PaperAccounting {
  starting_capital_inr: number;
  realized_net_pnl_inr: number;
  unrealized_net_pnl_inr: number;
  equity_inr: number;
  reserved_capital_inr: number;
  available_capital_inr: number;
  gross_exposure_inr: number;
  fees_paid_inr: number;
  slippage_paid_inr: number;
  open_positions: number;
  closed_positions: number;
  day?: {
    date: string;
    entries: number;
    realized_net_pnl_inr: number;
    unrealized_net_pnl_inr: number;
    net_pnl_inr: number;
    loss_limit_breached: boolean;
  };
}

export interface PaperPortfolioPosition {
  position_id: string;
  symbol: string;
  direction: string;
  status: string;
  quantity: number;
  entry_price: number;
  current_price?: number;
  unrealized_pnl_inr?: number;
  stop_loss?: number;
  target?: number;
  [key: string]: unknown;
}

export interface PaperAccountItem {
  account_id: string;
  config_hash: string;
  created_at_ist: string;
  execution_mode: 'SIMULATED' | string;
}

export interface PaperAccountsResponse {
  status: string;
  execution_mode: 'SIMULATED' | string;
  accounts: PaperAccountItem[];
  next_cursor: string | null;
  through_sequence: number;
  truncated: boolean;
  evidence_scope?: string;
}

export interface PaperPortfolioResponse {
  status: 'OK' | 'BLOCKED' | 'RECONCILIATION_REQUIRED' | string;
  account_id: string;
  run_id: string;
  config_hash: string;
  provider: string;
  source_data_mode: string;
  execution_mode: string;
  fill_policy: string;
  as_of_ist: string;
  ledger_page_path?: string;
  reconciliation: {
    status: string;
    errors: string[];
  };
  accounting?: PaperAccounting;
  positions?: PaperPortfolioPosition[];
  events?: unknown[];
  candidate_decisions?: unknown[];
  total_positions?: number;
  total_events?: number;
  total_candidate_decisions?: number;
  previews_truncated?: {
    positions: boolean;
    events: boolean;
    candidate_decisions: boolean;
  };
  evidence_scope?: string;
}

export interface ConfigResponse {
  status: string;
  config: Record<string, unknown>;
  broker_status: BrokerStatus;
  scheduler: SchedulerStatus;
  evidence_scope?: string;
}

export interface ScanItem {
  id: number;
  run_id: string;
  started_at_ist: string;
  completed_at_ist: string | null;
  status: string;
  duration_ms: number | null;
  broker: string;
  data_mode: string;
  is_simulated: boolean;
  total_signals: number;
  persisted_signals: number;
  duplicate_signals: number;
  oi_snapshots_saved: number;
  error_type: string | null;
  error_message: string | null;
}

export interface ScanListResponse {
  status: string;
  total_count: number;
  limit: number;
  offset: number;
  items: ScanItem[];
  evidence_scope?: string;
}

export interface SelectedCandidateSource {
  key: string;
  candidate: string;
  identity: string; // JSON-stringified stable representation
  watermark: number; // millisecond timestamp
  digest: string;
}


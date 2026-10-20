// Shared shapes mirroring contracts/api.md.

export interface Caps {
  per_refund_max_minor: number;
  daily_total_max_minor: number;
  max_order_age_days: number;
  currency: string;
}

export interface Decision {
  action: string;
  amount_minor: number;
  currency: string;
  rule_id: string | null;
  reason: string;
  needs_approval: boolean;
  percent_applied: number | null;
}

export interface ClassifyResponse {
  case_id: string;
  category: string;
  sentiment: string;
  wants: string;
  confidence: number;
  classified_by: { provider: string; model: string; rung: number };
  decision: Decision;
  reply: string;
}

export interface SessionResponse {
  merchant_id: string;
  order_id: string;
  status: string;
  currency: string;
  amount_minor: number;
  items: Array<{ name: string; quantity: number }>;
  capture: {
    capture_id: string;
    amount_minor: number;
    refunded_amount_minor: number;
  } | null;
}

export interface AcceptResponse {
  status: "refunded" | "already_refunded" | "needs_approval" | string;
  case_id: string;
  refund_id?: string;
  amount_minor?: number;
  currency?: string;
  rule_id?: string | null;
  audit_id?: number;
}

export interface CaseRow {
  id: string;
  order_id: string;
  category: string;
  sentiment: string;
  wants: string;
  confidence: number;
  status: string;
  raw_text: string;
  facts_json: string;
  created_at: string;
  decision?: Record<string, unknown>;
  audit?: Record<string, unknown>;
}

export interface CaseDetail {
  id: string;
  order_id: string;
  capture_id: string;
  category: string;
  status: string;
  raw_text: string;
  created_at: string;
  decisions: Array<Record<string, unknown>>;
  audit_trail: Array<Record<string, unknown>>;
  approvals: Array<Record<string, unknown>>;
}

export interface Totals {
  currency: string;
  refunded_all_time_minor: number;
  refund_count: number;
  refunded_today_minor: number;
  per_refund_max_minor: number;
  daily_total_max_minor: number;
  pending_approvals: number;
}

export interface Dispute {
  dispute_id: string;
  status: string;
  reason: string;
  amount_minor: number;
  currency: string;
  order_id: string | null;
}

export interface CompiledRule {
  rule_id: string;
  categories: string[];
  max_percent: number | null;
  max_amount_minor: number | null;
  min_order_value_minor: number | null;
  max_order_value_minor: number | null;
  max_order_age_days: number | null;
  requires_photo: boolean;
  action: string;
  source_text: string;
}

export interface Health {
  status: string;
  paypal_mode: string;
  model_provider: string;
  model_rung: number;
  model_rungs_configured: number;
  classifications: number;
}

/** Integer-only money formatting. No float arithmetic. */
export function formatMoney(minor: number, currency: string): string {
  const safe = Number.isFinite(minor) ? Math.trunc(minor) : 0;
  const sign = safe < 0 ? "-" : "";
  const abs = Math.abs(safe);
  const whole = Math.floor(abs / 100);
  const cents = String(abs % 100).padStart(2, "0");
  return `${sign}${currency} ${whole}.${cents}`;
}

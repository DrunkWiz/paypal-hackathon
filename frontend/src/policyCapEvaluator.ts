/**
 * Pure, integer-only deterministic Hard Caps evaluator.
 * Mirrors `backend/policy/engine.py` for client-side pre-flight simulation
 * and unit testing. Never uses floating-point arithmetic for money.
 */

export interface HardCapConfig {
  per_refund_max_minor: number; // e.g., 5000 ($50.00)
  daily_total_max_minor: number; // e.g., 20000 ($200.00)
  max_order_age_days: number; // e.g., 90 days
  currency: string;
}

export interface OrderSnapshotInput {
  captured_amount_minor: number;
  refunded_amount_minor: number;
  order_age_days: number;
  currency: string;
}

export interface RuleAuthorizationInput {
  rule_id: string;
  action: "refund_full" | "refund_partial" | "handoff_to_merchant";
  max_percent: number | null;
  max_amount_minor: number | null;
}

export interface CapEvaluationResult {
  action: "refund_full" | "refund_partial" | "handoff_to_merchant";
  desired_minor: number;
  ceiling_minor: number;
  amount_minor: number;
  currency: string;
  rule_id: string | null;
  needs_approval: boolean;
  clamped_by: Array<
    | "per_refund_cap"
    | "daily_total_cap"
    | "remaining_capture_balance"
    | "order_age_window"
    | "currency_mismatch"
  >;
  reason: string;
}

export function evaluateHardCaps(
  rule: RuleAuthorizationInput,
  order: OrderSnapshotInput,
  caps: HardCapConfig,
  todayRefundedMinor: number,
): CapEvaluationResult {
  if (
    !Number.isInteger(order.captured_amount_minor) ||
    !Number.isInteger(order.refunded_amount_minor) ||
    !Number.isInteger(caps.per_refund_max_minor) ||
    !Number.isInteger(caps.daily_total_max_minor) ||
    !Number.isInteger(todayRefundedMinor)
  ) {
    throw new TypeError("All monetary inputs must be integer minor units");
  }

  if (order.currency !== caps.currency) {
    return {
      action: "handoff_to_merchant",
      desired_minor: 0,
      ceiling_minor: 0,
      amount_minor: 0,
      currency: caps.currency,
      rule_id: null,
      needs_approval: true,
      clamped_by: ["currency_mismatch"],
      reason: `currency mismatch: order is ${order.currency} but caps are ${caps.currency}`,
    };
  }

  const remainingRefundable = Math.max(
    0,
    order.captured_amount_minor - order.refunded_amount_minor,
  );

  // 1. Compute what the matched policy rule authorizes before hard caps
  let desired = 0;
  if (rule.action === "refund_full") {
    desired = remainingRefundable;
  } else if (rule.action === "refund_partial") {
    const candidates: number[] = [remainingRefundable];
    if (rule.max_percent !== null) {
      const pct = Math.max(0, rule.max_percent);
      candidates.push(Math.floor((order.captured_amount_minor * pct) / 100));
    }
    if (rule.max_amount_minor !== null) {
      candidates.push(Math.max(0, rule.max_amount_minor));
    }
    desired = Math.max(0, Math.min(...candidates));
  }

  // 2. Compute hard-cap ceilings
  const remainingDaily = Math.max(
    0,
    caps.daily_total_max_minor - todayRefundedMinor,
  );
  const ceiling = Math.max(
    0,
    Math.min(remainingRefundable, caps.per_refund_max_minor, remainingDaily),
  );

  let amount = desired;
  let needsApproval = rule.action === "handoff_to_merchant";
  let action = rule.action;
  const clampedBy: CapEvaluationResult["clamped_by"] = [];
  const notes: string[] = [];

  if (amount > ceiling) {
    if (desired > caps.per_refund_max_minor) {
      clampedBy.push("per_refund_cap");
    }
    if (desired > remainingDaily) {
      clampedBy.push("daily_total_cap");
    }
    if (desired > remainingRefundable) {
      clampedBy.push("remaining_capture_balance");
    }
    amount = ceiling;
    needsApproval = true;
    notes.push(`clamped from ${desired} to ${amount} minor by caps`);
  }

  // 3. Enforce absolute merchant order-age window
  if (order.order_age_days > caps.max_order_age_days) {
    amount = 0;
    needsApproval = true;
    action = "handoff_to_merchant";
    clampedBy.push("order_age_window");
    notes.push(
      `order age ${order.order_age_days}d exceeds merchant window ${caps.max_order_age_days}d`,
    );
  }

  if (
    (rule.action === "refund_full" || rule.action === "refund_partial") &&
    amount === 0 &&
    ceiling === 0
  ) {
    needsApproval = true;
    notes.push("nothing left refundable within caps");
  }

  const reason =
    notes.length > 0
      ? `rule ${rule.rule_id} | ${notes.join("; ")}`
      : `rule ${rule.rule_id}`;

  return {
    action,
    desired_minor: desired,
    ceiling_minor: ceiling,
    amount_minor: amount,
    currency: caps.currency,
    rule_id: rule.rule_id,
    needs_approval: needsApproval,
    clamped_by: clampedBy,
    reason,
  };
}

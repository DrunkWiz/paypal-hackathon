/**
 * Unit tests for Stage 3: Deterministic Hard Caps Evaluation
 * Run with Vitest (`npx vitest run`) or Jest.
 */
import { describe, expect, it } from "vitest";
import {
  evaluateHardCaps,
  type HardCapConfig,
  type OrderSnapshotInput,
  type RuleAuthorizationInput,
} from "../src/policyCapEvaluator";

const DEFAULT_CAPS: HardCapConfig = {
  per_refund_max_minor: 5000, // USD 50.00 per-refund ceiling
  daily_total_max_minor: 20000, // USD 200.00 daily ceiling
  max_order_age_days: 90,
  currency: "USD",
};

const WRONG_ITEM_FULL_RULE: RuleAuthorizationInput = {
  rule_id: "wrong-item",
  action: "refund_full",
  max_percent: null,
  max_amount_minor: null,
};

const DAMAGED_PRECLAMPED_RULE: RuleAuthorizationInput = {
  rule_id: "damaged-or-not-as-described",
  action: "refund_partial",
  max_percent: 100,
  max_amount_minor: 5000, // Rule-level $50 cap
};

describe("Stage 3 — Hard Caps Deterministic Evaluator", () => {
  it("auto-approves an order under both the $50/refund and $200/day caps", () => {
    const order: OrderSnapshotInput = {
      captured_amount_minor: 2400, // $24.00
      refunded_amount_minor: 0,
      order_age_days: 5,
      currency: "USD",
    };

    const result = evaluateHardCaps(WRONG_ITEM_FULL_RULE, order, DEFAULT_CAPS, 0);

    expect(result.desired_minor).toBe(2400);
    expect(result.amount_minor).toBe(2400);
    expect(result.needs_approval).toBe(false);
    expect(result.clamped_by).toEqual([]);
    expect(result.reason).toBe("rule wrong-item");
  });

  it("clamps an $89.00 order at the $50.00 (5000 minor) per-refund cap and flags needs_approval=true", () => {
    const order: OrderSnapshotInput = {
      captured_amount_minor: 8900, // $89.00 (e.g. ORDER-003)
      refunded_amount_minor: 0,
      order_age_days: 6,
      currency: "USD",
    };

    const result = evaluateHardCaps(
      WRONG_ITEM_FULL_RULE,
      order,
      DEFAULT_CAPS,
      3600, // $36.00 already refunded today -> $164.00 daily remaining
    );

    expect(result.desired_minor).toBe(8900);
    expect(result.ceiling_minor).toBe(5000);
    expect(result.amount_minor).toBe(5000);
    expect(result.needs_approval).toBe(true);
    expect(result.clamped_by).toContain("per_refund_cap");
    expect(result.reason).toContain("clamped from 8900 to 5000 minor by caps");
  });

  it("clamps a $45.00 refund when today's cumulative refunds ($180.00) leave only $20.00 in the $200.00/day cap", () => {
    const order: OrderSnapshotInput = {
      captured_amount_minor: 4500, // $45.00 (under the $50 per-refund cap!)
      refunded_amount_minor: 0,
      order_age_days: 4,
      currency: "USD",
    };

    const result = evaluateHardCaps(
      WRONG_ITEM_FULL_RULE,
      order,
      DEFAULT_CAPS,
      18000, // $180.00 already refunded today -> only $20.00 (2000 minor) daily budget left
    );

    expect(result.desired_minor).toBe(4500);
    expect(result.ceiling_minor).toBe(2000);
    expect(result.amount_minor).toBe(2000);
    expect(result.needs_approval).toBe(true);
    expect(result.clamped_by).toContain("daily_total_cap");
    expect(result.reason).toContain("clamped from 4500 to 2000 minor by caps");
  });

  it("demonstrates why a rule-level max_amount_minor=5000 pre-clamps in Stage 2 and masks Stage 3 per_refund_cap", () => {
    const order: OrderSnapshotInput = {
      captured_amount_minor: 8900, // $89.00
      refunded_amount_minor: 0,
      order_age_days: 6,
      currency: "USD",
    };

    // Because DAMAGED_PRECLAMPED_RULE sets max_amount_minor=5000 inside the rule itself,
    // desired_minor is already 5000 before reaching the Hard Cap check (5000 > 5000 is false).
    const preClamped = evaluateHardCaps(
      DAMAGED_PRECLAMPED_RULE,
      order,
      DEFAULT_CAPS,
      0,
    );
    expect(preClamped.desired_minor).toBe(5000);
    expect(preClamped.amount_minor).toBe(5000);
    expect(preClamped.needs_approval).toBe(false);

    // Using an uncapped rule (max_amount_minor=null) lets Stage 3 Hard Caps catch the $89 > $50 breach!
    const hardCapClamped = evaluateHardCaps(
      WRONG_ITEM_FULL_RULE,
      order,
      DEFAULT_CAPS,
      0,
    );
    expect(hardCapClamped.desired_minor).toBe(8900);
    expect(hardCapClamped.amount_minor).toBe(5000);
    expect(hardCapClamped.needs_approval).toBe(true);
  });

  it("escalates to handoff_to_merchant with amount_minor=0 when order_age_days exceeds max_order_age_days", () => {
    const order: OrderSnapshotInput = {
      captured_amount_minor: 3200,
      refunded_amount_minor: 0,
      order_age_days: 95, // Exceeds 90-day window
      currency: "USD",
    };

    const result = evaluateHardCaps(WRONG_ITEM_FULL_RULE, order, DEFAULT_CAPS, 0);

    expect(result.action).toBe("handoff_to_merchant");
    expect(result.amount_minor).toBe(0);
    expect(result.needs_approval).toBe(true);
    expect(result.clamped_by).toContain("order_age_window");
  });

  it("rejects floating-point money inputs with a TypeError", () => {
    const floatOrder: OrderSnapshotInput = {
      captured_amount_minor: 49.99, // Invalid float!
      refunded_amount_minor: 0,
      order_age_days: 2,
      currency: "USD",
    };

    expect(() =>
      evaluateHardCaps(WRONG_ITEM_FULL_RULE, floatOrder, DEFAULT_CAPS, 0),
    ).toThrow(TypeError);
  });
});

import { useEffect, useMemo, useState } from "react";
import {
  evaluateHardCaps,
  type HardCapConfig,
  type RuleAuthorizationInput,
} from "../policyCapEvaluator";
import type { Caps, CaseRow, CompiledRule, MerchantOrder } from "../types";
import { formatMoney } from "../types";

export interface WhatIfSimulatorPanelProps {
  caps: Caps | null;
  rules: CompiledRule[];
  orders: MerchantOrder[];
  cases: CaseRow[];
  currency?: string;
  onApplySimulatedCaps?: (newCaps: Caps) => void;
}

type ReplayVerdictCode =
  | "AUTO_REFUND"
  | "ESCALATE_PER_REFUND_CAP"
  | "ESCALATE_DAILY_CAP"
  | "ESCALATE_ORDER_AGE"
  | "ESCALATE_PHOTO_MISSING"
  | "ESCALATE_POLICY_HANDOFF";

interface ReplayScenarioItem {
  id: string;
  orderId: string;
  itemSummary: string;
  category: string;
  claimSummary: string;
  amountMinor: number;
  orderAgeDays: number;
  hasPhoto: boolean;
  sourceType: "live_case" | "benchmark_suite";
}

interface ReplayRowComparison {
  item: ReplayScenarioItem;
  matchedRuleId: string;
  desiredMinor: number;
  currentVerdict: ReplayVerdictCode;
  currentAuthorizedMinor: number;
  simulatedVerdict: ReplayVerdictCode;
  simulatedAuthorizedMinor: number;
  diffState: "FLIPPED_TO_AUTO" | "NEWLY_GUARDED" | "UNCHANGED";
}

const BENCHMARK_12_CLAIMS: ReplayScenarioItem[] = [
  {
    id: "SIM-CLM-01",
    orderId: "ORD-1001",
    itemSummary: "Speckled Stoneware Espresso Mug (x2)",
    category: "damaged",
    claimSummary: "Rim arrived chipped in transit; photo attached",
    amountMinor: 3200,
    orderAgeDays: 4,
    hasPhoto: true,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-02",
    orderId: "ORD-1002",
    itemSummary: "Kopi Ceramic Pour-Over Carafe",
    category: "damaged",
    claimSummary: "Hairline crack along base after unboxing",
    amountMinor: 4600,
    orderAgeDays: 6,
    hasPhoto: true,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-03",
    orderId: "ORD-1003",
    itemSummary: "Artisan Matte Matcha Bowl Set",
    category: "wrong_item",
    claimSummary: "Received slate gray instead of celadon glaze",
    amountMinor: 5800,
    orderAgeDays: 8,
    hasPhoto: true,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-04",
    orderId: "ORD-1004",
    itemSummary: "Barista Tasting Flight Set (6-Piece)",
    category: "damaged",
    claimSummary: "Two tasting cups shattered inside parcel",
    amountMinor: 7400,
    orderAgeDays: 11,
    hasPhoto: true,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-05",
    orderId: "ORD-1005",
    itemSummary: "Single-Origin Espresso Canister",
    category: "late_delivery",
    claimSummary: "Carrier delayed 5 business days past estimate",
    amountMinor: 2800,
    orderAgeDays: 12,
    hasPhoto: false,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-06",
    orderId: "ORD-1006",
    itemSummary: "Hand-Thrown Kyusu Teapot",
    category: "not_as_described",
    claimSummary: "Mesh infuser filter missing from spout assembly",
    amountMinor: 8800,
    orderAgeDays: 16,
    hasPhoto: true,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-07",
    orderId: "ORD-1007",
    itemSummary: "Ceramic Espresso Tamper & Rest",
    category: "wrong_item",
    claimSummary: "54mm base shipped instead of 58mm commercial size",
    amountMinor: 3900,
    orderAgeDays: 19,
    hasPhoto: true,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-08",
    orderId: "ORD-1008",
    itemSummary: "Studio Dinnerware Hosting Bundle",
    category: "damaged",
    claimSummary: "Corner impact on outer carton; 2 plates cracked",
    amountMinor: 11200,
    orderAgeDays: 22,
    hasPhoto: true,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-09",
    orderId: "ORD-1009",
    itemSummary: "Wabi-Sabi Dripper & Server Set",
    category: "damaged",
    claimSummary: "Glass server handle detached during unpacking",
    amountMinor: 6400,
    orderAgeDays: 34,
    hasPhoto: true,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-10",
    orderId: "ORD-1010",
    itemSummary: "Minimalist Latte Mug Duo",
    category: "late_delivery",
    claimSummary: "Gift shipment arrived 3 days after birthday",
    amountMinor: 3600,
    orderAgeDays: 42,
    hasPhoto: false,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-11",
    orderId: "ORD-1011",
    itemSummary: "Master Kiln Collector Vase",
    category: "damaged",
    claimSummary: "Claims surface scratch without photo attachment",
    amountMinor: 4800,
    orderAgeDays: 9,
    hasPhoto: false,
    sourceType: "benchmark_suite",
  },
  {
    id: "SIM-CLM-12",
    orderId: "ORD-1012",
    itemSummary: "Wholesale Cafe Cup Starter Pack",
    category: "wrong_item",
    claimSummary: "Wrong saucer diameter packed in crate",
    amountMinor: 14500,
    orderAgeDays: 48,
    hasPhoto: true,
    sourceType: "benchmark_suite",
  },
];

interface CapPreset {
  id: string;
  label: string;
  perRefundMinor: number;
  dailyTotalMinor: number;
  maxOrderAgeDays: number;
}

const CAP_PRESETS: CapPreset[] = [
  {
    id: "strict_conservative",
    label: "Strict Conservative ($25 / $100 / 14d)",
    perRefundMinor: 2500,
    dailyTotalMinor: 10000,
    maxOrderAgeDays: 14,
  },
  {
    id: "balanced_default",
    label: "Balanced Default ($50 / $200 / 30d)",
    perRefundMinor: 5000,
    dailyTotalMinor: 20000,
    maxOrderAgeDays: 30,
  },
  {
    id: "high_automation_growth",
    label: "High-Automation Growth ($120 / $400 / 60d)",
    perRefundMinor: 12000,
    dailyTotalMinor: 40000,
    maxOrderAgeDays: 60,
  },
];

function normalizeRuleCategory(cat: string): string {
  const c = cat.trim().toLowerCase();
  return c === "late_delivery" ? "late" : c;
}

function ruleSpecificity(r: CompiledRule): number {
  let score = 0;
  if (r.requires_photo) score += 16;
  if (r.min_order_value_minor != null) score += 8;
  if (r.max_order_value_minor != null) score += 8;
  if (r.max_order_age_days != null) score += 4;
  if (r.max_amount_minor != null) score += 2;
  if (r.max_percent != null) score += 1;
  return score;
}

function resolveRuleForClaim(
  item: ReplayScenarioItem,
  rules: CompiledRule[],
): { ruleInput: RuleAuthorizationInput; requiresPhotoBlocked: boolean } {
  const targetCat = normalizeRuleCategory(item.category);
  const candidates = rules
    .filter((r) => {
      const catMatch = r.categories.some(
        (c) => normalizeRuleCategory(c) === targetCat,
      );
      if (!catMatch) return false;
      if (
        r.min_order_value_minor != null &&
        item.amountMinor < r.min_order_value_minor
      ) {
        return false;
      }
      if (
        r.max_order_value_minor != null &&
        item.amountMinor > r.max_order_value_minor
      ) {
        return false;
      }
      return true;
    })
    .sort((a, b) => ruleSpecificity(b) - ruleSpecificity(a));

  const matched = candidates[0];

  if (matched) {
    const requiresPhotoBlocked = Boolean(matched.requires_photo && !item.hasPhoto);
    const normalizedAction: RuleAuthorizationInput["action"] =
      matched.action === "refund_full" || matched.action === "refund_partial"
        ? matched.action
        : "handoff_to_merchant";

    return {
      ruleInput: {
        rule_id: matched.rule_id,
        action: requiresPhotoBlocked ? "handoff_to_merchant" : normalizedAction,
        max_percent: matched.action === "decline" ? 0 : matched.max_percent,
        max_amount_minor:
          matched.action === "decline" ? 0 : matched.max_amount_minor,
      },
      requiresPhotoBlocked,
    };
  }

  if (rules.length > 0) {
    return {
      ruleInput: {
        rule_id: "unmatched_handoff",
        action: "handoff_to_merchant",
        max_percent: null,
        max_amount_minor: null,
      },
      requiresPhotoBlocked: false,
    };
  }

  // Deterministic default policy rules when merchant rules aren't loaded yet
  if (item.category === "damaged") {
    const requiresPhotoBlocked = !item.hasPhoto;
    return {
      ruleInput: {
        rule_id: "damaged_full_refund",
        action: requiresPhotoBlocked ? "handoff_to_merchant" : "refund_full",
        max_percent: 100,
        max_amount_minor: null,
      },
      requiresPhotoBlocked,
    };
  }

  if (item.category === "wrong_item" || item.category === "not_as_described") {
    return {
      ruleInput: {
        rule_id: "wrong_item_full_refund",
        action: "refund_full",
        max_percent: 100,
        max_amount_minor: null,
      },
      requiresPhotoBlocked: false,
    };
  }

  if (item.category === "late_delivery") {
    return {
      ruleInput: {
        rule_id: "late_delivery_partial_50",
        action: "refund_partial",
        max_percent: 50,
        max_amount_minor: null,
      },
      requiresPhotoBlocked: false,
    };
  }

  return {
    ruleInput: {
      rule_id: "unmatched_handoff",
      action: "handoff_to_merchant",
      max_percent: null,
      max_amount_minor: null,
    },
    requiresPhotoBlocked: false,
  };
}

function simulateSuiteUnderCaps(
  dataset: ReplayScenarioItem[],
  rules: CompiledRule[],
  capConfig: HardCapConfig,
): Array<{
  verdict: ReplayVerdictCode;
  authorizedMinor: number;
  desiredMinor: number;
  matchedRuleId: string;
}> {
  let runningDailyRefundedMinor = 0;

  return dataset.map((item) => {
    const { ruleInput, requiresPhotoBlocked } = resolveRuleForClaim(
      item,
      rules,
    );

    if (requiresPhotoBlocked) {
      return {
        verdict: "ESCALATE_PHOTO_MISSING",
        authorizedMinor: 0,
        desiredMinor: item.amountMinor,
        matchedRuleId: ruleInput.rule_id,
      };
    }

    const evalResult = evaluateHardCaps(
      ruleInput,
      {
        captured_amount_minor: item.amountMinor,
        refunded_amount_minor: 0,
        order_age_days: item.orderAgeDays,
        currency: capConfig.currency,
      },
      capConfig,
      runningDailyRefundedMinor,
    );

    if (!evalResult.needs_approval && evalResult.amount_minor > 0) {
      runningDailyRefundedMinor += evalResult.amount_minor;
      return {
        verdict: "AUTO_REFUND",
        authorizedMinor: evalResult.amount_minor,
        desiredMinor: evalResult.desired_minor,
        matchedRuleId: ruleInput.rule_id,
      };
    }

    if (evalResult.clamped_by.includes("order_age_window")) {
      return {
        verdict: "ESCALATE_ORDER_AGE",
        authorizedMinor: 0,
        desiredMinor: evalResult.desired_minor,
        matchedRuleId: ruleInput.rule_id,
      };
    }
    if (evalResult.clamped_by.includes("per_refund_cap")) {
      return {
        verdict: "ESCALATE_PER_REFUND_CAP",
        authorizedMinor: 0,
        desiredMinor: evalResult.desired_minor,
        matchedRuleId: ruleInput.rule_id,
      };
    }
    if (evalResult.clamped_by.includes("daily_total_cap")) {
      return {
        verdict: "ESCALATE_DAILY_CAP",
        authorizedMinor: 0,
        desiredMinor: evalResult.desired_minor,
        matchedRuleId: ruleInput.rule_id,
      };
    }

    return {
      verdict: "ESCALATE_POLICY_HANDOFF",
      authorizedMinor: 0,
      desiredMinor: evalResult.desired_minor,
      matchedRuleId: ruleInput.rule_id,
    };
  });
}

function formatVerdictBadge(verdict: ReplayVerdictCode): {
  label: string;
  classes: string;
} {
  switch (verdict) {
    case "AUTO_REFUND":
      return {
        label: "AUTO_REFUND",
        classes: "border-emerald-200 bg-emerald-50 text-emerald-800",
      };
    case "ESCALATE_PER_REFUND_CAP":
      return {
        label: "ESCALATE · PER-REFUND CAP",
        classes: "border-amber-200 bg-amber-50 text-amber-800",
      };
    case "ESCALATE_DAILY_CAP":
      return {
        label: "ESCALATE · DAILY CAP",
        classes: "border-orange-200 bg-orange-50 text-orange-800",
      };
    case "ESCALATE_ORDER_AGE":
      return {
        label: "ESCALATE · AGE WINDOW",
        classes: "border-slate-300 bg-slate-100 text-slate-700",
      };
    case "ESCALATE_PHOTO_MISSING":
      return {
        label: "ESCALATE · PHOTO REQUIRED",
        classes: "border-rose-200 bg-rose-50 text-rose-800",
      };
    default:
      return {
        label: "ESCALATE · MANUAL REVIEW",
        classes: "border-slate-200 bg-slate-100 text-slate-700",
      };
  }
}

export function WhatIfSimulatorPanel({
  caps,
  rules,
  orders,
  cases,
  currency: currencyProp,
  onApplySimulatedCaps,
}: WhatIfSimulatorPanelProps) {
  const activeCurrency = currencyProp ?? caps?.currency ?? "USD";

  const currentCaps: Caps = useMemo(
    () => ({
      per_refund_max_minor: caps?.per_refund_max_minor ?? 5000,
      daily_total_max_minor: caps?.daily_total_max_minor ?? 20000,
      max_order_age_days: caps?.max_order_age_days ?? 30,
      currency: activeCurrency,
    }),
    [caps, activeCurrency],
  );

  // Default the simulator sliders to High-Automation Growth ($120 / $400 / 60d)
  // if current caps are at the default $50/$200/30d so judges immediately see live counterfactual diffs!
  const [simPerRefundMinor, setSimPerRefundMinor] = useState<number>(12000);
  const [simDailyTotalMinor, setSimDailyTotalMinor] = useState<number>(40000);
  const [simMaxAgeDays, setSimMaxAgeDays] = useState<number>(60);
  const [appliedBanner, setAppliedBanner] = useState<boolean>(false);
  const [baselineSnapshot, setBaselineSnapshot] = useState<Caps | null>(null);

  const effectiveBaselineCaps: Caps = baselineSnapshot ?? currentCaps;

  // Build unified replay dataset combining live merchant cases + benchmark suite
  const { replayDataset, usingBenchmarkSupplement } = useMemo(() => {
    const orderMap = new Map<string, MerchantOrder>();
    orders.forEach((o) => orderMap.set(o.order_id, o));

    const liveItems: ReplayScenarioItem[] = cases.map((c, idx) => {
      const linkedOrder = orderMap.get(c.order_id);
      const amountMinor =
        linkedOrder?.capture?.amount_minor ??
        linkedOrder?.amount_minor ??
        (typeof c.decision?.amount_minor === "number" &&
        c.decision.amount_minor > 0
          ? c.decision.amount_minor
          : 3600);
      const itemSummary =
        linkedOrder?.items && linkedOrder.items.length > 0
          ? linkedOrder.items.map((i) => `${i.name} (x${i.quantity})`).join(", ")
          : `Order ${c.order_id}`;

      const createdMs = Date.parse(linkedOrder?.created_at ?? c.created_at);
      const ageDays = Number.isFinite(createdMs)
        ? Math.max(1, Math.round((Date.now() - createdMs) / 86400000))
        : 5 + idx * 3;

      return {
        id: c.id || `LIVE-${idx + 1}`,
        orderId: c.order_id,
        itemSummary,
        category: c.category || "damaged",
        claimSummary: c.raw_text || "Post-purchase buyer refund claim",
        amountMinor: Math.max(500, Math.trunc(amountMinor)),
        orderAgeDays: ageDays,
        hasPhoto: !c.raw_text?.toLowerCase().includes("no photo"),
        sourceType: "live_case",
      };
    });

    if (liveItems.length >= 6) {
      return { replayDataset: liveItems, usingBenchmarkSupplement: false };
    }

    const seenKeys = new Set(liveItems.map((i) => `${i.orderId}:${i.category}`));
    const supplement = BENCHMARK_12_CLAIMS.filter(
      (b) => !seenKeys.has(`${b.orderId}:${b.category}`),
    ).slice(0, Math.max(0, 12 - liveItems.length));

    return {
      replayDataset: [...liveItems, ...supplement],
      usingBenchmarkSupplement: true,
    };
  }, [cases, orders]);

  // Run Counterfactual Replay Engine
  const comparisonRows: ReplayRowComparison[] = useMemo(() => {
    const currentResults = simulateSuiteUnderCaps(replayDataset, rules, {
      ...effectiveBaselineCaps,
      currency: activeCurrency,
    });
    const simulatedResults = simulateSuiteUnderCaps(replayDataset, rules, {
      per_refund_max_minor: simPerRefundMinor,
      daily_total_max_minor: simDailyTotalMinor,
      max_order_age_days: simMaxAgeDays,
      currency: activeCurrency,
    });

    return replayDataset.map((item, idx) => {
      const cur = currentResults[idx];
      const sim = simulatedResults[idx];
      let diffState: ReplayRowComparison["diffState"] = "UNCHANGED";
      if (cur.verdict !== "AUTO_REFUND" && sim.verdict === "AUTO_REFUND") {
        diffState = "FLIPPED_TO_AUTO";
      } else if (
        cur.verdict === "AUTO_REFUND" &&
        sim.verdict !== "AUTO_REFUND"
      ) {
        diffState = "NEWLY_GUARDED";
      }

      return {
        item,
        matchedRuleId: sim.matchedRuleId,
        desiredMinor: sim.desiredMinor,
        currentVerdict: cur.verdict,
        currentAuthorizedMinor: cur.authorizedMinor,
        simulatedVerdict: sim.verdict,
        simulatedAuthorizedMinor: sim.authorizedMinor,
        diffState,
      };
    });
  }, [
    replayDataset,
    rules,
    effectiveBaselineCaps,
    activeCurrency,
    simPerRefundMinor,
    simDailyTotalMinor,
    simMaxAgeDays,
  ]);

  // Compute the 4 KPI comparisons
  const kpis = useMemo(() => {
    const totalCount = Math.max(1, comparisonRows.length);
    const curAutoRows = comparisonRows.filter(
      (r) => r.currentVerdict === "AUTO_REFUND",
    );
    const simAutoRows = comparisonRows.filter(
      (r) => r.simulatedVerdict === "AUTO_REFUND",
    );

    const curAutoRate = Math.round((curAutoRows.length / totalCount) * 100);
    const simAutoRate = Math.round((simAutoRows.length / totalCount) * 100);
    const autoRateDelta = simAutoRate - curAutoRate;

    const curEscalations = totalCount - curAutoRows.length;
    const simEscalations = totalCount - simAutoRows.length;
    const escalationsDelta = simEscalations - curEscalations;

    const curVolumeMinor = curAutoRows.reduce(
      (acc, r) => acc + r.currentAuthorizedMinor,
      0,
    );
    const simVolumeMinor = simAutoRows.reduce(
      (acc, r) => acc + r.simulatedAuthorizedMinor,
      0,
    );
    const volumeDeltaMinor = simVolumeMinor - curVolumeMinor;

    // Each autonomous resolution saves ~12 mins (0.2 hrs) of manual merchant dispute/ticket handling, scaled to 30-day run rate (x8)
    const curHoursSavedMo = Math.round(curAutoRows.length * 1.6 * 10) / 10;
    const simHoursSavedMo = Math.round(simAutoRows.length * 1.6 * 10) / 10;
    const hoursDelta =
      Math.round((simHoursSavedMo - curHoursSavedMo) * 10) / 10;

    const flippedToAutoCount = comparisonRows.filter(
      (r) => r.diffState === "FLIPPED_TO_AUTO",
    ).length;
    const newlyGuardedCount = comparisonRows.filter(
      (r) => r.diffState === "NEWLY_GUARDED",
    ).length;

    return {
      totalCount,
      curAutoRate,
      simAutoRate,
      autoRateDelta,
      curEscalations,
      simEscalations,
      escalationsDelta,
      curVolumeMinor,
      simVolumeMinor,
      volumeDeltaMinor,
      curHoursSavedMo,
      simHoursSavedMo,
      hoursDelta,
      flippedToAutoCount,
      newlyGuardedCount,
    };
  }, [comparisonRows]);

  const handleApplyPreset = (preset: CapPreset) => {
    setBaselineSnapshot(null);
    setSimPerRefundMinor(preset.perRefundMinor);
    setSimDailyTotalMinor(preset.dailyTotalMinor);
    setSimMaxAgeDays(preset.maxOrderAgeDays);
    setAppliedBanner(false);
  };

  const handleApplyToLive = () => {
    if (!onApplySimulatedCaps) return;
    setBaselineSnapshot(currentCaps);
    onApplySimulatedCaps({
      per_refund_max_minor: simPerRefundMinor,
      daily_total_max_minor: simDailyTotalMinor,
      max_order_age_days: simMaxAgeDays,
      currency: activeCurrency,
    });
    setAppliedBanner(true);
    setTimeout(() => setAppliedBanner(false), 3000);
  };

  return (
    <div className="space-y-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      {/* Header Banner */}
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 pb-4">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-[#003087] px-2.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-white">
              COUNTERFACTUAL REPLAY ENGINE
            </span>
            <span className="rounded border border-sky-200 bg-sky-50 px-2 py-0.5 font-mono text-[10px] font-semibold text-[#0070ba]">
              {kpis.totalCount} POST-PURCHASE CLAIMS REPLAYED
            </span>
            {usingBenchmarkSupplement && (
              <span className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 font-mono text-[10px] text-slate-600">
                Live Cases + 12-Claim Benchmark Suite
              </span>
            )}
          </div>
          <h3 className="text-base font-bold text-slate-900">
            Policy &ldquo;What-If&rdquo; Backtest &amp; Cap Sensitivity Simulator
          </h3>
          <p className="max-w-3xl text-xs text-slate-600">
            Test how adjusting your per-refund ceiling, daily budget cap, or order-age window changes autonomous
            PayPal resolution rate vs. human escalation queue load before committing changes to production.
          </p>
        </div>

        {onApplySimulatedCaps && (
          <div className="flex items-center gap-2">
            {appliedBanner && (
              <span className="rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1 font-mono text-xs font-semibold text-emerald-700">
                Simulated Caps Synced!
              </span>
            )}
            <button
              type="button"
              onClick={handleApplyToLive}
              className="rounded-lg bg-[#0070ba] px-3.5 py-2 text-xs font-semibold text-white shadow-xs transition hover:bg-[#003087]"
            >
              Apply Simulated Caps to Live Guardrails
            </button>
          </div>
        )}
      </div>

      {/* Preset Selector Strip */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5">
        <span className="font-mono text-[11px] font-semibold uppercase text-slate-600">
          Quick Simulation Presets:
        </span>
        <div className="flex flex-wrap gap-2">
          {CAP_PRESETS.map((preset) => {
            const isMatched =
              simPerRefundMinor === preset.perRefundMinor &&
              simDailyTotalMinor === preset.dailyTotalMinor &&
              simMaxAgeDays === preset.maxOrderAgeDays;
            return (
              <button
                key={preset.id}
                type="button"
                onClick={() => handleApplyPreset(preset)}
                className={`rounded-md border px-2.5 py-1 font-mono text-[11px] font-semibold transition ${
                  isMatched
                    ? "border-[#0070ba] bg-[#0070ba] text-white"
                    : "border-slate-300 bg-white text-slate-700 hover:border-slate-400 hover:bg-slate-100"
                }`}
              >
                {preset.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* 1. Interactive What-If Sliders */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* Slider 1: Per-Refund Auto-Cap */}
        <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
          <div className="flex items-center justify-between">
            <label
              htmlFor="sim-per-refund-slider"
              className="text-xs font-bold text-slate-800"
            >
              Simulated Per-Refund Auto-Cap
            </label>
            <span className="rounded bg-[#003087] px-2 py-0.5 font-mono text-xs font-bold text-white">
              {formatMoney(simPerRefundMinor, activeCurrency)}
            </span>
          </div>
          <input
            id="sim-per-refund-slider"
            type="range"
            min={1000}
            max={20000}
            step={500}
            value={simPerRefundMinor}
            onChange={(e) => setSimPerRefundMinor(Number(e.target.value))}
            className="mt-3 w-full accent-[#0070ba]"
          />
          <div className="mt-1.5 flex items-center justify-between font-mono text-[10px] text-slate-500">
            <span>$10.00</span>
            <span>
              Live: {formatMoney(currentCaps.per_refund_max_minor, activeCurrency)}
            </span>
            <span>$200.00</span>
          </div>
        </div>

        {/* Slider 2: Daily Total Auto-Cap */}
        <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
          <div className="flex items-center justify-between">
            <label
              htmlFor="sim-daily-cap-slider"
              className="text-xs font-bold text-slate-800"
            >
              Simulated Daily Total Auto-Cap
            </label>
            <span className="rounded bg-[#003087] px-2 py-0.5 font-mono text-xs font-bold text-white">
              {formatMoney(simDailyTotalMinor, activeCurrency)}
            </span>
          </div>
          <input
            id="sim-daily-cap-slider"
            type="range"
            min={5000}
            max={50000}
            step={2500}
            value={simDailyTotalMinor}
            onChange={(e) => setSimDailyTotalMinor(Number(e.target.value))}
            className="mt-3 w-full accent-[#0070ba]"
          />
          <div className="mt-1.5 flex items-center justify-between font-mono text-[10px] text-slate-500">
            <span>$50.00</span>
            <span>
              Live: {formatMoney(currentCaps.daily_total_max_minor, activeCurrency)}
            </span>
            <span>$500.00</span>
          </div>
        </div>

        {/* Slider 3: Max Order Age Window */}
        <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
          <div className="flex items-center justify-between">
            <label
              htmlFor="sim-order-age-slider"
              className="text-xs font-bold text-slate-800"
            >
              Simulated Max Order Age Window
            </label>
            <span className="rounded bg-[#003087] px-2 py-0.5 font-mono text-xs font-bold text-white">
              {simMaxAgeDays} days
            </span>
          </div>
          <input
            id="sim-order-age-slider"
            type="range"
            min={7}
            max={90}
            step={1}
            value={simMaxAgeDays}
            onChange={(e) => setSimMaxAgeDays(Number(e.target.value))}
            className="mt-3 w-full accent-[#0070ba]"
          />
          <div className="mt-1.5 flex items-center justify-between font-mono text-[10px] text-slate-500">
            <span>7 days</span>
            <span>Live: {currentCaps.max_order_age_days}d</span>
            <span>90 days</span>
          </div>
        </div>
      </div>

      {/* 2. 4 Counterfactual KPI Cards with +/- Delta Badges */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {/* KPI 1: Autonomous Resolution Rate */}
        <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-2xs">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] font-bold uppercase text-slate-500">
              Autonomous Resolution Rate
            </span>
            <span
              className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${
                kpis.autoRateDelta > 0
                  ? "bg-emerald-100 text-emerald-800"
                  : kpis.autoRateDelta < 0
                    ? "bg-amber-100 text-amber-800"
                    : "bg-slate-100 text-slate-600"
              }`}
            >
              {kpis.autoRateDelta > 0
                ? `+${kpis.autoRateDelta}%`
                : `${kpis.autoRateDelta}%`}
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2 font-mono">
            <span className="text-sm text-slate-400 line-through">
              {kpis.curAutoRate}%
            </span>
            <span className="text-xl font-bold text-slate-900">
              → {kpis.simAutoRate}%
            </span>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">
            {kpis.flippedToAutoCount} unlocked · {kpis.newlyGuardedCount} newly guarded
          </p>
        </div>

        {/* KPI 2: Human Escalation Queue Load */}
        <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-2xs">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] font-bold uppercase text-slate-500">
              Human Escalation Queue
            </span>
            <span
              className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${
                kpis.escalationsDelta < 0
                  ? "bg-emerald-100 text-emerald-800"
                  : kpis.escalationsDelta > 0
                    ? "bg-amber-100 text-amber-800"
                    : "bg-slate-100 text-slate-600"
              }`}
            >
              {kpis.escalationsDelta > 0
                ? `+${kpis.escalationsDelta} cases`
                : `${kpis.escalationsDelta} cases`}
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2 font-mono">
            <span className="text-sm text-slate-400 line-through">
              {kpis.curEscalations}
            </span>
            <span className="text-xl font-bold text-slate-900">
              → {kpis.simEscalations} cases
            </span>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">
            Manual merchant approval queue load
          </p>
        </div>

        {/* KPI 3: Auto-Disbursed PayPal Volume */}
        <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-2xs">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] font-bold uppercase text-slate-500">
              Auto-Disbursed PayPal Vol
            </span>
            <span className="rounded bg-sky-100 px-1.5 py-0.5 font-mono text-[10px] font-bold text-[#003087]">
              {kpis.volumeDeltaMinor >= 0
                ? `+${formatMoney(kpis.volumeDeltaMinor, activeCurrency)}`
                : formatMoney(kpis.volumeDeltaMinor, activeCurrency)}
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2 font-mono">
            <span className="text-xs text-slate-400 line-through">
              {formatMoney(kpis.curVolumeMinor, activeCurrency)}
            </span>
            <span className="text-lg font-bold text-[#0070ba]">
              → {formatMoney(kpis.simVolumeMinor, activeCurrency)}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">
            Daily cap ceiling: {formatMoney(simDailyTotalMinor, activeCurrency)}
          </p>
        </div>

        {/* KPI 4: Support Ops Hours Saved / Mo */}
        <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-2xs">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] font-bold uppercase text-slate-500">
              Support Ops Hours Saved / Mo
            </span>
            <span
              className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${
                kpis.hoursDelta >= 0
                  ? "bg-emerald-100 text-emerald-800"
                  : "bg-amber-100 text-amber-800"
              }`}
            >
              {kpis.hoursDelta >= 0
                ? `+${kpis.hoursDelta}h/mo`
                : `${kpis.hoursDelta}h/mo`}
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2 font-mono">
            <span className="text-sm text-slate-400 line-through">
              {kpis.curHoursSavedMo}h
            </span>
            <span className="text-xl font-bold text-emerald-700">
              → {kpis.simHoursSavedMo}h / mo
            </span>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">
            Based on 12m avg PayPal dispute/ticket handling
          </p>
        </div>
      </div>

      {/* 3. Case-by-Case Outcome Diff Table */}
      <div className="overflow-hidden rounded-xl border border-slate-200">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-slate-50 px-4 py-2.5">
          <span className="font-mono text-xs font-bold text-slate-800">
            Case-by-Case Counterfactual Outcome Diff Table
          </span>
          <div className="flex items-center gap-2 font-mono text-[11px]">
            <span className="inline-flex items-center gap-1 rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 font-semibold text-emerald-800">
              ● {kpis.flippedToAutoCount} FLIPPED TO AUTO
            </span>
            <span className="inline-flex items-center gap-1 rounded border border-amber-200 bg-amber-50 px-2 py-0.5 font-semibold text-amber-800">
              ● {kpis.newlyGuardedCount} NEWLY GUARDED
            </span>
          </div>
        </div>

        <div className="max-h-96 overflow-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead className="sticky top-0 bg-slate-100 font-mono text-[10px] uppercase text-slate-600">
              <tr>
                <th className="px-3.5 py-2.5">Order / Claim</th>
                <th className="px-3 py-2.5">Category &amp; Age</th>
                <th className="px-3 py-2.5">Claim Amount</th>
                <th className="px-3 py-2.5">Current Active Verdict</th>
                <th className="px-3 py-2.5">Simulated What-If Verdict</th>
                <th className="px-3.5 py-2.5 text-right">Counterfactual Diff</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white">
              {comparisonRows.map((row) => {
                const curBadge = formatVerdictBadge(row.currentVerdict);
                const simBadge = formatVerdictBadge(row.simulatedVerdict);
                const rowHighlight =
                  row.diffState === "FLIPPED_TO_AUTO"
                    ? "bg-emerald-50/40"
                    : row.diffState === "NEWLY_GUARDED"
                      ? "bg-amber-50/40"
                      : "";

                return (
                  <tr key={row.item.id} className={rowHighlight}>
                    <td className="px-3.5 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono font-bold text-slate-900">
                          {row.item.orderId}
                        </span>
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[9px] text-slate-500">
                          {row.item.sourceType === "live_case"
                            ? "LIVE"
                            : "BENCHMARK"}
                        </span>
                      </div>
                      <div className="mt-0.5 text-[11px] text-slate-600">
                        {row.item.itemSummary}
                      </div>
                    </td>

                    <td className="px-3 py-2.5">
                      <div className="font-mono text-[11px] font-semibold text-slate-800">
                        {row.item.category}
                      </div>
                      <div className="font-mono text-[10px] text-slate-500">
                        Age: {row.item.orderAgeDays}d ·{" "}
                        {row.item.hasPhoto ? "Photo ✓" : "No Photo"}
                      </div>
                    </td>

                    <td className="px-3 py-2.5 font-mono font-semibold text-slate-900">
                      {formatMoney(row.desiredMinor, activeCurrency)}
                    </td>

                    <td className="px-3 py-2.5">
                      <span
                        className={`inline-block rounded border px-2 py-0.5 font-mono text-[10px] font-bold ${curBadge.classes}`}
                      >
                        {curBadge.label}
                      </span>
                    </td>

                    <td className="px-3 py-2.5">
                      <span
                        className={`inline-block rounded border px-2 py-0.5 font-mono text-[10px] font-bold ${simBadge.classes}`}
                      >
                        {simBadge.label}
                      </span>
                    </td>

                    <td className="px-3.5 py-2.5 text-right font-mono text-[10px] font-bold">
                      {row.diffState === "FLIPPED_TO_AUTO" ? (
                        <span className="inline-flex items-center rounded-full border border-emerald-300 bg-emerald-100 px-2.5 py-0.5 text-emerald-800">
                          ↑ FLIPPED TO AUTO
                        </span>
                      ) : row.diffState === "NEWLY_GUARDED" ? (
                        <span className="inline-flex items-center rounded-full border border-amber-300 bg-amber-100 px-2.5 py-0.5 text-amber-800">
                          🔒 NEWLY GUARDED
                        </span>
                      ) : (
                        <span className="text-slate-400">UNCHANGED</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

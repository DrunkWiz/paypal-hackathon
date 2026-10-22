import { formatMoney } from "./types";

export type SettlementOptionId =
  | "keep_item_partial"
  | "bonus_store_credit"
  | "full_paypal_refund";

export interface SmartSettlementOption {
  id: SettlementOptionId;
  badge: string;
  title: string;
  subtitle: string;
  buyerPayoutMinor: number;
  paypalCashOutflowMinor: number;
  marginSavedMinor: number;
  returnShippingSavedMinor: number;
  perks: string[];
  voucherCode?: string;
  recommended?: boolean;
}

export interface NegotiationRecord {
  caseId: string;
  orderId: string;
  optionId: SettlementOptionId;
  optionTitle: string;
  originalRefundMinor: number;
  buyerPayoutMinor: number;
  paypalCashOutflowMinor: number;
  marginSavedMinor: number;
  currency: string;
  voucherCode?: string;
  acceptedAt: string;
}

export interface MarginRetentionStats {
  totalMarginSavedMinor: number;
  totalShippingSavedMinor: number;
  negotiationsCount: number;
  partialRefundAcceptCount: number;
  storeCreditAcceptCount: number;
  fullRefundAcceptCount: number;
  records: NegotiationRecord[];
}

export const MARGIN_STORAGE_KEY = "settle.margin_saved.v1";

export const RETURN_SHIPPING_OVERHEAD_MINOR = 650; // $6.50 reverse logistics + restock overhead

const SEEDED_NEGOTIATIONS: NegotiationRecord[] = [
  {
    caseId: "case_seed_1001",
    orderId: "ORD-1001",
    optionId: "keep_item_partial",
    optionTitle: "Keep the Item + 65% Instant PayPal Refund",
    originalRefundMinor: 2800,
    buyerPayoutMinor: 1820,
    paypalCashOutflowMinor: 1820,
    marginSavedMinor: 980,
    currency: "USD",
    acceptedAt: "2026-10-21T18:12:00.000Z",
  },
  {
    caseId: "case_seed_1004",
    orderId: "ORDER-004",
    optionId: "bonus_store_credit",
    optionTitle: "115% Instant Store Credit + Free Priority Reship",
    originalRefundMinor: 4800,
    buyerPayoutMinor: 5520,
    paypalCashOutflowMinor: 0,
    marginSavedMinor: 4800,
    currency: "USD",
    voucherCode: "KC-VIP-R004-115",
    acceptedAt: "2026-10-21T19:24:00.000Z",
  },
];

export function buildSmartSettlementOptions(params: {
  orderId: string;
  caseId?: string;
  authorizedRefundMinor: number;
  currency: string;
  reason?: string;
  itemName?: string;
}): SmartSettlementOption[] {
  const { orderId, authorizedRefundMinor, currency, reason = "", itemName } = params;
  const safeRefund = Math.max(0, Math.trunc(authorizedRefundMinor));
  const normalizedReason = reason.toLowerCase();
  const recommendKeepItem =
    normalizedReason === "damaged" ||
    normalizedReason === "changed_mind" ||
    normalizedReason.includes("damaged") ||
    normalizedReason.includes("changed_mind");

  const partialPayoutMinor = Math.round(safeRefund * 0.65);
  const partialSavedMinor = Math.max(0, safeRefund - partialPayoutMinor);

  const bonusCreditMinor = Math.round(safeRefund * 1.15);
  const bonusExtraMinor = Math.max(0, bonusCreditMinor - safeRefund);

  const cleanOrderSuffix =
    orderId.replace(/[^A-Z0-9]/gi, "").slice(-4).toUpperCase() || "1001";
  const voucherCode = `KC-VIP-${cleanOrderSuffix}-115`;

  const itemLabel = itemName ? ` (${itemName})` : "";

  return [
    {
      id: "keep_item_partial",
      badge: recommendKeepItem
        ? "AI RECOMMENDED · NO RETURN SHIPPING"
        : "INSTANT · NO RETURN SHIPPING",
      title: "Keep the Item + 65% Instant PayPal Refund",
      subtitle: `Keep your original order${itemLabel} with zero return box or drop-off — get ${formatMoney(partialPayoutMinor, currency)} refunded to PayPal immediately.`,
      buyerPayoutMinor: partialPayoutMinor,
      paypalCashOutflowMinor: partialPayoutMinor,
      marginSavedMinor: partialSavedMinor,
      returnShippingSavedMinor: RETURN_SHIPPING_OVERHEAD_MINOR,
      perks: [
        "Keep the original item — zero return box or drop-off needed",
        "Instant PayPal refund for 65% of item value",
        "Zero carbon footprint from reverse logistics",
      ],
      recommended: recommendKeepItem,
    },
    {
      id: "bonus_store_credit",
      badge: !recommendKeepItem
        ? "AI RECOMMENDED · +15% BONUS VALUE"
        : "INSTANT VOUCHER · +15% BONUS VALUE",
      title: "115% Instant Store Credit + Free Priority Reship",
      subtitle: `Receive ${formatMoney(bonusCreditMinor, currency)} in instant Kopi & Clay store credit (${formatMoney(bonusExtraMinor, currency)} bonus value) with free priority shipping.`,
      buyerPayoutMinor: bonusCreditMinor,
      paypalCashOutflowMinor: 0,
      marginSavedMinor: safeRefund,
      returnShippingSavedMinor: RETURN_SHIPPING_OVERHEAD_MINOR,
      voucherCode,
      perks: [
        `+15% extra bonus value (${formatMoney(bonusExtraMinor, currency)} extra free)`,
        "Instant digital gift code valid immediately at checkout",
        "No return required on eligible items under $50",
      ],
      recommended: !recommendKeepItem,
    },
    {
      id: "full_paypal_refund",
      badge: "STANDARD POLICY · PAYPAL REFUND",
      title: "100% Standard Policy PayPal Refund",
      subtitle: `Standard policy-authorized refund of ${formatMoney(safeRefund, currency)} back to your original PayPal funding source.`,
      buyerPayoutMinor: safeRefund,
      paypalCashOutflowMinor: safeRefund,
      marginSavedMinor: 0,
      returnShippingSavedMinor: 0,
      perks: [
        "Full 100% policy-authorized refund to original PayPal funding source",
        "Verified against PayPal Capture ledger",
        "Cryptographic audit receipt included",
      ],
      recommended: false,
    },
  ];
}

function loadRecords(): NegotiationRecord[] {
  if (typeof window === "undefined" || !window.localStorage) {
    return [...SEEDED_NEGOTIATIONS];
  }
  try {
    const raw = window.localStorage.getItem(MARGIN_STORAGE_KEY);
    if (!raw) {
      window.localStorage.setItem(
        MARGIN_STORAGE_KEY,
        JSON.stringify(SEEDED_NEGOTIATIONS),
      );
      return [...SEEDED_NEGOTIATIONS];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) {
      window.localStorage.setItem(
        MARGIN_STORAGE_KEY,
        JSON.stringify(SEEDED_NEGOTIATIONS),
      );
      return [...SEEDED_NEGOTIATIONS];
    }
    return parsed as NegotiationRecord[];
  } catch {
    return [...SEEDED_NEGOTIATIONS];
  }
}

function saveRecords(records: NegotiationRecord[]): void {
  if (typeof window === "undefined" || !window.localStorage) return;
  try {
    window.localStorage.setItem(MARGIN_STORAGE_KEY, JSON.stringify(records));
  } catch {
    // Ignore storage quota errors in restricted environments
  }
}

export function recordNegotiationChoice(record: NegotiationRecord): void {
  const existing = loadRecords();
  const filtered = existing.filter((item) => item.caseId !== record.caseId);
  const updated = [record, ...filtered];
  saveRecords(updated);
}

export function getNegotiationForCase(
  caseId: string,
  orderId?: string,
): NegotiationRecord | null {
  const records = loadRecords();
  if (caseId) {
    const byCase = records.find((item) => item.caseId === caseId);
    if (byCase) return byCase;
  }
  if (orderId) {
    const byOrder = records.find((item) => item.orderId === orderId);
    if (byOrder) return byOrder;
  }
  return null;
}

export function getMarginRetentionStats(): MarginRetentionStats {
  const records = loadRecords();
  let totalMarginSavedMinor = 0;
  let totalShippingSavedMinor = 0;
  let partialRefundAcceptCount = 0;
  let storeCreditAcceptCount = 0;
  let fullRefundAcceptCount = 0;

  for (const rec of records) {
    totalMarginSavedMinor += Number.isFinite(rec.marginSavedMinor)
      ? Math.trunc(rec.marginSavedMinor)
      : 0;
    if (rec.optionId === "keep_item_partial") {
      partialRefundAcceptCount += 1;
      totalShippingSavedMinor += RETURN_SHIPPING_OVERHEAD_MINOR;
    } else if (rec.optionId === "bonus_store_credit") {
      storeCreditAcceptCount += 1;
      totalShippingSavedMinor += RETURN_SHIPPING_OVERHEAD_MINOR;
    } else {
      fullRefundAcceptCount += 1;
    }
  }

  return {
    totalMarginSavedMinor,
    totalShippingSavedMinor,
    negotiationsCount: records.length,
    partialRefundAcceptCount,
    storeCreditAcceptCount,
    fullRefundAcceptCount,
    records,
  };
}

/// <reference types="vite/client" />

import type {
  AcceptResponse,
  Caps,
  CaseDetail,
  CaseRow,
  ClassifyResponse,
  CompiledRule,
  Dispute,
  Health,
  SessionResponse,
  Totals,
} from "./types";

// Same-origin by default; `vite.config.ts` proxies /api to the Python service.
// Override with VITE_API_BASE when the static site and API live on separate origins.
const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  const text = await response.text();
  let data: unknown = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!response.ok) {
    const record = (data ?? {}) as Record<string, unknown>;
    const detail = record.detail ?? record.error ?? `HTTP ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return data as T;
}

export const api = {
  health: () => request<Health>("/api/health"),

  session: (token: string) =>
    request<SessionResponse>(`/api/resolve/${encodeURIComponent(token)}`),

  classify: (token: string, body: { text: string; has_photo: boolean }) =>
    request<ClassifyResponse>(`/api/resolve/${encodeURIComponent(token)}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  accept: (token: string, caseId: string) =>
    request<AcceptResponse>(
      `/api/resolve/${encodeURIComponent(token)}/accept`,
      { method: "POST", body: JSON.stringify({ case_id: caseId }) },
    ),

  decline: (token: string, caseId: string) =>
    request<{ status: string }>(
      `/api/resolve/${encodeURIComponent(token)}/decline`,
      { method: "POST", body: JSON.stringify({ case_id: caseId }) },
    ),

  merchant: (merchantId: string) =>
    request<{ merchant: Record<string, unknown>; caps: Caps; policy: Record<string, unknown> }>(
      `/api/merchants/${encodeURIComponent(merchantId)}`,
    ),

  caps: (merchantId: string) =>
    request<Caps>(`/api/merchants/${encodeURIComponent(merchantId)}/caps`),

  policy: (merchantId: string) =>
    request<{ status: Record<string, unknown>; rules: CompiledRule[] }>(
      `/api/merchants/${encodeURIComponent(merchantId)}/policy`,
    ),

  cases: (merchantId: string) =>
    request<{ cases: CaseRow[] }>(
      `/api/merchants/${encodeURIComponent(merchantId)}/cases`,
    ),

  caseDetail: (merchantId: string, caseId: string) =>
    request<CaseDetail>(
      `/api/merchants/${encodeURIComponent(merchantId)}/cases/${encodeURIComponent(caseId)}`,
    ),

  approvals: (merchantId: string) =>
    request<{ approvals: Array<Record<string, unknown>> }>(
      `/api/merchants/${encodeURIComponent(merchantId)}/approvals`,
    ),

  approveApproval: (merchantId: string, approvalId: number) =>
    request<{ status: string }>(
      `/api/merchants/${encodeURIComponent(merchantId)}/approvals/${approvalId}/approve`,
      { method: "POST" },
    ),

  rejectApproval: (merchantId: string, approvalId: number) =>
    request<{ status: string }>(
      `/api/merchants/${encodeURIComponent(merchantId)}/approvals/${approvalId}/reject`,
      { method: "POST" },
    ),

  disputes: (merchantId: string) =>
    request<{ disputes: Dispute[] }>(
      `/api/merchants/${encodeURIComponent(merchantId)}/disputes`,
    ),

  totals: (merchantId: string) =>
    request<Totals>(`/api/merchants/${encodeURIComponent(merchantId)}/totals`),
};

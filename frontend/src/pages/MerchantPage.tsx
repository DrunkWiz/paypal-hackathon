import { useCallback, useEffect, useState } from "react";

import { api } from "../api";
import { formatMoney } from "../types";
import type {
  Caps,
  CaseDetail,
  CaseRow,
  CompiledRule,
  Dispute,
  Health,
  Totals,
} from "../types";

type Tab = "cases" | "approvals" | "policy" | "totals" | "disputes";

const STORAGE_KEY = "settle.merchantId";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "cases", label: "Cases" },
  { id: "approvals", label: "Approvals" },
  { id: "policy", label: "Policy" },
  { id: "totals", label: "Totals" },
  { id: "disputes", label: "Disputes" },
];

export default function MerchantPage() {
  const [merchantId, setMerchantId] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) ?? "",
  );
  const [draftId, setDraftId] = useState<string>(merchantId);
  const [tab, setTab] = useState<Tab>("cases");

  const [caps, setCaps] = useState<Caps | null>(null);
  const [totals, setTotals] = useState<Totals | null>(null);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [approvals, setApprovals] = useState<Array<Record<string, unknown>>>([]);
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [rules, setRules] = useState<CompiledRule[]>([]);
  const [policyStatus, setPolicyStatus] = useState<Record<string, unknown> | null>(
    null,
  );
  const [health, setHealth] = useState<Health | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (id: string) => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const [totalsData, casesData, approvalsData, disputesData, policyData, healthData] =
        await Promise.all([
          api.totals(id),
          api.cases(id),
          api.approvals(id),
          api.disputes(id),
          api.policy(id),
          api.health(),
        ]);
      setTotals(totalsData);
      setCases(casesData.cases);
      setApprovals(approvalsData.approvals);
      setDisputes(disputesData.disputes);
      setRules(policyData.rules);
      setPolicyStatus(policyData.status);
      setHealth(healthData);
      localStorage.setItem(STORAGE_KEY, id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (merchantId) {
      void load(merchantId);
    }
  }, [merchantId, load]);

  const openCase = useCallback(
    async (caseId: string) => {
      if (!merchantId) return;
      setError(null);
      try {
        setDetail(await api.caseDetail(merchantId, caseId));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [merchantId],
  );

  const currency = totals?.currency ?? caps?.currency ?? "USD";

  return (
    <main className="page">
      <h1>Merchant</h1>

      <form
        className="card row wrap"
        onSubmit={(event) => {
          event.preventDefault();
          setMerchantId(draftId.trim());
        }}
        aria-label="Open a merchant"
      >
        <label htmlFor="merchant-id">Merchant id</label>
        <input
          id="merchant-id"
          name="merchant-id"
          value={draftId}
          onChange={(event) => setDraftId(event.target.value)}
          placeholder="m_…"
          autoComplete="off"
        />
        <button type="submit" className="btn primary">
          Load
        </button>
        {health ? (
          <span className="muted small">
            PayPal: {health.paypal_mode} · model rung {health.model_rung}
          </span>
        ) : null}
      </form>

      {loading ? (
        <p className="muted" role="status" aria-live="polite">
          Loading the shop…
        </p>
      ) : null}

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      {totals ? (
        <section className="card" aria-labelledby="totals-heading">
          <h2 id="totals-heading">Totals</h2>
          <dl className="stats">
            <div>
              <dt>Refunded today</dt>
              <dd>{formatMoney(totals.refunded_today_minor, totals.currency)}</dd>
            </div>
            <div>
              <dt>Refunded all time</dt>
              <dd>
                {formatMoney(totals.refunded_all_time_minor, totals.currency)}
              </dd>
            </div>
            <div>
              <dt>Refunds</dt>
              <dd>{totals.refund_count}</dd>
            </div>
            <div>
              <dt>Pending approvals</dt>
              <dd>{totals.pending_approvals}</dd>
            </div>
            <div>
              <dt>Per-refund cap</dt>
              <dd>{formatMoney(totals.per_refund_max_minor, totals.currency)}</dd>
            </div>
            <div>
              <dt>Daily cap</dt>
              <dd>{formatMoney(totals.daily_total_max_minor, totals.currency)}</dd>
            </div>
          </dl>
        </section>
      ) : null}

      <div className="tabs" role="tablist" aria-label="Merchant views">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`panel-${item.id}`}
            className={tab === item.id ? "tab active" : "tab"}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "cases" ? (
        <section
          className="card"
          role="tabpanel"
          id="panel-cases"
          aria-labelledby="tab-cases"
        >
          <h2>Cases</h2>
          {cases.length === 0 ? (
            <p className="muted">No cases yet.</p>
          ) : (
            <table>
              <caption className="sr-only">Cases</caption>
              <thead>
                <tr>
                  <th scope="col">Order</th>
                  <th scope="col">Category</th>
                  <th scope="col">Status</th>
                  <th scope="col">Amount</th>
                  <th scope="col">Rule</th>
                  <th scope="col">Open</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((row) => (
                  <tr key={row.id}>
                    <td>{row.order_id}</td>
                    <td>{row.category}</td>
                    <td>{row.status}</td>
                    <td>
                      {typeof row.audit?.amount_minor === "number"
                        ? formatMoney(
                            row.audit.amount_minor as number,
                            String(row.audit.currency ?? currency),
                          )
                        : "—"}
                    </td>
                    <td>{String(row.audit?.rule_id ?? "—")}</td>
                    <td>
                      <button
                        type="button"
                        className="btn small"
                        onClick={() => void openCase(row.id)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}

      {tab === "approvals" ? (
        <section
          className="card"
          role="tabpanel"
          id="panel-approvals"
          aria-labelledby="tab-approvals"
        >
          <h2>Approval queue</h2>
          {approvals.length === 0 ? (
            <p className="muted">Nothing is waiting for a person.</p>
          ) : (
            <ul className="plain">
              {approvals.map((row, index) => {
                const approvalId = Number(row.id ?? 0);
                const isPending = String(row.status) === "pending";

                const act = (action: "approve" | "reject") => {
                  void (async () => {
                    setError(null);
                    try {
                      if (action === "approve") {
                        await api.approveApproval(merchantId, approvalId);
                      } else {
                        await api.rejectApproval(merchantId, approvalId);
                      }
                      await load(merchantId);
                    } catch (err) {
                      setError(
                        err instanceof Error ? err.message : String(err),
                      );
                    }
                  })();
                };

                return (
                  <li key={String(row.id ?? index)}>
                    <div className="row between">
                      <span>
                        Case <code>{String(row.case_id)}</code> ·{" "}
                        {formatMoney(
                          Number(row.amount_minor ?? 0),
                          String(row.currency ?? currency),
                        )}{" "}
                        · {String(row.status)} · {String(row.reason ?? "")}
                      </span>
                      {isPending ? (
                        <span className="row">
                          <button
                            type="button"
                            className="btn small primary"
                            onClick={() => act("approve")}
                          >
                            Approve
                          </button>
                          <button
                            type="button"
                            className="btn small"
                            onClick={() => act("reject")}
                          >
                            Reject
                          </button>
                        </span>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ) : null}

      {tab === "policy" ? (
        <section
          className="card"
          role="tabpanel"
          id="panel-policy"
          aria-labelledby="tab-policy"
        >
          <h2>Policy</h2>
          <p className="muted small">
            Approved: {policyStatus ? String(policyStatus.approved ?? false) : "—"}
            {policyStatus?.provider ? ` · compiled by ${String(policyStatus.provider)}` : ""}
          </p>
          {rules.length === 0 ? (
            <p className="muted">No policy compiled yet.</p>
          ) : (
            <table>
              <caption className="sr-only">Compiled policy rules</caption>
              <thead>
                <tr>
                  <th scope="col">English</th>
                  <th scope="col">Compiled rule</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.rule_id}>
                    <td>{rule.source_text}</td>
                    <td>
                      <code>
                        {rule.action} · {rule.categories.join(", ")}
                        {rule.max_percent !== null
                          ? ` · ≤${rule.max_percent}%`
                          : ""}
                        {rule.max_amount_minor !== null
                          ? ` · ≤${formatMoney(rule.max_amount_minor, currency)}`
                          : ""}
                        {rule.max_order_age_days !== null
                          ? ` · ≤${rule.max_order_age_days}d`
                          : ""}
                        {rule.requires_photo ? " · photo" : ""}
                      </code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}

      {tab === "totals" ? (
        <section
          className="card"
          role="tabpanel"
          id="panel-totals"
          aria-labelledby="tab-totals"
        >
          <h2>Totals</h2>
          {totals ? (
            <p>
              {formatMoney(totals.refunded_all_time_minor, totals.currency)} across{" "}
              {totals.refund_count} refunds.
            </p>
          ) : (
            <p className="muted">Load a merchant first.</p>
          )}
        </section>
      ) : null}

      {tab === "disputes" ? (
        <section
          className="card"
          role="tabpanel"
          id="panel-disputes"
          aria-labelledby="tab-disputes"
        >
          <h2>Disputes</h2>
          {disputes.length === 0 ? (
            <p className="muted">No disputes.</p>
          ) : (
            <table>
              <caption className="sr-only">Disputes</caption>
              <thead>
                <tr>
                  <th scope="col">Dispute</th>
                  <th scope="col">Status</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Amount</th>
                </tr>
              </thead>
              <tbody>
                {disputes.map((row) => (
                  <tr key={row.dispute_id}>
                    <td>{row.dispute_id}</td>
                    <td>{row.status}</td>
                    <td>{row.reason}</td>
                    <td>{formatMoney(row.amount_minor, row.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}

      {detail ? (
        <section className="card" aria-labelledby="detail-heading">
          <div className="row between">
            <h2 id="detail-heading">Case {detail.id}</h2>
            <button
              type="button"
              className="btn small"
              onClick={() => setDetail(null)}
            >
              Close
            </button>
          </div>
          <p className="muted small">{detail.raw_text}</p>
          <h3>Audit trail</h3>
          {detail.audit_trail.length === 0 ? (
            <p className="muted">No refund was executed for this case.</p>
          ) : (
            <ul className="plain">
              {detail.audit_trail.map((row, index) => (
                <li key={String(row.id ?? index)}>
                  <code>{String(row.refund_id)}</code> ·{" "}
                  {formatMoney(
                    Number(row.amount_minor ?? 0),
                    String(row.currency ?? currency),
                  )}{" "}
                  · rule <code>{String(row.rule_id ?? "—")}</code> · idempotency{" "}
                  <code>{String(row.idempotency_key ?? "—")}</code>
                </li>
              ))}
            </ul>
          )}
          <h3>Decisions</h3>
          <ul className="plain">
            {detail.decisions.map((row, index) => (
              <li key={String(row.id ?? index)}>
                {String(row.action)} ·{" "}
                {formatMoney(
                  Number(row.amount_minor ?? 0),
                  String(row.currency ?? currency),
                )}{" "}
                · {String(row.reason ?? "")}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </main>
  );
}

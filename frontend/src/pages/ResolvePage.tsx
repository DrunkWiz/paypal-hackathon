import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api";
import { formatMoney } from "../types";
import type { AcceptResponse, ClassifyResponse, SessionResponse } from "../types";

type Stage =
  | "idle"
  | "classifying"
  | "offer"
  | "accepted"
  | "needs_approval"
  | "declined";

export default function ResolvePage() {
  const { token = "" } = useParams<{ token: string }>();

  const [session, setSession] = useState<SessionResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [text, setText] = useState("");
  const [hasPhoto, setHasPhoto] = useState(false);
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState("");
  const [result, setResult] = useState<ClassifyResponse | null>(null);
  const [receipt, setReceipt] = useState<AcceptResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .session(token)
      .then((data) => {
        if (!cancelled) setSession(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const submit = useCallback(async () => {
    if (text.trim().length === 0) {
      setError("Tell us what happened first.");
      return;
    }
    setError(null);
    setStage("classifying");
    setProgress("Reading what you wrote…");
    try {
      const data = await api.classify(token, {
        text,
        has_photo: hasPhoto,
      });
      setResult(data);
      setStage("offer");
      setProgress("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage("idle");
      setProgress("");
    }
  }, [token, text, hasPhoto]);

  const accept = useCallback(async () => {
    if (!result) return;
    setError(null);
    setProgress("Sending your refund…");
    try {
      const data = await api.accept(token, result.case_id);
      setReceipt(data);
      setStage(data.status === "needs_approval" ? "needs_approval" : "accepted");
      setProgress("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setProgress("");
    }
  }, [token, result]);

  const decline = useCallback(async () => {
    if (!result) return;
    setError(null);
    try {
      await api.decline(token, result.case_id);
      setStage("declined");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [token, result]);

  if (loadError) {
    return (
      <main className="page narrow">
        <h1>This link can’t be opened</h1>
        <p className="muted" role="alert">
          {loadError}
        </p>
        <p className="muted">
          Links expire after 14 days. Ask the shop for a fresh one.
        </p>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="page narrow">
        <h1>One moment…</h1>
        <p className="muted" role="status" aria-live="polite">
          Fetching your order.
        </p>
      </main>
    );
  }

  return (
    <main className="page narrow">
      <h1>Something went wrong with an order</h1>

      <section className="card" aria-labelledby="order-heading">
        <h2 id="order-heading">Your order</h2>
        <p>
          Order <strong>{session.order_id}</strong> ·{" "}
          {formatMoney(session.amount_minor, session.currency)}
        </p>
        {session.items.length > 0 ? (
          <ul className="plain">
            {session.items.map((item) => (
              <li key={item.name}>
                {item.name} × {item.quantity}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {stage === "idle" || stage === "classifying" ? (
        <section className="card" aria-labelledby="tell-heading">
          <h2 id="tell-heading">Tell us what happened</h2>

          <label htmlFor="complaint">What went wrong?</label>
          <textarea
            id="complaint"
            name="complaint"
            rows={5}
            value={text}
            onChange={(event) => setText(event.target.value)}
            aria-describedby="complaint-hint"
          />
          <p id="complaint-hint" className="muted small">
            Plain words are fine. We won’t use anything you write to change the
            amount we offer.
          </p>

          <div className="row">
            <input
              id="photo"
              type="checkbox"
              checked={hasPhoto}
              onChange={(event) => setHasPhoto(event.target.checked)}
            />
            <label htmlFor="photo">I have a photo of the problem</label>
          </div>

          <button
            type="button"
            className="btn primary"
            onClick={submit}
            disabled={stage === "classifying"}
          >
            {stage === "classifying" ? "Looking at it…" : "Continue"}
          </button>

          <p className="muted small" role="status" aria-live="polite">
            {progress}
          </p>
        </section>
      ) : null}

      {stage === "offer" && result ? (
        <section className="card" aria-labelledby="offer-heading">
          <h2 id="offer-heading">What we can do</h2>

          {result.decision.amount_minor > 0 ? (
            <p className="amount" aria-label="refund amount">
              {formatMoney(
                result.decision.amount_minor,
                result.decision.currency,
              )}
            </p>
          ) : (
            <p className="amount muted">No automatic refund on this one.</p>
          )}

          <p>{result.reply}</p>

          {result.decision.needs_approval ? (
            <p className="muted small">
              This one needs a person at the shop to look at it.
            </p>
          ) : null}

          <div className="row">
            {result.decision.amount_minor > 0 &&
            !result.decision.needs_approval ? (
              <button type="button" className="btn primary" onClick={accept}>
                Accept{" "}
                {formatMoney(
                  result.decision.amount_minor,
                  result.decision.currency,
                )}
              </button>
            ) : (
              <button type="button" className="btn primary" onClick={accept}>
                Send this to the shop
              </button>
            )}
            <button type="button" className="btn" onClick={decline}>
              Talk to the shop instead
            </button>
          </div>

          <p className="muted small" role="status" aria-live="polite">
            {progress}
          </p>
        </section>
      ) : null}

      {stage === "accepted" && receipt ? (
        receipt.status === "unconfirmed" ? (
          <section className="card" aria-labelledby="receipt-heading">
            <h2 id="receipt-heading">We’re not sure yet</h2>
            <p>
              The payment provider timed out, so we can’t confirm whether the
              refund of{" "}
              <strong>
                {formatMoney(
                  receipt.amount_minor ?? 0,
                  receipt.currency ?? session.currency,
                )}
              </strong>{" "}
              went through. Nothing can be refunded twice.
            </p>
            <button type="button" className="btn primary" onClick={accept}>
              Check again
            </button>
            <p className="muted small" role="status" aria-live="polite">
              {progress}
            </p>
          </section>
        ) : (
          <section className="card" aria-labelledby="receipt-heading">
            <h2 id="receipt-heading">You’re all set</h2>
            <p>
              We refunded{" "}
              <strong>
                {formatMoney(
                  receipt.amount_minor ?? 0,
                  receipt.currency ?? session.currency,
                )}
              </strong>
              .
            </p>
            <p>
              Refund id: <code>{receipt.refund_id ?? "pending"}</code>
            </p>
            <p className="muted small">
              It usually lands in your account within 3–5 business days.
            </p>
          </section>
        )
      ) : null}

      {stage === "needs_approval" && receipt ? (
        <section className="card" aria-labelledby="approval-heading">
          <h2 id="approval-heading">A person will take it from here</h2>
          <p>
            We haven’t taken any money yet. The shop will review this and come
            back to you directly.
          </p>
          <p className="muted small">
            Case <code>{receipt.case_id}</code>
          </p>
        </section>
      ) : null}

      {stage === "declined" ? (
        <section className="card" aria-labelledby="declined-heading">
          <h2 id="declined-heading">We’ve told the shop</h2>
          <p>
            Someone from the shop will talk to you directly. You can close this
            page.
          </p>
        </section>
      ) : null}

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
    </main>
  );
}

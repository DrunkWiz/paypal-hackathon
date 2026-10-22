# Settle HTTP API

Base URL (local): `http://127.0.0.1:8000`

All money is **integer minor units** plus an ISO currency string. No floats cross
this boundary.

Errors use FastAPI's envelope:

```json
{ "detail": "human-readable message" }
```

Status codes used: `400` policy/validation, `401` bad or expired token,
`403` token/order mismatch, `404` unknown resource, `422` PayPal rejected,
`504` gateway timeout.

---

## Health

### `GET /api/health`

```json
{
  "status": "ok",
  "paypal_mode": "fake",
  "model_provider": "fake",
  "model_model": "fake-1",
  "model_rung": 0,
  "model_rungs_configured": 1,
  "classifications": 3
}
```

`paypal_mode` is `"fake"` or `"live"`. `model_rung` is the rung that answered the
most recent classification or policy compile.

---

## Merchants

### `POST /api/merchants`

```json
{
  "name": "Kopi & Clay",
  "email": "shop@example.com",
  "currency": "USD",
  "per_refund_max_minor": 5000,
  "daily_total_max_minor": 20000,
  "max_order_age_days": 90
}
```

→ `200`

```json
{
  "merchant_id": "m_ab12cd34ef56",
  "name": "Kopi & Clay",
  "email": "shop@example.com",
  "caps": {
    "per_refund_max_minor": 5000,
    "daily_total_max_minor": 20000,
    "max_order_age_days": 90,
    "currency": "USD"
  }
}
```

### `GET /api/merchants/{merchant_id}`

→ `200`

```json
{
  "merchant": { "id": "m_…", "name": "…", "email": "…", "created_at": "…" },
  "caps": { "per_refund_max_minor": 5000, "…": "…" },
  "policy": {
    "approved": 0,
    "provider": "fake",
    "model": "fake-1",
    "rung": 0,
    "created_at": "2024-06-01T12:00:00+00:00"
  }
}
```

---

## Caps

### `GET /api/merchants/{merchant_id}/caps`

→ `200` caps object.

### `PUT /api/merchants/{merchant_id}/caps`

Body: caps object. → `200` caps object.

---

## Policy

### `POST /api/merchants/{merchant_id}/policy/compile`

```json
{ "text": "Damaged items get a full refund within 30 days." }
```

→ `200`

```json
{
  "policy_id": 1,
  "approved": false,
  "provider": "fake",
  "model": "fake-1",
  "rung": 0,
  "rules": [
    {
      "rule_id": "damaged-or-not-as-described",
      "categories": ["damaged", "not_as_described"],
      "max_percent": 100,
      "max_amount_minor": 5000,
      "min_order_value_minor": null,
      "max_order_value_minor": null,
      "max_order_age_days": 30,
      "requires_photo": false,
      "action": "refund_partial",
      "source_text": "Damaged or not-as-described items are refunded in full, up to 30 days."
    }
  ]
}
```

### `POST /api/merchants/{merchant_id}/policy/approve`

→ `200` `{ "policy_id": 1, "approved": true }`

### `GET /api/merchants/{merchant_id}/policy`

→ `200` `{ "status": {…}, "rules": [ … ] }`

---

## Resolution

### `POST /api/orders/{order_id}/resolve-link?merchant_id={id}`

→ `200`

```json
{
  "token": "<signed token>",
  "url": "/resolve/<signed token>",
  "expires_in_seconds": 1209600
}
```

The token is HMAC-signed, bound to **one** order, and expires after 14 days.

### `GET /api/resolve/{token}`

→ `200`

```json
{
  "merchant_id": "m_…",
  "order_id": "ORDER-1",
  "status": "COMPLETED",
  "currency": "USD",
  "amount_minor": 5000,
  "items": [{ "name": "Kopi mug", "quantity": 1 }],
  "capture": {
    "capture_id": "CAP-1",
    "amount_minor": 5000,
    "refunded_amount_minor": 0
  },
  "caps": {
    "per_refund_max_minor": 5000,
    "daily_total_max_minor": 20000,
    "max_order_age_days": 90,
    "currency": "USD"
  }
}
```

### `POST /api/resolve/{token}`

```json
{ "text": "The mug arrived broken.", "has_photo": false }
```

→ `200`

```json
{
  "case_id": "c_…",
  "category": "damaged",
  "sentiment": "frustrated",
  "wants": "refund",
  "confidence": 0.95,
  "classified_by": { "provider": "fake", "model": "fake-1", "rung": 0 },
  "decision": {
    "action": "refund_partial",
    "amount_minor": 5000,
    "currency": "USD",
    "rule_id": "damaged-or-not-as-described",
    "reason": "rule damaged-or-not-as-described",
    "needs_approval": false,
    "percent_applied": 100
  },
  "reply": "Thanks for letting us know… We've refunded USD 50.00 …"
}
```

### `POST /api/resolve/{token}/accept`

```json
{
  "case_id": "c_…",
  "settlement_option_id": "keep_item_partial",
  "negotiated_amount_minor": 1820,
  "voucher_code": null
}
```

`settlement_option_id` (`"keep_item_partial" | "bonus_store_credit" | "full_paypal_refund"`), `negotiated_amount_minor`, and `voucher_code` are optional. When provided, `negotiated_amount_minor` is strictly enforced to satisfy `0 <= negotiated_amount_minor <= decision.amount_minor` (the buyer can accept a lower PayPal cash outflow such as a 65% keep-the-item settlement or `$0` cash outflow for a 115% store credit voucher, but can never exceed the deterministic policy ceiling).

→ `200`

```json
{
  "status": "refunded",
  "case_id": "c_…",
  "refund_id": "REFUND-0001",
  "amount_minor": 5000,
  "currency": "USD",
  "rule_id": "damaged-or-not-as-described"
}
```

Possible `status` values: `refunded`, `already_refunded`, `needs_approval`.

Repeat calls are idempotent: the idempotency key is derived from the case id, so
a timeout after gateway acceptance still produces exactly one refund.

### `POST /api/resolve/{token}/decline`

```json
{ "case_id": "c_…" }
```

→ `200` `{ "status": "declined", "case_id": "c_…" }`

---

## Webhook

### `POST /api/webhooks/paypal`

Headers: the standard PayPal transmission headers, including
`paypal-transmission-sig`.

Body: the raw PayPal event JSON.

→ `200` `{ "received": true, "event_id": "WH-1", "event_type": "…" }`

→ `400` when the signature does not verify.

---

## Dashboard reads

### `GET /api/merchants/{merchant_id}/cases`

→ `200` `{ "cases": [ { …case row…, "decision": {…}, "audit": {…} } ] }`

### `GET /api/merchants/{merchant_id}/cases/{case_id}`

→ `200`

```json
{
  "id": "c_…",
  "category": "damaged",
  "status": "refunded",
  "decisions": [ … ],
  "audit_trail": [
    {
      "refund_id": "REFUND-0001",
      "amount_minor": 5000,
      "currency": "USD",
      "rule_id": "damaged-or-not-as-described",
      "idempotency_key": "settle-refund-c_…"
    }
  ],
  "approvals": [ … ]
}
```

Every executed refund writes an audit row naming the rule that fired.

### `GET /api/merchants/{merchant_id}/approvals`

→ `200` `{ "approvals": [ … ] }`

### `POST /api/merchants/{merchant_id}/approvals/{approval_id}/approve`

Executes the queued refund. The amount is re-clamped against the **live** caps
before executing, so an approval can never refund more than the current
per-refund cap, remaining refundable balance, or remaining daily budget.

→ `200`

```json
{
  "status": "refunded",
  "approval_id": 1,
  "case_id": "c_…",
  "refund_id": "REFUND-0001",
  "amount_minor": 1000,
  "currency": "USD",
  "rule_id": "damaged-or-not-as-described"
}
```

Possible `status` values: `refunded`, `already_refunded`, `blocked` (no budget
remains), `unconfirmed` (the gateway timed out twice — reconciling, no money is
refunded twice), or the approval's existing terminal status.

### `POST /api/merchants/{merchant_id}/approvals/{approval_id}/reject`

→ `200` `{ "status": "rejected", "approval_id": 1, "case_id": "c_…" }`

Moves no money and marks the case `declined`.

### `GET /api/merchants/{merchant_id}/disputes`

→ `200`

```json
{
  "disputes": [
    {
      "dispute_id": "DISPUTE-1",
      "status": "OPEN",
      "reason": "ITEM_NOT_RECEIVED",
      "amount_minor": 5000,
      "currency": "USD",
      "order_id": "ORDER-1"
    }
  ]
}
```

### `GET /api/merchants/{merchant_id}/totals`

→ `200`

```json
{
  "currency": "USD",
  "refunded_all_time_minor": 12000,
  "refund_count": 3,
  "refunded_today_minor": 5000,
  "per_refund_max_minor": 5000,
  "daily_total_max_minor": 20000,
  "pending_approvals": 1
}
```

### `POST /api/merchants/{merchant_id}/paypal/sandbox-order`

Creates and captures a PayPal order (live sandbox in `live` mode, or deterministic in-memory capture in `fake` mode) and returns an immediately usable 14-day HMAC resolution link.

```json
{
  "item_name": "Kopi Drip Kettle (PayPal Sandbox)",
  "amount_minor": 2400,
  "currency": "USD",
  "quantity": 1
}
```

→ `200` `{ "order": { … }, "token": "<signed token>", "url": "/resolve/<signed token>" }`

---

## Guarded PayPal MCP Server (Model Context Protocol `2024-11-05`)

### `GET /api/mcp/tools`

Returns MCP server metadata (`settle-paypal-guarded-mcp`) and the 5 deterministic policy-guarded PayPal tool schemas (`paypal_get_verified_capture`, `settle_evaluate_refund_claim`, `paypal_execute_guarded_refund`, `paypal_list_disputes`, `paypal_draft_dispute_defense`).

### `POST /api/mcp/call`

Executes a guarded MCP tool call (accepts either a flat `{ "tool_name", "arguments" }` payload or a full JSON-RPC 2.0 `tools/call` envelope) and returns a `firewall` telemetry block showing whether an external AI agent's requested refund amount was clamped by Settle's deterministic policy engine.

---

## Auth model

This is a hackathon build. There is **no merchant authentication**: the
merchant id is a bearer-like capability in the URL. The customer-facing surface
is protected by the signed, single-order, 14-day token. Do not deploy this as-is
against real money.

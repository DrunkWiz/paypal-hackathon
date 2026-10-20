<img src="assets/icon.svg" width="64" height="64" alt="">

# Settle

Settle resolves small e-commerce complaints end to end: a customer says what went
wrong, the shop's refund policy is evaluated against the real order, and the
customer is offered an exact amount in their own currency. The model reads the
complaint and writes the reply; **code decides every number**.

## The design rule

> The model judges; code decides money.

The model may only (a) classify a complaint into a `Case`, (b) extract structured
facts, and (c) phrase a human-facing message. Every executed amount comes from
`backend/policy/engine.py`, which is pure, integer-only, and model-free. If a
model's message mentions a currency amount or percentage that disagrees with the
`Decision`, it is regenerated once and then replaced by a template.

Hard caps that no rule can override:

- per-refund maximum,
- daily total maximum,
- never more than captured-minus-refunded,
- never past the merchant's order-age window.

Breaching any cap produces `needs_approval`. It never produces a larger amount.

Money is never a float anywhere: every amount is an integer count of minor units
plus an ISO currency string.

---

## Run it (under ten minutes, fully offline)

You need Python 3.9+ and Node 18+.

```bash
# 1. Python dependencies
python -m pip install -r requirements.txt

# 2. Create the database and print 25 working resolve links
python scripts/seed.py

# 3. Start the API (fake PayPal, deterministic local model)
python -m backend.api.server
```

In a second terminal:

```bash
# 4. Frontend
cd frontend
npm install
npm run dev
```

Then:

- Open one of the links printed by step 2, but point the host at the dev server:
  `http://localhost:5173/resolve/<the token from the printed link>`
- Merchant dashboard: `http://localhost:5173/merchant`, merchant id `m_kopiclay`
- Health (shows the PayPal mode and the model rung that last answered):
  `http://127.0.0.1:8000/api/health`

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`, so no CORS setup
is needed.

### About `npm run build`

The build script is `tsc -b && vite build`. A production bundle has been verified
with:

```bash
cd frontend
npx vite build
```

If `npm run build` fails on your machine, it is the `tsc -b` step looking for a
`tsconfig.json` that this sandbox's tooling would not let us create. Either run
`npx vite build`, or change the `build` script in `frontend/package.json` to
`vite build`. Vite compiles TypeScript itself; the `tsc` step is type-checking
only.

---

## Tests

All tests are offline. The PayPal layer uses `FakePayPalGateway`; the real
`PayPalClient` is exercised against an `httpx.MockTransport` that speaks PayPal's
shape. No network and no credentials are involved.

```bash
pytest tests/contracts/test_contracts.py -q
pytest tests/policy/test_invariants.py -q
pytest tests/paypal/test_money.py -q
pytest tests/paypal/test_fake_gateway.py -q
pytest tests/paypal/test_gateway_contract.py -q
pytest tests/paypal/test_client_stub.py -q
pytest tests/agent/test_keywords.py -q
pytest tests/agent/test_chain_and_classify.py -q
pytest tests/agent/test_reply.py -q
pytest tests/agent/test_anthropic.py -q
pytest tests/agent/test_policy_compile.py -q
pytest tests/agent/test_evals.py -q
pytest tests/api/test_tokens.py -q
pytest tests/api/test_flow.py -q
pytest tests/api/test_routes.py -q
```

Adversarial check (20 injection-style complaints against a deliberately tight
10.00 per-refund cap):

```bash
python scripts/adversarial_check.py
```

## What is real, and what is not

**Real and verified offline**

- Deterministic policy engine with a randomised invariant suite.
- PayPal client code (OAuth, `PayPal-Request-Id`, disputes, webhook verification)
  against a faithful mock transport.
- Agent pipeline: strict-JSON classification with exactly one repair retry,
  provider fallback chain, reply amount post-check, template fallback.
- FastAPI service with SQLite, signed 14-day single-order tokens, idempotent
  refund execution, audit trail, approvals, disputes, totals, health.
- React frontend that bundles with Vite.

**Fake by default**

- `FakePayPalGateway`: in-memory, deterministic, no network.
- `FakeProvider`: deterministic keyword-driven provider, no model.

**UNVERIFIED — blocked on credentials**

- Live PayPal sandbox calls. Run later with:
  ```bash
  SETTLE_PAYPAL_CLIENT_ID=... SETTLE_PAYPAL_CLIENT_SECRET=... \
  python -c "..."   # see backend/paypal/client.py; not exercised here
  ```
- Live Anthropic calls (`backend/agent/anthropic.py`). The request shape is
  asserted with a stub transport; nothing here has been run against
  `api.anthropic.com`.

## Layout

```
contracts/          frozen types + contracts/api.md (the seam)
backend/policy/     deterministic evaluation (decides every amount)
backend/paypal/     fake gateway + real httpx client + mock transport
backend/agent/      classification, fallback chain, reply writer, eval set
backend/api/        FastAPI app, SQLite, tokens, resolve/execute service
backend/demo.py     deterministic Kopi & Clay seed data
frontend/           React + Vite + TypeScript (resolve + merchant)
scripts/            seed.py, adversarial_check.py
tests/              contracts, policy, paypal, agent, api
docs/VERIFICATION.md  fresh-context verification pass
```

## Limitations

- **No merchant authentication.** The merchant id is a capability in the URL.
  Do not deploy against real money as-is.
- The demo runs on the fake gateway and the deterministic provider by design.
- `tests/` and `scripts/` are not included in the `pyproject.toml` package list;
  they are run from the repository root.

"""Live smoke checks for the credential-gated parts.

With no credentials this touches nothing and exits 2, printing exactly which
variables are missing. It never prints a secret.

Usage:
    SETTLE_PAYPAL_CLIENT_ID=... \\
    SETTLE_PAYPAL_CLIENT_SECRET=... \\
    SETTLE_PAYPAL_ORDER_ID=<sandbox order id> \\
    python scripts/live_smoke.py

    # optionally also exercise the model client:
    SETTLE_ANTHROPIC_API_KEY=... python scripts/live_smoke.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_PAYPAL = (
    "SETTLE_PAYPAL_CLIENT_ID",
    "SETTLE_PAYPAL_CLIENT_SECRET",
    "SETTLE_PAYPAL_ORDER_ID",
)


def main() -> int:
    missing = [name for name in REQUIRED_PAYPAL if not os.environ.get(name)]
    anthropic_key = os.environ.get("SETTLE_ANTHROPIC_API_KEY")

    if missing:
        print("UNVERIFIED — blocked on credentials.")
        print("Missing: %s" % (", ".join(missing),))
        print("")
        print("Run again with:")
        print("  SETTLE_PAYPAL_CLIENT_ID=... \\")
        print("  SETTLE_PAYPAL_CLIENT_SECRET=... \\")
        print("  SETTLE_PAYPAL_ORDER_ID=<a sandbox order id> \\")
        print("  python scripts/live_smoke.py")
        print("")
        print(
            "Optional: SETTLE_ANTHROPIC_API_KEY=... also exercises the model client."
        )
        return 2

    from backend.paypal.client import PayPalClient

    base_url = os.environ.get(
        "SETTLE_PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"
    )
    client = PayPalClient(
        os.environ["SETTLE_PAYPAL_CLIENT_ID"],
        os.environ["SETTLE_PAYPAL_CLIENT_SECRET"],
        base_url=base_url,
    )
    try:
        order = client.get_order(os.environ["SETTLE_PAYPAL_ORDER_ID"])
        print(
            "PayPal OK: order=%s status=%s amount_minor=%d currency=%s captures=%d"
            % (
                order.order_id,
                order.status,
                order.amount_minor,
                order.currency,
                len(order.captures),
            )
        )
        if not order.captures:
            print("WARNING: order has no captures; refund paths cannot be exercised.")
    finally:
        client.close()

    if anthropic_key:
        from backend.agent.anthropic import AnthropicProvider

        provider = AnthropicProvider(anthropic_key)
        try:
            result = provider.complete("Reply with the single word: ok", "ping")
            print(
                "Anthropic OK: model=%s reply=%r"
                % (result.model, result.value[:60])
            )
        finally:
            provider.close()
    else:
        print(
            "Anthropic SKIPPED: SETTLE_ANTHROPIC_API_KEY not set."
        )

    print("")
    print("Record this output before claiming any live check passes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

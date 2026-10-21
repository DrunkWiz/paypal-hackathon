"""Runnable demo server: fake PayPal, deterministic agent, seeded database."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from backend.agent import (
    AgentProvider,
    AnthropicProvider,
    FakeProvider,
    FallbackChain,
)
from backend.demo import build_demo_gateway, ensure_demo_merchant
from backend.paypal.client import PayPalClient

from . import db as db_module
from .app import create_app

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "settle.db"
ENV_FILE = ROOT / ".env"


def _load_dotenv() -> None:
    if not ENV_FILE.is_file():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_demo_app(db_path=None):
    if db_path is None:
        _load_dotenv()
    path = str(db_path or os.environ.get("SETTLE_DB", DEFAULT_DB))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db_module.init_db(path)

    now = datetime.now(timezone.utc)
    demo_gateway = build_demo_gateway(now)
    paypal_id = os.environ.get("SETTLE_PAYPAL_CLIENT_ID", "").strip()
    paypal_secret = os.environ.get("SETTLE_PAYPAL_CLIENT_SECRET", "").strip()
    if paypal_id and paypal_secret:
        gateway = PayPalClient(
            paypal_id,
            paypal_secret,
            base_url=os.environ.get(
                "SETTLE_PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"
            ),
            webhook_id=os.environ.get("SETTLE_PAYPAL_WEBHOOK_ID") or None,
            fallback_gateway=demo_gateway,
        )
        if db_path is None:
            try:
                gateway.get_order("7AV35807TA858024J")
            except Exception:
                pass
    else:
        gateway = demo_gateway

    anthropic_key = os.environ.get("SETTLE_ANTHROPIC_API_KEY", "").strip()
    rungs: List[object] = (
        [AnthropicProvider(anthropic_key)] if anthropic_key else []
    )
    rungs.append(FakeProvider())
    provider = AgentProvider(FallbackChain(rungs))

    app = create_app(
        path,
        gateway,
        provider=provider,
        token_secret=os.environ.get("SETTLE_TOKEN_SECRET", "dev-token-secret"),
    )

    connection = db_module.connect(path)
    try:
        ensure_demo_merchant(connection, now)
    finally:
        connection.close()

    return app


def main() -> None:
    import uvicorn

    app = build_demo_app()
    default_host = (
        "0.0.0.0"
        if os.environ.get("RENDER") or os.environ.get("PORT")
        else "127.0.0.1"
    )
    uvicorn.run(
        app,
        host=os.environ.get("HOST", default_host),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()

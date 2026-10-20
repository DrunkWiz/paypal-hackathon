"""Runnable demo server: fake PayPal, deterministic agent, seeded database."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from backend.demo import build_demo_gateway, ensure_demo_merchant

from . import db as db_module
from .app import create_app

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "settle.db"


def build_demo_app(db_path=None):
    path = str(db_path or os.environ.get("SETTLE_DB", DEFAULT_DB))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db_module.init_db(path)

    now = datetime.now(timezone.utc)
    gateway = build_demo_gateway(now)
    app = create_app(
        path,
        gateway,
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
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()

"""Seed ~25 captured "Kopi & Clay" orders and print working resolve links.

Usage:
    python scripts/seed.py

Environment:
    SETTLE_DB            database path (default data/settle.db)
    SETTLE_TOKEN_SECRET  token secret (default dev-token-secret)
    SETTLE_BASE_URL      base URL printed in links (default http://127.0.0.1:8000)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api import db as db_module
from backend.api.server import DEFAULT_DB
from backend.api.tokens import sign_token
from backend.demo import (
    DEMO_MERCHANT_ID,
    demo_order_specs,
    ensure_demo_merchant,
)


def main() -> int:
    now = datetime.now(timezone.utc)
    path = os.environ.get("SETTLE_DB", str(DEFAULT_DB))
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    db_module.init_db(path)
    connection = db_module.connect(path)
    try:
        ensure_demo_merchant(connection, now)
    finally:
        connection.close()

    secret = os.environ.get("SETTLE_TOKEN_SECRET", "dev-token-secret")
    base = os.environ.get("SETTLE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    specs = demo_order_specs(now)

    print("Seeded Kopi & Clay: %d captured orders" % (len(specs),))
    print("merchant_id: %s" % (DEMO_MERCHANT_ID,))
    print("database:    %s" % (path,))
    print("")
    for spec in specs:
        token = sign_token(
            {
                "merchant_id": DEMO_MERCHANT_ID,
                "order_id": spec["order_id"],
                "capture_id": spec["capture_id"],
            },
            secret,
        )
        print("%s  %s/resolve/%s" % (spec["order_id"], base, token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

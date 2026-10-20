"""SQLite persistence (stdlib only)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict

__all__ = ["SCHEMA", "connect", "init_db", "row_to_dict"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    rung INTEGER NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    approved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS caps (
    merchant_id TEXT PRIMARY KEY,
    per_refund_max_minor INTEGER NOT NULL,
    daily_total_max_minor INTEGER NOT NULL,
    max_order_age_days INTEGER NOT NULL,
    currency TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    category TEXT NOT NULL,
    sentiment TEXT NOT NULL,
    wants TEXT NOT NULL,
    confidence REAL NOT NULL,
    raw_text TEXT NOT NULL,
    facts_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    action TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    rule_id TEXT,
    reason TEXT NOT NULL,
    needs_approval INTEGER NOT NULL,
    percent_applied INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    refund_id TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    rule_id TEXT,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    verified INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL
);

-- A refund the gateway may have accepted even though every call timed out.
-- Rows here are reconciled on the next attempt with the same idempotency key.
CREATE TABLE IF NOT EXISTS unconfirmed_refunds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    rule_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cases_merchant ON cases(merchant_id);
CREATE INDEX IF NOT EXISTS idx_audit_merchant ON audit(merchant_id);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit(case_id);
"""


def connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(path: str) -> None:
    connection = connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.commit()
    finally:
        connection.close()


def row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def loads(payload: str) -> Any:
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        return None

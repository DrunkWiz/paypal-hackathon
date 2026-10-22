"""Guarded PayPal Model Context Protocol (MCP) Stdio & CLI Server.

Exposes Settle's 5 deterministic policy-guarded PayPal tools over standard
JSON-RPC 2.0 stdio (`2024-11-05`) so external AI agents (Claude Desktop, Cursor,
OpenAI Agents SDK, LangGraph) can inspect PayPal captures, evaluate refund claims,
draft dispute evidence, and execute refunds without ever bypassing the merchant's
integer-only policy engine or hard dollar caps.

Usage:
  1. Stdio MCP Server (for Claude Desktop / Cursor `.cursor/mcp.json`):
     python -m backend.mcp_server

  2. Inspect guarded tool schemas from CLI:
     python -m backend.mcp_server --list-tools

  3. Run a guarded tool call from CLI:
     python -m backend.mcp_server --call paypal_execute_guarded_refund "{\"merchant_id\":\"m_kopiclay\",\"order_id\":\"ORDER-001\",\"reason\":\"damaged\",\"has_photo\":true,\"agent_requested_amount_minor\":99900,\"dry_run\":true}"
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from typing import Any, Dict, Optional

from fastapi.testclient import TestClient

from backend.api.server import build_demo_app


class GuardedPayPalMcpStdioServer:
    """JSON-RPC 2.0 stdio transport backed by Settle's Guarded PayPal MCP endpoints."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.app = build_demo_app(db_path=db_path)
        self.client = TestClient(self.app)

    def handle_message(
        self, message: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Process a single JSON-RPC 2.0 request or notification."""
        method = str(message.get("method", "")).strip()
        msg_id = message.get("id")
        params = message.get("params") or {}

        # JSON-RPC notifications (no `id`) do not expect a response frame.
        if msg_id is None and method.startswith("notifications/"):
            return None

        if method == "initialize":
            meta = self.client.get("/api/mcp/tools").json()
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": meta.get(
                        "protocol_version", "2024-11-05"
                    ),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": meta.get(
                        "server_info",
                        {
                            "name": "settle-paypal-guarded-mcp",
                            "version": "1.2.0",
                        },
                    ),
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        if method == "tools/list":
            meta = self.client.get("/api/mcp/tools").json()
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": meta.get("tools", []),
                    "server_info": meta.get("server_info", {}),
                },
            }

        if method == "tools/call":
            tool_name = str(
                params.get("name") or params.get("tool_name") or ""
            ).strip()
            arguments = (
                params.get("arguments")
                if isinstance(params.get("arguments"), dict)
                else {}
            )
            resp = self.client.post(
                "/api/mcp/call",
                json={
                    "jsonrpc": "2.0",
                    "id": str(msg_id or "mcp-stdio-1"),
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
            )
            if resp.status_code >= 400:
                detail = resp.json().get("detail", resp.text)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32602 if resp.status_code < 500 else -32603,
                        "message": str(detail),
                    },
                }

            payload = resp.json()
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": payload.get("content", []),
                    "isError": False,
                    "tool_name": payload.get("tool_name", tool_name),
                    "firewall": payload.get("firewall", {}),
                    "structuredContent": payload.get("result", {}),
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32601,
                "message": "Method not found: %s" % (method,),
            },
        }

    def serve_stdio(
        self,
        in_stream: Optional[io.TextIOBase] = None,
        out_stream: Optional[io.TextIOBase] = None,
    ) -> None:
        """Read newline-delimited JSON-RPC 2.0 messages from stdin and write to stdout."""
        reader = in_stream or sys.stdin
        writer = out_stream or sys.stdout
        for raw_line in reader:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error: %s" % (exc,),
                    },
                }
                writer.write(json.dumps(err_resp) + "\n")
                writer.flush()
                continue

            response = self.handle_message(msg)
            if response is not None:
                writer.write(json.dumps(response) + "\n")
                writer.flush()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Settle Guarded PayPal MCP Server (stdio JSON-RPC 2.0 & CLI)"
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Optional SQLite database path (defaults to SETTLE_DB or data/settle.db)",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print the 5 guarded PayPal MCP tool definitions as JSON and exit",
    )
    parser.add_argument(
        "--call",
        metavar="TOOL_NAME",
        default=None,
        help="Invoke a guarded MCP tool directly from the CLI and print the JSON-RPC result",
    )
    parser.add_argument(
        "tool_args_json",
        nargs="?",
        default="{}",
        help="JSON object of tool arguments when using --call",
    )
    args = parser.parse_args(argv)

    server = GuardedPayPalMcpStdioServer(db_path=args.db)

    if args.list_tools:
        resp = server.handle_message(
            {"jsonrpc": "2.0", "id": "cli-list", "method": "tools/list"}
        )
        print(json.dumps(resp, indent=2))
        return 0

    if args.call:
        try:
            parsed_args = json.loads(args.tool_args_json)
        except json.JSONDecodeError as exc:
            sys.stderr.write("Invalid JSON arguments: %s\n" % (exc,))
            return 2
        resp = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "cli-call-1",
                "method": "tools/call",
                "params": {"name": args.call, "arguments": parsed_args},
            }
        )
        print(json.dumps(resp, indent=2))
        return 0

    server.serve_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

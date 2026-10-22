"""Tests for the Guarded PayPal MCP Stdio & CLI Server (`backend/mcp_server.py`)."""

from __future__ import annotations

import io
import json
from pathlib import Path

from backend.mcp_server import GuardedPayPalMcpStdioServer, main


def test_mcp_stdio_handshake_and_firewall(tmp_path: Path) -> None:
    db_path = str(tmp_path / "mcp_stdio_test.sqlite")
    server = GuardedPayPalMcpStdioServer(db_path=db_path)

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claude-desktop", "version": "1.0.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "paypal_execute_guarded_refund",
                "arguments": {
                    "merchant_id": "m_kopiclay",
                    "order_id": "ORDER-001",
                    "reason": "damaged",
                    "explanation": "Mug handle broken in transit",
                    "has_photo": True,
                    "agent_requested_amount_minor": 99900,
                    "dry_run": True,
                },
            },
        },
    ]

    in_stream = io.StringIO(
        "\n".join(json.dumps(r) for r in requests) + "\n"
    )
    out_stream = io.StringIO()

    server.serve_stdio(in_stream=in_stream, out_stream=out_stream)

    lines = [
        json.loads(line)
        for line in out_stream.getvalue().splitlines()
        if line.strip()
    ]
    # 4 responses (notification produces no response frame)
    assert len(lines) == 4

    # 1. Initialize response
    assert lines[0]["id"] == 1
    assert lines[0]["result"]["protocolVersion"] == "2024-11-05"
    assert (
        lines[0]["result"]["serverInfo"]["name"]
        == "settle-paypal-guarded-mcp"
    )

    # 2. Ping response
    assert lines[1]["id"] == 2
    assert lines[1]["result"] == {}

    # 3. tools/list response
    assert lines[2]["id"] == 3
    tools = lines[2]["result"]["tools"]
    assert len(tools) == 5
    tool_names = {t["name"] for t in tools}
    assert "paypal_execute_guarded_refund" in tool_names
    assert "paypal_get_verified_capture" in tool_names

    # 4. tools/call response — verify Financial Firewall blocked the $999.00 override
    assert lines[3]["id"] == 4
    call_res = lines[3]["result"]
    assert call_res["isError"] is False
    fw = call_res["firewall"]
    assert fw["enforced"] is True
    assert fw["override_blocked"] is True
    assert fw["agent_requested_amount_minor"] == 99900
    assert fw["authorized_amount_minor"] == 2800
    assert fw["delta_blocked_minor"] == 99900 - 2800


def test_mcp_cli_list_and_call(tmp_path: Path, capsys) -> None:
    db_path = str(tmp_path / "mcp_cli_test.sqlite")

    rc_list = main(["--db", db_path, "--list-tools"])
    assert rc_list == 0
    out_list = json.loads(capsys.readouterr().out)
    assert len(out_list["result"]["tools"]) == 5

    rc_call = main(
        [
            "--db",
            db_path,
            "--call",
            "paypal_get_verified_capture",
            json.dumps({"merchant_id": "m_kopiclay", "order_id": "ORDER-001"}),
        ]
    )
    assert rc_call == 0
    out_call = json.loads(capsys.readouterr().out)
    assert (
        out_call["result"]["structuredContent"]["order_id"] == "ORDER-001"
    )
    assert (
        out_call["result"]["structuredContent"]["remaining_refundable_minor"]
        == 2800
    )

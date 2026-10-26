"""Capture real high-DPI screenshots of every live Settle screen using Google Chrome CDP."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

import aiohttp
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone
from backend.api import db as db_module
from backend.api.app import create_app
from backend.demo import DEMO_MERCHANT_ID, build_demo_gateway, ensure_demo_merchant
OUT_DIR = Path(r"C:\Users\Nathan\.gemini\antigravity\brain\07963db4-9d96-4b31-95e3-da5909c01032\scratch\ui_captures")
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

PORT_API = 8769
PORT_CDP = 9339


class CDPClient:
    def __init__(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self.ws = ws
        self._msg_id = 0

    async def send(self, method: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        self._msg_id += 1
        mid = self._msg_id
        await self.ws.send_json({"id": mid, "method": method, "params": params or {}})
        while True:
            msg = await self.ws.receive_json()
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"CDP error in {method}: {msg['error']}")
                return msg.get("result", {})

    async def eval_js(self, expression: str) -> Any:
        res = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        return res.get("result", {}).get("value")

    async def screenshot(self, filename: str) -> Path:
        res = await self.send("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(res["data"])
        path = OUT_DIR / filename
        path.write_bytes(data)
        print(f"  [saved] {filename} ({len(data) // 1024} KB)", flush=True)
        return path


def _start_api_server() -> uvicorn.Server:
    db_file = OUT_DIR / "demo_capture.sqlite"
    if db_file.exists():
        db_file.unlink()
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    db_module.init_db(str(db_file))
    gateway = build_demo_gateway(now)
    app = create_app(
        db_path=str(db_file),
        gateway=gateway,
        token_secret="demo-video-capture-secret",
        now_fn=lambda: now,
    )
    conn = db_module.connect(str(db_file))
    try:
        ensure_demo_merchant(conn, now)
    finally:
        conn.close()
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT_API, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(1.5)
    return server


async def _capture_all() -> None:
    server = _start_api_server()
    user_data = OUT_DIR / f"chrome_profile_{int(time.time())}"
    chrome_proc = subprocess.Popen(
        [
            CHROME_PATH,
            "--headless=new",
            f"--remote-debugging-port={PORT_CDP}",
            f"--user-data-dir={user_data}",
            "--window-size=1920,1080",
            "--force-device-scale-factor=1.5",
            "--hide-scrollbars",
            "--disable-gpu-vsync",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        await asyncio.sleep(2.0)
        async with aiohttp.ClientSession() as session:
            # Seed 2 background cases so Merchant Console table has rich multi-case history
            for oid, claim_txt, has_ph in [
                ("ORDER-002", "Delivery arrived 4 days late for our office coffee event.", False),
                ("ORDER-005", "Received the wrong color glaze carafe instead of matte charcoal.", True),
            ]:
                async with session.post(f"http://127.0.0.1:{PORT_API}/api/orders/{oid}/resolve-link?merchant_id={DEMO_MERCHANT_ID}") as r_tok:
                    td = await r_tok.json()
                    tok = td["token"]
                async with session.post(f"http://127.0.0.1:{PORT_API}/api/resolve/{tok}", json={"text": claim_txt, "has_photo": has_ph}) as r_ev:
                    evd = await r_ev.json()
                if evd.get("decision", {}).get("action") in ("AUTO_REFUND", "PARTIAL_REFUND") and not evd["decision"].get("needs_approval"):
                    await session.post(f"http://127.0.0.1:{PORT_API}/api/resolve/{tok}/accept", json={"case_id": evd["case_id"]})

            # Mint a resolve token for ORDER-001 via API for live browser walkthrough
            async with session.post(f"http://127.0.0.1:{PORT_API}/api/orders/ORDER-001/resolve-link?merchant_id={DEMO_MERCHANT_ID}") as resp:
                link_data = await resp.json()
                resolve_url = f"http://127.0.0.1:{PORT_API}/resolve/{link_data['token']}"

            targets = await (await session.get(f"http://127.0.0.1:{PORT_CDP}/json")).json()
            page_target = next(t for t in targets if t.get("type") == "page")
            ws_url = page_target["webSocketDebuggerUrl"]

            async with session.ws_connect(ws_url, max_msg_size=50 * 1024 * 1024) as ws:
                cdp = CDPClient(ws)
                await cdp.send("Page.enable")
                await cdp.send("Network.enable")
                await cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
                await cdp.send("Runtime.enable")
                await cdp.send(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": 1920, "height": 1080, "deviceScaleFactor": 1.5, "mobile": False},
                )

                # 1. Landing Page (Dark/3D Hero)
                print("1. Capturing Landing Page...", flush=True)
                await cdp.send("Page.navigate", {"url": f"http://127.0.0.1:{PORT_API}/"})
                await asyncio.sleep(2.2)
                await cdp.screenshot("01_landing_hero.png")

                # Scroll down Landing Page to show Architecture & Simulator
                await cdp.eval_js("window.scrollTo({top: 880, behavior: 'instant'})")
                await asyncio.sleep(0.8)
                await cdp.screenshot("02_landing_simulator.png")

                # 2. Customer Self-Service Portal (/resolve/:token) - Stage 1 AI Vision Preset
                print("2. Capturing Customer Portal Stage 1 (AI Vision Inspection)...", flush=True)
                await cdp.send("Page.navigate", {"url": resolve_url})
                await asyncio.sleep(1.5)
                # Click both the "Damaged item" scenario chip (fills complaint text) and "Cracked Mug (98% Match)" photo preset
                await cdp.eval_js(
                    """
                    (() => {
                      const btns = Array.from(document.querySelectorAll('button'));
                      const scenarioBtn = btns.find(b => b.textContent && b.textContent.includes('Damaged item'));
                      if (scenarioBtn) scenarioBtn.click();
                      const mugBtn = btns.find(b => b.textContent && b.textContent.includes('Cracked Mug'));
                      if (mugBtn) mugBtn.click();
                    })()
                    """
                )
                await asyncio.sleep(1.0)
                await cdp.eval_js("window.scrollTo({top: 520, behavior: 'instant'})")
                await asyncio.sleep(0.4)
                await cdp.screenshot("03_resolve_vision.png")

                # 3. Customer Portal Stage 2: Submit claim -> 3-Way Smart Settlement Negotiator
                print("3. Capturing Customer Portal Stage 2 (3-Way Smart Settlement)...", flush=True)
                await cdp.eval_js(
                    """
                    (() => {
                      const continueBtn = Array.from(document.querySelectorAll('button')).find(
                        b => b.textContent && (b.textContent.includes('Continue') || b.textContent.includes('Evaluate'))
                      );
                      if (continueBtn) continueBtn.click();
                    })()
                    """
                )
                await asyncio.sleep(2.2)
                await cdp.eval_js("window.scrollTo({top: 300, behavior: 'instant'})")
                await asyncio.sleep(0.5)
                await cdp.screenshot("04_resolve_negotiator.png")

                # Select 115% Bonus Store Credit option & capture
                await cdp.eval_js(
                    """
                    (() => {
                      const creditCard = Array.from(document.querySelectorAll('[role="radio"], button, div')).find(
                        el => el.textContent && el.textContent.includes('115% Instant Store Credit') && el.getAttribute('role') === 'radio'
                      );
                      if (creditCard) creditCard.click();
                    })()
                    """
                )
                await asyncio.sleep(0.6)
                await cdp.screenshot("05_resolve_store_credit.png")

                # 4. Accept offer -> Stage 3 Cryptographic Receipt
                print("4. Capturing Customer Portal Stage 3 (Settled Receipt)...", flush=True)
                await cdp.eval_js(
                    """
                    (() => {
                      const btns = Array.from(document.querySelectorAll('button'));
                      const acceptBtn = btns.find(b => b.className.includes('primary') && (b.textContent.includes('Accept') || b.textContent.includes('Claim')));
                      if (acceptBtn) acceptBtn.click();
                    })()
                    """
                )
                await asyncio.sleep(1.8)
                await cdp.eval_js("window.scrollTo({top: 120, behavior: 'instant'})")
                await asyncio.sleep(0.4)
                await cdp.screenshot("06_resolve_receipt.png")

                # 5. Merchant Command Center Overview
                print("5. Capturing Merchant Command Center...", flush=True)
                await cdp.send("Page.navigate", {"url": f"http://127.0.0.1:{PORT_API}/merchant"})
                await asyncio.sleep(2.2)
                await cdp.screenshot("07_merchant_overview.png")

                # Open Slide-Over Case Inspector Drawer on ORDER-001 (Damaged Cracked Mug case)
                await cdp.eval_js(
                    """
                    (() => {
                      const rows = Array.from(document.querySelectorAll('tbody tr'));
                      const mugRow = rows.find(r => r.textContent && r.textContent.includes('ORDER-001')) || rows[0];
                      if (mugRow) {
                        const btn = mugRow.querySelector('button');
                        if (btn) btn.click();
                        else mugRow.click();
                      }
                    })()
                    """
                )
                await asyncio.sleep(1.0)
                await cdp.eval_js(
                    """
                    (() => {
                      const drawerBody = document.querySelector('.drawer-body, .ops-drawer-body, aside .ops-panel-body, aside');
                      if (drawerBody) drawerBody.scrollTop = 280;
                    })()
                    """
                )
                await asyncio.sleep(0.4)
                await cdp.screenshot("08_merchant_case_drawer.png")

                # Close drawer
                await cdp.eval_js(
                    """
                    (() => {
                      const closeBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent && b.textContent.includes('Close'));
                      if (closeBtn) closeBtn.click();
                    })()
                    """
                )
                await asyncio.sleep(0.5)

                # Helper to scroll both window and any scrollable main container
                scroll_helper = """
                (topPx) => {
                  window.scrollTo({top: topPx, behavior: 'instant'});
                  document.querySelectorAll('main, .main-content, .workspace-main, .content-scroll').forEach(el => {
                    el.scrollTop = topPx;
                  });
                }
                """

                # 6. Guarded PayPal MCP Firewall Tab + Trigger Rogue Agent $999 Attack Preset
                print("6. Capturing Guarded PayPal MCP Firewall...", flush=True)
                await cdp.eval_js(
                    """
                    (() => {
                      const tab = Array.from(document.querySelectorAll('button')).find(
                        b => b.textContent && (b.textContent.includes('PayPal MCP Firewall') || b.textContent.includes('MCP Inspector'))
                      );
                      if (tab) tab.click();
                    })()
                    """
                )
                await asyncio.sleep(1.5)
                await cdp.eval_js(
                    """
                    (() => {
                      const presetBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent && b.textContent.includes('Rogue Agent'));
                      if (presetBtn) presetBtn.click();
                    })()
                    """
                )
                await asyncio.sleep(1.4)
                await cdp.eval_js(f"({scroll_helper})(240)")
                await asyncio.sleep(0.5)
                await cdp.screenshot("09_mcp_firewall_blocked.png")

                # 7. Policy & Guardrails Tab (What-If Simulator + Red-Team Arena)
                print("7. Capturing Policy & Guardrails (What-If Simulator & Red-Team Arena)...", flush=True)
                await cdp.eval_js(
                    """
                    (() => {
                      const tab = Array.from(document.querySelectorAll('button')).find(
                        b => b.textContent && b.textContent.includes('Policy & Guardrails')
                      );
                      if (tab) tab.click();
                    })()
                    """
                )
                await asyncio.sleep(1.2)
                # Click High-Automation Growth preset in What-If Simulator
                await cdp.eval_js(
                    """
                    (() => {
                      const growthBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent && b.textContent.includes('High-Automation Growth'));
                      if (growthBtn) growthBtn.click();
                    })()
                    """
                )
                await asyncio.sleep(0.8)
                await cdp.eval_js(f"({scroll_helper})(640)")
                await asyncio.sleep(0.5)
                await cdp.screenshot("10_what_if_simulator.png")

                # Run Red-Team Batch & scroll to Red-Team Arena
                await cdp.eval_js(
                    """
                    (() => {
                      const batchBtn = Array.from(document.querySelectorAll('button')).find(
                        b => b.textContent && (b.textContent.includes('Run All 8 Attacks') || b.textContent.includes('Run Full'))
                      );
                      if (batchBtn) batchBtn.click();
                    })()
                    """
                )
                await asyncio.sleep(2.8)
                await cdp.eval_js(f"({scroll_helper})(1750)")
                await asyncio.sleep(0.5)
                await cdp.screenshot("11_red_team_arena.png")

                # 8. PayPal Disputes Tab + Draft Defense Packet
                print("8. Capturing PayPal Disputes Auto-Drafter...", flush=True)
                await cdp.eval_js(f"({scroll_helper})(0)")
                await cdp.eval_js(
                    """
                    (() => {
                      const tab = Array.from(document.querySelectorAll('button')).find(
                        b => b.textContent && b.textContent.includes('PayPal Disputes')
                      );
                      if (tab) tab.click();
                    })()
                    """
                )
                await asyncio.sleep(1.2)
                await cdp.eval_js(
                    """
                    (() => {
                      const draftBtn = Array.from(document.querySelectorAll('button')).find(
                        b => b.textContent && (b.textContent.includes('Draft Defense') || b.textContent.includes('Evidence'))
                      );
                      if (draftBtn) draftBtn.click();
                    })()
                    """
                )
                await asyncio.sleep(1.0)
                await cdp.eval_js(f"({scroll_helper})(220)")
                await asyncio.sleep(0.5)
                await cdp.screenshot("12_disputes_autodrafter.png")

    finally:
        chrome_proc.terminate()
        server.should_exit = True


if __name__ == "__main__":
    asyncio.run(_capture_all())

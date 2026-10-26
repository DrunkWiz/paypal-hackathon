"""Render the Settle Cinema-Grade Product Launch Film (.mp4 and .webm, 1920x1080 @ 30fps).

Built around 12 real Chromium high-DPI (2880x1620, 1.5x Retina) captures of the live Settle application:
- True 3D perspective browser window projection (homography matrix via Image.Transform.PERSPECTIVE)
- Smooth cubic-bezier Virtual Cinema Camera focal zooms (1.0x -> 1.72x) & pans at native Retina sharpness
- High-precision animated vector cursor with cubic-bezier paths & click shockwave ripples
- Real frosted-glass (Gaussian-blurred) telemetry HUD callout cards & word-synced broadcast captions
- Neural voiceover narration (edge-tts) + stereo ambient synth score + frame-accurate UI click SFX
"""
from __future__ import annotations

import asyncio
import math
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import edge_tts
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

SCRATCH_CAPTURES_DIR = Path(
    r"C:\Users\Nathan\.gemini\antigravity\brain\07963db4-9d96-4b31-95e3-da5909c01032\scratch\ui_captures"
)
LOCAL_CAPTURES_DIR = DOCS_DIR / "ui_captures"

WIDTH = 1920
HEIGHT = 1080
FPS = 30
SAMPLE_RATE = 44100
VOICE = "en-US-AndrewMultilingualNeural"

# Source screenshot dimensions (1.5x Retina 1080p)
SRC_W = 2880
SRC_H = 1620
CHROME_BAR_H = 68
BROWSER_W = SRC_W
BROWSER_H = SRC_H + CHROME_BAR_H

# ---------------------------------------------------------------------------
# Typography Helpers
# ---------------------------------------------------------------------------
FONT_DIR = Path("C:/Windows/Fonts")


def _load_font(candidates: List[str], size: int) -> ImageFont.FreeTypeFont:
    for name in candidates:
        p = FONT_DIR / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def font_sans_bold(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf", "bahnschrift.ttf"], size)


def font_sans_semibold(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"], size)


def font_sans_reg(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(["segoeui.ttf", "arial.ttf", "calibri.ttf"], size)


def font_mono_bold(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(["cascadiamono.ttf", "consolab.ttf", "courbd.ttf", "arialbd.ttf"], size)


def font_mono_reg(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(["cascadiamono.ttf", "consola.ttf", "cour.ttf", "arial.ttf"], size)


# ---------------------------------------------------------------------------
# Easing & Math Utilities
# ---------------------------------------------------------------------------
def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def sub_p(p: float, start: float, end: float) -> float:
    if end <= start:
        return 1.0 if p >= end else 0.0
    return clamp01((p - start) / (end - start))


def ease_out_cubic(x: float) -> float:
    x = clamp01(x)
    return 1.0 - pow(1.0 - x, 3)


def ease_out_quint(x: float) -> float:
    x = clamp01(x)
    return 1.0 - pow(1.0 - x, 5)


def ease_in_out_cubic(x: float) -> float:
    x = clamp01(x)
    return 4.0 * x * x * x if x < 0.5 else 1.0 - pow(-2.0 * x + 2.0, 3) / 2.0


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * clamp01(t)


def lerp_pt(p1: Tuple[float, float], p2: Tuple[float, float], t: float) -> Tuple[float, float]:
    t = clamp01(t)
    return (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)


def bezier_pt(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    t: float,
) -> Tuple[float, float]:
    """Quadratic bezier curve for natural curved mouse cursor trajectories."""
    t = clamp01(t)
    u = 1.0 - t
    x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
    y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
    return (x, y)


def _find_perspective_coeffs(
    dst_pts: List[Tuple[float, float]],
    src_pts: List[Tuple[float, float]],
) -> List[float]:
    """Compute the 8 projective homography coefficients for PIL Image.Transform.PERSPECTIVE.

    Maps dst_pts (on output canvas) -> src_pts (on source image).
    """
    matrix = []
    for (dx, dy), (sx, sy) in zip(dst_pts, src_pts):
        matrix.append([dx, dy, 1.0, 0.0, 0.0, 0.0, -sx * dx, -sx * dy])
        matrix.append([0.0, 0.0, 0.0, dx, dy, 1.0, -sy * dx, -sy * dy])
    A = np.array(matrix, dtype=np.float64)
    B = np.array([coord for pt in src_pts for coord in pt], dtype=np.float64)
    res = np.linalg.solve(A, B)
    return res.tolist()


# ---------------------------------------------------------------------------
# Scene Script & Metadata (7 Rich Product Chapters)
# ---------------------------------------------------------------------------
SCENES: List[Dict[str, Any]] = [
    {
        "id": "01",
        "chapter": "01 / 07 · THE DETERMINISTIC FIREWALL",
        "url": "https://settle.pay",
        "narration": (
            "Autonomous AI agents are transforming e-commerce, yet no merchant can trust a probabilistic LLM "
            "with direct write access to their PayPal balance. Meet Settle: where AI classifies the claim, "
            "and deterministic code governs every single cent."
        ),
        "clicks": [0.58],
    },
    {
        "id": "02",
        "chapter": "02 / 07 · MULTIMODAL AI VISION PROOF",
        "url": "https://settle.pay/resolve/ORDER-001",
        "narration": (
            "When a buyer opens a magic resolution link, Settle verifies the live PayPal capture and runs "
            "multimodal computer vision on damaged-item photos—pinpointing structural fractures and packing slip OCR "
            "with ninety-eight percent authenticity."
        ),
        "clicks": [0.20, 0.88],
    },
    {
        "id": "03",
        "chapter": "03 / 07 · 3-WAY SMART SETTLEMENT NEGOTIATOR",
        "url": "https://settle.pay/resolve/ORDER-001?stage=offer",
        "narration": (
            "Instead of defaulting to a hundred-percent cash loss, Settle's AI Margin-Retention Negotiator "
            "presents a three-way instant settlement: keep the item for a sixty-five percent instant PayPal refund, "
            "claim a hundred-fifteen percent bonus store credit voucher, or take a standard refund."
        ),
        "clicks": [0.40, 0.72],
    },
    {
        "id": "04",
        "chapter": "04 / 07 · MERCHANT COMMAND & PAYER TRUST GRAPH",
        "url": "https://settle.pay/merchant/overview",
        "narration": (
            "Inside the Merchant Command Center, operators track net cash retained alongside real-time PayPal "
            "Payer Trust and Velocity scores—catching serial refund abuse while inspecting caliper-verified "
            "wrong-SKU evidence in a single click."
        ),
        "clicks": [0.44],
    },
    {
        "id": "05",
        "chapter": "05 / 07 · GUARDED PAYPAL MCP SERVER FIREWALL",
        "url": "https://settle.pay/merchant/mcp-firewall",
        "narration": (
            "With Settle's Model Context Protocol server, external agents in Claude, Cursor, or LangGraph "
            "invoke PayPal tools safely. When a rogue agent attempts a nine-hundred-ninety-nine dollar refund override "
            "on a twenty-eight dollar mug, the MCP firewall intercepts the call and clamps execution to exact policy limits."
        ),
        "clicks": [0.26],
    },
    {
        "id": "06",
        "chapter": "06 / 07 · COUNTERFACTUAL REPLAY & RED-TEAM ARENA",
        "url": "https://settle.pay/merchant/policy-guardrails",
        "narration": (
            "Before changing a single guardrail, merchants replay historical claims in the Counterfactual "
            "What-If Simulator to forecast automation gains—and stress-test their rules against adversarial "
            "prompt injections with zero dollar leakage."
        ),
        "clicks": [0.54],
    },
    {
        "id": "07",
        "chapter": "07 / 07 · 1-CLICK DISPUTE EVIDENCE AUTO-DRAFTER",
        "url": "https://settle.pay/merchant/disputes",
        "narration": (
            "And if a buyer files a PayPal chargeback after already settling, Settle auto-drafts a cryptographic "
            "provide-evidence defense packet citing the exact PayPal capture and refund IDs. Settle: autonomous speed "
            "for buyers, mathematical certainty for PayPal merchants."
        ),
        "clicks": [0.24],
    },
]


# ---------------------------------------------------------------------------
# Load & Wrap Real 2880x1620 Chromium Screenshots in macOS Studio Frame
# ---------------------------------------------------------------------------
CAPTURE_FILES: Dict[str, Tuple[str, str]] = {
    "01_landing_hero": ("01_landing_hero.png", "https://settle.pay · Autonomous PayPal Refund Firewall"),
    "02_landing_simulator": ("02_landing_simulator.png", "https://settle.pay/#pipeline · 4-Stage Deterministic Engine"),
    "03_resolve_vision": ("03_resolve_vision.png", "https://settle.pay/resolve/ORDER-001 · Multimodal Vision Intake"),
    "04_resolve_negotiator": ("04_resolve_negotiator.png", "https://settle.pay/resolve/ORDER-001 · AI 3-Way Smart Settlement"),
    "05_resolve_store_credit": ("05_resolve_store_credit.png", "https://settle.pay/resolve/ORDER-001 · 115% Instant Store Credit"),
    "06_resolve_receipt": ("06_resolve_receipt.png", "https://settle.pay/resolve/ORDER-001 · Verified PayPal Settlement Receipt"),
    "07_merchant_overview": ("07_merchant_overview.png", "https://settle.pay/merchant · Kopi & Clay Command Center"),
    "08_merchant_case_drawer": ("08_merchant_case_drawer.png", "https://settle.pay/merchant/cases/c_b024c7 · Payer Trust & CV Inspector"),
    "09_mcp_firewall_blocked": ("09_mcp_firewall_blocked.png", "https://settle.pay/merchant/mcp · settle-paypal-guarded-mcp (JSON-RPC 2.0)"),
    "10_what_if_simulator": ("10_what_if_simulator.png", "https://settle.pay/merchant/policy · Counterfactual What-If Replay"),
    "11_red_team_arena": ("11_red_team_arena.png", "https://settle.pay/merchant/policy · Red-Team Prompt Injection Arena"),
    "12_disputes_autodrafter": ("12_disputes_autodrafter.png", "https://settle.pay/merchant/disputes · PayPal provide-evidence Auto-Drafter"),
}


def _load_and_frame_captures(fonts: Dict[str, ImageFont.FreeTypeFont]) -> Dict[str, Image.Image]:
    """Load all 12 2880x1620 screenshots and wrap each in a sleek dark macOS/Arc browser frame."""
    LOCAL_CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    framed: Dict[str, Image.Image] = {}

    for key, (filename, url_label) in CAPTURE_FILES.items():
        src_path = SCRATCH_CAPTURES_DIR / filename
        dst_path = LOCAL_CAPTURES_DIR / filename
        if src_path.exists():
            shutil.copy2(src_path, dst_path)
        load_path = src_path if src_path.exists() else dst_path
        if not load_path.exists():
            raise FileNotFoundError(f"Missing real UI capture: {load_path}")

        raw_img = Image.open(load_path).convert("RGB")
        if raw_img.size != (SRC_W, SRC_H):
            raw_img = raw_img.resize((SRC_W, SRC_H), Image.Resampling.LANCZOS)

        canvas = Image.new("RGB", (BROWSER_W, BROWSER_H), (13, 19, 33))
        draw = ImageDraw.Draw(canvas)

        # Top macOS / Arc studio chrome bar (height = 68px)
        draw.rectangle((0, 0, BROWSER_W, CHROME_BAR_H), fill=(15, 23, 42))
        draw.line([(0, 1), (BROWSER_W, 1)], fill=(56, 78, 112), width=2)
        draw.line([(0, CHROME_BAR_H - 1), (BROWSER_W, CHROME_BAR_H - 1)], fill=(30, 41, 59), width=2)

        # macOS traffic lights
        lights = [((42, 34), (255, 95, 86)), ((76, 34), (255, 189, 46)), ((110, 34), (39, 201, 63))]
        for (lx, ly), col in lights:
            draw.ellipse((lx - 10, ly - 10, lx + 10, ly + 10), fill=col)

        # Sleek centered URL bar
        ub_w = 1120
        ub_h = 42
        ub_x = (BROWSER_W - ub_w) // 2
        ub_y = (CHROME_BAR_H - ub_h) // 2
        draw.rounded_rectangle(
            (ub_x, ub_y, ub_x + ub_w, ub_y + ub_h),
            radius=11,
            fill=(9, 14, 26),
            outline=(45, 62, 92),
            width=2,
        )
        # Green SSL Verified dot + URL text
        draw.ellipse((ub_x + 18, ub_y + 14, ub_x + 32, ub_y + 28), fill=(16, 185, 129))
        bbox = draw.textbbox((0, 0), url_label, font=fonts["mono_b_18"])
        tw = bbox[2] - bbox[0]
        draw.text((ub_x + (ub_w - tw) // 2 + 8, ub_y + 9), url_label, font=fonts["mono_b_18"], fill=(226, 232, 240))

        # Right status pill inside browser chrome
        pill_txt = "PAYPAL GUARDED SESSION · TLS 1.3"
        draw.rounded_rectangle(
            (BROWSER_W - 390, ub_y + 4, BROWSER_W - 34, ub_y + ub_h - 4),
            radius=9,
            fill=(12, 34, 64),
            outline=(0, 112, 186),
            width=1,
        )
        draw.text((BROWSER_W - 372, ub_y + 10), pill_txt, font=fonts["mono_b_15"], fill=(125, 211, 252))

        # Paste crisp 2880x1620 Chromium UI capture below chrome bar
        canvas.paste(raw_img, (0, CHROME_BAR_H))
        framed[key] = canvas

    return framed


# ---------------------------------------------------------------------------
# Virtual Cinema Camera, 3D Perspective Projection & Vector Cursor Engine
# ---------------------------------------------------------------------------
def _draw_cursor_and_ripples_cropped(
    cropped: Image.Image,
    ix1: int,
    iy1: int,
    cursor_xy: Optional[Tuple[float, float]],
    click_ripples: Optional[List[Tuple[Tuple[float, float], float]]] = None,
    pressing: bool = False,
) -> None:
    """Draw high-precision macOS/Linear vector pointer and expanding click shockwaves directly on the cropped view."""
    if cursor_xy is None and not click_ripples:
        return

    # 1. Expanding concentric click shockwave ripples (local patch composite)
    if click_ripples:
        for (rx, ry), rp in click_ripples:
            if 0.0 < rp < 1.0:
                cx_local = rx - ix1
                cy_local = (ry + CHROME_BAR_H) - iy1
                r_outer = int(20 + ease_out_cubic(rp) * 145)
                r_inner = int(10 + ease_out_cubic(rp) * 85)
                pad = r_outer + 12
                px1 = max(0, int(cx_local - pad))
                py1 = max(0, int(cy_local - pad))
                px2 = min(cropped.width, int(cx_local + pad))
                py2 = min(cropped.height, int(cy_local + pad))
                if px2 > px1 and py2 > py1:
                    patch = cropped.crop((px1, py1, px2, py2)).convert("RGBA")
                    over = Image.new("RGBA", patch.size, (0, 0, 0, 0))
                    odraw = ImageDraw.Draw(over)
                    lx = cx_local - px1
                    ly = cy_local - py1
                    alpha_outer = int((1.0 - rp) * 230)
                    alpha_inner = int((1.0 - rp) * 185)
                    odraw.ellipse(
                        (lx - r_outer, ly - r_outer, lx + r_outer, ly + r_outer),
                        outline=(0, 168, 234, alpha_outer),
                        width=6,
                    )
                    odraw.ellipse(
                        (lx - r_inner, ly - r_inner, lx + r_inner, ly + r_inner),
                        fill=(56, 189, 248, int((1.0 - rp) * 55)),
                        outline=(255, 255, 255, alpha_inner),
                        width=4,
                    )
                    cropped.paste(Image.alpha_composite(patch, over).convert("RGB"), (px1, py1))

    # 2. Crisp Vector Arrow Cursor (local patch composite)
    if cursor_xy is not None:
        cx_local = cursor_xy[0] - ix1
        cy_local = (cursor_xy[1] + CHROME_BAR_H) - iy1
        scale = 1.42 if not pressing else 1.16

        px1 = max(0, int(cx_local - 16))
        py1 = max(0, int(cy_local - 16))
        px2 = min(cropped.width, int(cx_local + 90))
        py2 = min(cropped.height, int(cy_local + 96))
        if px2 > px1 and py2 > py1:
            patch = cropped.crop((px1, py1, px2, py2)).convert("RGBA")
            over = Image.new("RGBA", patch.size, (0, 0, 0, 0))
            odraw = ImageDraw.Draw(over)
            lx = cx_local - px1
            ly = cy_local - py1
            raw_poly = [
                (0, 0),
                (0, 38),
                (10, 29),
                (18, 46),
                (25, 42),
                (17, 25),
                (30, 25),
            ]
            shadow_pts = [(lx + px * scale + 5, ly + py * scale + 7) for px, py in raw_poly]
            cursor_pts = [(lx + px * scale, ly + py * scale) for px, py in raw_poly]
            odraw.polygon(shadow_pts, fill=(0, 0, 0, 155))
            odraw.polygon(cursor_pts, fill=(15, 23, 42, 255), outline=(255, 255, 255, 255), width=4)
            cropped.paste(Image.alpha_composite(patch, over).convert("RGB"), (px1, py1))


def _render_camera_view(
    stage_bg: Image.Image,
    browser_img: Image.Image,
    cx: float,
    cy: float,
    zoom: float,
    tilt_x_deg: float = 0.0,
    tilt_y_deg: float = 0.0,
    spotlight_box: Optional[Tuple[int, int, int, int]] = None,
    spotlight_strength: float = 0.0,
    cursor_xy: Optional[Tuple[float, float]] = None,
    click_ripples: Optional[List[Tuple[Tuple[float, float], float]]] = None,
    pressing: bool = False,
) -> Image.Image:
    """Project the 2880x1692 high-DPI browser onto the 1920x1080 studio stage with camera zoom & 3D tilt."""
    # 1. Compute camera crop window in 2880x1692 space
    target_cy = cy + CHROME_BAR_H
    crop_w = BROWSER_W / max(1.0, zoom)
    crop_h = BROWSER_H / max(1.0, zoom)

    x1 = cx - crop_w / 2.0
    y1 = target_cy - crop_h / 2.0
    x1 = max(0.0, min(float(BROWSER_W) - crop_w, x1))
    y1 = max(0.0, min(float(BROWSER_H) - crop_h, y1))
    x2 = x1 + crop_w
    y2 = y1 + crop_h

    ix1, iy1, ix2, iy2 = int(x1), int(y1), int(x2), int(y2)
    cropped = browser_img.crop((ix1, iy1, ix2, iy2))

    # Draw cursor & ripples directly on the cropped region (zero full-frame copy overhead!)
    _draw_cursor_and_ripples_cropped(cropped, ix1, iy1, cursor_xy, click_ripples, pressing)

    # 2. Determine destination quad on the 1920x1080 studio canvas
    expand_t = clamp01((zoom - 1.0) / 0.45)
    dst_w = lerp(1660.0, 1836.0, expand_t)
    dst_h = lerp(975.0, 1032.0, expand_t)
    dst_cx = WIDTH / 2.0
    dst_cy = lerp(522.0, 528.0, expand_t)

    half_w = dst_w / 2.0
    half_h = dst_h / 2.0

    tl = [dst_cx - half_w, dst_cy - half_h]
    tr = [dst_cx + half_w, dst_cy - half_h]
    br = [dst_cx + half_w, dst_cy + half_h]
    bl = [dst_cx - half_w, dst_cy + half_h]

    yaw = tilt_y_deg * 3.2
    pitch = tilt_x_deg * 2.6

    tl[1] += yaw - pitch * 0.6
    bl[1] -= yaw + pitch * 0.6
    tr[1] -= yaw + pitch * 0.6
    br[1] += yaw - pitch * 0.6

    tl[0] += abs(yaw) * 0.9 + pitch * 1.3
    tr[0] -= abs(yaw) * 0.9 + pitch * 1.3
    bl[0] += abs(yaw) * 0.9 - pitch * 1.3
    br[0] -= abs(yaw) * 0.9 - pitch * 1.3

    dst_pts = [(tl[0], tl[1]), (tr[0], tr[1]), (br[0], br[1]), (bl[0], bl[1])]
    cw, ch = float(cropped.width), float(cropped.height)
    src_pts = [(0.0, 0.0), (cw, 0.0), (cw, ch), (0.0, ch)]

    coeffs = _find_perspective_coeffs(dst_pts, src_pts)
    warped_rgb = cropped.transform(
        (WIDTH, HEIGHT),
        Image.Transform.PERSPECTIVE,
        coeffs,
        resample=Image.Resampling.BILINEAR,
    )

    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.polygon(dst_pts, fill=255)

    out = stage_bg.copy()
    s_draw = ImageDraw.Draw(out)
    shadow_pts = [(px + 12, py + 24) for px, py in dst_pts]
    s_draw.polygon(shadow_pts, fill=(2, 5, 12))

    out.paste(warped_rgb, (0, 0), mask)

    b_draw = ImageDraw.Draw(out)
    b_draw.polygon(dst_pts, outline=(56, 98, 152), width=3)
    b_draw.line([dst_pts[0], dst_pts[1]], fill=(125, 211, 252), width=2)

    return out


# ---------------------------------------------------------------------------
# Frosted Glass HUD Callout & Chrome Overlay Primitives
# ---------------------------------------------------------------------------
def _draw_frosted_callout(
    frame: Image.Image,
    box: Tuple[int, int, int, int],
    badge_text: str,
    headline: str,
    subtext: str,
    accent_rgb: Tuple[int, int, int],
    fonts: Dict[str, ImageFont.FreeTypeFont],
    enter_p: float = 1.0,
) -> None:
    """Render a genuine frosted-glass (Gaussian-blurred background) floating callout card."""
    if enter_p <= 0.02:
        return
    ep = ease_out_cubic(enter_p)
    x1, y1, x2, y2 = box
    slide_y = int((1.0 - ep) * 28)
    y1 += slide_y
    y2 += slide_y
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(WIDTH, x2)
    y2 = min(HEIGHT, y2)
    if x2 <= x1 + 20 or y2 <= y1 + 20:
        return

    # Blur underlying region for authentic glassmorphism
    region = frame.crop((x1, y1, x2, y2)).filter(ImageFilter.GaussianBlur(radius=12))
    dark_tint = Image.new("RGB", (x2 - x1, y2 - y1), (8, 15, 29))
    frosted = Image.blend(region, dark_tint, alpha=0.82)

    mask = Image.new("L", (x2 - x1, y2 - y1), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rounded_rectangle((0, 0, x2 - x1 - 1, y2 - y1 - 1), radius=18, fill=255)
    frame.paste(frosted, (x1, y1), mask)

    draw = ImageDraw.Draw(frame)
    draw.rounded_rectangle((x1, y1, x2, y2), radius=18, outline=accent_rgb, width=2)
    # Left accent bar
    draw.rounded_rectangle((x1 + 14, y1 + 16, x1 + 20, y2 - 16), radius=3, fill=accent_rgb)

    # Badge pill
    draw.text((x1 + 34, y1 + 14), badge_text, font=fonts["mono_b_14"], fill=accent_rgb)
    draw.text((x1 + 34, y1 + 36), headline, font=fonts["sans_b_22"], fill=(248, 250, 252))
    draw.text((x1 + 34, y1 + 66), subtext, font=fonts["sans_r_17"], fill=(186, 202, 224))


def _draw_top_minimal_bar(
    frame: Image.Image,
    scene_idx: int,
    scene: Dict[str, Any],
    fonts: Dict[str, ImageFont.FreeTypeFont],
) -> None:
    """Draw a sleek, unobtrusive top-left chapter badge and top-right progress indicator."""
    draw = ImageDraw.Draw(frame)

    # Top-left Settle brand + chapter pill
    draw.rounded_rectangle(
        (44, 14, 620, 52),
        radius=12,
        fill=(9, 15, 28),
        outline=(36, 58, 92),
        width=2,
    )
    draw.rounded_rectangle((54, 20, 80, 46), radius=7, fill=(0, 112, 186))
    draw.text((61, 20), "S", font=fonts["sans_b_18"], fill=(255, 255, 255))
    draw.text((92, 22), "SETTLE 1.2", font=fonts["sans_b_16"], fill=(248, 250, 252))
    draw.text((196, 23), "·", font=fonts["sans_b_16"], fill=(100, 116, 139))
    draw.text((212, 23), scene["chapter"], font=fonts["mono_b_15"], fill=(125, 211, 252))

    # Top-right progress segments
    px = WIDTH - 360
    draw.rounded_rectangle(
        (px - 16, 14, WIDTH - 44, 52),
        radius=12,
        fill=(9, 15, 28),
        outline=(36, 58, 92),
        width=2,
    )
    for idx in range(len(SCENES)):
        pw = 48 if idx == scene_idx else 30
        col = (56, 189, 248) if idx == scene_idx else ((0, 112, 186) if idx < scene_idx else (30, 45, 72))
        draw.rounded_rectangle((px, 27, px + pw, 39), radius=6, fill=col)
        px += pw + 8


def _draw_broadcast_caption_bar(
    frame: Image.Image,
    narration: str,
    vo_progress: float,
    fonts: Dict[str, ImageFont.FreeTypeFont],
) -> None:
    """Draw a compact, frosted broadcast subtitle pill at the bottom edge."""
    words = narration.split()
    if not words:
        return
    active_word_idx = min(len(words) - 1, int(vo_progress * len(words)))

    # Group words into chunks of ~11 words so caption is a clean single line
    chunk_size = 11
    chunk_idx = active_word_idx // chunk_size
    chunk_words = words[chunk_idx * chunk_size : (chunk_idx + 1) * chunk_size]
    local_active = active_word_idx - chunk_idx * chunk_size

    draw = ImageDraw.Draw(frame)
    fnt = fonts["sans_s_21"]
    space_w = draw.textbbox((0, 0), " ", font=fnt)[2]
    word_widths = [draw.textbbox((0, 0), w, font=fnt)[2] for w in chunk_words]
    total_w = sum(word_widths) + space_w * max(0, len(chunk_words) - 1)

    pad_x = 28
    box_w = total_w + pad_x * 2
    box_x1 = max(60, (WIDTH - box_w) // 2)
    box_x2 = min(WIDTH - 60, box_x1 + box_w)
    box_y1 = HEIGHT - 66
    box_y2 = HEIGHT - 16

    draw.rounded_rectangle(
        (box_x1, box_y1, box_x2, box_y2),
        radius=25,
        fill=(7, 12, 23),
        outline=(42, 68, 108),
        width=2,
    )

    cx = (WIDTH - total_w) // 2
    cy = box_y1 + 11
    for i, (w, ww) in enumerate(zip(chunk_words, word_widths)):
        if i < local_active:
            color = (226, 232, 240)
        elif i == local_active:
            color = (56, 189, 248)
        else:
            color = (148, 163, 184)
        draw.text((cx, cy), w, font=fnt, fill=color)
        cx += ww + space_w


# ---------------------------------------------------------------------------
# 7 Cinema Scene Renderers (Real High-DPI Captures + 3D Camera + Cursor)
# ---------------------------------------------------------------------------
def _render_scene_01(
    stage_bg: Image.Image,
    p: float,
    captures: Dict[str, Image.Image],
    fonts: Dict[str, ImageFont.FreeTypeFont],
) -> Image.Image:
    """Scene 1: Kinetic Title Reveal -> 3D WebGL Landing Hero -> 4-Stage Deterministic Pipeline."""
    # Phase A (p = 0.0 -> 0.18): High-impact Stripe/Linear Kinetic Opener over blurred 3D hero
    if p < 0.18:
        kp = sub_p(p, 0.0, 0.18)
        if "_cache_s1_bg" not in captures:
            hero_preview = _render_camera_view(
                stage_bg,
                captures["01_landing_hero"],
                cx=1440,
                cy=810,
                zoom=1.02,
                tilt_x_deg=4.0,
                tilt_y_deg=-8.0,
            )
            blurred = hero_preview.filter(ImageFilter.GaussianBlur(radius=14))
            captures["_cache_s1_bg"] = ImageEnhance.Brightness(blurred).enhance(0.42)
        dark = captures["_cache_s1_bg"].copy()
        draw = ImageDraw.Draw(dark)

        enter = ease_out_cubic(sub_p(kp, 0.0, 0.55))
        y_off = int((1.0 - enter) * 35)

        # Pill badge
        pill_txt = "SETTLE 1.2 · DETERMINISTIC PAYPAL COMMERCE AGENT"
        tw_p = draw.textbbox((0, 0), pill_txt, font=fonts["mono_b_18"])[2]
        px1 = (WIDTH - tw_p) // 2 - 24
        draw.rounded_rectangle(
            (px1, 310 + y_off, px1 + tw_p + 48, 354 + y_off),
            radius=22,
            fill=(10, 32, 64),
            outline=(56, 189, 248),
            width=2,
        )
        draw.text((px1 + 24, 321 + y_off), pill_txt, font=fonts["mono_b_18"], fill=(125, 211, 252))

        # Giant headline
        h1 = "LLMs Hallucinate. Refunds Can't."
        tw1 = draw.textbbox((0, 0), h1, font=fonts["sans_b_64"])[2]
        draw.text(((WIDTH - tw1) // 2, 388 + y_off), h1, font=fonts["sans_b_64"], fill=(255, 255, 255))

        h2 = "AI classifies the claim. Deterministic Python code governs every single cent."
        tw2 = draw.textbbox((0, 0), h2, font=fonts["sans_r_26"])[2]
        draw.text(((WIDTH - tw2) // 2, 482 + y_off), h2, font=fonts["sans_r_26"], fill=(186, 202, 224))
        return dark

    # Phase B (p = 0.18 -> 0.62): 3D Camera Reveal & Zoom on 01_landing_hero.png
    if p < 0.62:
        bp = sub_p(p, 0.18, 0.62)
        t_move = ease_in_out_cubic(bp)
        cx = lerp(1440.0, 1720.0, t_move)
        cy = lerp(760.0, 700.0, t_move)
        zoom = lerp(1.0, 1.38, t_move)
        tilt_y = lerp(-6.5, -1.5, t_move)
        tilt_x = lerp(2.5, 0.5, t_move)

        # Animated cursor moving toward the 3D Interactive Policy Trace card
        cur_t = ease_in_out_cubic(sub_p(bp, 0.25, 0.88))
        cur_xy = bezier_pt((920.0, 960.0), (1380.0, 620.0), (1860.0, 720.0), cur_t)
        ripples = [((1860.0, 720.0), sub_p(bp, 0.88, 1.0))] if bp >= 0.88 else []

        frame = _render_camera_view(
            stage_bg,
            captures["01_landing_hero"],
            cx=cx,
            cy=cy,
            zoom=zoom,
            tilt_x_deg=tilt_x,
            tilt_y_deg=tilt_y,
            cursor_xy=cur_xy,
            click_ripples=ripples,
            pressing=(0.86 <= bp <= 0.92),
        )
        _draw_frosted_callout(
            frame,
            (64, 836, 740, 940),
            "ARCHITECTURAL SEPARATION OF POWERS",
            "Untrusted LLM Intake -> Pure Code Verdict",
            "No AI model ever holds direct write access to PayPal Captures.",
            (56, 189, 248),
            fonts,
            enter_p=sub_p(bp, 0.12, 0.40),
        )
        return frame

    # Phase C (p = 0.62 -> 1.00): 4-Stage Deterministic Pipeline & Live Simulator (02_landing_simulator.png)
    cp = sub_p(p, 0.62, 1.0)
    t_move = ease_in_out_cubic(cp)
    cx = lerp(1440.0, 1440.0, t_move)
    cy = lerp(520.0, 960.0, t_move)
    zoom = lerp(1.22, 1.46, math.sin(cp * math.pi))
    tilt_y = lerp(-1.5, 2.0, t_move)

    cur_xy = bezier_pt((1860.0, 480.0), (1520.0, 820.0), (1180.0, 1080.0), ease_in_out_cubic(cp))

    frame = _render_camera_view(
        stage_bg,
        captures["02_landing_simulator"],
        cx=cx,
        cy=cy,
        zoom=zoom,
        tilt_x_deg=0.8,
        tilt_y_deg=tilt_y,
        spotlight_box=(150, 210, 2730, 740) if cp < 0.55 else (150, 750, 2730, 1520),
        spotlight_strength=0.65,
        cursor_xy=cur_xy,
    )
    _draw_frosted_callout(
        frame,
        (64, 836, 790, 940),
        "4-STAGE DETERMINISTIC PIPELINE",
        "01 Vision -> 02 Rule Match -> 03 Cap Guard -> 04 PayPal v2",
        "100% integer minor-unit math with cryptographic SHA-256 audit trace.",
        (16, 185, 129),
        fonts,
        enter_p=sub_p(cp, 0.05, 0.30),
    )
    return frame


def _render_scene_02(
    stage_bg: Image.Image,
    p: float,
    captures: Dict[str, Image.Image],
    fonts: Dict[str, ImageFont.FreeTypeFont],
) -> Image.Image:
    """Scene 2: Customer Self-Service Portal & Multimodal AI Vision Bounding Boxes (03_resolve_vision.png)."""
    # Cursor clicks Preset 1 ("Cracked Mug (98% Match)") at p=0.20, inspects CV boxes, then glides to Continue
    if p < 0.35:
        cur_t = ease_in_out_cubic(sub_p(p, 0.02, 0.20))
        cur_xy = bezier_pt((1440.0, 480.0), (1260.0, 680.0), (1120.0, 868.0), cur_t)
    elif p < 0.72:
        cur_t = ease_in_out_cubic(sub_p(p, 0.35, 0.70))
        cur_xy = bezier_pt((1120.0, 868.0), (1260.0, 1080.0), (1380.0, 1210.0), cur_t)
    else:
        cur_t = ease_in_out_cubic(sub_p(p, 0.72, 0.88))
        cur_xy = bezier_pt((1380.0, 1210.0), (1300.0, 1380.0), (1220.0, 1525.0), cur_t)

    ripples: List[Tuple[Tuple[float, float], float]] = []
    if 0.20 <= p <= 0.38:
        ripples.append(((1120.0, 868.0), sub_p(p, 0.20, 0.38)))
    if 0.88 <= p <= 1.0:
        ripples.append(((1220.0, 1525.0), sub_p(p, 0.88, 1.0)))

    pressing = (0.18 <= p <= 0.23) or (0.86 <= p <= 0.91)

    # Camera keeps the 2880x1620 Buyer Portal column (centered at x=1440) dead-center while zooming into Multimodal Vision
    if p < 0.25:
        t_cam = ease_in_out_cubic(sub_p(p, 0.0, 0.25))
        cx = lerp(1440.0, 1440.0, t_cam)
        cy = lerp(740.0, 960.0, t_cam)
        zoom = lerp(1.06, 1.30, t_cam)
        tilt_y = lerp(4.0, 1.2, t_cam)
    elif p < 0.78:
        t_cam = ease_in_out_cubic(sub_p(p, 0.25, 0.55))
        cx = lerp(1440.0, 1450.0, t_cam)
        cy = lerp(960.0, 1140.0, t_cam)
        zoom = lerp(1.30, 1.52, t_cam)
        tilt_y = lerp(1.2, 0.0, t_cam)
    else:
        t_cam = ease_in_out_cubic(sub_p(p, 0.78, 1.0))
        cx = lerp(1450.0, 1440.0, t_cam)
        cy = lerp(1140.0, 1220.0, t_cam)
        zoom = lerp(1.52, 1.36, t_cam)
        tilt_y = lerp(0.0, -1.2, t_cam)

    frame = _render_camera_view(
        stage_bg,
        captures["03_resolve_vision"],
        cx=cx,
        cy=cy,
        zoom=zoom,
        tilt_x_deg=0.5,
        tilt_y_deg=tilt_y,
        cursor_xy=cur_xy,
        click_ripples=ripples,
        pressing=pressing,
    )

    _draw_frosted_callout(
        frame,
        (64, 836, 820, 940),
        "STAGE 01A · MULTIMODAL VISION TELEMETRY",
        "98% Authenticity · FRACTURED_HANDLE (0.98)",
        "Packing slip OCR verified ORDER-001 · Zero synthetic image artifacts.",
        (16, 185, 129),
        fonts,
        enter_p=sub_p(p, 0.22, 0.42),
    )
    return frame


def _render_scene_03(
    stage_bg: Image.Image,
    p: float,
    captures: Dict[str, Image.Image],
    fonts: Dict[str, ImageFont.FreeTypeFont],
) -> Image.Image:
    """Scene 3: 3-Way Smart Settlement Negotiator (04_resolve_negotiator -> 05_store_credit -> 06_receipt)."""
    if p < 0.40:
        base_cap = captures["04_resolve_negotiator"]
        cur_t = ease_in_out_cubic(sub_p(p, 0.12, 0.40))
        cur_xy = bezier_pt((1200.0, 1120.0), (1440.0, 1020.0), (1680.0, 1120.0), cur_t)
        ripples = []
        pressing = 0.38 <= p <= 0.40
    elif p < 0.74:
        base_cap = captures["05_resolve_store_credit"]
        cur_t = ease_in_out_cubic(sub_p(p, 0.48, 0.72))
        cur_xy = bezier_pt((1680.0, 1120.0), (1540.0, 1340.0), (1440.0, 1500.0), cur_t)
        ripples = []
        if 0.40 <= p <= 0.56:
            ripples.append(((1680.0, 1120.0), sub_p(p, 0.40, 0.56)))
        if 0.72 <= p <= 0.74:
            ripples.append(((1440.0, 1500.0), sub_p(p, 0.72, 0.86)))
        pressing = 0.70 <= p <= 0.74
    else:
        base_cap = captures["06_resolve_receipt"]
        cur_xy = lerp_pt((1440.0, 1500.0), (1440.0, 680.0), ease_out_cubic(sub_p(p, 0.74, 0.95)))
        ripples = [((1440.0, 1500.0), sub_p(p, 0.72, 0.86))] if p <= 0.86 else []
        pressing = False

    if p < 0.40:
        t_cam = ease_in_out_cubic(sub_p(p, 0.0, 0.35))
        cx = lerp(1440.0, 1440.0, t_cam)
        cy = lerp(760.0, 1050.0, t_cam)
        zoom = lerp(1.10, 1.46, t_cam)
        tilt_y = lerp(-3.0, 0.0, t_cam)
    elif p < 0.74:
        t_cam = ease_in_out_cubic(sub_p(p, 0.40, 0.65))
        cx = lerp(1440.0, 1460.0, t_cam)
        cy = lerp(1050.0, 1080.0, t_cam)
        zoom = lerp(1.46, 1.52, t_cam)
        tilt_y = 0.0
    else:
        t_cam = ease_in_out_cubic(sub_p(p, 0.74, 0.92))
        cx = lerp(1460.0, 1440.0, t_cam)
        cy = lerp(1080.0, 660.0, t_cam)
        zoom = lerp(1.52, 1.42, t_cam)
        tilt_y = lerp(0.0, 1.8, t_cam)

    frame = _render_camera_view(
        stage_bg,
        base_cap,
        cx=cx,
        cy=cy,
        zoom=zoom,
        tilt_x_deg=0.5,
        tilt_y_deg=tilt_y,
        cursor_xy=cur_xy,
        click_ripples=ripples,
        pressing=pressing,
    )

    if p < 0.74:
        _draw_frosted_callout(
            frame,
            (64, 836, 820, 940),
            "AI MARGIN-RETENTION NEGOTIATOR",
            "65% Keep-Item Refund ($18.20) or 115% Store Credit ($32.20)",
            "Saves up to 100% of PayPal cash outflow + $6.50 reverse shipping.",
            (56, 189, 248),
            fonts,
            enter_p=sub_p(p, 0.08, 0.28),
        )
    else:
        _draw_frosted_callout(
            frame,
            (64, 836, 820, 940),
            "INSTANT PAYPAL SETTLEMENT RECEIPT",
            "Saved Merchant USD 9.80 · Keep-the-Item Waiver Confirmed",
            "Audited against rule 'damaged-or-not-as-described' · Case c_b024c7.",
            (16, 185, 129),
            fonts,
            enter_p=sub_p(p, 0.74, 0.86),
        )
    return frame


def _render_scene_04(
    stage_bg: Image.Image,
    p: float,
    captures: Dict[str, Image.Image],
    fonts: Dict[str, ImageFont.FreeTypeFont],
) -> Image.Image:
    """Scene 4: Merchant Command Center (07_merchant_overview) -> Case Inspector Drawer (08_merchant_case_drawer)."""
    if p < 0.44:
        base_cap = captures["07_merchant_overview"]
        cur_t = ease_in_out_cubic(sub_p(p, 0.15, 0.44))
        cur_xy = bezier_pt((1620.0, 390.0), (1380.0, 680.0), (1150.0, 945.0), cur_t)
        ripples = []
        pressing = 0.42 <= p <= 0.44

        t_cam = ease_in_out_cubic(sub_p(p, 0.0, 0.40))
        cx = lerp(1520.0, 1460.0, t_cam)
        cy = lerp(640.0, 760.0, t_cam)
        zoom = lerp(1.06, 1.34, t_cam)
        tilt_y = lerp(-4.5, -1.0, t_cam)
    else:
        base_cap = captures["08_merchant_case_drawer"]
        dp = sub_p(p, 0.44, 1.0)
        cur_xy = bezier_pt((1150.0, 945.0), (1860.0, 740.0), (2280.0, 1120.0), ease_in_out_cubic(dp))
        ripples = [((1150.0, 945.0), sub_p(p, 0.44, 0.60))] if p <= 0.60 else []
        pressing = False

        t_cam = ease_in_out_cubic(sub_p(p, 0.44, 0.68))
        t_pan_down = ease_in_out_cubic(sub_p(p, 0.68, 0.96))
        cx = lerp(1460.0, 2180.0, t_cam)
        cy = lerp(760.0, 640.0, t_cam) + lerp(0.0, 420.0, t_pan_down)
        zoom = lerp(1.34, 1.50, t_cam)
        tilt_y = lerp(-1.0, 1.2, t_cam)

    frame = _render_camera_view(
        stage_bg,
        base_cap,
        cx=cx,
        cy=cy,
        zoom=zoom,
        tilt_x_deg=0.6,
        tilt_y_deg=tilt_y,
        cursor_xy=cur_xy,
        click_ripples=ripples,
        pressing=pressing,
    )

    _draw_frosted_callout(
        frame,
        (64, 836, 840, 940),
        "PAYPAL PAYER TRUST & MULTIMODAL INSPECTOR",
        "Net Cash Retained: USD 105.30 · Payer Trust 82/100",
        "Caliper gauge verified 58.02mm vs 53.0mm packing slip SKU mismatch.",
        (56, 189, 248),
        fonts,
        enter_p=sub_p(p, 0.08, 0.28),
    )
    return frame


def _render_scene_05(
    stage_bg: Image.Image,
    p: float,
    captures: Dict[str, Image.Image],
    fonts: Dict[str, ImageFont.FreeTypeFont],
) -> Image.Image:
    """Scene 5: Guarded PayPal MCP Server Firewall (09_mcp_firewall_blocked.png)."""
    if p < 0.32:
        cur_t = ease_in_out_cubic(sub_p(p, 0.04, 0.26))
        cur_xy = bezier_pt((1640.0, 420.0), (1280.0, 520.0), (980.0, 680.0), cur_t)
    else:
        cur_t = ease_in_out_cubic(sub_p(p, 0.32, 0.78))
        cur_xy = bezier_pt((980.0, 680.0), (1380.0, 1120.0), (1620.0, 1420.0), cur_t)

    ripples = [((980.0, 680.0), sub_p(p, 0.26, 0.44))] if 0.26 <= p <= 0.44 else []

    if p < 0.32:
        t_cam = ease_in_out_cubic(sub_p(p, 0.0, 0.30))
        cx = lerp(1540.0, 1580.0, t_cam)
        cy = lerp(640.0, 680.0, t_cam)
        zoom = lerp(1.06, 1.24, t_cam)
        tilt_y = lerp(3.5, 0.5, t_cam)
    else:
        t_cam = ease_in_out_cubic(sub_p(p, 0.32, 0.68))
        cx = lerp(1580.0, 1610.0, t_cam)
        cy = lerp(680.0, 1140.0, t_cam)
        zoom = lerp(1.24, 1.32, t_cam)
        tilt_y = lerp(0.5, -1.0, t_cam)

    frame = _render_camera_view(
        stage_bg,
        captures["09_mcp_firewall_blocked"],
        cx=cx,
        cy=cy,
        zoom=zoom,
        tilt_x_deg=0.5,
        tilt_y_deg=tilt_y,
        cursor_xy=cur_xy,
        click_ripples=ripples,
        pressing=(0.24 <= p <= 0.28),
    )

    _draw_frosted_callout(
        frame,
        (64, 836, 860, 940),
        "SETTLE-PAYPAL-GUARDED-MCP · PROTOCOL 2024-11-05",
        "Rogue $999.00 Override Blocked -> Clamped to $28.00",
        "delta_blocked_minor = 97100 ($971.00 saved) · Rule: damaged-or-not-as-described",
        (244, 63, 94),
        fonts,
        enter_p=sub_p(p, 0.26, 0.45),
    )
    return frame


def _render_scene_06(
    stage_bg: Image.Image,
    p: float,
    captures: Dict[str, Image.Image],
    fonts: Dict[str, ImageFont.FreeTypeFont],
) -> Image.Image:
    """Scene 6: Counterfactual What-If Replay (10_what_if_simulator) -> Red-Team Injection Arena (11_red_team_arena)."""
    if p < 0.50:
        base_cap = captures["10_what_if_simulator"]
        wp = sub_p(p, 0.0, 0.50)
        cur_xy = bezier_pt((1120.0, 460.0), (1680.0, 580.0), (2260.0, 610.0), ease_in_out_cubic(wp))
        ripples = []
        pressing = False

        t_cam = ease_in_out_cubic(wp)
        cx = lerp(1580.0, 1610.0, t_cam)
        cy = lerp(580.0, 680.0, t_cam)
        zoom = lerp(1.12, 1.32, math.sin(wp * math.pi * 0.85))
        tilt_y = lerp(-2.8, 0.5, t_cam)
    else:
        base_cap = captures["11_red_team_arena"]
        rp = sub_p(p, 0.50, 1.0)
        cur_t = ease_in_out_cubic(sub_p(rp, 0.0, 0.45))
        cur_xy = bezier_pt((2460.0, 495.0), (1920.0, 640.0), (1540.0, 960.0), cur_t)
        ripples = [((2460.0, 495.0), sub_p(p, 0.52, 0.68))] if 0.52 <= p <= 0.68 else []
        pressing = 0.51 <= p <= 0.55

        t_cam = ease_in_out_cubic(rp)
        cx = lerp(1610.0, 1600.0, t_cam)
        cy = lerp(620.0, 880.0, t_cam)
        zoom = lerp(1.22, 1.30, t_cam)
        tilt_y = lerp(0.5, -1.5, t_cam)

    frame = _render_camera_view(
        stage_bg,
        base_cap,
        cx=cx,
        cy=cy,
        zoom=zoom,
        tilt_x_deg=0.5,
        tilt_y_deg=tilt_y,
        cursor_xy=cur_xy,
        click_ripples=ripples,
        pressing=pressing,
    )

    if p < 0.50:
        _draw_frosted_callout(
            frame,
            (64, 836, 830, 940),
            "COUNTERFACTUAL WHAT-IF POLICY SIMULATOR",
            "ORD-1003, ORD-1007, ORD-1008 -> FLIPPED TO AUTO",
            "Replay historical claims against candidate caps before deploying live.",
            (16, 185, 129),
            fonts,
            enter_p=sub_p(p, 0.06, 0.24),
        )
    else:
        _draw_frosted_callout(
            frame,
            (64, 836, 830, 940),
            "ADVERSARIAL RED-TEAM PROMPT INJECTION ARENA",
            "8 / 8 Jailbreak Vectors Neutralized · $0.00 Leakage",
            "SQLi, roleplay, and $500 override prompts clamped by deterministic code.",
            (56, 189, 248),
            fonts,
            enter_p=sub_p(p, 0.52, 0.68),
        )
    return frame


def _render_scene_07(
    stage_bg: Image.Image,
    p: float,
    captures: Dict[str, Image.Image],
    fonts: Dict[str, ImageFont.FreeTypeFont],
) -> Image.Image:
    """Scene 7: PayPal Dispute Evidence Auto-Drafter (12_disputes_autodrafter) -> Finale 3D Showcase Lockup."""
    if p < 0.70:
        dp = sub_p(p, 0.0, 0.70)
        cur_t = ease_in_out_cubic(sub_p(dp, 0.05, 0.45))
        cur_xy = bezier_pt((820.0, 480.0), (1480.0, 740.0), (2060.0, 920.0), cur_t)
        ripples = [((820.0, 480.0), sub_p(p, 0.22, 0.38))] if 0.22 <= p <= 0.38 else []

        t_cam = ease_in_out_cubic(dp)
        cx = lerp(1560.0, 1610.0, t_cam)
        cy = lerp(660.0, 880.0, t_cam)
        zoom = lerp(1.08, 1.28, t_cam)
        tilt_y = lerp(3.0, -0.8, t_cam)

        frame = _render_camera_view(
            stage_bg,
            captures["12_disputes_autodrafter"],
            cx=cx,
            cy=cy,
            zoom=zoom,
            tilt_x_deg=0.5,
            tilt_y_deg=tilt_y,
            cursor_xy=cur_xy,
            click_ripples=ripples,
            pressing=(0.20 <= p <= 0.24),
        )
        _draw_frosted_callout(
            frame,
            (64, 836, 850, 940),
            "1-CLICK PAYPAL DISPUTES API AUTO-DRAFTER",
            "POST /v1/customer/disputes/DISPUTE-001/provide-evidence",
            "Cross-references PayPal Capture ID & Settle Refund Ledger automatically.",
            (56, 189, 248),
            fonts,
            enter_p=sub_p(p, 0.06, 0.25),
        )
        return frame

    # Finale Lockup (p = 0.70 -> 1.00): 3D Multi-Screen Perspective Hero Showcase + Brand Lockup
    fp = ease_out_cubic(sub_p(p, 0.70, 0.92))
    if "_cache_s7_bg" not in captures:
        bg_view = _render_camera_view(
            stage_bg,
            captures["07_merchant_overview"],
            cx=1440,
            cy=810,
            zoom=1.0,
            tilt_x_deg=5.0,
            tilt_y_deg=7.0,
        )
        blurred = bg_view.filter(ImageFilter.GaussianBlur(radius=10))
        captures["_cache_s7_bg"] = ImageEnhance.Brightness(blurred).enhance(0.36)
    canvas = captures["_cache_s7_bg"].copy()
    draw = ImageDraw.Draw(canvas)

    # 3 floating miniature real UI cards across the top half
    thumbs = [
        ("03_resolve_vision", "AI VISION + OCR PROOF", (110, 118), (520, 292)),
        ("04_resolve_negotiator", "3-WAY SMART NEGOTIATOR", (700, 98), (520, 292)),
        ("09_mcp_firewall_blocked", "GUARDED PAYPAL MCP SERVER", (1290, 118), (520, 292)),
    ]
    for cap_key, label, (tx, ty), (tw, th) in thumbs:
        ty_anim = int(ty + (1.0 - fp) * 35)
        thumb_img = captures[cap_key].resize((tw, th), Image.Resampling.BILINEAR)
        t_mask = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(t_mask).rounded_rectangle((0, 0, tw - 1, th - 1), radius=14, fill=255)
        draw.rounded_rectangle((tx - 3, ty_anim - 3, tx + tw + 3, ty_anim + th + 3), radius=16, fill=(10, 22, 42), outline=(56, 189, 248), width=2)
        canvas.paste(thumb_img, (tx, ty_anim), t_mask)
        draw.rounded_rectangle((tx + 12, ty_anim + th - 36, tx + 290, ty_anim + th - 10), radius=8, fill=(8, 15, 28), outline=(0, 112, 186), width=1)
        draw.text((tx + 22, ty_anim + th - 32), label, font=fonts["mono_b_14"], fill=(125, 211, 252))

    # Central Finale Hero Card
    cy_off = int((1.0 - fp) * 28)
    draw.rounded_rectangle(
        (110, 445 + cy_off, 1810, 905 + cy_off),
        radius=26,
        fill=(9, 17, 32),
        outline=(56, 189, 248),
        width=3,
    )
    # Settle Shield Emblem
    draw.rounded_rectangle((164, 492 + cy_off, 236, 564 + cy_off), radius=16, fill=(0, 112, 186))
    draw.text((186, 494 + cy_off), "S", font=fonts["sans_b_44"], fill=(255, 255, 255))
    draw.text(
        (262, 488 + cy_off),
        "Settle — The Financial Firewall for Agentic Commerce",
        font=fonts["sans_b_40"],
        fill=(255, 255, 255),
    )
    draw.text(
        (262, 542 + cy_off),
        "AI Classifies the Claim. Deterministic Python Code Governs Every Single Cent.",
        font=fonts["sans_r_22"],
        fill=(148, 163, 184),
    )

    # 4 Proof Pillars inside Finale Card
    pillars = [
        ("402 / 402", "Automated Tests Passing", "Full contract, policy & 20-user E2E suite", (16, 185, 129)),
        ("5 TOOLS", "Guarded PayPal MCP", "JSON-RPC 2.0 + stdio agent firewall", (56, 189, 248)),
        ("3-WAY AI", "Smart Settlement Engine", "65% Keep-Item & 115% Store Credit", (96, 165, 250)),
        ("USD 0.00", "Hallucination Leakage", "100% integer minor-unit cap math", (52, 211, 153)),
    ]
    for idx, (stat, title, desc, col) in enumerate(pillars):
        px = 160 + idx * 405
        py = 618 + cy_off
        draw.rounded_rectangle((px, py, px + 382, py + 235), radius=18, fill=(13, 25, 46), outline=col, width=2)
        draw.text((px + 24, py + 24), stat, font=fonts["mono_b_44"], fill=col)
        draw.text((px + 24, py + 98), title, font=fonts["sans_b_22"], fill=(248, 250, 252))
        draw.text((px + 24, py + 136), desc, font=fonts["sans_r_17"], fill=(148, 163, 184))

    return canvas


SCENE_RENDERERS = [
    _render_scene_01,
    _render_scene_02,
    _render_scene_03,
    _render_scene_04,
    _render_scene_05,
    _render_scene_06,
    _render_scene_07,
]


# ---------------------------------------------------------------------------
# Studio Stage Backdrop
# ---------------------------------------------------------------------------
def _create_studio_stage_backdrop() -> Image.Image:
    """Create a deep obsidian + PayPal blue radial studio stage backdrop."""
    y_grid, x_grid = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)

    # Top-center studio key light (#0070ba)
    d1 = np.sqrt(((x_grid - 960.0) / 1.35) ** 2 + (y_grid - 180.0) ** 2) / 920.0
    g1 = np.clip(1.0 - d1, 0.0, 1.0) ** 2.0

    # Bottom-right cyan rim glow (#00a8ea)
    d2 = np.sqrt((x_grid - 1580.0) ** 2 + (y_grid - 880.0) ** 2) / 960.0
    g2 = np.clip(1.0 - d2, 0.0, 1.0) ** 2.3

    r = 5.0 + g1 * 10.0 + g2 * 6.0
    g = 9.0 + g1 * 46.0 + g2 * 58.0
    b = 19.0 + g1 * 112.0 + g2 * 120.0

    arr = np.stack([r, g, b], axis=-1).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    draw = ImageDraw.Draw(img)

    # Subtle perspective studio floor grid lines
    for gx in range(0, WIDTH, 96):
        draw.line([(gx, 0), (gx, HEIGHT)], fill=(15, 25, 44), width=1)
    for gy in range(0, HEIGHT, 96):
        draw.line([(0, gy), (WIDTH, gy)], fill=(15, 25, 44), width=1)

    return img


# ---------------------------------------------------------------------------
# Voiceover Synthesis & Master Audio Soundtrack with Frame-Accurate UI SFX
# ---------------------------------------------------------------------------
async def _synthesize_scene_voiceovers(temp_dir: Path, ffmpeg_bin: str) -> List[np.ndarray]:
    pcm_clips: List[np.ndarray] = []
    for idx, scene in enumerate(SCENES):
        mp3_path = temp_dir / f"vo_{idx:02d}.mp3"
        wav_path = temp_dir / f"vo_{idx:02d}.wav"
        comm = edge_tts.Communicate(scene["narration"], VOICE, rate="+4%")
        await comm.save(str(mp3_path))
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp3_path),
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "2",
                "-f",
                "wav",
                str(wav_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with wave.open(str(wav_path), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            samples = samples.reshape(-1, 2)
        pcm_clips.append(samples)
    return pcm_clips


def _build_master_soundtrack(
    vo_clips: List[np.ndarray],
    scene_timings: List[Tuple[float, float, float]],
    total_duration: float,
) -> np.ndarray:
    """Synthesize a Stripe/Linear ambient synth score + UI click & transition SFX mixed with voiceover."""
    total_samples = int(total_duration * SAMPLE_RATE)
    t = np.arange(total_samples, dtype=np.float32) / SAMPLE_RATE

    vo_track = np.zeros((total_samples, 2), dtype=np.float32)
    vo_active = np.zeros(total_samples, dtype=np.float32)

    for clip, (start_s, vo_offset_s, _end_s) in zip(vo_clips, scene_timings):
        pos = int((start_s + vo_offset_s) * SAMPLE_RATE)
        end_pos = min(total_samples, pos + len(clip))
        length = end_pos - pos
        if length > 0:
            vo_track[pos:end_pos] += clip[:length] * 1.10
            vo_active[max(0, pos - int(0.15 * SAMPLE_RATE)) : min(total_samples, end_pos + int(0.25 * SAMPLE_RATE))] = 1.0

    # Sidechain ducking envelope
    kernel_size = int(0.18 * SAMPLE_RATE)
    kernel = np.ones(kernel_size, dtype=np.float32) / kernel_size
    vo_smooth = np.convolve(vo_active, kernel, mode="same")
    duck_gain = 1.0 - 0.72 * np.clip(vo_smooth, 0.0, 1.0)

    # Warm lush chord progression: Cm9 -> Abmaj7 -> Fm9 -> G7sus4
    chords = [
        (65.41, [130.81, 155.56, 196.00, 233.08, 293.66]),
        (51.91, [103.83, 155.56, 196.00, 246.94, 311.13]),
        (43.65, [130.81, 174.61, 207.65, 261.63, 311.13]),
        (49.00, [146.83, 196.00, 220.00, 261.63, 293.66]),
    ]

    pad_l = np.zeros(total_samples, dtype=np.float32)
    pad_r = np.zeros(total_samples, dtype=np.float32)

    bar_len = 8.0
    num_bars = int(math.ceil(total_duration / bar_len))
    for b in range(num_bars):
        b_start = int(b * bar_len * SAMPLE_RATE)
        b_end = min(total_samples, int((b + 1) * bar_len * SAMPLE_RATE))
        if b_end <= b_start:
            continue
        bt = t[b_start:b_end] - b * bar_len
        blen = b_end - b_start
        env = np.ones(blen, dtype=np.float32)
        fade_n = min(blen // 3, int(0.8 * SAMPLE_RATE))
        if fade_n > 0:
            env[:fade_n] = np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
            env[-fade_n:] = np.linspace(1.0, 0.0, fade_n, dtype=np.float32)

        bass_f, notes = chords[b % len(chords)]
        sub = 0.21 * np.sin(2 * np.pi * bass_f * bt) + 0.06 * np.sin(2 * np.pi * (bass_f * 2) * bt)
        pad_l[b_start:b_end] += sub * env
        pad_r[b_start:b_end] += sub * env

        for n_idx, nf in enumerate(notes):
            detune = 1.0015 if n_idx % 2 == 0 else 0.9985
            pan_l = 0.65 if n_idx % 2 == 0 else 0.35
            pan_r = 1.0 - pan_l
            w_l = np.sin(2 * np.pi * nf * bt)
            w_r = np.sin(2 * np.pi * (nf * detune) * bt + 0.4)
            pad_l[b_start:b_end] += 0.052 * pan_l * w_l * env
            pad_r[b_start:b_end] += 0.052 * pan_r * w_r * env

    # Subtle 120 BPM 8th-note marimba/synth pulse
    step_s = 0.25
    arp_notes = [261.63, 311.13, 392.00, 466.16, 523.25, 466.16, 392.00, 311.13]
    num_steps = int(total_duration / step_s)
    for s_idx in range(num_steps):
        s_pos = int(s_idx * step_s * SAMPLE_RATE)
        s_len = min(int(0.18 * SAMPLE_RATE), total_samples - s_pos)
        if s_len <= 0:
            continue
        st = np.arange(s_len, dtype=np.float32) / SAMPLE_RATE
        af = arp_notes[s_idx % len(arp_notes)]
        a_env = np.exp(-st * 18.0)
        pluck = 0.042 * np.sin(2 * np.pi * af * st) * a_env
        if s_idx % 2 == 0:
            pad_l[s_pos : s_pos + s_len] += pluck
            pad_r[s_pos : s_pos + s_len] += pluck * 0.5
        else:
            pad_l[s_pos : s_pos + s_len] += pluck * 0.5
            pad_r[s_pos : s_pos + s_len] += pluck

    # Scene transition chimes + frame-accurate UI click sound effects
    fx_l = np.zeros(total_samples, dtype=np.float32)
    fx_r = np.zeros(total_samples, dtype=np.float32)
    for idx, (start_s, _vo_off, end_s) in enumerate(scene_timings):
        pos = int(start_s * SAMPLE_RATE)
        w_len = min(int(0.42 * SAMPLE_RATE), total_samples - pos)
        if w_len > 0:
            wt = np.arange(w_len, dtype=np.float32) / SAMPLE_RATE
            f_start = 220.0 if idx % 2 == 0 else 293.66
            f_end = f_start * 1.5
            phase = 2 * np.pi * (f_start * wt + 0.5 * (f_end - f_start) * wt * wt / 0.42)
            w_env = np.sin(np.pi * wt / 0.42) * np.exp(-wt * 5.2)
            chime = 0.075 * np.sin(phase) * w_env
            fx_l[pos : pos + w_len] += chime
            fx_r[pos : pos + w_len] += chime

        # Add tactile UI click & confirmation harmonic at each scene's click timestamps
        s_dur = max(0.01, end_s - start_s)
        for click_p in SCENES[idx].get("clicks", []):
            c_pos = int((start_s + click_p * s_dur) * SAMPLE_RATE)
            c_len = min(int(0.12 * SAMPLE_RATE), total_samples - c_pos)
            if c_len > 0:
                ct = np.arange(c_len, dtype=np.float32) / SAMPLE_RATE
                # Crisp mechanical switch transient + subtle 880Hz confirmation ping
                click_wave = (
                    0.11 * np.sin(2 * np.pi * 1450.0 * ct) * np.exp(-ct * 95.0)
                    + 0.055 * np.sin(2 * np.pi * 880.0 * ct) * np.exp(-ct * 28.0)
                )
                fx_l[c_pos : c_pos + c_len] += click_wave
                fx_r[c_pos : c_pos + c_len] += click_wave

    fade_out_n = min(total_samples, int(1.4 * SAMPLE_RATE))
    master_env = np.ones(total_samples, dtype=np.float32)
    master_env[-fade_out_n:] = np.linspace(1.0, 0.0, fade_out_n, dtype=np.float32)

    music_l = (pad_l * duck_gain + fx_l) * master_env
    music_r = (pad_r * duck_gain + fx_r) * master_env

    mix = np.zeros((total_samples, 2), dtype=np.float32)
    mix[:, 0] = np.clip(vo_track[:, 0] + music_l, -0.98, 0.98)
    mix[:, 1] = np.clip(vo_track[:, 1] + music_r, -0.98, 0.98)
    return mix


# ---------------------------------------------------------------------------
# Full Pipeline Orchestrator
# ---------------------------------------------------------------------------
def main() -> None:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg binary not found in PATH")

    fonts = {
        "sans_b_64": font_sans_bold(64),
        "sans_b_44": font_sans_bold(44),
        "sans_b_40": font_sans_bold(40),
        "sans_b_28": font_sans_bold(28),
        "sans_b_22": font_sans_bold(22),
        "sans_b_18": font_sans_bold(18),
        "sans_b_16": font_sans_bold(16),
        "sans_s_21": font_sans_semibold(21),
        "sans_r_26": font_sans_reg(26),
        "sans_r_22": font_sans_reg(22),
        "sans_r_17": font_sans_reg(17),
        "mono_b_44": font_mono_bold(44),
        "mono_b_18": font_mono_bold(18),
        "mono_b_15": font_mono_bold(15),
        "mono_b_14": font_mono_bold(14),
    }

    print("[0/4] Loading & framing 12 real 2880x1620 Chromium UI captures...", flush=True)
    captures = _load_and_frame_captures(fonts)
    stage_bg = _create_studio_stage_backdrop()

    with tempfile.TemporaryDirectory() as tmp_str:
        temp_dir = Path(tmp_str)
        print("[1/4] Synthesizing studio neural voiceover via edge-tts...", flush=True)
        vo_clips = asyncio.run(_synthesize_scene_voiceovers(temp_dir, ffmpeg_bin))

        scene_timings: List[Tuple[float, float, float]] = []
        cursor = 0.0
        for clip in vo_clips:
            vo_dur = len(clip) / SAMPLE_RATE
            vo_offset = 0.42
            scene_dur = vo_dur + 1.15
            scene_timings.append((cursor, vo_offset, cursor + scene_dur))
            cursor += scene_dur

        total_duration = cursor + 0.9
        total_frames = int(total_duration * FPS)
        print(f"      Total Launch Film duration: {total_duration:.2f}s ({total_frames} frames @ {FPS}fps)", flush=True)

        print("[2/4] Synthesizing Stripe/Linear ambient score & frame-accurate UI SFX...", flush=True)
        master_audio = _build_master_soundtrack(vo_clips, scene_timings, total_duration)
        master_wav = temp_dir / "master_audio.wav"
        with wave.open(str(master_wav), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            pcm16 = (master_audio * 32767.0).astype(np.int16)
            wf.writeframes(pcm16.tobytes())

        mp4_path = DOCS_DIR / "settle_launch_film.mp4"
        webm_path = DOCS_DIR / "settle_launch_film.webm"

        print(f"[3/4] Rendering {total_frames} 1080p frames directly to {mp4_path.name}...", flush=True)
        ffmpeg_cmd = [
            ffmpeg_bin,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-pix_fmt",
            "rgb24",
            "-r",
            str(FPS),
            "-i",
            "-",
            "-i",
            str(master_wav),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "17",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(mp4_path),
        ]
        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert proc.stdin is not None

        for f_idx in range(total_frames):
            t_sec = f_idx / FPS
            active_idx = len(SCENES) - 1
            for s_idx, (s_start, _vo_off, s_end) in enumerate(scene_timings):
                if t_sec < s_end or s_idx == len(SCENES) - 1:
                    active_idx = s_idx
                    break

            s_start, vo_off, s_end = scene_timings[active_idx]
            s_dur = max(0.01, s_end - s_start)
            scene_p = clamp01((t_sec - s_start) / s_dur)
            vo_dur = max(0.01, s_dur - 1.15)
            vo_p = clamp01((t_sec - (s_start + vo_off)) / vo_dur)

            frame = SCENE_RENDERERS[active_idx](stage_bg, scene_p, captures, fonts)

            # Smooth 0.25s optical cross-dissolve between scenes
            if t_sec - s_start < 0.24 and active_idx > 0:
                blend_alpha = clamp01((t_sec - s_start) / 0.24)
                prev_frame = SCENE_RENDERERS[active_idx - 1](stage_bg, 1.0, captures, fonts)
                frame = Image.blend(prev_frame, frame, alpha=ease_in_out_cubic(blend_alpha))

            _draw_top_minimal_bar(frame, active_idx, SCENES[active_idx], fonts)
            _draw_broadcast_caption_bar(frame, SCENES[active_idx]["narration"], vo_p, fonts)

            proc.stdin.write(frame.tobytes())
            if f_idx % 300 == 0 or f_idx == total_frames - 1:
                print(f"      Frame {f_idx + 1}/{total_frames} ({(f_idx + 1) * 100 // total_frames}%)", flush=True)

        proc.stdin.close()
        ret = proc.wait()
        if ret != 0:
            raise RuntimeError(f"ffmpeg mp4 encode failed ({ret})")

        print(f"[4/4] Exporting WebM companion file ({webm_path.name})...", flush=True)
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp4_path),
                "-c:v",
                "libvpx-vp9",
                "-crf",
                "30",
                "-b:v",
                "0",
                "-deadline",
                "realtime",
                "-cpu-used",
                "6",
                "-row-mt",
                "1",
                "-c:a",
                "libopus",
                "-b:a",
                "128k",
                str(webm_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        print(
            f"DONE! MP4 ({mp4_path.stat().st_size / (1024*1024):.2f} MB) & WebM ({webm_path.stat().st_size / (1024*1024):.2f} MB) ready.",
            flush=True,
        )


if __name__ == "__main__":
    main()

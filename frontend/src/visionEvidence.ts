export interface VisionBoundingBox {
  id: string;
  label: string;
  confidence: number;
  xPct: number;
  yPct: number;
  wPct: number;
  hPct: number;
  tone: "verified" | "warning" | "danger";
}

export interface VisionEvidencePreset {
  id: string;
  title: string;
  shortLabel: string;
  badgeText: string;
  verdict: "VERIFIED_DAMAGE" | "VERIFIED_WRONG_ITEM" | "VERIFIED_TRANSIT_DAMAGE" | "SPOOF_SUSPECTED" | "CUSTOM_UPLOAD";
  authenticityScore: number; // 0..100
  passesPhotoRequirement: boolean; // Maps deterministically to ClaimInput.has_photo
  suggestedComplaint: string;
  skuMatched: string;
  defectSummary: string;
  exifStatus: string;
  policySignal: string;
  modelName: string;
  latencyMs: number;
  imageSvgDataUri: string;
  boxes: VisionBoundingBox[];
}

function encodeSvgDataUri(svg: string): string {
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg.trim())}`;
}

const MUG_CRACKED_SVG = encodeSvgDataUri(`
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 380" width="640" height="380">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#1c1917"/>
      <stop offset="55%" stop-color="#292524"/>
      <stop offset="100%" stop-color="#0f172a"/>
    </linearGradient>
    <linearGradient id="wood" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#44403c"/>
      <stop offset="100%" stop-color="#292524"/>
    </linearGradient>
    <linearGradient id="mugBody" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#64748b"/>
      <stop offset="50%" stop-color="#475569"/>
      <stop offset="100%" stop-color="#334155"/>
    </linearGradient>
    <linearGradient id="boxGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#a16207"/>
      <stop offset="100%" stop-color="#713f12"/>
    </linearGradient>
  </defs>
  <!-- Background studio surface -->
  <rect width="640" height="265" fill="url(#bg)"/>
  <rect y="265" width="640" height="115" fill="url(#wood)"/>
  <line x1="0" y1="265" x2="640" y2="265" stroke="#57534e" stroke-width="2"/>

  <!-- Shipping Carton in Background -->
  <g transform="translate(52, 74)">
    <rect x="0" y="0" width="185" height="192" rx="6" fill="url(#boxGrad)" stroke="#ca8a04" stroke-width="1.5"/>
    <rect x="16" y="20" width="152" height="84" rx="4" fill="#fefce8" stroke="#d6d3d1"/>
    <text x="26" y="40" font-family="monospace" font-size="11" font-weight="bold" fill="#1c1917">KOPI &amp; CLAY ROASTERS</text>
    <text x="26" y="57" font-family="monospace" font-size="10" fill="#44403c">ORDER: ORDER-001</text>
    <text x="26" y="72" font-family="monospace" font-size="10" fill="#44403c">SKU: MUG-CER-01 (x1)</text>
    <!-- Barcode lines -->
    <g fill="#1c1917" transform="translate(26, 80)">
      <rect x="0" width="3" height="16"/><rect x="6" width="1.5" height="16"/><rect x="11" width="4" height="16"/>
      <rect x="18" width="2" height="16"/><rect x="23" width="5" height="16"/><rect x="31" width="1.5" height="16"/>
      <rect x="36" width="3" height="16"/><rect x="43" width="2" height="16"/><rect x="48" width="4" height="16"/>
      <rect x="56" width="1.5" height="16"/><rect x="61" width="3" height="16"/><rect x="68" width="5" height="16"/>
      <rect x="77" width="2" height="16"/><rect x="83" width="3" height="16"/><rect x="90" width="4" height="16"/>
    </g>
  </g>

  <!-- Shadow under mug -->
  <ellipse cx="365" cy="300" rx="115" ry="20" fill="#090d16" opacity="0.55"/>

  <!-- Stoneware Mug Body -->
  <g transform="translate(265, 112)">
    <rect x="0" y="18" width="150" height="168" rx="16" fill="url(#mugBody)" stroke="#94a3b8" stroke-width="2"/>
    <ellipse cx="75" cy="20" rx="75" ry="16" fill="#1e293b" stroke="#cbd5e1" stroke-width="2"/>
    <!-- Brand stamp near base -->
    <text x="42" y="164" font-family="monospace" font-size="10" letter-spacing="1.5" fill="#cbd5e1" opacity="0.8">KOPI &amp; CLAY</text>

    <!-- Jagged Rim Chip & Deep Crack -->
    <polygon points="92,12 115,8 106,32 95,25" fill="#0f172a" stroke="#f87171" stroke-width="1.5"/>
    <path d="M102,28 L94,58 L108,84 L96,118 L112,144" fill="none" stroke="#0f172a" stroke-width="4" stroke-linecap="round"/>
    <path d="M102,28 L94,58 L108,84 L96,118 L112,144" fill="none" stroke="#fca5a5" stroke-width="1.3" stroke-dasharray="4 2"/>

    <!-- Fractured Detached Handle Upper Junction -->
    <path d="M150,48 C192,48 198,84 184,108" fill="none" stroke="#475569" stroke-width="16" stroke-linecap="round"/>
    <path d="M150,144 C178,144 186,132 182,120" fill="none" stroke="#475569" stroke-width="16" stroke-linecap="round"/>
    <!-- Exposed raw ceramic fracture gap -->
    <polygon points="145,40 162,43 158,57 144,54" fill="#fef2f2" stroke="#ef4444" stroke-width="1.5"/>
    <polygon points="175,104 191,109 187,122 172,117" fill="#fef2f2" stroke="#ef4444" stroke-width="1.5"/>
  </g>

  <!-- Detached Ceramic Shards on Table -->
  <g transform="translate(455, 275)">
    <polygon points="0,16 26,6 38,24 14,32" fill="#64748b" stroke="#e2e8f0" stroke-width="1.5"/>
    <polygon points="46,24 68,14 76,30 52,36" fill="#475569" stroke="#fca5a5" stroke-width="1.5"/>
    <polygon points="22,38 40,33 44,45 25,46" fill="#94a3b8" stroke="#e2e8f0" stroke-width="1.2"/>
  </g>

  <!-- Camera HUD Timestamp -->
  <rect x="18" y="16" width="250" height="26" rx="5" fill="#090d16" opacity="0.75"/>
  <text x="28" y="33" font-family="monospace" font-size="11" fill="#e2e8f0">EXIF: iPhone 15 Pro · ISO 125 · RAW Verified</text>
</svg>
`);

const TAMPER_WRONG_SIZE_SVG = encodeSvgDataUri(`
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 380" width="640" height="380">
  <defs>
    <linearGradient id="bg2" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#1e293b"/>
    </linearGradient>
    <linearGradient id="steel" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#94a3b8"/>
      <stop offset="50%" stop-color="#f8fafc"/>
      <stop offset="100%" stop-color="#64748b"/>
    </linearGradient>
    <linearGradient id="walnut" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#78350f"/>
      <stop offset="100%" stop-color="#451a03"/>
    </linearGradient>
  </defs>
  <rect width="640" height="380" fill="url(#bg2)"/>

  <!-- Packing Slip Document on Left -->
  <g transform="translate(42, 58)">
    <rect width="230" height="265" rx="6" fill="#f8fafc" stroke="#cbd5e1" stroke-width="2"/>
    <text x="20" y="34" font-family="monospace" font-size="13" font-weight="bold" fill="#0f172a">PACKING SLIP · KOPI &amp; CLAY</text>
    <line x1="20" y1="45" x2="210" y2="45" stroke="#cbd5e1"/>
    <text x="20" y="68" font-family="monospace" font-size="11" fill="#334155">ORDERED SPEC:</text>
    <rect x="18" y="78" width="194" height="44" rx="4" fill="#fef3c7" stroke="#f59e0b" stroke-width="1.5"/>
    <text x="26" y="98" font-family="monospace" font-size="12" font-weight="bold" fill="#92400e">53.0 mm Breville Pro Tamper</text>
    <text x="26" y="114" font-family="monospace" font-size="10" fill="#78350f">SKU: TAMP-53-WAL · Qty: 1</text>

    <text x="20" y="152" font-family="monospace" font-size="11" fill="#475569">RECEIVED BOX STAMP:</text>
    <rect x="18" y="162" width="194" height="44" rx="4" fill="#fee2e2" stroke="#ef4444" stroke-width="1.5"/>
    <text x="26" y="182" font-family="monospace" font-size="12" font-weight="bold" fill="#991b1b">58.0 mm E61 Commercial Base</text>
    <text x="26" y="198" font-family="monospace" font-size="10" fill="#b91c1c">SKU: TAMP-58-WAL (WRONG SIZE)</text>
  </g>

  <!-- Espresso Tamper + Digital Caliper Measurement on Right -->
  <g transform="translate(335, 76)">
    <!-- Walnut handle -->
    <path d="M70,0 C115,0 125,45 108,92 L98,132 L52,132 L42,92 C25,45 35,0 70,0 Z" fill="url(#walnut)" stroke="#b45309" stroke-width="1.5"/>
    <!-- Steel collar & 58mm base -->
    <rect x="44" y="132" width="62" height="18" rx="3" fill="url(#steel)"/>
    <rect x="12" y="150" width="126" height="32" rx="4" fill="url(#steel)" stroke="#e2e8f0" stroke-width="1.5"/>
    <text x="38" y="170" font-family="monospace" font-size="12" font-weight="bold" fill="#0f172a">Ø 58.0 mm</text>

    <!-- Digital Caliper Jaws & LCD Readout -->
    <line x1="12" y1="184" x2="12" y2="238" stroke="#38bdf8" stroke-width="3"/>
    <line x1="138" y1="184" x2="138" y2="238" stroke="#38bdf8" stroke-width="3"/>
    <line x1="12" y1="218" x2="138" y2="218" stroke="#38bdf8" stroke-width="2" stroke-dasharray="4 3"/>
    <rect x="18" y="226" width="114" height="36" rx="5" fill="#020617" stroke="#38bdf8" stroke-width="2"/>
    <text x="30" y="249" font-family="monospace" font-size="15" font-weight="bold" fill="#4ade80">58.02 mm</text>
  </g>

  <rect x="18" y="16" width="275" height="26" rx="5" fill="#020617" opacity="0.78"/>
  <text x="28" y="33" font-family="monospace" font-size="11" fill="#e2e8f0">OPTICAL GAUGE + OCR: 58.02mm vs 53.00mm</text>
</svg>
`);

const PARCEL_CRUSHED_SVG = encodeSvgDataUri(`
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 380" width="640" height="380">
  <defs>
    <linearGradient id="bg3" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#18181b"/>
      <stop offset="100%" stop-color="#27272a"/>
    </linearGradient>
    <linearGradient id="cardboard" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#b45309"/>
      <stop offset="100%" stop-color="#78350f"/>
    </linearGradient>
  </defs>
  <rect width="640" height="380" fill="url(#bg3)"/>

  <!-- Crushed Corrugated Carton -->
  <g transform="translate(88, 66)">
    <polygon points="0,30 220,10 265,62 248,220 12,230" fill="url(#cardboard)" stroke="#f59e0b" stroke-width="2"/>
    <!-- Crushed/torn top-right corner crease lines -->
    <polygon points="155,16 220,10 265,62 195,95" fill="#451a03" stroke="#ef4444" stroke-width="2"/>
    <path d="M155,16 L188,68 L248,58" fill="none" stroke="#fca5a5" stroke-width="2"/>
    <!-- Shipping label -->
    <rect x="28" y="55" width="128" height="74" rx="4" fill="#fafaf9" stroke="#a8a29e"/>
    <text x="38" y="75" font-family="monospace" font-size="10" font-weight="bold" fill="#1c1917">CARRIER: PRIORITY</text>
    <text x="38" y="92" font-family="monospace" font-size="10" fill="#44403c">MERCHANT: m_kopiclay</text>
    <text x="38" y="108" font-family="monospace" font-size="9.5" fill="#dc2626">STATUS: DAMAGED IN TRANSIT</text>
  </g>

  <!-- Punctured Whole-Bean Coffee Valve Bag + Spilled Beans -->
  <g transform="translate(375, 92)">
    <rect x="0" y="0" width="154" height="196" rx="10" fill="#fef3c7" stroke="#d97706" stroke-width="2"/>
    <circle cx="77" cy="44" r="10" fill="#d6d3d1" stroke="#78716c" stroke-width="1.5"/>
    <text x="24" y="84" font-family="monospace" font-size="12" font-weight="bold" fill="#451a03">KOPI &amp; CLAY</text>
    <text x="24" y="102" font-family="monospace" font-size="10" fill="#78350f">SINGLE ORIGIN 250G</text>
    <!-- Jagged puncture tear in bag -->
    <polygon points="32,126 118,114 134,154 48,162" fill="#292524" stroke="#ef4444" stroke-width="2"/>
    <text x="48" y="143" font-family="monospace" font-size="10" font-weight="bold" fill="#fca5a5">SEAL BREACHED</text>
    <!-- Spilled coffee beans -->
    <ellipse cx="44" cy="216" rx="10" ry="6" fill="#451a03" stroke="#78350f"/>
    <ellipse cx="72" cy="224" rx="11" ry="6" fill="#451a03" stroke="#78350f"/>
    <ellipse cx="98" cy="214" rx="10" ry="6" fill="#451a03" stroke="#78350f"/>
    <ellipse cx="124" cy="226" rx="11" ry="6" fill="#451a03" stroke="#78350f"/>
    <ellipse cx="62" cy="238" rx="10" ry="6" fill="#451a03" stroke="#78350f"/>
  </g>

  <rect x="18" y="16" width="295" height="26" rx="5" fill="#09090b" opacity="0.8"/>
  <text x="28" y="33" font-family="monospace" font-size="11" fill="#e2e8f0">CV SCAN: CARTON CRUSH + PRIMARY SEAL BREACH</text>
</svg>
`);

const SPOOF_STOCK_SVG = encodeSvgDataUri(`
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 380" width="640" height="380">
  <rect width="640" height="380" fill="#334155"/>
  <!-- Generic stock studio backdrop -->
  <rect x="40" y="45" width="560" height="290" rx="8" fill="#e2e8f0" stroke="#ef4444" stroke-width="2" stroke-dasharray="8 4"/>
  <!-- Generic white cup (wrong SKU geometry) -->
  <ellipse cx="320" cy="240" rx="95" ry="22" fill="#cbd5e1"/>
  <rect x="255" y="125" width="130" height="105" rx="8" fill="#ffffff" stroke="#94a3b8" stroke-width="2"/>
  <path d="M385,145 C420,145 420,205 385,205" fill="none" stroke="#ffffff" stroke-width="14"/>
  <!-- Stock photo watermark grid -->
  <g opacity="0.32" fill="#dc2626" font-family="monospace" font-size="18" font-weight="bold">
    <text x="80" y="110" transform="rotate(-14 80,110)">STOCK PHOTO WATERMARK · SHUTTER-ID-99412</text>
    <text x="110" y="210" transform="rotate(-14 110,210)">GENERIC ROYALTY-FREE CATALOG IMAGE</text>
    <text x="130" y="305" transform="rotate(-14 130,305)">NO EXIF CAMERA METADATA · WEB SCRAPED</text>
  </g>
  <rect x="18" y="16" width="355" height="26" rx="5" fill="#450a0a" stroke="#ef4444"/>
  <text x="28" y="33" font-family="monospace" font-size="11" font-weight="bold" fill="#fecaca">ALERT: REVERSE-IMAGE HIT (99%) · EXIF STRIPPED</text>
</svg>
`);

export const VISION_EVIDENCE_PRESETS: VisionEvidencePreset[] = [
  {
    id: "mug_cracked_authentic",
    title: "Cracked Stoneware Mug (Authentic)",
    shortLabel: "Cracked Mug (98% Match)",
    badgeText: "VERIFIED DAMAGE · 98%",
    verdict: "VERIFIED_DAMAGE",
    authenticityScore: 98,
    passesPhotoRequirement: true,
    suggestedComplaint:
      "My stoneware mug arrived broken with a fractured handle and chipped rim.",
    skuMatched: "Kopi & Clay Matte Stoneware Mug (SKU: MUG-CER-01 · 97% match)",
    defectSummary:
      "Structural fracture detected at upper handle junction + 2 detached ceramic shards on surface.",
    exifStatus:
      "PASS · iPhone 15 Pro (f/1.78, ISO 125) · Captured 2h after delivery · No stock/AI watermark",
    policySignal:
      "Sets has_photo = true → Unlocks autonomous damaged-item refund rule within $50.00 hard cap",
    modelName: "claude-3-5-sonnet-vision + settle-cv-v2",
    latencyMs: 340,
    imageSvgDataUri: MUG_CRACKED_SVG,
    boxes: [
      {
        id: "box-handle-crack",
        label: "FRACTURED_HANDLE (0.98)",
        confidence: 0.98,
        xPct: 62,
        yPct: 38,
        wPct: 14,
        hPct: 36,
        tone: "verified",
      },
      {
        id: "box-shards",
        label: "CERAMIC_SHARDS (0.95)",
        confidence: 0.95,
        xPct: 70,
        yPct: 70,
        wPct: 16,
        hPct: 16,
        tone: "verified",
      },
      {
        id: "box-shipping-label",
        label: "LABEL_OCR: ORDER-001 (0.99)",
        confidence: 0.99,
        xPct: 10,
        yPct: 24,
        wPct: 25,
        hPct: 24,
        tone: "verified",
      },
    ],
  },
  {
    id: "tamper_wrong_size",
    title: "Wrong SKU Size: 58mm vs 53mm Ordered",
    shortLabel: "Wrong Item 58mm vs 53mm (96%)",
    badgeText: "VERIFIED WRONG SKU · 96%",
    verdict: "VERIFIED_WRONG_ITEM",
    authenticityScore: 96,
    passesPhotoRequirement: true,
    suggestedComplaint:
      "You sent the wrong item size (58mm tamper instead of the 53mm tamper I ordered).",
    skuMatched:
      "Optical caliper confirms 58.02mm base vs. ordered 53.0mm packing slip spec",
    defectSummary:
      "Fulfillment SKU mismatch verified via optical gauge readout (58.02mm) and packing slip OCR.",
    exifStatus:
      "PASS · Pixel 8 Pro · Original sensor noise verified · Non-manipulated capture",
    policySignal:
      "Sets has_photo = true → Triggers wrong_item (100% refund_full; clamps at $50.00 cap on orders > $50)",
    modelName: "claude-3-5-sonnet-vision + settle-cv-v2",
    latencyMs: 385,
    imageSvgDataUri: TAMPER_WRONG_SIZE_SVG,
    boxes: [
      {
        id: "box-slip-spec",
        label: "PACKING_SLIP_OCR: 53.0mm (0.97)",
        confidence: 0.97,
        xPct: 9,
        yPct: 34,
        wPct: 31,
        hPct: 37,
        tone: "warning",
      },
      {
        id: "box-caliper",
        label: "CALIPER_GAUGE: 58.02mm (0.96)",
        confidence: 0.96,
        xPct: 53,
        yPct: 58,
        wPct: 24,
        hPct: 32,
        tone: "verified",
      },
    ],
  },
  {
    id: "parcel_crushed_transit",
    title: "Crushed Parcel & Punctured Coffee Bag",
    shortLabel: "Crushed Parcel & Bag (94%)",
    badgeText: "VERIFIED TRANSIT DAMAGE · 94%",
    verdict: "VERIFIED_TRANSIT_DAMAGE",
    authenticityScore: 94,
    passesPhotoRequirement: true,
    suggestedComplaint:
      "My shipping box arrived crushed and the whole-bean coffee bag inside was punctured open.",
    skuMatched: "Kopi & Clay 250g Single-Origin Valve Bag + Priority Shipper",
    defectSummary:
      "Severe outer carton compression + punctured food-grade valve bag with spilled whole beans.",
    exifStatus:
      "PASS · Original HEIC/JPEG capture · Delivery timestamp & carrier label verified",
    policySignal:
      "Sets has_photo = true → Satisfies visual evidence requirement for damaged item refund",
    modelName: "claude-3-5-sonnet-vision + settle-cv-v2",
    latencyMs: 360,
    imageSvgDataUri: PARCEL_CRUSHED_SVG,
    boxes: [
      {
        id: "box-carton-crush",
        label: "CARTON_CRUSH_ZONE (0.94)",
        confidence: 0.94,
        xPct: 34,
        yPct: 19,
        wPct: 21,
        hPct: 25,
        tone: "verified",
      },
      {
        id: "box-bag-puncture",
        label: "PRIMARY_SEAL_BREACH (0.92)",
        confidence: 0.92,
        xPct: 62,
        yPct: 52,
        wPct: 20,
        hPct: 35,
        tone: "verified",
      },
    ],
  },
  {
    id: "spoof_stock_photo",
    title: "Recycled Web Stock Photo (Spoof Test)",
    shortLabel: "Spoof / Web Stock Photo (14%)",
    badgeText: "SPOOF FLAGGED · 14%",
    verdict: "SPOOF_SUSPECTED",
    authenticityScore: 14,
    passesPhotoRequirement: false,
    suggestedComplaint:
      "My mug arrived completely shattered in the box, please send a full refund right now.",
    skuMatched:
      "MISMATCH · Generic white porcelain cup (does not match Kopi & Clay stoneware SKU)",
    defectSummary:
      "Reverse-image hash matches public stock catalog (SHUTTER-ID-99412); zero damage detected on cup.",
    exifStatus:
      "FAIL · Camera EXIF stripped · Web-scraped re-encoding signature detected",
    policySignal:
      "Sets has_photo = false → Blocks automatic photo-gated payout & routes to merchant review",
    modelName: "claude-3-5-sonnet-vision + settle-cv-v2",
    latencyMs: 290,
    imageSvgDataUri: SPOOF_STOCK_SVG,
    boxes: [
      {
        id: "box-watermark",
        label: "STOCK_WATERMARK_HIT (0.99)",
        confidence: 0.99,
        xPct: 12,
        yPct: 20,
        wPct: 76,
        hPct: 60,
        tone: "danger",
      },
      {
        id: "box-sku-mismatch",
        label: "SKU_GEOMETRY_MISMATCH (0.89)",
        confidence: 0.89,
        xPct: 38,
        yPct: 31,
        wPct: 26,
        hPct: 32,
        tone: "danger",
      },
    ],
  },
];

const STORAGE_KEY = "settle.vision_evidence.v1";

interface StoredEvidenceMap {
  byCaseId: Record<string, VisionEvidencePreset>;
  byOrderId: Record<string, VisionEvidencePreset>;
}

function readStore(): StoredEvidenceMap {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { byCaseId: {}, byOrderId: {} };
    const parsed = JSON.parse(raw) as Partial<StoredEvidenceMap>;
    return {
      byCaseId: parsed.byCaseId || {},
      byOrderId: parsed.byOrderId || {},
    };
  } catch {
    return { byCaseId: {}, byOrderId: {} };
  }
}

export function saveVisionEvidence(
  orderId: string,
  caseId: string | null,
  preset: VisionEvidencePreset,
): void {
  try {
    const store = readStore();
    if (orderId) {
      store.byOrderId[orderId] = preset;
    }
    if (caseId) {
      store.byCaseId[caseId] = preset;
    }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Ignore storage quota errors in restricted environments
  }
}

export function getVisionEvidenceForCase(
  caseId: string,
  orderId: string,
  category?: string,
  rawText?: string,
): VisionEvidencePreset {
  const store = readStore();
  if (caseId && store.byCaseId[caseId]) {
    return store.byCaseId[caseId];
  }
  if (orderId && store.byOrderId[orderId]) {
    return store.byOrderId[orderId];
  }
  const textLower = (rawText || "").toLowerCase();
  const catLower = (category || "").toLowerCase();
  if (
    catLower.includes("wrong") ||
    textLower.includes("wrong") ||
    textLower.includes("instead of") ||
    orderId === "ORDER-002" ||
    orderId === "ORDER-003" ||
    orderId === "ORDER-008"
  ) {
    return VISION_EVIDENCE_PRESETS[1];
  }
  if (
    textLower.includes("ignore your rules") ||
    textLower.includes("system:") ||
    textLower.includes("admin mode")
  ) {
    return VISION_EVIDENCE_PRESETS[3];
  }
  if (
    textLower.includes("box") ||
    textLower.includes("crush") ||
    textLower.includes("bag") ||
    textLower.includes("transit")
  ) {
    return VISION_EVIDENCE_PRESETS[2];
  }
  return VISION_EVIDENCE_PRESETS[0];
}

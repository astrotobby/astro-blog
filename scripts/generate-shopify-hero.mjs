import sharp from "sharp";
import { writeFileSync } from "fs";
import path from "path";

const W = 2400;
const H = 900;

// deterministic pseudo-random for reproducible layout
function mulberry32(seed) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(42);

// --- circuit trace generator (right 65% of canvas, sparse on the left) ---
function circuitPath(startX, startY, segments, step) {
  let x = startX;
  let y = startY;
  let d = `M ${x} ${y}`;
  const nodes = [];
  for (let i = 0; i < segments; i++) {
    const horizontal = rand() > 0.5;
    const dist = step * (0.5 + rand());
    if (horizontal) x += rand() > 0.5 ? dist : -dist;
    else y += rand() > 0.5 ? dist : -dist;
    x = Math.max(W * 0.32, Math.min(W - 40, x));
    y = Math.max(40, Math.min(H - 40, y));
    d += ` L ${x} ${y}`;
    if (rand() > 0.55) nodes.push([x, y]);
  }
  return { d, nodes };
}

let circuitPaths = "";
let circuitNodes = "";
for (let i = 0; i < 14; i++) {
  const startX = W * (0.34 + rand() * 0.6);
  const startY = rand() * H;
  const { d, nodes } = circuitPath(startX, startY, 5 + Math.floor(rand() * 4), 90);
  const color = rand() > 0.5 ? "#22d3ee" : "#a855f7";
  const op = (0.18 + rand() * 0.22).toFixed(2);
  circuitPaths += `<path d="${d}" stroke="${color}" stroke-width="2" fill="none" opacity="${op}" filter="url(#glow-soft)"/>`;
  for (const [nx, ny] of nodes) {
    const r = 2.5 + rand() * 3;
    circuitNodes += `<circle cx="${nx.toFixed(1)}" cy="${ny.toFixed(1)}" r="${r.toFixed(1)}" fill="${color}" opacity="${(0.4 + rand() * 0.4).toFixed(2)}" filter="url(#glow-soft)"/>`;
  }
}

// --- glass "product card" panels, right side ---
const cards = [
  { x: 1650, y: 150, w: 300, h: 190, icon: "chip" },
  { x: 1990, y: 400, w: 300, h: 190, icon: "bolt" },
  { x: 1620, y: 560, w: 280, h: 180, icon: "chart" },
];

function iconSvg(type, cx, cy) {
  const s = "#e0f2fe";
  if (type === "chip") {
    return `<g stroke="${s}" stroke-width="3" fill="none" opacity="0.85">
      <rect x="${cx - 26}" y="${cy - 26}" width="52" height="52" rx="6"/>
      <rect x="${cx - 12}" y="${cy - 12}" width="24" height="24" rx="3"/>
      <line x1="${cx - 26}" y1="${cy - 14}" x2="${cx - 38}" y2="${cy - 14}"/>
      <line x1="${cx - 26}" y1="${cy + 14}" x2="${cx - 38}" y2="${cy + 14}"/>
      <line x1="${cx + 26}" y1="${cy - 14}" x2="${cx + 38}" y2="${cy - 14}"/>
      <line x1="${cx + 26}" y1="${cy + 14}" x2="${cx + 38}" y2="${cy + 14}"/>
      <line x1="${cx - 14}" y1="${cy - 26}" x2="${cx - 14}" y2="${cy - 38}"/>
      <line x1="${cx + 14}" y1="${cy - 26}" x2="${cx + 14}" y2="${cy - 38}"/>
      <line x1="${cx - 14}" y1="${cy + 26}" x2="${cx - 14}" y2="${cy + 38}"/>
      <line x1="${cx + 14}" y1="${cy + 26}" x2="${cx + 14}" y2="${cy + 38}"/>
    </g>`;
  }
  if (type === "bolt") {
    return `<path d="M ${cx + 8} ${cy - 38} L ${cx - 22} ${cy + 6} L ${cx - 2} ${cy + 6} L ${cx - 10} ${cy + 38} L ${cx + 24} ${cy - 8} L ${cx + 4} ${cy - 8} Z"
      fill="#a855f7" opacity="0.85"/>`;
  }
  return `<g stroke="${s}" stroke-width="3" fill="none" opacity="0.85">
    <line x1="${cx - 30}" y1="${cy + 30}" x2="${cx + 30}" y2="${cy + 30}"/>
    <line x1="${cx - 30}" y1="${cy + 30}" x2="${cx - 30}" y2="${cy - 30}"/>
    <polyline points="${cx - 22},${cy + 10} ${cx - 4},${cy - 8} ${cx + 10},${cy + 4} ${cx + 26},${cy - 26}" stroke="#22d3ee"/>
  </g>`;
}

let cardsSvg = "";
for (const c of cards) {
  cardsSvg += `
  <rect x="${c.x}" y="${c.y}" width="${c.w}" height="${c.h}" rx="18"
    fill="url(#glass)" stroke="url(#cardBorder)" stroke-width="1.5"/>
  ${iconSvg(c.icon, c.x + c.w / 2, c.y + c.h / 2 - 10)}
  `;
}

// --- glow blobs (bokeh) ---
const blobs = [
  { cx: 2150, cy: 180, r: 260, color: "#22d3ee", op: 0.22 },
  { cx: 1750, cy: 700, r: 300, color: "#a855f7", op: 0.20 },
  { cx: 2300, cy: 650, r: 220, color: "#ec4899", op: 0.16 },
  { cx: 300, cy: 780, r: 320, color: "#1e3a8a", op: 0.35 },
];
let blobsSvg = "";
for (const b of blobs) {
  blobsSvg += `<circle cx="${b.cx}" cy="${b.cy}" r="${b.r}" fill="${b.color}" opacity="${b.op}" filter="url(#glow-strong)"/>`;
}

// --- perspective floor grid, bottom, fading ---
let gridSvg = "";
for (let i = -6; i <= 14; i++) {
  const xTop = 900 + i * 140;
  const xBot = 900 + i * 340;
  gridSvg += `<line x1="${xTop}" y1="${H * 0.55}" x2="${xBot}" y2="${H}" stroke="#22d3ee" stroke-width="1" opacity="0.10"/>`;
}
for (let j = 0; j < 6; j++) {
  const y = H * 0.55 + j * j * 9;
  gridSvg += `<line x1="0" y1="${y}" x2="${W}" y2="${y}" stroke="#22d3ee" stroke-width="1" opacity="${(0.05 + j * 0.01).toFixed(2)}"/>`;
}

// --- particle dust ---
let particles = "";
for (let i = 0; i < 70; i++) {
  const x = rand() * W;
  const y = rand() * H;
  const r = 0.6 + rand() * 1.8;
  const op = (0.15 + rand() * 0.5).toFixed(2);
  particles += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" fill="#bae6fd" opacity="${op}"/>`;
}

const svg = `
<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#060815"/>
      <stop offset="45%" stop-color="#0b1030"/>
      <stop offset="75%" stop-color="#1a0f3d"/>
      <stop offset="100%" stop-color="#05030c"/>
    </linearGradient>
    <linearGradient id="scrim" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#000000" stop-opacity="0.55"/>
      <stop offset="38%" stop-color="#000000" stop-opacity="0.28"/>
      <stop offset="70%" stop-color="#000000" stop-opacity="0.05"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="glass" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#93c5fd" stop-opacity="0.14"/>
      <stop offset="100%" stop-color="#a855f7" stop-opacity="0.06"/>
    </linearGradient>
    <linearGradient id="cardBorder" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#67e8f9" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="#c084fc" stop-opacity="0.35"/>
    </linearGradient>
    <filter id="glow-soft" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="2.2"/>
    </filter>
    <filter id="glow-strong" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="70"/>
    </filter>
    <radialGradient id="vignette" cx="50%" cy="45%" r="75%">
      <stop offset="55%" stop-color="#000000" stop-opacity="0"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0.45"/>
    </radialGradient>
  </defs>

  <rect width="${W}" height="${H}" fill="url(#bg)"/>
  ${gridSvg}
  ${blobsSvg}
  ${particles}
  ${circuitPaths}
  ${circuitNodes}
  ${cardsSvg}
  <rect width="${W}" height="${H}" fill="url(#scrim)"/>
  <rect width="${W}" height="${H}" fill="url(#vignette)"/>
</svg>
`;

const outSvg = path.resolve("scripts/.shopify-hero.svg");
writeFileSync(outSvg, svg, "utf-8");

const outJpg = path.resolve("scripts/.shopify-hero.jpg");
await sharp(Buffer.from(svg)).jpeg({ quality: 90 }).toFile(outJpg);

console.log("Written:", outJpg);

import sharp from "sharp";
import path from "path";

// One-off branded hero generator for the "Top 5 Digital Skills" article.
// Same visual language as generate-shopify-hero.mjs (deep space gradient,
// circuit traces, glass cards, bokeh) but with a left-aligned title block.
const W = 2400;
const H = 1260; // ~1.9:1, close to a 1200x630 social crop scaled up

function mulberry32(seed) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(2026);

function circuitPath(startX, startY, segments, step) {
  let x = startX, y = startY, d = `M ${x} ${y}`;
  const nodes = [];
  for (let i = 0; i < segments; i++) {
    const horizontal = rand() > 0.5;
    const dist = step * (0.5 + rand());
    if (horizontal) x += rand() > 0.5 ? dist : -dist;
    else y += rand() > 0.5 ? dist : -dist;
    x = Math.max(W * 0.5, Math.min(W - 40, x));
    y = Math.max(40, Math.min(H - 40, y));
    d += ` L ${x} ${y}`;
    if (rand() > 0.55) nodes.push([x, y]);
  }
  return { d, nodes };
}

let circuitPaths = "", circuitNodes = "";
for (let i = 0; i < 14; i++) {
  const startX = W * (0.52 + rand() * 0.45);
  const startY = rand() * H;
  const { d, nodes } = circuitPath(startX, startY, 5 + Math.floor(rand() * 4), 100);
  const color = rand() > 0.5 ? "#22d3ee" : "#a855f7";
  const op = (0.18 + rand() * 0.22).toFixed(2);
  circuitPaths += `<path d="${d}" stroke="${color}" stroke-width="2.5" fill="none" opacity="${op}" filter="url(#glow-soft)"/>`;
  for (const [nx, ny] of nodes) {
    const r = 2.5 + rand() * 3.5;
    circuitNodes += `<circle cx="${nx.toFixed(1)}" cy="${ny.toFixed(1)}" r="${r.toFixed(1)}" fill="${color}" opacity="${(0.4 + rand() * 0.4).toFixed(2)}" filter="url(#glow-soft)"/>`;
  }
}

const blobs = [
  { cx: 2050, cy: 240, r: 320, color: "#22d3ee", op: 0.22 },
  { cx: 1750, cy: 980, r: 360, color: "#a855f7", op: 0.20 },
  { cx: 2280, cy: 900, r: 260, color: "#ec4899", op: 0.16 },
  { cx: 260, cy: 1050, r: 380, color: "#1e3a8a", op: 0.35 },
];
let blobsSvg = "";
for (const b of blobs)
  blobsSvg += `<circle cx="${b.cx}" cy="${b.cy}" r="${b.r}" fill="${b.color}" opacity="${b.op}" filter="url(#glow-strong)"/>`;

let particles = "";
for (let i = 0; i < 80; i++) {
  const x = rand() * W, y = rand() * H, r = 0.6 + rand() * 1.9;
  particles += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" fill="#bae6fd" opacity="${(0.15 + rand() * 0.5).toFixed(2)}"/>`;
}

// big numeral "5" watermark on the right
const bigFive = `<text x="1980" y="900" font-family="Georgia, 'Times New Roman', serif" font-size="760" font-weight="700" fill="#67e8f9" opacity="0.10">5</text>`;

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
      <stop offset="0%" stop-color="#000000" stop-opacity="0.60"/>
      <stop offset="42%" stop-color="#000000" stop-opacity="0.30"/>
      <stop offset="72%" stop-color="#000000" stop-opacity="0.05"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#22d3ee"/>
      <stop offset="100%" stop-color="#a855f7"/>
    </linearGradient>
    <filter id="glow-soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4"/></filter>
    <filter id="glow-strong" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="80"/></filter>
    <radialGradient id="vignette" cx="50%" cy="45%" r="75%">
      <stop offset="55%" stop-color="#000000" stop-opacity="0"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0.45"/>
    </radialGradient>
  </defs>

  <rect width="${W}" height="${H}" fill="url(#bg)"/>
  ${blobsSvg}
  ${particles}
  ${bigFive}
  ${circuitPaths}
  ${circuitNodes}
  <rect width="${W}" height="${H}" fill="url(#scrim)"/>
  <rect width="${W}" height="${H}" fill="url(#vignette)"/>

  <text x="150" y="330" font-family="Arial, Helvetica, sans-serif" font-size="40" letter-spacing="8" fill="#7dd3fc">ASTRO SIGNAL &#183; 2026 SKILLS GUIDE</text>
  <text x="146" y="520" font-family="Georgia, 'Times New Roman', serif" font-size="150" font-weight="700" fill="#ffffff">Top 5 Digital Skills</text>
  <text x="150" y="680" font-family="Georgia, 'Times New Roman', serif" font-size="150" font-weight="700" fill="#ffffff">Worth Learning in 2026</text>
  <rect x="152" y="760" width="220" height="10" rx="5" fill="url(#accent)"/>
  <text x="150" y="880" font-family="Arial, Helvetica, sans-serif" font-size="52" fill="#c7d2fe">The skills that save you decades of hard work</text>
</svg>
`;

const outJpg = path.resolve("public/top-5-digital-skills-2026.jpg");
await sharp(Buffer.from(svg)).jpeg({ quality: 86, mozjpeg: true }).toFile(outJpg);
console.log("Written:", outJpg);

// Shared hero-image logic for posts.
// External image services proved unreliable (pollinations.ai -> HTTP 402 paywall,
// loremflickr -> very slow). Strategy: honour a real frontmatter image, otherwise
// render an INSTANT inline-SVG gradient "topic card" (a data URI, zero network).

const STOPWORDS = new Set([
  'the','a','an','to','of','in','for','and','or','is','are','on','with','as','at','by','from',
  'how','why','what','this','that','its','it','vs','new','up','out','over','under','your','our',
  'we','will','can','do','does','no','not','but','if','into','after','before','amid','despite',
  'more','than','get','gets','their','his','her','you','about',
]);

function keywordOf(title: string): string {
  const clean = (title || '')
    .toLowerCase()
    .replace(/['’]s\b/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
  const word = clean.split(' ').filter((w) => w && !STOPWORDS.has(w))[0] || 'signal';
  return word.charAt(0).toUpperCase() + word.slice(1);
}

/** Instant, dependency-free gradient card as a data: URI. */
export function svgFallback(title: string): string {
  const label = keywordOf(title);
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">` +
    `<defs>` +
    `<linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0" stop-color="#6366F1"/>` +
    `<stop offset="0.5" stop-color="#8B5CF6"/>` +
    `<stop offset="1" stop-color="#0F1222"/>` +
    `</linearGradient>` +
    `<radialGradient id="glow" cx="0.8" cy="0.15" r="0.7">` +
    `<stop offset="0" stop-color="#EC4899" stop-opacity="0.55"/>` +
    `<stop offset="1" stop-color="#EC4899" stop-opacity="0"/>` +
    `</radialGradient>` +
    `</defs>` +
    `<rect width="1280" height="720" fill="url(#g)"/>` +
    `<rect width="1280" height="720" fill="url(#glow)"/>` +
    `<text x="80" y="120" font-family="Arial, Helvetica, sans-serif" font-size="28" letter-spacing="3" fill="#C7D2FE">ASTRO TOBBY&#39;S BLUEPRINT</text>` +
    `<text x="80" y="440" font-family="Georgia, serif" font-size="104" font-weight="700" fill="#FFFFFF">${label}</text>` +
    `<rect x="80" y="500" width="120" height="6" rx="3" fill="#EC4899"/>` +
    `</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/** The image to actually display for a post. */
export function displayImage(title: string, image?: string | null): string {
  const real = image && !/(pollinations\.ai|loremflickr\.com)/.test(image) ? image : null;
  return real || svgFallback(title);
}

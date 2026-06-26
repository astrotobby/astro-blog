#!/usr/bin/env node
/**
 * repurpose.mjs (in-repo) — turn every blog post into a free-distribution social pack.
 *
 * Mirrors growth-engine/repurpose.mjs but runs INSIDE the astro-blog repo so the
 * GitHub Action (.github/workflows/repurpose-content.yml) can regenerate packs and
 * commit them back on every content push. Zero dependencies.
 *
 * Reads:  src/content/blog/*.md
 * Writes: social-packs/<slug>.md   (not served by Astro — just versioned assets)
 *
 * Usage:  node scripts/repurpose.mjs --all
 *         node scripts/repurpose.mjs <path-to-post.md> ["Clean Title Override"]
 */
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from 'node:fs';
import { join, basename, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO = join(__dirname, '..');
const BLOG_DIR = join(REPO, 'src', 'content', 'blog');
const OUT_DIR = join(REPO, 'social-packs');
const SITE = 'https://astrotobby.site';

const PRODUCTS = {
  aeo:       { name: 'AEO Masterguide 2026', price: '$14' },
  seo:       { name: 'AEO Masterguide 2026', price: '$14' },
  search:    { name: 'AEO Masterguide 2026', price: '$14' },
  automation:{ name: 'Make.com Autoblogging Blueprint 2026', price: '$22' },
  make:      { name: 'Make.com Autoblogging Blueprint 2026', price: '$22' },
  pipeline:  { name: 'AI Agent Automation Pipeline Pack', price: '$19' },
  agent:     { name: 'Agentic AI Workflow Pack 2026', price: '$32' },
  agentic:   { name: 'Agentic AI Workflow Pack 2026', price: '$32' },
  prompt:    { name: 'AI Prompt Vault 2026', price: '$12' },
  video:     { name: 'AI Prompt Vault 2026', price: '$12' },
  coding:    { name: 'The Agentic Coding Playbook', price: '$12' },
};
const DEFAULT_PRODUCT = { name: 'the full toolkit', price: '' };

function stripTags(s) {
  return s.replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&')
          .replace(/&#39;|&rsquo;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, ' ').trim();
}

function parse(file) {
  const raw = readFileSync(file, 'utf8');
  const fm = raw.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  const front = {};
  if (fm) for (const line of fm[1].split(/\r?\n/)) {
    const m = line.match(/^(\w+):\s*(.*)$/);
    if (m) front[m[1]] = m[2].replace(/^['"]|['"]$/g, '').trim();
  }
  const body = raw.slice(fm ? fm[0].length : 0);
  const headings = [...body.matchAll(/<h[23][^>]*>([\s\S]*?)<\/h[23]>/gi)]
    .map(h => stripTags(h[1])).filter(Boolean);
  const firstPara = stripTags((body.match(/<p[^>]*>([\s\S]*?)<\/p>/i)?.[1]) || body).slice(0, 320);
  const tags = (front.tags || '').replace(/[\[\]]/g, '').split(',').map(t => t.trim().toLowerCase()).filter(Boolean);
  return { front, headings, firstPara, tags };
}

function pickProduct(title, tags) {
  const hay = (title + ' ' + tags.join(' ')).toLowerCase();
  for (const key of Object.keys(PRODUCTS)) if (hay.includes(key)) return PRODUCTS[key];
  return DEFAULT_PRODUCT;
}

function cleanTitle(t) {
  return t.replace(/\s+/g, ' ').replace(/\s+[a-z]$/i, '').trim();
}

function pack(file, titleOverride) {
  const { front, headings, firstPara, tags } = parse(file);
  const title = cleanTitle(titleOverride || front.title || basename(file));
  const slug = basename(file).replace(/\.mdx?$/, '');
  const url = `${SITE}/blog/${slug}/`;
  const prod = pickProduct(title, tags);
  const buy = `${SITE}/products`;
  const pts = headings.slice(0, 7);

  const thread = [
    `🧵 ${title}\n\nWhat most people get wrong (and the 2026 fix) 👇`,
    ...pts.map((h, i) => `${i + 1}. ${h}\n\n${i === 0 ? firstPara.slice(0, 180) : 'The key: ' + h.toLowerCase() + ' is where the leverage is.'}`),
    `That's the short version.\n\nFull breakdown (with examples): ${url}`,
    `If you'd rather skip the work, ${prod.name}${prod.price ? ` (${prod.price})` : ''} does it for you → ${buy}`,
  ].join('\n\n—\n\n');

  return `# Social Pack — ${title}

> Source: ${url}
> Matched product: **${prod.name}** ${prod.price} → ${buy}
> Tags: ${tags.join(', ') || '—'}

---

## YouTube (for the blog-to-video pipeline)
**Title options**
- ${title} (2026)
- The truth about ${title.toLowerCase()} nobody tells you
- ${title} — explained in 60 seconds

**Description**
${firstPara}

🔗 Full article: ${url}
🛠️ Get ${prod.name}${prod.price ? ` (${prod.price})` : ''}: ${buy}
#AI #automation #2026

---

## TikTok / Reels / Shorts hook (first 3 seconds)
"Here's what nobody tells you about ${title.toLowerCase()}…"
Caption: ${title} — full guide in bio. ${prod.name} linked too. #ai #tech #2026 #automation

---

## Instagram caption
${title} 👇

${pts.slice(0, 3).map(p => `• ${p}`).join('\n')}

Full breakdown on the blog (link in bio). Want the done-for-you version? ${prod.name} ${prod.price}.

---

## Facebook post
${firstPara.slice(0, 200)}…

I broke the whole thing down here 👉 ${url}
(If you want the shortcut, ${prod.name} is ${prod.price}.)

---

## X / Twitter thread
${thread}

---

## Pinterest text overlay
"${title}" — save this for later. Full 2026 guide → astrotobby.site

---

## Reddit / Quora seed answer (give value FIRST, link last)
Genuinely useful 120–150 word answer to a real thread about "${tags[0] || 'this topic'}".
Draft: ${firstPara.slice(0, 220)}…
Only if it truly helps the asker, end with: "I wrote a fuller breakdown here: ${url}".

---

## ✨ AI-refine prompt (paste into Claude/ChatGPT to polish any section)
"You are a direct-response social copywriter. Rewrite the [SECTION] above for [PLATFORM].
Keep it specific, lead with a hook, one idea per line, end with a soft CTA to ${url}.
Match an audience of people searching for help with ${tags.join(', ') || title.toLowerCase()}."
`;
}

function run() {
  mkdirSync(OUT_DIR, { recursive: true });
  const args = process.argv.slice(2);
  if (args[0] === '--all' || !args[0]) {
    const files = readdirSync(BLOG_DIR).filter(f => /\.mdx?$/.test(f));
    for (const f of files) writeFileSync(join(OUT_DIR, f.replace(/\.mdx?$/, '.md')), pack(join(BLOG_DIR, f)));
    console.log(`Wrote ${files.length} social packs to social-packs/`);
    return;
  }
  const file = args[0];
  writeFileSync(join(OUT_DIR, basename(file).replace(/\.mdx?$/, '.md')), pack(file, args[1]));
  console.log(`Wrote social pack for ${basename(file)}`);
}
run();

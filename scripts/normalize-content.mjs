// Build-time SEO normalizer — runs after sanitize-frontmatter, before astro build.
// Makes every post (especially raw autoblogger output) competitive without manual work:
//   1. Fills an empty/missing `description` with a clean ~155-char meta summary
//      derived from the body — empty meta descriptions kill CTR and AI citation.
//   2. Derives `tags` when missing so the in-article product CTA + store grid can
//      match the right product to the post (tagless posts otherwise mis-match).
//   3. Collapses the double-spaces that the autoblogger leaves where it stripped
//      punctuation from titles ("The  Ghost   Why..." -> "The Ghost Why...").
// Never touches slug/date/pubDate (those URLs are indexed). Idempotent. Never throws.
import fs from 'node:fs';
import path from 'node:path';

const DIR = 'src/content/blog';

// keyword (lowercased, word-ish) -> canonical tag. Order matters for relevance.
const TAG_RULES = [
  ['answer engine', 'aeo'], ['aeo', 'aeo'], ['perplexity', 'aeo'], ['ai overview', 'aeo'],
  ['seo', 'seo'], ['search engine', 'seo'], ['ranking', 'seo'],
  ['make.com', 'make'], ['autoblog', 'automation'], ['automation', 'automation'],
  ['n8n', 'pipeline'], ['pipeline', 'pipeline'], ['workflow', 'automation'],
  ['multi-agent', 'agent'], ['agentic', 'agentic'], ['ai agent', 'agent'], ['agent', 'agent'],
  ['prompt', 'prompt'], ['llm', 'llm'], ['gpt', 'llm'], ['claude', 'llm'], ['gemini', 'llm'],
  ['video', 'video'], ['capcut', 'video'], ['sora', 'video'], ['runway', 'video'],
  ['coding', 'coding'], ['code', 'coding'], ['developer', 'coding'], ['vibe coding', 'coding'],
  ['crypto', 'crypto'], ['bitcoin', 'crypto'], ['ethereum', 'crypto'],
  ['email marketing', 'marketing'], ['marketing', 'marketing'],
  ['nvidia', 'hardware'], ['apple', 'tech'], ['google', 'tech'], ['meta', 'tech'],
];

function stripTags(s) {
  return s
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&')
    .replace(/&#39;|&rsquo;|&lsquo;/g, "'").replace(/&quot;|&ldquo;|&rdquo;/g, '"')
    .replace(/&[a-z]+;/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function makeDescription(body) {
  // Drop the affiliate-disclaimer boilerplate and any leading markdown emphasis.
  const cleaned = body
    .replace(/\*[^*]*affiliate links[^*]*\*/gi, ' ')
    .replace(/^[\s\-*#>]+/, ' ');
  let text = stripTags(cleaned);
  // Autoblogger sometimes opens the body with a "SEO Title | ASTROSIGNAL" line and a
  // stuffed keyword list. Drop everything up to/including the brand marker if it's near
  // the start, so the description begins at the real first sentence.
  const brand = text.search(/ASTRO\s*SIGNAL/i);
  if (brand !== -1 && brand < 130) text = text.slice(brand).replace(/^ASTRO\s*SIGNAL[\s|:–—-]*/i, '');
  if (text.length < 40) return '';
  if (text.length <= 158) return text;
  // Cut at the last word boundary before 158 chars, prefer ending on a sentence.
  let slice = text.slice(0, 158);
  const lastStop = Math.max(slice.lastIndexOf('. '), slice.lastIndexOf('? '), slice.lastIndexOf('! '));
  if (lastStop > 90) return slice.slice(0, lastStop + 1).trim();
  return slice.slice(0, slice.lastIndexOf(' ')).trim() + '…';
}

function deriveTags(title, body) {
  const hay = (title + ' ' + stripTags(body).slice(0, 1200)).toLowerCase();
  const out = [];
  for (const [kw, tag] of TAG_RULES) {
    if (hay.includes(kw) && !out.includes(tag)) out.push(tag);
    if (out.length >= 5) break;
  }
  if (!out.includes('ai') && /\bai\b|artificial intelligence/.test(hay)) out.unshift('ai');
  return out.length ? out : ['ai'];
}

function getField(fm, key) {
  const m = fm.match(new RegExp(`^${key}:\\s*(.*)$`, 'm'));
  return m ? m[1].trim() : null;
}

let fixed = 0;
try {
  if (fs.existsSync(DIR)) {
    for (const name of fs.readdirSync(DIR)) {
      if (!/\.(md|mdx)$/i.test(name)) continue;
      const fp = path.join(DIR, name);
      try {
        const txt = fs.readFileSync(fp, 'utf8');
        const m = txt.match(/^---\r?\n([\s\S]*?)\r?\n---/);
        if (!m) continue;
        let fm = m[1];
        const body = txt.slice(m[0].length);
        const before = fm;

        // 1. Title: collapse runs of whitespace (autoblogger punctuation stripping).
        fm = fm.replace(/^(title:\s*)(.*)$/m, (w, k, v) => k + v.replace(/\s{2,}/g, ' ').trimEnd());

        // 2. Description: fill when empty or missing.
        const desc = getField(fm, 'description');
        const descEmpty = desc === null || desc === "''" || desc === '""' || desc === ''
          || /ASTRO\s*SIGNAL/i.test(desc || '');   // self-heal earlier brand-leak descriptions
        if (descEmpty) {
          const generated = makeDescription(body).replace(/"/g, "'");
          if (generated) {
            const line = `description: "${generated}"`;
            fm = /^description:\s*.*$/m.test(fm)
              ? fm.replace(/^description:\s*.*$/m, line)
              : fm + `\n${line}`;
          }
        }

        // 3. Tags: derive when missing entirely.
        if (!/^tags:/m.test(fm)) {
          const title = (getField(fm, 'title') || name).replace(/^["']|["']$/g, '');
          const tags = deriveTags(title, body);
          fm = fm + `\ntags: [${tags.map((t) => JSON.stringify(t)).join(', ')}]`;
        }

        if (fm !== before) {
          fs.writeFileSync(fp, txt.replace(before, fm), 'utf8');
          fixed++;
          console.log('[normalize] improved', name);
        }
      } catch (e) {
        console.log('[normalize] skip', name, '-', e.message);
      }
    }
  }
  console.log(`[normalize] done; ${fixed} file(s) improved`);
} catch (e) {
  console.log('[normalize] non-fatal error:', e.message);
}
process.exit(0);

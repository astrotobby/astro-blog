// Build-time safety net: repair malformed frontmatter in blog posts BEFORE
// `astro build`, so one bad autoblogger post can't break the whole site build/deploy.
//
// Primary target: the recurring malformed inline `tags` array, e.g.
//   tags: ["AI,""machine learning,""open source"]   (invalid YAML -> build crash)
// It rewrites that line to a clean array: ["AI", "machine learning", "open source"].
// Idempotent (valid lines are left unchanged) and never throws (a sanitizer bug must
// never be what breaks the build). Fixes are in-place on the build's working copy.
import fs from 'node:fs';
import path from 'node:path';

const DIR = 'src/content/blog';
let fixed = 0;

function repairTags(fm) {
  // Only the inline form `tags: [ ... ]` on a single line.
  return fm.replace(/^(\s*tags:\s*)\[(.*)\]\s*$/m, (whole, key, inner) => {
    const items = inner
      .replace(/["']/g, '')      // drop all quotes (handles the broken ,"" quoting)
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const rebuilt = '[' + items.map((s) => JSON.stringify(s)).join(', ') + ']';
    return key + rebuilt;
  });
}

try {
  if (fs.existsSync(DIR)) {
    for (const name of fs.readdirSync(DIR)) {
      if (!/\.(md|mdx)$/i.test(name)) continue;
      const fp = path.join(DIR, name);
      try {
        const txt = fs.readFileSync(fp, 'utf8');
        const m = txt.match(/^---\r?\n([\s\S]*?)\r?\n---/);
        if (!m) continue;
        const fm = m[1];
        const newFm = repairTags(fm);
        if (newFm !== fm) {
          fs.writeFileSync(fp, txt.replace(fm, newFm), 'utf8');
          fixed++;
          console.log('[sanitize] repaired tags in', name);
        }
      } catch (e) {
        console.log('[sanitize] skip', name, '-', e.message);
      }
    }
  }
  console.log(`[sanitize] done; ${fixed} file(s) repaired`);
} catch (e) {
  console.log('[sanitize] non-fatal error:', e.message);
}
process.exit(0);   // never fail the build because of the sanitizer

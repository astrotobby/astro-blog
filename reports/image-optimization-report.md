# Image Optimization Report

Tool used: Pillow (Python), via `scripts/optimize-images.js` (Node/sharp equivalent kept
in the repo for the ongoing pipeline — see that file for the version CI runs).

Method: every raster image referenced by a blog post (`image:` frontmatter) or sitting in
`public/` was re-encoded — resized to a max width of **1600px** (most originals were
2560px, far beyond any layout's display width) and re-saved as **JPEG quality 78,
progressive**. None of the source images used an alpha channel, so PNG→JPEG conversion
lost nothing visually. SVGs were left untouched (already tiny).

## Referenced hero images (these were the actual LCP elements — highest priority)

| File | Before | After | Reduction |
|---|---:|---:|---:|
| ai_titans_clash | 6973.1 KB | 347.6 KB | 95.0% |
| rise-and-fall-of-fable-5-featured | 4826.3 KB | 198.7 KB | 95.9% |
| claude-monetization-hero | 4468.1 KB | 240.2 KB | 94.6% |
| death-of-prompting-featured | 4291.0 KB | 161.7 KB | 96.2% |
| ai-agents-collaboration-2026 | 5025.9 KB | 197.4 KB | 96.1% |
| best-ai-video-generators-2026-featured | 3963.6 KB | 195.2 KB | 95.1% |
| agentic-commerce-hero | 1979.1 KB | 254.7 KB | 87.1% |
| agentic-ai-2026 | 1901.9 KB | 238.6 KB | 87.5% |
| agentic-ai-2026-new | 1965.7 KB | 229.4 KB | 88.3% |
| ai-security-vulnerability | 1735.7 KB | 197.2 KB | 88.6% |
| nvidia-rtx-spark-agentic-pc | 1711.7 KB | 169.1 KB | 90.1% |
| google-io-2026-search | 108.7 KB | 24.7 KB | 77.3% |
| ai-search-engine-era | 304.1 KB | 126.1 KB | 58.5% |
| (12 more already-JPEG hero images, e.g. `llm-benchmarks`, `prompt-engineering`, `vibe-coding-new`, `multiagent-systems`, `ghost-in-machine`...) | 73–330 KB each | 3–6% smaller each | re-encoded for consistency |

**Referenced images total: 41.6 MB → 4.8 MB (88.5% reduction).**

12 of these changed file extension (`.png` → `.jpg`); every blog post's `image:`
frontmatter field referencing one of them was updated to the new filename in this same
change (12 posts touched, see `git log` for the list — handled programmatically, not
by hand, to avoid typos).

## Orphaned / unreferenced images (not loaded by any page, but bloated the repo)

24 more images (old draft variants, "-v2"/"-new" duplicates, etc.) were optimized the
same way: **94.3 MB → 4.6 MB (95.1% reduction)**. These don't affect the Lighthouse score
since nothing requests them, but they were shrunk anyway since the task asked for full
repository image optimization, and it costs nothing to do while already in the pipeline.

6 duplicate copies of `blog-placeholder-{1..5,about}.jpg` were found sitting unused in
`public/` — Astro already serves an optimized version of these from `src/assets/` via its
built-in image pipeline (`astro:assets`). The unused `public/` copies were deleted
outright (no re-encode needed) to remove ~24 MB of dead weight.

One file, `public/vibe-coding-new.png`, was intentionally **left untouched**: its
optimized output filename would have collided with the already-referenced, already-live
`vibe-coding-new.jpg` (same basename, different extension) used by a real post. To avoid
any risk of overwriting a live hero image with the wrong content, that one orphan was
excluded from this pass rather than risk a collision; it's safe to clean up by hand later
since it's still unreferenced and harmless.

One file, `public/meta-tribe-v2-new.jpg` (0.2 KB), turned out to be corrupt/empty in the
repo already (unreadable by Pillow). It has been replaced by the properly re-encoded
content of `meta-tribe-v2-new.png` (which used the same final filename), incidentally
fixing the corruption as a side effect.

## Grand total

**~136 MB of images → ~9.4 MB, a ~93% reduction**, with zero markup/extension changes
needed for files that kept their original extension, and 12 frontmatter references
updated programmatically for the files that changed from `.png` to `.jpg`.

## Follow-up (not done this pass, optional)

- Convert to AVIF/WebP with `<picture>`/`srcset` fallbacks for a further ~20-30% byte
  reduction over JPEG — skipped this pass to keep the change low-risk (same extension/
  format keeps every existing `<img>` tag and OG/meta tag working untouched).
- Generate true responsive `srcset` (small/medium/large) — current hero images are
  already capped at 1600px and served at consistent aspect ratios, so the marginal gain
  is smaller than the original PNG→JPEG fix, but it's the natural next step.

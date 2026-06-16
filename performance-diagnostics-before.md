# Performance Diagnostics — Before Optimization

Date: 2026-06-17
Site: https://astrotobby.site/ (Astro 6 + `@astrojs/cloudflare`, deployed on Cloudflare Pages)

## How this was gathered

The Google PageSpeed Insights API (`pagespeedonline/v5`) returned `429` (quota exhausted)
for every attempt from this environment, so a live Lighthouse run could not be captured
this session. Diagnostics below are from direct inspection instead: `curl` against the
live edge (headers, sizes, TTFB), the rendered homepage HTML, and the actual repo source
(`git/trees` + `raw.githubusercontent.com` via the GitHub REST API, since plain `git`
clone/fetch of this repo times out in this environment — see project memory).

**If you want an official before/after Lighthouse score**, run:
`https://pagespeed.web.dev/analysis?url=https://astrotobby.site` manually, or re-run the
API call later once the public quota resets.

## Headline finding: image payload was the dominant problem

`public/` contained **~156 MB of images**, many of them **raw AI-generated PNG/JPEG
hero images at 1.7 MB–7 MB each**, used directly as blog-post hero images and Open
Graph images with no resizing or compression:

| Image (referenced live) | Original size |
|---|---|
| `ai_titans_clash.png` | 6.97 MB |
| `rise-and-fall-of-fable-5-featured.png` | 4.83 MB |
| `claude-monetization-hero.png` | 4.47 MB |
| `death-of-prompting-featured.png` | 4.29 MB |
| `ai-agents-collaboration-2026.png` | 5.03 MB |
| `best-ai-video-generators-2026-featured.png` | 3.96 MB |
| `agentic-ai-2026.png` / `-new.png` | ~1.9 MB each |
| `agentic-commerce-hero.png` | 1.98 MB |
| `ai-security-vulnerability.png` | 1.74 MB |
| `nvidia-rtx-spark-agentic-pc.png` | 1.71 MB |

Every one of these is the **LCP element** on its respective blog post page (the hero
image, `fetchpriority="high"`, top of viewport). On mobile network throughput, a single
5–7 MB LCP image is enough by itself to blow the "Largest Contentful Paint" and "Total
byte weight" audits and tank the Performance score — this is almost certainly the
majority of the gap between 65 and 90+.

An additional ~94 MB lived in unreferenced/orphaned images (old drafts, "-v2"/"-new"
duplicate variants, and 6 duplicate copies of `blog-placeholder-*.jpg` that Astro already
serves an optimized version of from `src/assets/`). These don't directly hurt the
Lighthouse run (nothing requests them), but they bloat the repo and were cleaned up too.

## Secondary findings

- **Homepage LCP image was lazy-loaded.** The "Featured Insight" card — the largest
  above-the-fold element on `/` — had `loading="lazy"` with no `width`/`height`, which
  both delays LCP (browser preload scanner skips lazy images) and risks CLS.
  (`src/pages/index.astro`, featured-card `<img>`.)
- **No `preconnect` to `images.pexels.com`**, which is where featured/recent post images
  are actually served from at runtime (Pexels API, see `[[project-astro-autoblog]]`)
  — every such image pays a fresh DNS+TLS handshake.
- **`public/_headers` had security headers but no `Cache-Control` for static assets**
  (images, fonts, `/_astro/*` build output) — repeat views and CDN edge caching weren't
  using long-lived immutable caching.
- **CSS**: two render-blocking stylesheets, `Header.*.css` (15.6 KB) and `index.*.css`
  (7.4 KB) — both already Astro-scoped/minified build output, not bloated by hand-written
  unused rules; left as-is.
- **JS**: already in good shape — AdSense loads `async`, Metricool tracker injects
  itself off the critical path, the only inline scripts are small (aurora background +
  scroll-reveal, nav toggle, reading-progress bar). No action needed here.
- **Fonts**: Google Fonts already loaded via the non-blocking
  `media="print" onload="this.media='all'"` trick with `preconnect`/`dns-prefetch` —
  already avoiding render-blocking. Self-hosting would save one more DNS+TLS round trip
  but wasn't done this pass (lower priority than the image fix); listed as a follow-up.
- **Response**: `CF-Cache-Status: HIT`, `Content-Encoding: zstd` — Cloudflare edge caching
  and compression were already working correctly for the HTML document itself.

## What was fixed this session

See `reports/image-optimization-report.md` for the full before/after numbers. Summary:
**~136 MB of images reduced to ~9.4 MB (≈93% reduction)** by resizing to max 1600px
width and re-encoding as JPEG quality 78; homepage LCP image un-lazied + given
`fetchpriority="high"`; `preconnect` added for Pexels; `_headers` given long-lived
immutable caching for static assets.

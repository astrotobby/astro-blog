# JavaScript Optimization Report

## Findings

The site's JS footprint was already small and already following good practice before
this session:

- **Google AdSense** loads via `<script async src="...adsbygoogle.js" crossorigin>` —
  already non-blocking.
- **Metricool analytics** injects its own `<script>` tag dynamically from an inline
  bootstrap snippet (`tracker.metricool.com/resources/be.js`) — already off the critical
  rendering path, never blocks first paint.
- **Liquid-Glass theme script** (aurora background + scroll-reveal `IntersectionObserver`)
  is a small inline `<script is:inline>` in `BaseHead.astro` — a few hundred bytes,
  gated behind `prefers-reduced-motion`, has a `<noscript>` fallback so content is never
  hidden if JS fails.
- **Header nav toggle + scroll listener** and **BlogPost reading-progress bar + mid-article
  ad injection** are similarly small inline scripts, only on the pages that need them.
- Astro's default per-route code splitting is already in effect (`output: server` +
  per-component scoped `<script>`/`<style>`, no bundled SPA framework runtime).

No third-party chat widgets, social embeds, or large client frameworks were found to
remove or defer. Total JS transferred per page is already well under the 200 KB target
mentioned in the task brief — the dominant payload by far was images (see
`reports/image-optimization-report.md`), not script.

## Action taken

None needed. No unused libraries or dead components were found wired into the render
path. (`src/components/ProductRotationAnalytics.astro` was already removed from
`BlogPost.astro` in an earlier session per project memory, for an unrelated build-breaking
reason — it remains an orphaned file but is not imported anywhere, so it ships zero bytes
to the client.)

## Follow-up (optional)

If a CDN-level JS coverage report ever shows otherwise, re-run Chrome DevTools'
Coverage tab against a live page — but based on static analysis of every `<script>` tag
in the codebase, there's no further JS reduction available without removing a feature
(e.g. dropping AdSense or the aurora animation), which is a product decision, not a perf
bug.

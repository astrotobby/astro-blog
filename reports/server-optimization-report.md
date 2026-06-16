# Server & Response Optimization Report

## Findings (before)

- Cloudflare Pages, `CF-Cache-Status: HIT`, `Content-Encoding: zstd` — the HTML document
  itself was already edge-cached and compressed correctly.
- `public/_headers` set a solid set of security headers (CSP-report-only, HSTS, frame
  options, etc.) but had **no `Cache-Control` rules for static assets at all** — images,
  fonts, and `/_astro/*` build output were falling back to Cloudflare Pages' default
  asset caching rather than an explicit long-lived immutable policy.
- Relevant static pages already use `export const prerender = true` (homepage, blog
  index, about/contact/privacy) per a prior optimization pass — confirmed still in place.

## Action taken

Added to `public/_headers`:

```
/_astro/*
  Cache-Control: public, max-age=31536000, immutable

/*.jpg / /*.jpeg / /*.png / /*.webp / /*.svg
  Cache-Control: public, max-age=31536000, immutable

/fonts/*
  Cache-Control: public, max-age=31536000, immutable

/favicon.ico
  Cache-Control: public, max-age=31536000, immutable
```

All of these are either content-hashed build output (`/_astro/*`, safe to cache forever)
or images that are immutable once published (a post's hero image doesn't change URL when
its content changes — the autoblogger writes new files, it doesn't overwrite old ones).

## Preconnect added

`<link rel="preconnect">` + `dns-prefetch` for `https://images.pexels.com`, the CDN that
serves featured/recent-post images at runtime (the autoblogger's live image source —
see project memory `project-astro-autoblog.md`). This was missing; every such image was
paying a full DNS+TLS handshake with no early hint.

## Not changed

`output: "server"` in `astro.config.mjs` and the Cloudflare adapter were left as-is —
this is a deliberate architectural choice (the site has SSR API routes: `/api/subscribe`,
`/api/chat`, `/api/shopify-products`, plus Shopify product pages) and isn't something to
flip without breaking those features. Static pages already opt into prerendering
individually where it's safe to do so.

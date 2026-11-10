# Font Optimization Report

## Findings

Fonts are loaded from Google Fonts (`Inter` 400/500/600/700/800 + `Charter`) via:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="dns-prefetch" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="...css2?family=..." media="print" onload="this.media='all'">
<noscript><link rel="stylesheet" href="...css2?family=..."></noscript>
```

This is already the standard "non-blocking Google Fonts" pattern: the stylesheet is
fetched with low priority (`media="print"`) and swapped to `all` once loaded, so it
never blocks rendering, and `preconnect` hides the DNS/TLS cost. This was already in
place from a prior optimization pass (see project memory, "Perf pass 2").

There's also a separately self-hosted pair of woff fonts already in the repo
(`src/assets/fonts/atkinson-{regular,bold}.woff`) — these appear to be leftover from the
original Astro starter template and are not referenced by the current Liquid-Glass theme
(`global.css` only references `Inter`/`Charter`). They ship 0 bytes to users since nothing
`@font-face`s them, so no action was needed there either.

## Action taken

None — the current approach is already close to optimal for a Google-Fonts-based setup.

## Follow-up (optional, bigger lift)

Fully self-hosting `Inter`+`Charter` (downloading, Latin-subsetting, converting to
`woff2`, serving from `/fonts/`) would remove the remaining two cross-origin round trips
(`fonts.googleapis.com` CSS fetch + `fonts.gstatic.com` font file fetch) entirely. This is
a real, available win, but it's a larger, riskier change (new files to maintain, subsetting
tooling, `@font-face` declarations to get exactly right) relative to its payoff once the
non-blocking pattern is already in place — deprioritized this pass in favor of the image
fix, which was ~1000x larger in absolute bytes saved. Worth doing in a follow-up PR if
chasing the last few PSI points.

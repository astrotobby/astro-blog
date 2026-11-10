# CSS Optimization Report

## Findings

Total CSS payload on a typical page: `Header.*.css` (15.7 KB) + `index.*.css`/per-route
CSS (7.4 KB) + a small inline `<style>` block for the newsletter section (~3.4 KB,
embedded directly in `index.astro`'s frontmatter-scoped styles) ≈ **26 KB total**,
already at the low end of the task's 10–30 KB target band.

This is Astro's own scoped-CSS build output (`data-astro-cid-*` attribute scoping) —
each component's `<style>` block is automatically extracted, minified, and deduplicated
by Astro/Vite at build time. There is no hand-maintained global stylesheet sprawl or
unused utility-class framework (Tailwind is explicitly **not** installed in this project,
confirmed via `astro.config.mjs` and project memory) to purge.

## Action taken

None needed — running PurgeCSS against already-scoped, already-minified, already small
(26 KB) component CSS would have negligible-to-zero additional benefit and adds a new
build dependency for a a fraction-of-a-KB win. Time was better spent on the image
payload, which was 1000x larger.

## Action taken elsewhere that helps CSS delivery

`public/_headers` now sends `Cache-Control: public, max-age=31536000, immutable` for
everything under `/_astro/*` (where Astro's compiled CSS/JS bundles live), so repeat
visits across pages don't even re-fetch this CSS — it's reused from cache.

## Follow-up (optional)

If the global aurora/glass theme CSS in `src/styles/global.css` grows significantly
larger in the future, re-evaluate with `npx astro build` + a coverage check, but at the
current ~26 KB total this isn't the bottleneck.

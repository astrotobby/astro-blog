# publish-queue

Staging area for posts that are scheduled to go live but **not yet published**.
Files here are NOT part of the Astro content collection, so they do not appear on
the site until moved into `src/content/blog/`.

The `.github/workflows/scheduled-publisher.yml` workflow publishes **one post per
run**, in filename order (`01-`, `02-`, … `10-`), at:

- **12:00 & 15:00 EAT** (09:00 & 12:00 UTC) — 2 posts/day
- **Mon Jun 29 → Fri Jul 3, 2026** — 5 days, 10 slots, 10 posts

On each run the workflow takes the next `NN-*.md` file, strips the `NN-` prefix
(so the live URL slug is clean), moves it into `src/content/blog/`, and pushes —
which triggers the Cloudflare Pages build that takes it live.

To publish manually / test: run the **scheduled-publisher** workflow from the
Actions tab (set `dry = true` to preview the next post without publishing).

The `NN-` number prefix only controls publish ORDER; it never appears in the URL.

# HONEST-LIMITS.md — read this once, save yourself a ban

You post **5×/day**. That's 5 videos/day. Here is what each platform actually
tolerates on a free tier with automation, and what the pipeline does about it.

Approach: **direct official APIs, no server.** Only platforms without an app-review
gate are automated. LinkedIn is deferred.

| Platform | Automated now? | The real catch | Pipeline behavior |
|----------|----------------|----------------|-------------------|
| **YouTube** | ✅ yes | Quota = 6 uploads/day default (upload=1,600 of 10,000 units). 5/day is fine. Main + Short = 2 uploads. | 1 upload/post. Set `youtube.also_short: true` only if ≤3 posts/day. |
| **Tumblr** | ✅ yes | none meaningful (register an app, OAuth1) | direct via PyTumblr |
| **X / Twitter** | ✅ capped | Free tier = ~500 writes/month ≈ 16/day. Video upload counts. | direct via tweepy; capped at `limits.x_per_day` (default 3). |
| **Facebook** | ✅ yes | Needs a long-lived Page access token (60 days). | direct via Graph API; token refresh workflow included. |
| **Instagram** | ✅ yes | Needs Meta Business account + Page token (same app as Facebook). | direct via Graph API; uses Facebook Page token. |
| **Threads** | ✅ yes | Needs separate Threads access token (same Meta app). | direct via Threads API. |
| **TikTok** | ✅ yes | Needs TikTok Content Posting app registration. | direct via TikTok API. |
| **Rumble** | ✅ yes | No API — uses headless Playwright browser automation. Needs 2FA off. | headless browser upload. |
| **Pinterest** | ✅ yes | Needs Pinterest developer app + access token. | direct via Pinterest API. |
| **Reddit** | ⚠️ opt-in | **Auto-posting to multiple subs = shadowban in <24h.** | ONE sub/day max, only subs you list in `config.yaml`, **off by default**. Treat as manual. |
| **LinkedIn** | ⛔ deferred | `w_member_social` video posting needs LinkedIn app review. | artifact for hand-upload. |

### Why direct APIs instead of Publer/Buffer
Self-hosted schedulers (Postiz, Publer) need a server to run AND you still register
your own IG/FB/LinkedIn dev apps — so they don't actually remove the app-review work
for the gated platforms. Direct APIs keep it serverless: nothing to host, one secret
per platform. The only deferred platform is LinkedIn (requires app review).

### Double-posting protection (built in)
Every posted slug + content-hash is written to `.pipeline/state/processed.json`,
persisted across GitHub Action runs via `actions/cache`. If the same post fires
the workflow again (e.g. you edit an unrelated line and the file's mtime changes),
it is **skipped**. Force a re-post with `python scripts/crosspost.py … --force`.

### The volume math you should accept
- **Automated free, daily:** YouTube + Tumblr + Facebook + Instagram + Threads + TikTok + Rumble + Pinterest (+ X capped, + Reddit if you opt in).
- **Deferred (manual until app review):** LinkedIn.
- Pushing identical content to many platforms 5×/day will get **X and Reddit flagged**
regardless of tooling. The per-platform caps in `config.yaml` exist for this reason.

### Openverse image search
The pipeline uses the Openverse API for topical photo search. Without an API key,
requests are rate-limited to 5/day (unusable for batch pipelines). Get a free key
at [api.openverse.org](https://api.openverse.org/) and set it as the
`OPENVERSE_TOKEN` secret.

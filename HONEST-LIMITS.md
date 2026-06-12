# HONEST-LIMITS.md — read this once, save yourself a ban

You post **5×/day**. That's 5 videos/day. Here is what each platform actually
tolerates on a free tier with automation, and what the pipeline does about it.

Approach: **direct official APIs, no server, no Postiz.** Only platforms without
an app-review gate are automated now. The rest are saved as artifacts for hand-upload.

| Platform | Automated now? | The real catch | Pipeline behavior |
|----------|----------------|----------------|-------------------|
| **YouTube** | ✅ yes | Quota = 6 uploads/day default (upload=1,600 of 10,000 units). 5/day is fine. Main + Short = 2 uploads. | 1 upload/post. Set `youtube.also_short: true` only if ≤3 posts/day. |
| **Tumblr** | ✅ yes | none meaningful (register an app, OAuth1) | direct via PyTumblr |
| **X / Twitter** | ✅ capped | Free tier = ~500 writes/month ≈ 16/day. Video upload counts. | direct via tweepy; capped at `limits.x_per_day` (default 3). |
| **Reddit** | ⚠️ opt-in | **Auto-posting to multiple subs = shadowban in <24h.** | ONE sub/day max, only subs you list in `config.yaml`, **off by default**. Treat as manual. |
| **Instagram Reels** | ⛔ deferred | Needs Meta Business app + **App Review** (Content Publishing). No free shortcut — Postiz self-host wouldn't skip this either. | Reel saved as artifact for hand-upload. |
| **Facebook Reels** | ⛔ deferred | Same Meta App Review story. | artifact for hand-upload. |
| **LinkedIn** | ⛔ deferred | `w_member_social` video posting needs LinkedIn app review. | artifact for hand-upload. |
| **Pinterest** | ⛔ deferred | API only gives **trial/sandbox** access until app review. | artifact for hand-upload. |

### Why we don't fabricate a "Makefun.ai free unlimited avatar API"
No such documented public API exists. Free AI-video sites give you a *web UI*,
not an automatable endpoint, and they throttle. Building against a fake endpoint
would silently 404 in production. The pipeline instead uses **edge-tts** (real,
free, no key) + **Pollinations** images + **ffmpeg** — all scriptable today.

### Want a talking-head later?
Add `scripts/lipsync_colab.ipynb` (SadTalker on free Colab GPU). It's real but:
- ~3–6 min render per clip on free GPU,
- Colab disconnects under heavy use,
- not reliable at 5/day. Use it for your *best* post of the day, not all.

### Why direct APIs instead of Postiz/Publer
Postiz self-hosted is $0 in licensing, but it needs a server to run AND you still
register your own IG/FB/LinkedIn dev apps — so it doesn't actually remove the
app-review work for the gated platforms. Direct APIs keep it serverless: nothing
to host, one secret per platform, and the gated four are simply deferred until
you decide their app review is worth it.

### Double-posting protection (built in)
Every posted slug + content-hash is written to `.pipeline/state/processed.json`,
persisted across GitHub Action runs via `actions/cache`. If the same post fires
the workflow again (e.g. you edit an unrelated line and the file's mtime changes),
it is **skipped**. Force a re-post with `python scripts/crosspost.py … --force`.

### The volume math you should accept
- **Automated free, daily:** YouTube + Tumblr (+ X capped, + Reddit if you opt in).
- **Deferred (manual until you do their apps):** Instagram, Facebook, LinkedIn, Pinterest.
- Pushing identical content to many platforms 5×/day will get **X and Reddit flagged**
  regardless of tooling. The per-platform caps in `config.yaml` exist for this reason.

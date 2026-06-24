# blog-to-video — zero-budget blog → video → social autopilot

Turns every new blog post in your GitHub repo into a captioned, voiced
motion-graphics video and cross-posts it to YouTube + (via self-hosted Postiz)
Instagram, Facebook, LinkedIn, X, Tumblr, Pinterest and Reddit.

Everything runs **free on GitHub Actions** — your laptop can be off.

---

## How it works

```
new commit to /posts  ──►  GitHub Action  ──►  pipeline
                                               1. fetch_post.py   (read the new .md/.mdx)
                                               2. build_script.py (title + 45s VO script + image prompts)
                                               3. generate_video.py
                                                    • edge-tts        -> voiceover.mp3   (free, no key)
                                                    • Pollinations    -> scene images    (free, no key)
                                                    • faster-whisper  -> captions.srt     (free, local)
                                                    • ffmpeg          -> video_9x16.mp4 + video_16x9.mp4
                                               4. crosspost.py
                                                    • YouTube Data API  (direct, instant)
                                                    • Postiz API        (IG/FB/LinkedIn/X/Tumblr/Pinterest/Reddit)
                                               5. notify.py        (Telegram summary: ✅/❌ per platform)
```

There is **no paid service in this pipeline.** Read `HONEST-LIMITS.md` before you
expect magic — some platforms cannot be naively spammed 5×/day.

---

## 0. One-time setup (do these in order)

### A. Free accounts / keys to create

| # | Service | Why | Link | Cost |
|---|---------|-----|------|------|
| 1 | GitHub (have it) | repo + Actions runner | — | free |
| 2 | Telegram bot | success/fail summary | https://t.me/BotFather | free |
| 3 | Google Cloud project | YouTube Data API v3 | https://console.cloud.google.com/ | free |
| 4 | Tumblr app | Tumblr posting (no review) | https://www.tumblr.com/oauth/apps | free |
| 5 | X / Twitter app | X posting (free tier, capped) | https://developer.x.com/ | free |
| 6 | Reddit app (optional) | Reddit posting (off by default) | https://www.reddit.com/prefs/apps | free |
| 7 | Pixabay (optional) | royalty-free bg music | https://pixabay.com/api/docs/ | free |

`edge-tts` and `Pollinations.ai` need **no key at all.**

**Instagram / Facebook / LinkedIn / Pinterest are deferred** — each needs its own
developer app + review, which no free tool skips. The pipeline renders the Reels
and saves them as Action artifacts so you can hand-upload those four meanwhile.

### B. Install locally (only needed to test before pushing)

```powershell
# from the project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# FFmpeg (Windows):
winget install Gyan.FFmpeg
```

### C. Put the project in (or next to) your blog repo

This pipeline assumes your posts live in a folder like `posts/` or `src/content/blog/`.
Set the path in `config.yaml` (`posts_dir`). Copy the `scripts/`, `config.yaml`,
`requirements.txt` and `.github/workflows/blog-to-video.yml` into your blog repo root.

### D. Add GitHub repo secrets

Repo → Settings → Secrets and variables → Actions → **New repository secret**.
Names must match `.env.template`:

```
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
YOUTUBE_CLIENT_ID
YOUTUBE_CLIENT_SECRET
YOUTUBE_REFRESH_TOKEN
TUMBLR_CONSUMER_KEY
TUMBLR_CONSUMER_SECRET
TUMBLR_OAUTH_TOKEN
TUMBLR_OAUTH_SECRET
TUMBLR_BLOG
X_API_KEY
X_API_SECRET
X_ACCESS_TOKEN
X_ACCESS_SECRET
REDDIT_CLIENT_ID       # optional (off by default)
REDDIT_CLIENT_SECRET   # optional
REDDIT_USERNAME        # optional
REDDIT_PASSWORD        # optional
PIXABAY_API_KEY        # optional
SITE_BASE_URL          # e.g. https://astrotobby.site  (used for the CTA link)
```

You don't need all of these to start — set only the platforms you want live. A
missing platform's secrets just mean it's skipped (logged as "no creds").

---

## 1. Get the YouTube refresh token (one time)

```powershell
python scripts/youtube_auth.py
```

Opens a browser, you approve once, it prints a `YOUTUBE_REFRESH_TOKEN`.
Paste it into repo secrets. Done forever.

## 2. Get the social tokens (direct APIs, no server)

Each platform is independent — set up only the ones you want live. The pipeline
skips any platform whose secrets are missing.

- **Tumblr** (no review): create an app at https://www.tumblr.com/oauth/apps →
  copy consumer key/secret. Then open https://api.tumblr.com/console, sign in, and
  it shows all four OAuth values (`TUMBLR_OAUTH_TOKEN`, `TUMBLR_OAUTH_SECRET`).
  Set `TUMBLR_BLOG` to your blog host (e.g. `astrotobby.tumblr.com`).
- **X / Twitter** (free tier): https://developer.x.com/ → create a project/app with
  **Read and Write** → generate API key/secret + access token/secret (4 values).
- **Reddit** (optional, off by default): https://www.reddit.com/prefs/apps → create
  a **script** app → use its id/secret + your reddit username/password. Then set
  `limits.reddit_enabled: true` and list safe subs in `config.yaml`.

Enable each in `config.yaml → platforms.direct` (default `[tumblr, x]`).

> **Instagram / Facebook / LinkedIn / Pinterest** are deferred — they each require
> their own developer app + review (no free tool, Postiz included, skips this). The
> workflow saves the rendered 9:16 Reels as downloadable Action artifacts so you can
> hand-upload those four until you decide their apps are worth doing.

---

## 3. Test each stage locally

```powershell
# 1. fetch the most recent post
python scripts/fetch_post.py --latest

# 2. build the narration script + image prompts
python scripts/build_script.py .pipeline/post.json

# 3. render the videos (this is the heavy one)
python scripts/generate_video.py .pipeline/script.json

# 4. dry-run the cross-poster (no real uploads)
python scripts/crosspost.py .pipeline/render.json --dry-run

# 5. send yourself a test Telegram message
python scripts/notify.py --test
```

Outputs land in `.pipeline/` and `.pipeline/out/`.

## 4. Go live

Push a new post to `posts/`. Watch **Actions** tab. Within ~5–8 min you get a
Telegram message with ✅/❌ per platform and links.

---

## Files

| File | Role |
|------|------|
| `.github/workflows/blog-to-video.yml` | the trigger + cloud runner |
| `config.yaml` | posts dir, voice, hashtags, subreddits, posting rules |
| `scripts/fetch_post.py` | finds the new/changed post, parses front-matter |
| `scripts/build_script.py` | hook + 45s VO script + per-scene image prompts |
| `scripts/generate_video.py` | edge-tts → Pollinations → whisper → ffmpeg |
| `scripts/crosspost.py` | dispatcher: dedup + daily caps over the direct posters |
| `scripts/platforms.py` | direct API posters (YouTube, Tumblr, Reddit, X) |
| `scripts/youtube_auth.py` | one-time refresh-token helper |
| `scripts/notify.py` | Telegram summary |
| `scripts/run_pipeline.py` | runs all stages in order (what the Action calls) |
| `assets/music/` | drop royalty-free tracks here; auto-mixed + ducked (empty = no music) |
| `HONEST-LIMITS.md` | what actually works free, and what will ban you |

### Reliability features baked in
- **Source-agnostic trigger:** watches the `src/content/blog/**` path, not any
  Make scenario ID. All 5 (or 50) of your autoblogging scenarios feed the same
  pipeline just by committing a post — nothing to wire per scenario.
- **Processes every new post in a push:** if one commit drops multiple posts, each
  is rendered + cross-posted; none are silently dropped.
- **Serialized runs:** the workflow's `concurrency` group queues near-simultaneous
  commits so parallel runs can't corrupt the shared dedup ledger / daily caps.
- **No double-posting:** content-hash ledger in `.pipeline/state/`, cached across
  Action runs. Re-triggering the same post is skipped (override with `--force`).
- **Daily caps:** X capped to `limits.x_per_day`, Reddit off by default — over the
  cap it's simply not posted that day (see `HONEST-LIMITS.md`).
- **Missing creds = skipped, not crashed:** set up platforms one at a time.
- **Music auto-ducks** under the voiceover via sidechain compression.
- **Soft-fail per platform:** one platform erroring never blocks the others; you
  get a per-platform ✅/❌ in Telegram.

---

## Living avatar — gestures, expressions, real lip-sync (free, one-time setup)

Wav2Lip only moves the **mouth**. To get hand gestures, head movement and facial
expressions too, give it a short clip of your avatar **already moving** — Wav2Lip then
overlays accurate lip-sync onto that real motion and loops it across the whole
voiceover. The motion is baked into the base clip; you make it **once, for free**.

### Make the base clip (pick any one, all have free tiers)
Animate your existing `assets/avatar.png` into a 6–10s clip of the person talking
naturally — subtle hand gestures, friendly expressions, slight head movement,
head-and-shoulders framing, plain/blurred background:

| Tool | Free tier | Notes |
|------|-----------|-------|
| **Hailuo / MiniMax (Image-to-Video)** | free daily credits | best motion quality; upload the photo + prompt |
| **Kling AI (Image-to-Video)** | free daily credits | great gestures; 5–10s clips |
| **Pika / Vidu / Hailuo** | free credits | quick image-to-video |
| **D-ID / HeyGen** | free trial | true presenter avatars (watermark on free) |
| **LivePortrait (HF Space)** | free | drives your photo with a sample acting video |

**Prompt to use:** *"Professional presenter talking to camera, natural subtle hand
gestures, warm facial expressions, slight head movement, upper body, soft studio
background, looping."*

### Drop it in
1. Save the clip as **`astro-blog/assets/avatar_motion.mp4`** (the path in
   `config.yaml → avatar.motion_video`).
2. Keep it **head-and-shoulders** and roughly portrait/centered (the pipeline crops to
   `avatar.face_cx/face_cy/face_zoom`; tweak those if the framing is off).
3. A short clip is fine — Wav2Lip **auto-loops** it to match the narration length.
4. Commit it. If the file is missing the pipeline silently falls back to the still
   image (lips-only), so nothing breaks.

That's it — every future post renders with a gesturing, expressive, lip-synced avatar,
fully automatically and free.

See `HONEST-LIMITS.md` and `TROUBLESHOOTING.md`.

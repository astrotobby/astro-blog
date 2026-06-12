# TROUBLESHOOTING — zero-budget gotchas

**Action runs but no post is picked up**
- `paths:` in the workflow must match `posts_dir` in `config.yaml`. Edit both.
- The diff step only sees files changed in the pushed commit. Use the
  `workflow_dispatch` → `latest` run to force the newest post.

**`ffmpeg: command not found` locally**
- `winget install Gyan.FFmpeg`, then open a NEW PowerShell so PATH refreshes.

**Pollinations images are blank / time out**
- It's a free service and occasionally rate-limits. The fetch retries 3×. If a
  scene stays blank, re-run; or lower `visuals.scenes` to 4 in `config.yaml`.

**edge-tts: `NoAudioReceived`**
- Usually a transient network blip or a bad voice name. Run
  `edge-tts --list-voices` and confirm `voice.name`. Retry the step.

**Whisper is slow / OOM on the runner**
- `base` model on CPU is fine for 45s audio (~20s). If it struggles, set
  `video.captions: false` — the video still renders, just without burned subs.

**YouTube `quotaExceeded`**
- Default quota = ~6 uploads/day. With 5 posts/day you're at the edge; do NOT
  enable `also_short` (that doubles uploads). Request a quota increase (free) in
  Cloud Console if you need more.

**YouTube `invalid_grant` / token expired**
- Refresh tokens for apps in "Testing" mode expire after 7 days. In the OAuth
  consent screen, **publish the app to Production** (still free, no review needed
  for the upload scope on your own channel). Re-run `youtube_auth.py`.

**Postiz post returns 4xx**
- Confirm the account is connected in the Postiz UI and the `integrations`
  values in `config.yaml -> platforms.postiz.targets` match the integration
  identifiers Postiz expects. Check Postiz logs: `docker compose logs -f`.

**X / Reddit got restricted**
- Expected if you exceed caps — see `HONEST-LIMITS.md`. Lower `limits.x_per_day`,
  keep `reddit_enabled: false`, and never post identical text to many subs.

**Everything "succeeds" but nothing posts**
- You're in `--dry-run` (the `workflow_dispatch` "dry" mode). Use "latest".

**Action minutes**
- Each run ≈ 4–8 min. 5 posts/day ≈ 1,200 min/mo — under the 2,000 free min.
  If you go over, render only vertical (`make_horizontal: false`) to cut ~40%.

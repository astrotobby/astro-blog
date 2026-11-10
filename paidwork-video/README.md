# Paidwork YouTube gig video

A standalone talking-head video produced with **this repo's blog-to-video render
stage** (`scripts/generate_video.py`) — edge-tts voiceover → Pollinations/Openverse
visuals → Wav2Lip talking head → ffmpeg montage (hook card, burned captions, ducked
music, end card).

**This video is NOT part of the automated pipeline.** It is not committed to
`src/content/blog`, it is not cross-posted, and it does not touch the dedup ledger.
Only the render stage was reused; `crosspost.py` was never run. Upload it to YouTube
by hand for the gig.

## What it is
- **Talking head:** the suit-man portrait (`assets/avatar_paidwork.jpg`, cropped from
  the supplied image) lip-synced by Wav2Lip and composited lower-right over the montage.
- **Length:** ~3m33s voiceover (clears the gig's 3-minute minimum).
- **Cuts rendered:** `video_16x9.mp4` (YouTube, primary) and `video_9x16.mp4` (vertical short, bonus).

## How it was rendered
`generate_video.py` reads `config.yaml`, so these **temporary** overrides were applied
for this render only, then reverted (production `config.yaml` is unchanged):

| Setting | Production default | This video |
|---|---|---|
| `voice.rate` | `+0%` | `-6%` (calmer; keeps VO past 3:00) |
| `avatar.enabled` | `false` | `true` |
| `avatar.image` | `assets/avatar.png` | `assets/avatar_paidwork.jpg` |
| `avatar.motion_video` | `assets/avatar_motion.mp4` | `""` (still image → suit-man talking head) |
| `avatar.timeout` | `1900` | `5400` (full 3-min CPU lip-sync) |
| `video.end_card_lines` | blog/AI Starter Pack | Paidwork copy |

The narration + scene prompts + YouTube metadata live in `script.json`
(fed directly to `generate_video.py`, bypassing `build_script.py` so the script is the
exact Paidwork tutorial rather than an auto-generated clickbait cut).

To reproduce:
```bash
# one-time: pip install edge-tts Pillow requests PyYAML imageio-ffmpeg huggingface_hub
#           bash scripts/setup_wav2lip.sh   (torch CPU + weights)
# apply the overrides above to config.yaml, then:
cp paidwork-video/script.json .pipeline/script.json
python3 scripts/generate_video.py .pipeline/script.json
# outputs -> .pipeline/out/video_16x9.mp4  and  video_9x16.mp4
```

## YouTube upload copy

**Title:**
> How I Earn Money Online With Paidwork (Free Beginner's Guide)

**Description:** (⚠️ replace `YOUR_REFERRAL_CODE` with your real Paidwork referral link)
```
In this video I show you exactly how to earn money online with Paidwork — how to sign
up, how the tasks work, and how to get paid. Beginner friendly and free to start.

👉 Join Paidwork with my referral link: https://paidwork.com/?ref=YOUR_REFERRAL_CODE

What you'll learn:
• What Paidwork is and how it pays you
• How to sign up in ~2 minutes (email or Google)
• The task types: surveys, offers, videos and games
• How to cash out via PayPal, crypto or gift cards
• How the referral program earns you extra

Drop a comment with which task you'll try first, and subscribe for more ways to earn online.

#Paidwork #MakeMoneyOnline #EarnOnline #SideHustle #WorkFromHome
```

## Gig submission checklist
- [ ] Paste your real Paidwork referral link into the description.
- [ ] Upload `video_16x9.mp4` to YouTube (public).
- [ ] Video is under 7 days old at submission time.
- [ ] Screenshot the published video showing **title, views, description (with your
      referral link), and publication date** — that screenshot is the gig proof.
- [ ] (Optional) Record a few seconds of the real Paidwork app to satisfy the "show
      real app usage" line; the montage here is illustrative b-roll, not app screens.

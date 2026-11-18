# Dual-channel long-form video pipeline design

**Status:** Design proposal; no production workflow, credentials, or publishing behavior changed by this document.

## Objective

Produce four original long-form YouTube videos per day from one GitHub Actions-based system:

- **Astrotobby:** two videos daily about current news, entertainment, and explainers; owner Google account: `goodlucktobby@gmail.com`.
- **Digital Nomad:** two videos daily about AI, technology, tools, coding, and automation; owner Google account: `chanzera3@gmail.com`.
- **Duration:** every finished main video must be at least 10:00.

The two channels are managed under separate Google accounts. Each channel must use its own refresh token issued while signed in as its stated owner account, and each token must resolve to the matching YouTube channel before uploading.
- **Orchestration:** GitHub Actions; no Make.com dependency and no requirement to keep the owner's laptop online.

The existing blog-to-video workflow remains a separate ingestion path until the new scheduled pipeline is proven. It must not publish duplicate YouTube videos for topics already owned by the new scheduler.

## Current repository findings

The existing pipeline already provides reusable components:

- `scripts/build_script.py` creates narration and scene prompts from a blog post.
- `scripts/generate_video.py` assembles narration, footage, captions, and FFmpeg masters.
- `scripts/platforms.py` contains the YouTube Data API uploader.
- `scripts/crosspost.py` handles destination deduplication and retry bookkeeping.
- `.github/workflows/blog-to-video.yml` runs on blog-content pushes and a periodic sweep.
- `config.yaml` currently sets `script.target_seconds: 75`, so it is not a long-form configuration.
- The YouTube uploader now supports explicit channel-specific refresh tokens and verifies the selected channel before uploading. The legacy generic token remains available only for older posts without an explicit channel profile.
- The long-form scheduler, topic discovery, ten-minute script mode, long-form renderer, and scheduled-publication workflow are still to be implemented.
- The current workflow is post-driven; it does not independently discover four daily topics.

The new pipeline should reuse stable code where practical, but should not change the existing short-form defaults globally. Long-form behavior should be an explicit profile/job mode.

## Daily schedule

Confirmed publication timetable in Africa/Nairobi (UTC+3):

| Publish time (Kenya) | `publishAt` / UTC | Channel | Owner Google account | Editorial lane |
|---|---:|---|---|---|
| 10:00 AM | 07:00 UTC | Astrotobby | `goodlucktobby@gmail.com` | News and entertainment |
| 12:00 PM | 09:00 UTC | Digital Nomad | `chanzera3@gmail.com` | AI and technology developments |
| 3:00 PM | 12:00 UTC | Astrotobby | `goodlucktobby@gmail.com` | Trending stories and explainers |
| 6:00 PM | 15:00 UTC | Digital Nomad | `chanzera3@gmail.com` | Automation, tutorials, practical workflows |

These are the **publication times**, not merely the time at which a render should begin. Because GitHub Actions scheduled starts can be delayed and long-form rendering may take substantial time, production should run ahead of each slot. Upload each validated video as private with YouTube's scheduled-publication `status.publishAt` set to the table's UTC timestamp. The job must verify the scheduled publication metadata after upload. A failed or late render must be reported as delayed/failed rather than silently published at an unrelated time. GitHub cron dispatches and queue workers should run early enough to meet these publishAt deadlines.

## Proposed architecture

### 1. Channel profiles

Add a declarative file such as `config/channel_profiles.yaml` with two isolated profiles. Each profile owns:

- stable internal channel key (`digital_nomad` or `astrotobbyc`)
- expected YouTube channel ID
- niche, voice/tone, audience, allowed topic categories, and excluded categories
- source-feed allowlist and freshness policy
- title/thumbnail/description rules
- target duration and words-per-minute
- upload privacy and publication behavior
- schedule slots

Never infer the destination channel from the video title, post filename, or current YouTube Studio browser selection.

### 2. Topic discovery and queue

Add a topic-discovery stage that runs for the scheduled channel/slot. It should:

1. Read that channel's approved RSS feeds and/or configured news APIs.
2. Record source URL, publisher, published timestamp, retrieved timestamp, headline, and a short factual summary.
3. Rank candidate topics by relevance, freshness, source quality, audience interest, and uniqueness.
4. Reject topics already used or too similar to a recently published topic on either channel.
5. Save a durable job record before starting expensive work.

For Astrotobby, prefer recent stories and enforce a configurable freshness window. For Digital Nomad, mix current developments with useful evergreen tutorials. If the source pool is weak, create a failed/needs-review job rather than inventing a breaking story.

The research stage must use sources as evidence, not copy their articles. Scripts should be original commentary and explanation, with source links retained in the video description and job metadata.

### 3. Long-form script

Create a long-form script mode separate from the current 75-second mode.

- Initial target: 1,600–1,800 spoken words.
- Minimum verified narration duration: 10:00.
- Structure: cold open, context, chapters/sections, concrete examples, counterpoints or caveats, recap, and channel-specific CTA.
- Avoid padding, repeated paragraphs, unsupported claims, and fabricated quotations.
- Keep source URLs and claim-to-source notes in the script JSON.
- If the available evidence cannot support a useful ten-minute treatment, reject or replace the topic.

A configured LLM may assist with research synthesis and narration, but it must not be the only fact-checking layer. Missing API credentials should produce an explicit unavailable/review state, not silently downgrade a long-form job to a short script.

### 4. Long-form render

Use a dedicated long-form renderer/profile. Do not simply stretch the existing 12-scene short-form montage.

The render should combine:
- narration generated through the existing TTS fallback chain;
- licensed or otherwise permitted B-roll and relevant stills;
- varied scene durations, chapter cards, data/stat cards, diagrams, and visual examples;
- readable captions and a consistent horizontal 16:9 master;
- controlled background music mixed below narration;
- FFmpeg assembly and final media probing.

LTX-2 should remain an optional enhancement for selected short segments. It must not be required to generate every shot or block a job when the external model service is unavailable.

Before upload, probe the final file and validate:
- duration >= 600 seconds;
- valid video and audio streams;
- expected 16:9 dimensions and supported encoding;
- non-zero file size and successful full render;
- narration is present and not clipped;
- title, description, tags, thumbnail, and source references exist.

A job that fails validation must never reach the upload stage.

### 5. Channel-safe YouTube publishing

Reuse the existing channel-specific refresh tokens already configured in **AI-GEMS** rather than creating new authorizations by default. The owner has confirmed that the channels are under separate Google accounts: Astrotobby uses `goodlucktobby@gmail.com`; Digital Nomad uses `chanzera3@gmail.com`. Do not authorize both channels using the same browser-selected account by assumption.

The actual GitHub secret inventory was checked with the authenticated GitHub CLI:

- **Astrotobby destination:** AI-GEMS secret `YOUTUBE_REFRESH_TOKEN_ASTRO_TOBBY`; channel title in the existing target configuration is `Astro Tobby`; owner account supplied by the user is `goodlucktobby@gmail.com`.
- **Digital Nomad destination:** AI-GEMS secret `YOUTUBE_REFRESH_TOKEN_DIJITOL_NOMAD`; channel title in the existing target configuration is `DIJITOL NOMAD`; owner account supplied by the user is `chanzera3@gmail.com`.
- Shared OAuth credentials present in AI-GEMS include `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`, `CLIENT_ID` / `CLIENT_SECRET`, and legacy `YOUTUBECLIENT_ID` / `YOUTUBECLIENT_SECTRET`.
- The `astro-blog` repository does **not** contain the two channel-specific refresh-token secrets; it has only its legacy generic YouTube token and client credentials. GitHub secrets are repository-scoped.

Therefore, the long-form workflow and read-only credential validation must run from AI-GEMS, where both channel refresh tokens already live, and check out `astrotobby/astro-blog` as the production-code repository. This avoids copying secrets between repositories. The first AI-GEMS change is a manual-only validator workflow, `.github/workflows/validate-youtube-channels.yml`, which uses the channel-specific secrets and the validation script from astro-blog. Do not use GitHub Actions Variables for token values.

The two accounts must never share or substitute refresh tokens. The shared OAuth client candidates must be passed without printing their values. The new publisher must never use the generic legacy token as a fallback for an explicitly selected channel.

Also configure expected channel IDs as non-secret settings or repository variables where available:

- `YOUTUBE_CHANNEL_ID_DIGITAL_NOMAD`
- `YOUTUBE_CHANNEL_ID_ASTROTOBBYC`

For each channel token, refresh it using its matching OAuth client, call `channels.list(mine=true)`, and verify both the configured channel ID (when supplied) and the expected channel title (`DIJITOL NOMAD` or `Astro Tobby`) before any upload. If the token identifies the wrong channel, stop the job. Never fall back to the other token.

These two destinations belong to separate Google login accounts. Existing tokens should be reused if they refresh successfully and resolve to the intended channel; only a missing, revoked, expired, or mismatched authorization should require reauthentication. Channel ID/title verification confirms the YouTube destination. The OAuth account-to-channel ownership mapping is additionally recorded from the owner's confirmation above; do not claim the email itself was verified unless the OAuth grant includes the appropriate Google identity scope. Keep token values only in GitHub Actions Secrets; never put them in YAML, code, logs, artifacts, or this repository. Do not ask the user to paste refresh tokens into chat.

### 6. Durable state and idempotency

Use a job identity derived from channel key + normalized topic/source identity + format/version. Persist state transitions:

`discovered -> researched -> scripted -> rendered -> validated -> uploading -> published`

Failures should retain the last successful artifact and stage, then retry only the failed stage. Store the YouTube video ID and returned URL after successful upload.

The state store must survive independent GitHub Actions runs and cache expiry. Prefer a dedicated state branch or another durable repository-backed store with serialized writes. GitHub Actions cache may accelerate processing but must not be the only source of truth.

Use separate concurrency groups for channel workers plus a state-write lock. Prevent two workers from claiming the same topic. A retry after an ambiguous upload response must first reconcile with the job ledger and YouTube channel's recent uploads before attempting another insert.

### 7. GitHub Actions layout

Proposed workflows/scripts:

- `.github/workflows/longform-scheduler.yml`: four UTC schedule triggers plus manual dispatch.
- `scripts/topic_discovery.py`: channel-specific topic selection and source records.
- `scripts/longform_script.py`: source-backed narration and duration gate.
- `scripts/render_longform.py`: long-form media assembly.
- `scripts/publish_longform.py`: channel-token validation, upload, and result reconciliation.
- `scripts/longform_job.py`: one job's state machine and retry/resume logic.
- `config/channel_profiles.yaml`: editorial profiles and schedule.

Run one video per job initially, not all four sequentially in one 120-minute run. Benchmark actual render time and runner memory before choosing parallelism. If a render regularly approaches the runner time limit, split research, narration, rendering, and upload into resumable jobs or move rendering to a suitable authorized runner. The owner's HP ProBook should not be the production render dependency.

The existing blog-triggered workflow remains on its legacy single-channel credential and must not be repurposed for the two long-form channels. The long-form scheduler runs in AI-GEMS and checks out the astro-blog code at a pinned ref. Reconcile topic identities across the legacy blog workflow and new scheduler so the same article/topic cannot be uploaded by both systems. During rollout, keep new long-form uploads private or unlisted until channel routing and media quality are verified.

## Rollout plan

1. **Inventory and configuration:** confirm both channel IDs and map each channel's editorial profile.
2. **OAuth validation:** reuse the existing channel-specific tokens; verify each against its expected channel title and configured channel ID without uploading. Reauthorize only a token that is absent, revoked, expired, or mismatched.
3. **Dry-run discovery:** generate and inspect a queue for each channel; verify topic separation and freshness.
4. **Script validation:** produce 10-minute scripts and validate word count, source traceability, and duration estimates.
5. **Render benchmark:** render one sample per channel; measure elapsed time, memory, artifact size, and actual media duration.
6. **Private upload test:** upload one test video to each intended channel as private/unlisted and verify the returned channel/video IDs.
7. **Controlled launch:** enable one scheduled slot per channel, monitor failures and quality, then ramp to all four daily slots.
8. **Steady state:** publish only after validation, retain failure artifacts, and report all four job outcomes daily.

## Acceptance criteria

- Four independent publication jobs are created per day at 10:00 AM, 12:00 PM, 3:00 PM, and 6:00 PM Kenya time.
- Exactly two jobs target Astrotobby (`goodlucktobby@gmail.com`) and two target Digital Nomad (`chanzera3@gmail.com`).
- Each upload is uploaded ahead of time and carries the correct UTC `publishAt` value for its Kenya publication slot.
- No job can upload unless its OAuth token resolves to the expected channel ID.
- Every uploaded main video is at least 10:00 and passes media validation.
- No topic/job is uploaded twice after retry, timeout, or overlapping workflow runs.
- A failed job does not block the other three.
- Source URLs and job results are retained.
- No Make.com subscription or always-on personal laptop is required.
- A daily report lists each slot as published, failed, delayed, or awaiting review, with the video URL where available.

## External API notes

The YouTube Data API requires OAuth for uploads. The `videos.insert` endpoint currently documents a 100-call/day upload quota bucket; four uploads/day are comfortably below that documented limit. Channel validation should use the authenticated channel identity rather than assuming a Google login maps to only one channel.

References:
- https://developers.google.com/youtube/data/guides/authentication
- https://developers.google.com/youtube/data/v3/docs/channels/list
- https://developers.google.com/youtube/v3/docs/videos/insert
- https://support.google.com/youtube/answer/4642409

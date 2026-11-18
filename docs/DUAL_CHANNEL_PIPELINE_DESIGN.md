# Dual-channel long-form video pipeline design

**Status:** Design proposal; no production workflow, credentials, or publishing behavior changed by this document.

## Objective

Produce four original long-form YouTube videos per day from one GitHub Actions-based system:

- **Digital Nomad:** two videos daily about AI, technology, tools, coding, and automation.
- **Astrotobbyc:** two videos daily about current news, entertainment, and explainers.
- **Duration:** every finished main video must be at least 10:00.
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
- YouTube currently reads one `YOUTUBE_REFRESH_TOKEN`, so explicit channel routing is not implemented.
- The current workflow is post-driven; it does not independently discover four daily topics.

The new pipeline should reuse stable code where practical, but should not change the existing short-form defaults globally. Long-form behavior should be an explicit profile/job mode.

## Daily schedule

Initial proposed schedule in Africa/Nairobi (UTC+3):

| Local time | UTC cron time | Channel | Editorial lane |
|---|---:|---|---|
| 07:15 | 04:15 | Digital Nomad | AI and technology developments |
| 12:15 | 09:15 | Astrotobbyc | News and entertainment |
| 17:15 | 14:15 | Digital Nomad | Automation, tutorials, practical workflows |
| 21:15 | 18:15 | Astrotobbyc | Trending stories and explainers |

GitHub Actions cron is UTC. The minute offset avoids scheduling every job at the top of the hour. These are dispatch targets, not a guarantee of exact publication time: GitHub may delay scheduled starts. A queue should retain jobs that do not start on time.

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

For Astrotobbyc, prefer recent stories and enforce a configurable freshness window. For Digital Nomad, mix current developments with useful evergreen tutorials. If the source pool is weak, create a failed/needs-review job rather than inventing a breaking story.

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

Use one shared OAuth client ID/secret if both authorizations were created in the same Google Cloud project, but use a separate refresh token for each channel:

- `YOUTUBE_REFRESH_TOKEN_DIGITAL_NOMAD`
- `YOUTUBE_REFRESH_TOKEN_ASTROTOBBYC`
- `YOUTUBE_CLIENT_ID` (shared)
- `YOUTUBE_CLIENT_SECRET` (shared)

Also configure expected channel IDs as non-secret settings or repository variables:

- `YOUTUBE_CHANNEL_ID_DIGITAL_NOMAD`
- `YOUTUBE_CHANNEL_ID_ASTROTOBBYC`

A single Google login can manage multiple YouTube channels, but that does not mean one refresh token safely selects both destinations. Authorize each channel explicitly, choosing the intended channel during Google's OAuth/channel selection where available. For each token, call `channels.list(mine=true)` and compare the returned channel ID with the configured expected ID before any upload. If it does not match, stop the job. Never fall back to the other token.

Use the `youtube.upload` scope (or an already-granted compatible scope). Keep tokens only in GitHub Actions Secrets; never put tokens in YAML, code, logs, artifacts, or this repository. Do not request the user's Google password or paste refresh tokens into chat.

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

The existing blog-triggered workflow must be reconciled with the new scheduler so the same article/topic cannot be uploaded by both systems. During rollout, keep new long-form uploads private or unlisted until channel routing and media quality are verified.

## Rollout plan

1. **Inventory and configuration:** confirm both channel IDs and map each channel's editorial profile.
2. **OAuth setup:** create and validate the two channel-specific refresh tokens; verify each token against its expected channel ID without uploading.
3. **Dry-run discovery:** generate and inspect a queue for each channel; verify topic separation and freshness.
4. **Script validation:** produce 10-minute scripts and validate word count, source traceability, and duration estimates.
5. **Render benchmark:** render one sample per channel; measure elapsed time, memory, artifact size, and actual media duration.
6. **Private upload test:** upload one test video to each intended channel as private/unlisted and verify the returned channel/video IDs.
7. **Controlled launch:** enable one scheduled slot per channel, monitor failures and quality, then ramp to all four daily slots.
8. **Steady state:** publish only after validation, retain failure artifacts, and report all four job outcomes daily.

## Acceptance criteria

- Four independent scheduled jobs are created per day.
- Exactly two jobs target each configured channel.
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

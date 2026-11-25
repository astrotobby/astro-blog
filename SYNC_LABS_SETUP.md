# Sync Labs Sync-3 setup for the AI influencer

## Why this replaces the local model path

Sync-3 runs on Sync Labs' hosted infrastructure. The long-form runner no longer needs
an NVIDIA GPU, CUDA, a 15 GB checkpoint download, or a dedicated self-hosted GPU
machine. The pipeline continues to use only the two approved Kling presenter clips.

The integration processes each presenter shot against its own narration excerpt. It
does not concatenate unrelated speech, loop/boomerang the Kling source, or fall back
to an unsynchronized face. If the API rejects a job, the render stops.

## Free preview

Sync Labs' free account currently includes three shared lip-sync video
generations per month, up to 20 seconds each, with no credit card required. At most
one of those three can use Sync-3, and a Sync-3 generation is limited to 15 seconds.
Free outputs include a Sync Labs watermark. The free allowance is enough for one
private quality preview, not daily long-form production.

The manual workflow is in the `astrotobby/AI-GEMS` repository:

**Actions -> Sync Labs Sync-3 free-trial preview -> Run workflow**

Choose one of the existing Kling looks and tick the confirmation only after verifying
that the account still has its free Sync-3 generation available and has no prepaid
balance that could be consumed. The workflow submits exactly one generation and
uploads a private preview artifact. It does not publish to YouTube.

Review the output for natural mouth shapes, jaw/teeth movement, accurate timing,
stable eyes and identity, and natural facial expression before considering production.

## Required API secret

1. Create a free API account and API key from the [Sync Labs dashboard](https://sync.so/).
2. In the `astrotobby/AI-GEMS` GitHub repository, open **Settings -> Secrets and variables -> Actions -> New repository secret**.
3. Name the secret exactly `SYNC_API_KEY` and paste the key as its value.

The smoke-test and scheduled long-form workflows both read this same secret from
AI-GEMS. Do not commit the key to either repository, a config file, or a log.

## Production spending guard

Sync-3 is priced at approximately $0.1066–$0.1334 per generated second (the exact rate
depends on the account plan). A 4.8-second presenter shot therefore has an upper-bound
estimate of about $0.64. A long-form video may contain multiple presenter cuts, and the
pipeline may create both horizontal and vertical masters.

Production API calls are disabled by default. The current config caps the timeline
at two presenter shots per master (opening and closing). Because the workflow renders
both vertical and horizontal masters, that is at most four 4.8-second generations per
long-form video. At the published Sync-3 rate, the raw estimate is `4 × 4.8 × $0.1334 = $2.56`.
The spend guard adds two frames of safety per job, so it reserves up to about $2.61
for a complete long-form run. Actual spend can be lower when shots are shorter. The
free Sync-3 allowance does not cover a complete run.

The long-form workflow requires the AI-GEMS repository variable:

`SYNC_LABS_MAX_SPEND_USD_PER_RUN`

Set it to the maximum amount, in USD, that the complete workflow run may reserve for
Sync-3 calls. It defaults to `0`. With it unset or zero, the pipeline fails its
preflight before making any Sync Labs generation request. The adapter estimates every
shot at the upper published rate, reserves the full batch before submitting the first
job, and blocks any batch that exceeds the remaining run budget. The reservation is
shared across the vertical and horizontal renders in the same Python workflow process.
It never switches to Wav2Lip or unsynchronized presenter footage when blocked.

The variable is a per-workflow-run ceiling, not a monthly quota. With four scheduled
long-form runs per day, a $2.60 ceiling on every run would permit up to about $10.42/day
or $312.48/month in generation usage. For clean, watermark-free published output, Sync Labs
currently requires Creator or higher; Creator is listed at $19/month. That makes this
illustrative upper bound approximately $332/month including the Creator subscription,
before any taxes or currency conversion. Free and Hobbyist outputs have a watermark, so
the free preview is for lip-sync quality evaluation, not a final upload. Keep the variable
at `0` until the free preview has passed visual review and you have explicitly approved
a recurring budget.

## Operational requirements

- Existing Kling MP4 clips and narration WAV excerpts are uploaded directly to the API;
  no public hosting or GPU is needed.
- Local input uploads are kept below 20 MB as a conservative account-compatible limit.
- Sync-3 preview inputs are capped at 15 seconds.
- Each source clip is trimmed to the actual narration excerpt length; frame looping is
  not used to fill a longer audio track.
- The API output is downloaded and checked with ffprobe against the narration duration.
- A missing key, zero/insufficient budget, API error, missing output, or duration mismatch
  blocks the render. There is no unsynchronized fallback.

The long-form YouTube workflow still has its own YouTube OAuth and publishing checks.
This change only replaces the AI influencer lip-sync provider; it does not alter existing
scheduled uploads.

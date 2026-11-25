# Sync Labs Sync-3 setup for the AI influencer

## Why this replaces the local model path

Sync-3 runs on Sync Labs' hosted infrastructure. The long-form runner no longer needs
an NVIDIA GPU, CUDA, a 15 GB checkpoint download, or a dedicated self-hosted GPU
machine. The pipeline continues to use only the two approved Kling presenter clips.

The integration processes each presenter shot against its own narration excerpt. It
does not concatenate unrelated speech, loop/boomerang the Kling source, or fall back
to an unsynchronized face. If the API rejects a job, the render stops.

## Free preview

Sync Labs' free account currently allows one Sync-3 generation per month, up to
15 seconds, with no credit card required. The free allowance is sufficient for one
private 4–5 second quality preview, not daily long-form production.

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

Sync-3 is priced at approximately $0.107–$0.133 per generated second (the exact rate
depends on the account plan). A 4.8-second presenter shot therefore has an upper-bound
estimate of about $0.64. A long-form video may contain multiple presenter cuts, and the
pipeline may create both horizontal and vertical masters.

Production API calls are disabled by default. The long-form workflow requires the
AI-GEMS repository variable:

`SYNC_LABS_MAX_SPEND_USD_PER_RUN`

Set it to the maximum amount, in USD, that the complete workflow run may reserve for
Sync-3 calls. It defaults to `0`. With it unset or zero, the pipeline fails its
preflight before making any Sync Labs request. The adapter estimates every shot at the
upper published rate, reserves the full batch before submitting the first job, and
blocks a batch that exceeds the remaining run budget. It never switches to Wav2Lip or
unsynchronized presenter footage when blocked.

Do not set a positive production budget until the free preview has passed visual review
and you have explicitly approved the expected recurring spend.

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

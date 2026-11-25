# TBDub Student GPU runner setup

## What is free

The TBDub source code and the authors' released Student weights are published under
Apache License 2.0. There is no per-second API fee or required commercial lip-sync
subscription. The inference still consumes GPU compute, electricity, storage and
network bandwidth. Third-party checkpoints and dependencies retain their own licences;
review those terms before monetizing output.

## Hardware requirements

The automated setup deliberately fails before downloading the large model files unless
the runner has:

- Linux and an NVIDIA Ampere-class (compute capability 8.0+) CUDA GPU with native BF16 support
- At least 16 GiB total VRAM and approximately 15 GiB free VRAM
- At least 24 GiB host RAM and approximately 21 GiB available RAM
- At least 26 GB free persistent disk space
- Python 3.10, Git, curl, FFmpeg and CUDA-compatible drivers

A 24 GiB GPU and 32 GiB system RAM are recommended to leave some headroom.
Examples of compatible architectures include NVIDIA A100, RTX 30-series, RTX 40-series,
L4 and newer BF16-capable devices with enough available memory. NVIDIA T4 (compute
capability 7.5) and P100 do not meet TBDub's native BF16 requirement, despite some
free notebook tiers offering those cards. The standard GitHub-hosted `ubuntu-24.04`
runner is CPU-only and cannot execute TBDub.

## Configure the AI-GEMS repository

Register a persistent Linux NVIDIA GPU runner to the `astrotobby/AI-GEMS` repository.
Then configure these repository variables:

1. `LONGFORM_RUNNER_LABELS`: JSON array of labels that identify that runner. Example:
   `["self-hosted","linux","x64","gpu"]`. Use the exact labels assigned to your runner.
2. `TBDUB_CHECKPOINT_DIR`: absolute path to a persistent folder on that runner with at
   least 26 GB free. Model files are downloaded here and are not committed to Git.

The workflow keeps using the ordinary GitHub-hosted CPU runner when
`LONGFORM_RUNNER_LABELS` is unset. The TBDub setup step then fails closed before
downloading weights. It will not silently invoke Wav2Lip or produce an unsynchronized
presenter. No cloud GPU service or paid endpoint is started automatically.

## What the pipeline does

- Uses only the two existing approved Kling video clips in
  `assets/influencer/looks.yaml`.
- Runs TBDub Student (two inference steps) against one matching audio excerpt per
  presenter segment. It never concatenates unrelated narration segments or pre-loops
  the source clip to fill the narration.
- Caps presenter shots at 2.8 seconds so each fits one 72-frame Student stride at 25
  fps. It chooses a deterministic, varied starting frame from the existing Kling clip,
  then verifies at least 72 real source frames remain after that seek. Any segment
  that would require TBDub's internal ping-pong frame padding is rejected.
- Verifies generated video duration against the matching speech excerpt.
- Checks GPU/model availability and MediaPipe face preprocessing before a render.
- Aborts on any missing model, face detection failure, inference error, missing segment,
  or duration mismatch. There is no unsynchronized-video fallback.

## Acceptance gate

The CPU-only unit tests are run by the long-form workflow. Production activation still
requires one private 5–10 second smoke test on the actual GPU runner using existing
Kling footage and a matching narration sample. Inspect the mouth, jaw, teeth, eyes,
identity, motion continuity and audio timing before enabling scheduled production.
Do not publish the test clip. Do not merge the production branch solely because model
download or inference returned exit code zero.

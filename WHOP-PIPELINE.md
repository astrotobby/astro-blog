# Whop Content Rewards pipeline

The repository now includes `scripts/whop_pipeline.py`, a provider-agnostic safety core for the clipping workflow.

## What is implemented

- Strict campaign normalization with HTTPS URL checks.
- Allowed-platform validation.
- Explainable campaign scoring based on platform overlap, creator fit, payout, budget, and rule/material completeness.
- Clip validation against source duration, minimum/maximum duration, allowed platform, captions, and non-overlap.
- Atomic JSON state with `put_once()` idempotency keys.
- Manual Whop submission packet generation with a rules/materials/public-post checklist.
- Unit tests covering the safety layer.

## Run the validator

```bash
python scripts/whop_pipeline.py campaign.json clips.json \
  --source-duration 180 \
  --state .pipeline/state/whop.json \
  --output .pipeline/whop-submission.json
```

`campaign.json` must include a `campaign_id`, `title`, HTTPS `campaign_url`, allowed platforms, and any known requirements/material URLs. `clips.json` may be an array or `{ "clips": [...] }`.

## Make integration contract

The Make scenario should call this core (or an equivalent hosted endpoint) after:

1. Campaign discovery and normalization.
2. Material download/transcript extraction.
3. Clip planning.

The publisher adapter must write `output_url`, `post_url`, and an explicit status of `PUBLISHED`, `DRAFT`, `FAILED`, or `SKIPPED` before the packet is generated. A draft/inbox result must never be reported as a public post.

## Still required for live operation

- A Whop campaign discovery source/API or a permitted public discovery adapter.
- Rotated Supadata and Bookoly credentials stored in secure Make credentials, not inline HTTP headers.
- A real rendering adapter with polling and media QC.
- Authorized social publisher credentials for at least one campaign-approved platform.
- A hosted execution endpoint or GitHub Actions trigger for Make to call the script.

The existing Make scenario remains inactive while those live dependencies are unresolved; the new core is safe to test with fixtures and dry-run publishing.

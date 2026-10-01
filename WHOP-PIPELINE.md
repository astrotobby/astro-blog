# Whop Content Rewards pipeline

The repository now includes `scripts/whop_pipeline.py`, a provider-agnostic safety core for the clipping workflow.

## What is implemented

- Strict campaign normalization with HTTPS URL checks.
- Allowed-platform validation.
- Explainable campaign scoring based on platform overlap, creator fit, payout, budget, and rule/material completeness.
- Clip validation against source duration, minimum/maximum duration, allowed platform, captions, and non-overlap.
- Atomic JSON state with `put_once()` idempotency keys.
- Manual-posting packet generation with a rules/materials checklist and optional post-URL fields.
- An explicit `posting_mode: manual` contract; this core never publishes to social platforms.
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

The posting stage is intentionally **manual**. The automation must stop after rendering and QC. It must return the final clip file URL, caption, hashtags, campaign link, and rules checklist. The user posts the clip manually and then adds the public post URL to Whop.

The packet uses:

```json
{
  "status": "ready_for_manual_posting",
  "posting_mode": "manual",
  "checklist": {
    "manual_posting_required": true,
    "manual_whop_submission_required": true
  }
}
```

No social publisher credentials are needed for this mode. `post_url` remains empty until the user posts the clip. A future publisher must not be added without changing this contract explicitly.

## Still required for live operation

- A Whop campaign discovery source/API or a permitted public discovery adapter.
- Rotated Supadata and Bookoly credentials stored in secure Make credentials, not inline HTTP headers.
- A real rendering adapter with polling and media QC.
- A hosted execution endpoint or GitHub Actions trigger for Make to call the script.

The existing Make scenario remains inactive while those live dependencies are unresolved; the new core is safe to test with fixtures. The intended live flow ends at **manual social posting**, followed by **manual Whop submission**.

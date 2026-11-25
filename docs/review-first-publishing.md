# Review-first article publishing

## What this adds

The Make scenario can write generated articles into `review-queue/` instead of the live `src/content/blog/` folder. A GitHub Action validates each queued Markdown article using the repository's existing `scripts/blog_quality.py` rules, then opens or updates a **draft pull request** that moves the article into the live content folder. The website is not changed by the draft PR. Only a human-approved merge publishes the article and starts the existing downstream blog-to-video and social-pack workflows.

The GitHub workflow in `.github/workflows/blog-review-queue.yml` is intentionally limited to pushes to `main` under `review-queue/`. It never merges its own PR. It refuses to overwrite an article whose slug already exists in the live blog.

## Make scenario change to make after this PR is approved

The current `YouTube → Blog (Gemini)` scenario is paused. Keep it paused while editing and testing it. In the blueprint:

1. In the GitHub Contents API module (`Publish to GitHub`), change the destination from `src/content/blog/{{9.slug}}.md` to `review-queue/{{9.slug}}.md`.
2. Change the commit message to say it is a draft queued for review, not a published post.
3. In the datastore record, replace `status: published` with `status: pending-review`. Keep the video ID as the dedup key so the same source is not regenerated on every polling run.
4. Keep the scenario's existing three-article daily cap and 3-hour polling cadence for the first test. Do not turn the scenario on until a test article has produced a valid draft PR and a human has verified the PR/merge behavior.

This does not add the video tutorial's Blogger, AlphaPost, or Bluesky services. It retains Astro Signal, the existing YouTube-source pipeline, and existing downstream processing.

## Editorial review

The validator checks required frontmatter, title/description length, the supported tag list, a 3–8-word slug, a 600–1,200-word body, required headings, and leaked model labels. These are structural checks, not fact-checking. A reviewer must verify claims against the source video, remove invented or misleading statements, check image suitability and rights, and review attribution before merging.

## Posting cadence and platform scope

This queue gates publication of blog articles; it does not itself schedule five social posts per day. The Make scenario currently generates at most three articles per day. The repository already regenerates social packs when a live blog article changes and has a separate long-form video social bridge, but this PR does not enable or change public publishing to Instagram, Threads, Facebook profile/page, or Bluesky. Keep those platform schedules and account choices as a separate reviewed change; do not raise cadence or enable public distribution as part of this PR.

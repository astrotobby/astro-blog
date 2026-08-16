"""Stage 4: cross-post the rendered videos via direct official APIs (no server).

Automated free, no app review:  YouTube + Tumblr + Reddit + X (capped) + Pinterest.
Deferred (need platform app review): Instagram / Facebook / LinkedIn
  -> the workflow saves the rendered Reels as artifacts for hand-upload.

Keeps a content-hash dedup ledger and per-platform daily caps, both persisted
across GitHub Action runs (.pipeline/state, cached by the workflow).

Usage:
  python scripts/crosspost.py .pipeline/render.json [--dry-run] [--force]
"""
import argparse
import datetime as dt
import json

import platforms
from common import (STATE, content_hash, load_config, load_ledger, log,
                    normalize_title, read_json, save_ledger, write_json)

COUNTS = STATE / "post_counts.json"


# ---------- daily cap bookkeeping (persisted in STATE) ----------
def _load_counts():
    today = dt.date.today().isoformat()
    if COUNTS.exists():
        data = json.loads(COUNTS.read_text())
        if data.get("date") == today:
            return data
    return {"date": today, "counts": {}}


def _bump(state, key):
    state["counts"][key] = state["counts"].get(key, 0) + 1
    COUNTS.write_text(json.dumps(state, indent=2))


def _under_cap(state, key, cap):
    return state["counts"].get(key, 0) < cap


def _prior_ok(prior, chash, key, dry, force):
    """True only when this exact content already succeeded on this destination."""
    if dry or force or not prior or prior.get("hash") != chash:
        return False
    result = (prior.get("results") or {}).get(key) or {}
    return result.get("ok") is True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("render_json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="ignore dedup ledger")
    args = ap.parse_args()
    cfg = load_config()
    render = read_json(args.render_json)
    post = render["post"]

    # ----- dedup/retry: preserve successes, retry only failed destinations -----
    chash = content_hash(post["slug"], post["title"], post["description"])
    ledger = load_ledger()
    prior = ledger.get(post["slug"])
    prior_results = (prior or {}).get("results") or {}
    if prior and prior.get("hash") == chash and not args.dry_run and not args.force:
        retryable = any(
            isinstance(result, dict) and result.get("error")
            for result in prior_results.values())
        if not retryable:
            log(f"already posted '{post['slug']}' (hash {chash}); skipping. Use --force to repost.")
            write_json("results.json", {"post": post, "results": prior_results,
                                        "skipped": "duplicate"})
            return
        log(f"retrying failed destinations for '{post['slug']}' without reposting prior successes")

    state = _load_counts()
    results = dict(prior_results) if prior and prior.get("hash") == chash and not args.force else {}
    enabled = set(cfg["platforms"].get("direct", []))

    # ----- YouTube (own module: handles main + optional Short) -----
    if (cfg["platforms"]["youtube"]["enabled"]
            and (not _prior_ok(prior, chash, "youtube", args.dry_run, args.force)
                 or (cfg["platforms"]["youtube"].get("also_short")
                     and not _prior_ok(prior, chash, "youtube_short", args.dry_run, args.force)))):
        try:
            results.update(platforms.post_youtube(render, cfg, args.dry_run))
        except Exception as e:  # noqa
            results["youtube"] = {"ok": False, "error": str(e)}

    # ----- Tumblr (no cap) -----
    if ("tumblr" in enabled
            and not _prior_ok(prior, chash, "tumblr", args.dry_run, args.force)):
        results["tumblr"] = platforms.post_tumblr(render, cfg, args.dry_run)

    also_story = cfg["platforms"].get("also_story", True)

    # ----- Facebook Page (no cap) + Story (TikTok has no Stories API) -----
    if "facebook" in enabled:
        if not _prior_ok(prior, chash, "facebook", args.dry_run, args.force):
            results["facebook"] = platforms.post_facebook(render, cfg, args.dry_run)
        if (also_story and not _prior_ok(prior, chash, "facebook_story", args.dry_run, args.force)):
            results["facebook_story"] = platforms.post_facebook_story(render, cfg, args.dry_run)

    # ----- Instagram (reuses FB token; needs a public video URL via GitHub Release) + Story -----
    if "instagram" in enabled:
        if not _prior_ok(prior, chash, "instagram", args.dry_run, args.force):
            results["instagram"] = platforms.post_instagram(render, cfg, args.dry_run)
        if (also_story and not _prior_ok(prior, chash, "instagram_story", args.dry_run, args.force)):
            results["instagram_story"] = platforms.post_instagram_story(render, cfg, args.dry_run)

    # ----- Threads (no cap; needs a public video URL via GitHub Release) -----
    if ("threads" in enabled
            and not _prior_ok(prior, chash, "threads", args.dry_run, args.force)):
        results["threads"] = platforms.post_threads(render, cfg, args.dry_run)

    # ----- TikTok (draft/inbox mode; no cap) -----
    if ("tiktok" in enabled
            and not _prior_ok(prior, chash, "tiktok", args.dry_run, args.force)):
        results["tiktok"] = platforms.post_tiktok(render, cfg, args.dry_run)

    # ----- Rumble (browser automation; no official API; no cap) -----
    if ("rumble" in enabled
            and not _prior_ok(prior, chash, "rumble", args.dry_run, args.force)):
        results["rumble"] = platforms.post_rumble(render, cfg, args.dry_run)

    # ----- X / Twitter (daily cap) -----
    if "x" in enabled and not _prior_ok(prior, chash, "x", args.dry_run, args.force):
        if _under_cap(state, "x", cfg["limits"]["x_per_day"]):
            results["x"] = platforms.post_twitter(render, cfg, args.dry_run)
            if not args.dry_run and results["x"].get("ok"):
                _bump(state, "x")
        else:
            results["x"] = {"ok": False, "skipped": "daily cap reached"}

    # ----- Reddit (opt-in + daily cap; off by default, see HONEST-LIMITS.md) -----
    if ("reddit" in enabled and cfg["limits"].get("reddit_enabled")
            and not _prior_ok(prior, chash, "reddit", args.dry_run, args.force)):
        if _under_cap(state, "reddit", cfg["limits"]["reddit_per_day"]):
            results["reddit"] = platforms.post_reddit(render, cfg, args.dry_run)
            if not args.dry_run and results["reddit"].get("ok"):
                _bump(state, "reddit")
        else:
            results["reddit"] = {"ok": False, "skipped": "daily cap reached"}

    # ----- Pinterest (pin the post hero image; no cap) -----
    if ("pinterest" in enabled
            and not _prior_ok(prior, chash, "pinterest", args.dry_run, args.force)):
        results["pinterest"] = platforms.post_pinterest(render, cfg, args.dry_run)

    # ----- record in ledger -----
    if not args.dry_run:
        ledger[post["slug"]] = {"hash": chash, "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                                "title_key": normalize_title(post["title"]),
                                "results": results}
        save_ledger(ledger)

    summary = {"post": post, "results": results}
    for plat, r in results.items():
        flag = "OK " if r.get("ok") else "FAIL"
        log(f"  [{flag}] {plat}: {r.get('url') or r.get('error') or r.get('skipped') or ''}")
    write_json("results.json", summary)


if __name__ == "__main__":
    main()

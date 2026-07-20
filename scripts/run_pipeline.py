"""Orchestrator: runs all stages in order. This is what the GitHub Action calls.

Source-agnostic: it processes EVERY new blog post that went live in this push,
no matter which Make scenario (or anything else) committed it. If a single push
adds several posts, each is rendered + cross-posted in turn — none are dropped.

Usage:
  python scripts/run_pipeline.py --latest
  python scripts/run_pipeline.py --changed file1 file2 ...
  python scripts/run_pipeline.py --latest --dry-run
"""
import argparse
import re
import subprocess
import sys

from common import (PIPE, ROOT, find_duplicate_title, load_config, load_ledger,
                    log, normalize_title, save_ledger)

PY = sys.executable
S = ROOT / "scripts"

# Hard cap on how many not-yet-posted articles a single run will render+post.
# crosspost.py posts to ~10 platforms sequentially, several with multi-minute
# worst-case waits (Threads/Instagram processing polls, Rumble browser upload) —
# an unbounded sweep over a big backlog can blow the job's timeout-minutes. When
# GitHub Actions hard-cancels a timed-out job, the cache save (which persists the
# dedup ledger across runs) does NOT run, so every post that succeeded earlier in
# that same run gets reprocessed (== reposted/duplicated) on the next trigger,
# while posts further back in the backlog never get reached. Capping guarantees
# each run finishes well inside the timeout and hands off a shrinking backlog to
# the next trigger instead of risking losing a whole run's progress.
# Measured 2026-07-02: one post = ~17 min sequential (~14 with threaded image
# fetch), so 3 posts + setup fits the 60-min budget with margin; 6 did not.
MAX_POSTS_PER_RUN = 3


def step(args):
    log("RUN " + " ".join(str(a) for a in args))
    subprocess.run([PY, *[str(a) for a in args]], check=True, cwd=str(ROOT))


def list_posts(changed):
    """Ask fetch_post which changed files are posts to process (oldest->newest)."""
    cmd = [PY, str(S / "fetch_post.py"), "--list"]
    cmd += (["--changed", *changed] if changed else [])
    out = subprocess.run(cmd, check=True, cwd=str(ROOT),
                         capture_output=True, text=True).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def prime_ledger():
    """Baseline: mark EVERY post currently on the site as already-posted, WITHOUT
    rendering or posting anything. Run once so the backlog never gets auto-published —
    only posts that go live AFTER this will be processed."""
    import datetime as dt
    import pathlib
    from fetch_post import parse
    from common import content_hash, load_ledger, save_ledger
    cfg = load_config()
    out = subprocess.run([PY, str(S / "fetch_post.py"), "--list", "--all"],
                         check=True, cwd=str(ROOT), capture_output=True, text=True).stdout
    files = [ln.strip() for ln in out.splitlines() if ln.strip()]
    led = load_ledger()
    n = 0
    for fp in files:
        try:
            post = parse(pathlib.Path(fp), cfg)
        except Exception as e:  # noqa
            log(f"prime: skip {fp} ({e})")
            continue
        led[post["slug"]] = {
            "hash": content_hash(post["slug"], post["title"], post["description"]),
            "title_key": normalize_title(post["title"]),
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(), "primed": True,
        }
        n += 1
    save_ledger(led)
    log(f"primed ledger with {n} existing posts — none of these will be (re)posted")


def _astro_slug(stem: str) -> str:
    """Delegate to fetch_post.astro_slug so the sweep's slug ALWAYS matches the ledger
    key. (A local copy drifted — it hyphenated underscores while the ledger keeps them —
    causing the sweep to re-select underscore-filename posts forever -> repeat Telegrams.)"""
    from fetch_post import astro_slug
    return astro_slug(stem)


def sweep_posts():
    """Every post on the site (= in the repo) that isn't in the dedup ledger yet.
    Catches anything that goes live by ANY route (any Make scenario, manual commit,
    backfill, or a push that didn't fire the trigger) — not just the latest push."""
    cmd = [PY, str(S / "fetch_post.py"), "--list", "--all"]
    out = subprocess.run(cmd, check=True, cwd=str(ROOT),
                         capture_output=True, text=True).stdout
    allp = [ln.strip() for ln in out.splitlines() if ln.strip()]
    led = load_ledger()
    import pathlib
    new = [p for p in allp if _astro_slug(pathlib.Path(p).stem) not in led]
    log(f"sweep: {len(allp)} live posts, {len(new)} not yet posted")
    return new


def _prepare_run(posts, force):
    """Two safety nets applied to the candidate post list, in order:

    1) Title-dedup: the autoblog content pipeline has twice republished the same
       story under a brand-new filename/slug (see git history: c578994, 6b13849).
       Since the ledger keys on slug, those looked "new" and got a second video +
       cross-post. Catch that here by fuzzy-matching against every already-posted
       title, BEFORE spending time rendering. Matches are recorded in the ledger
       under their own slug (so they're not retried every run) but never posted.
    2) Per-run cap (MAX_POSTS_PER_RUN): guarantees this run can't blow the job
       timeout and lose a whole run's ledger writes (see MAX_POSTS_PER_RUN docstring).
       Posts are already oldest-first, so this always makes forward progress and
       hands the rest to the next trigger.
    """
    import datetime as dt
    import pathlib

    from fetch_post import parse
    if force:
        return posts[:MAX_POSTS_PER_RUN]
    cfg = load_config()
    led = load_ledger()
    keep = []
    for pf in posts:
        try:
            title = parse(pathlib.Path(pf), cfg)["title"]
        except Exception as e:  # noqa
            log(f"dedup-check: could not parse {pf} ({e}); keeping it in the run")
            keep.append(pf)
            continue
        dup_of = find_duplicate_title(title, led)
        if dup_of:
            slug = _astro_slug(pathlib.Path(pf).stem)
            log(f"skip '{pf}': title matches already-posted '{dup_of}' "
                f"(likely a republish of the same story) -> not rendering/posting")
            led[slug] = {"title_key": normalize_title(title),
                        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "skipped_duplicate_of": dup_of}
        else:
            keep.append(pf)
    save_ledger(led)
    if len(keep) > MAX_POSTS_PER_RUN:
        log(f"{len(keep)} posts are due; processing the oldest {MAX_POSTS_PER_RUN} this "
            f"run, {len(keep) - MAX_POSTS_PER_RUN} will roll to the next trigger")
    return keep[:MAX_POSTS_PER_RUN]


def process_one(post_file, dry, force=False):
    step([S / "fetch_post.py", "--file", post_file])
    step([S / "build_script.py", PIPE / "post.json"])
    step([S / "generate_video.py", PIPE / "script.json"])
    cross = [S / "crosspost.py", PIPE / "render.json"]
    if dry:
        cross += ["--dry-run"]
    if force:
        cross += ["--force"]
    step(cross)
    try:
        step([S / "notify.py", PIPE / "results.json"])
    except Exception as e:  # noqa
        log(f"notify failed (non-fatal): {e}")


def unskip_duplicates():
    """Ledger repair: forget entries recorded only as skipped_duplicate_of (the
    over-loose dedup of run 28570465256 wrongly skipped unrelated posts). They
    then look unposted again and the normal sweep/latest path picks them up
    under the fixed matcher."""
    led = load_ledger()
    bad = [s for s, e in led.items()
           if e.get("skipped_duplicate_of") and not e.get("results")]
    for s in bad:
        del led[s]
        log(f"unskip: removed wrongly-skipped ledger entry '{s}'")
    if bad:
        save_ledger(led)
    log(f"unskip: {len(bad)} entry(ies) removed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--changed", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="ignore the dedup ledger and repost (for testing)")
    ap.add_argument("--sweep", action="store_true",
                    help="process every live post not yet in the ledger (manual safety net)")
    ap.add_argument("--prime", action="store_true",
                    help="baseline: mark all current posts as done WITHOUT posting (run once)")
    ap.add_argument("--unskip", action="store_true",
                    help="repair ledger first: forget skipped-as-duplicate entries")
    args = ap.parse_args()

    if args.unskip:
        unskip_duplicates()

    if args.prime:
        prime_ledger()
        return

    if args.sweep:
        posts = sweep_posts()
    else:
        posts = list_posts(args.changed if args.changed else None)
    if not posts:
        log("no new posts to process — exiting cleanly")
        return

    posts = _prepare_run(posts, args.force)
    if not posts:
        log("nothing left to process after dedup — exiting cleanly")
        return

    log(f"{len(posts)} post(s) went live this run")
    failures = 0
    for i, pf in enumerate(posts, 1):
        log(f"=== post {i}/{len(posts)}: {pf} ===")
        try:
            process_one(pf, args.dry_run, args.force)
        except Exception as e:  # noqa
            failures += 1
            log(f"post failed (continuing with the rest): {e}")

    if failures:
        raise SystemExit(f"{failures}/{len(posts)} post(s) failed")


if __name__ == "__main__":
    main()

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

from common import PIPE, ROOT, load_config, load_ledger, log

PY = sys.executable
S = ROOT / "scripts"


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
            "ts": dt.datetime.utcnow().isoformat(), "primed": True,
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
    args = ap.parse_args()

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

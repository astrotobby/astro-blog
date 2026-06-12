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
import subprocess
import sys

from common import PIPE, ROOT, log

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


def process_one(post_file, dry):
    step([S / "fetch_post.py", "--file", post_file])
    step([S / "build_script.py", PIPE / "post.json"])
    step([S / "generate_video.py", PIPE / "script.json"])
    cross = [S / "crosspost.py", PIPE / "render.json"]
    if dry:
        cross += ["--dry-run"]
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
    args = ap.parse_args()

    posts = list_posts(args.changed if args.changed else None)
    if not posts:
        log("no new posts to process — exiting cleanly")
        return

    log(f"{len(posts)} post(s) went live this run")
    failures = 0
    for i, pf in enumerate(posts, 1):
        log(f"=== post {i}/{len(posts)}: {pf} ===")
        try:
            process_one(pf, args.dry_run)
        except Exception as e:  # noqa
            failures += 1
            log(f"post failed (continuing with the rest): {e}")

    if failures:
        raise SystemExit(f"{failures}/{len(posts)} post(s) failed")


if __name__ == "__main__":
    main()

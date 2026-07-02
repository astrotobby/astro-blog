"""Stage 1: find the new/changed blog post and parse it.

Usage:
  python scripts/fetch_post.py --latest         # most recently modified post
  python scripts/fetch_post.py --file PATH       # a specific file
  python scripts/fetch_post.py --changed A B ... # files from the Action diff
"""
import argparse
import pathlib
import re

import frontmatter
from markdown_it import MarkdownIt

from common import ROOT, git_added_times, load_config, log, write_json

md = MarkdownIt()


def _sort_key(files, posts_dir):
    """Order files by real publish time (git history), not filesystem mtime —
    actions/checkout resets mtimes to checkout time, which made 'latest'/sweep
    ordering effectively arbitrary on a fresh CI runner."""
    added = git_added_times(posts_dir)
    def key(p):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        ts = added.get(rel)
        return ts if ts is not None else p.stat().st_mtime
    return sorted(files, key=key)


def astro_slug(stem: str) -> str:
    """Match Astro 5 glob-loader id generation: lowercase, strip punctuation,
    spaces -> hyphens. IMPORTANT: Astro KEEPS underscores (the live URLs are e.g.
    '...top_multi_agent_ai...'), so we must NOT convert '_' to '-' — doing so 404s
    the link. Hyphens and underscores are both preserved as-is."""
    s = stem.lower()
    s = re.sub(r"[^\w\s-]", "", s)      # drop apostrophes, colons, parens, em-dashes, etc.
    s = re.sub(r"\s+", "-", s)           # spaces -> hyphen (underscores left intact)
    s = re.sub(r"-{2,}", "-", s)         # collapse repeated hyphens
    return s.strip("-")


def strip_md(text: str) -> str:
    html = md.render(text)
    plain = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", plain).strip()


def pick_latest(cfg) -> pathlib.Path:
    posts_dir = ROOT / cfg["posts_dir"]
    exts = set(cfg["post_extensions"])
    files = [p for p in posts_dir.rglob("*") if p.suffix in exts]
    if not files:
        raise SystemExit(f"no posts found in {posts_dir}")
    return _sort_key(files, posts_dir)[-1]


def parse(path: pathlib.Path, cfg) -> dict:
    fm = frontmatter.load(path)
    keys = cfg["frontmatter"]
    body = strip_md(fm.content)
    title = fm.get(keys["title"]) or path.stem.replace("-", " ").title()
    desc = fm.get(keys["description"]) or body[:280]
    # Astro routes /blog/<post.id>, where id is the slugified filename (no
    # frontmatter slug in these posts), so derive the URL slug the same way.
    slug = fm.get(keys["slug"]) or astro_slug(path.stem)
    tags = fm.get(keys["tags"]) or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    url = cfg["site"]["post_url_pattern"].format(
        base=cfg["site"]["base_url"].rstrip("/"), slug=slug
    )
    raw_image = fm.get("image") or ""
    base = cfg["site"]["base_url"].rstrip("/")
    image_url = (raw_image if raw_image.startswith("http")
                 else f"{base}{raw_image}") if raw_image else ""
    return {
        "file": str(path.relative_to(ROOT)),
        "title": str(title).strip(),
        "description": str(desc).strip(),
        "slug": str(slug),
        "tags": tags,
        "url": url,
        "body": body,
        "image_url": image_url,
    }


def changed_posts(cfg, changed):
    """Every changed file that is a blog post, oldest->newest. Source-agnostic:
    it doesn't care which Make scenario committed it, only that a post went live."""
    exts = set(cfg["post_extensions"])
    posts_dir = (ROOT / cfg["posts_dir"]).resolve()
    cand = [
        (ROOT / c).resolve()
        for c in changed
        if pathlib.Path(c).suffix in exts
        and str((ROOT / c).resolve()).startswith(str(posts_dir))
    ]
    return _sort_key(cand, posts_dir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--changed", nargs="*")
    ap.add_argument("--list", action="store_true",
                    help="print matching post paths (one/line) instead of parsing")
    ap.add_argument("--all", action="store_true",
                    help="with --list: every post on the site (oldest->newest), for the sweep")
    args = ap.parse_args()
    cfg = load_config()

    # --list: enumerate the posts to process; the orchestrator loops over these.
    if args.list:
        if args.all:
            exts = set(cfg["post_extensions"])
            pd = ROOT / cfg["posts_dir"]
            files = _sort_key([p for p in pd.rglob("*") if p.suffix in exts], pd)
        elif args.changed:
            files = changed_posts(cfg, args.changed)
        else:
            files = [pick_latest(cfg)]
        for f in files:
            print(str(f))
        if not files:
            log("no changed files are blog posts; nothing to do")
        return

    if args.file:
        path = (ROOT / args.file).resolve()
    elif args.changed:
        cand = changed_posts(cfg, args.changed)
        if not cand:
            log("no changed files are blog posts; nothing to do")
            raise SystemExit(0)
        path = cand[-1]  # newest
    else:
        path = pick_latest(cfg)

    post = parse(path, cfg)
    log(f"post: {post['title']}  ({post['url']})")
    write_json("post.json", post)


if __name__ == "__main__":
    main()

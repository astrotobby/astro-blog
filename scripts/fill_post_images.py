"""Fill a header image for posts that only carry an `imageQuery:` front-matter line.

The YouTube -> blog Make scenario can't reach the PEXELS_API_KEY GitHub secret, so it
publishes posts with a placeholder `image:` plus `imageQuery: "..."`. This script
looks the query up on Pexels, rewrites the `image:` line and drops `imageQuery:`.
Only those two lines change, so the rest of the front matter stays byte-identical.

Usage: python scripts/fill_post_images.py [post.md ...]   (no args = every post)
"""
import json
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
POSTS = ROOT / "src" / "content" / "blog"
QUERY_RE = re.compile(r'^imageQuery:\s*"?(.*?)"?\s*$', re.M)
IMAGE_RE = re.compile(r"^image:.*$", re.M)


def pexels_image(query, api_key):
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "per_page": 1})
    request = urllib.request.Request(url, headers={"Authorization": api_key,
                                                   "User-Agent": "astro-blog-images"})
    with urllib.request.urlopen(request, timeout=30) as response:
        photos = json.load(response).get("photos") or []
    return photos[0]["src"]["landscape"] if photos else None


def fill(path, api_key):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end < 0:
        return False
    front, rest = text[:end], text[end:]
    match = QUERY_RE.search(front)
    if not match:
        return False
    image = None
    if match.group(1).strip():
        try:
            image = pexels_image(match.group(1).strip(), api_key)
        except Exception as exc:  # noqa
            print(f"{path.name}: Pexels lookup failed ({exc}); keeping placeholder image")
    if image:
        front = IMAGE_RE.sub(f'image: "{image}"', front, count=1)
    front = QUERY_RE.sub("", front).replace("\n\n", "\n")
    path.write_text(front + rest, encoding="utf-8")
    print(f"{path.name}: image -> {image or 'placeholder'}")
    return True


def main():
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if not api_key:
        print("PEXELS_API_KEY not set; nothing to do")
        return 0
    files = [pathlib.Path(a) for a in sys.argv[1:]] or sorted(POSTS.glob("*.md"))
    changed = [f for f in files if f.exists() and f.suffix in (".md", ".mdx") and fill(f, api_key)]
    print(f"{len(changed)} post(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Shared helpers: config, env, paths, logging, persistent state."""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
PIPE = ROOT / ".pipeline"
OUT = PIPE / "out"
# STATE survives across GitHub Action runs via actions/cache (see workflow).
# Holds the dedup ledger and per-platform daily counters.
STATE = PIPE / "state"
PIPE.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)
STATE.mkdir(parents=True, exist_ok=True)


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8"))
    return h.hexdigest()[:16]


def normalize_title(title: str) -> str:
    """Lowercase, punctuation-stripped title key used for cross-slug dedup.
    The autoblog content pipeline has twice republished the same story under a
    new filename/timestamp (see git history) -> the dedup ledger, which is keyed
    by slug, never caught those. Comparing normalized titles catches it too."""
    t = re.sub(r"[^\w\s]", "", (title or "").lower())
    return re.sub(r"\s+", " ", t).strip()


# Boilerplate words carry no identity: two unrelated "What Is X in 2026" posts on
# an AI blog overlap heavily through these alone. Run 28570465256 skipped 4 posts
# this way, 3 of them unrelated (incl. the Claude Fable 5 article, which "matched"
# an always-on-AI post through {what,is,ai,in,2026}). Only DISTINCTIVE words may
# vote on duplicate identity.
_GENERIC_TITLE_WORDS = set(
    "what is are was were how why when which who the a an in on of for to and or vs "
    "versus guide explained explainer complete ultimate best top new its it your you "
    "here heres difference between everything need know really actually ai 2024 2025 "
    "2026 2027".split())


def _title_core(key: str) -> set:
    return {w for w in key.split() if w not in _GENERIC_TITLE_WORDS}


def find_duplicate_title(title: str, ledger: dict, threshold: float = 0.8):
    """Return the slug of an already-posted entry covering the same underlying
    story as `title`, or None. Word-SET overlap (order-invariant, since the
    autoblog LLM rewrites headlines from scratch) — but computed over DISTINCTIVE
    words only, with generic headline filler stripped, so republished stories are
    still caught ("AI Automation for Small Business..." ~ "AI Automation Small
    Business 2026") while unrelated posts sharing boilerplate are not. Both
    titles need >=3 distinctive words to be judged at all, and entries that were
    themselves skipped as duplicates don't vote (no cascading skips)."""
    core = _title_core(normalize_title(title))
    if len(core) < 3:
        return None
    for slug, entry in ledger.items():
        if entry.get("skipped_duplicate_of"):
            continue
        prev = entry.get("title_key")
        if not prev:
            continue
        prev_core = _title_core(prev)
        if len(prev_core) < 3:
            continue
        inter = core & prev_core
        if len(inter) >= 3 and len(inter) / min(len(core), len(prev_core)) >= threshold:
            return slug
    return None


def git_added_times(rel_dir) -> dict:
    """Map of relative-path -> unix timestamp of the commit that (most recently)
    added that file, built from one `git log` scan. actions/checkout resets every
    checked-out file's mtime to the checkout time, so filesystem mtime can't be
    trusted to reconstruct real publish order on a fresh CI runner -> use git
    history instead. Falls back to an empty map (callers fall back to mtime) if
    git isn't available (e.g. no .git, shallow/unusual checkout)."""
    times = {}
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--name-only",
             "--format=%x00%at", "--", str(rel_dir)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        ts = None
        for line in out.stdout.splitlines():
            if line.startswith("\x00"):
                ts = line[1:].strip()
            elif line.strip():
                # git log is newest-first; keep the first (=newest) timestamp seen
                # per path so a file re-added after a delete uses its latest add.
                times.setdefault(line.strip().replace("\\", "/"), float(ts) if ts else None)
    except Exception:  # noqa
        pass
    return times


def load_ledger() -> dict:
    p = STATE / "processed.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_ledger(led: dict) -> None:
    (STATE / "processed.json").write_text(
        json.dumps(led, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def ig_token() -> str:
    """The current Instagram token: the auto-refreshed one kept in the state cache
    (STATE/ig_token.txt) if present, else the INSTAGRAM_TOKEN secret (the seed).
    The daily refresh job rolls ig_token.txt so the token never expires."""
    p = STATE / "ig_token.txt"
    if p.exists():
        t = p.read_text(encoding="utf-8").strip()
        if t:
            return t
    return env("INSTAGRAM_TOKEN")


def tiktok_refresh_token() -> str:
    """Current TikTok refresh token: the rotated one in the state cache
    (STATE/tt_refresh.txt) if present, else the TIKTOK_REFRESH_TOKEN secret seed."""
    p = STATE / "tt_refresh.txt"
    if p.exists():
        t = p.read_text(encoding="utf-8").strip()
        if t:
            return t
    return env("TIKTOK_REFRESH_TOKEN")


def save_tiktok_refresh(tok: str) -> None:
    """TikTok rotates the refresh token on each use — persist the newest so the
    chain survives forever (cache is restored every run)."""
    if tok:
        (STATE / "tt_refresh.txt").write_text(tok.strip() + "\n", encoding="utf-8")


def load_config() -> dict:
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def load_dotenv() -> None:
    """Tiny .env loader so local runs work without extra deps."""
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def shorten_url(url: str) -> str:
    """Shorten a URL with a free, no-key service: TinyURL, then is.gd, then v.gd.
    A real User-Agent is required or is.gd's Cloudflare returns 403. Returns the
    original URL on any failure so a post never breaks over a shortener hiccup."""
    import urllib.parse
    import urllib.request
    if not url:
        return url
    enc = urllib.parse.quote(url, safe="")
    apis = [
        f"https://tinyurl.com/api-create.php?url={enc}",
        f"https://is.gd/create.php?format=simple&url={enc}",
        f"https://v.gd/create.php?format=simple&url={enc}",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (blog-to-video link shortener)"}
    for api in apis:
        try:
            req = urllib.request.Request(api, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                short = r.read().decode().strip()
            if short.startswith("http") and " " not in short:
                return short
        except Exception:  # noqa
            continue
    return url


def read_json(path) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def write_json(name: str, data: dict) -> pathlib.Path:
    p = PIPE / name
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote {p.relative_to(ROOT)}")
    return p


def log(msg: str) -> None:
    print(f"[blog2video] {msg}", file=sys.stderr, flush=True)


load_dotenv()

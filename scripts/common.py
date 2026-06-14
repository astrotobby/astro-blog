"""Shared helpers: config, env, paths, logging, persistent state."""
import hashlib
import json
import os
import pathlib
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


def load_ledger() -> dict:
    p = STATE / "processed.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_ledger(led: dict) -> None:
    (STATE / "processed.json").write_text(
        json.dumps(led, indent=2, ensure_ascii=False), encoding="utf-8"
    )


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

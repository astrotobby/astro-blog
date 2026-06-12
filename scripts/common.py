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

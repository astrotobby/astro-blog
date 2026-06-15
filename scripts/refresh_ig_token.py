"""Daily: refresh the Instagram long-lived token and keep it in the pipeline state
cache so it lasts FOREVER — no Personal Access Token, no secret writes.

Self-contained (stdlib only) so the refresh job needs no pip installs. Reads the
current token from .pipeline/state/ig_token.txt (or the INSTAGRAM_TOKEN secret seed
on the first run), calls ig_refresh_token (extends ~60 days), writes the new token
back. The state dir is cached across runs and the daily schedule keeps it warm, so
the chain never breaks.
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

STATE = pathlib.Path(__file__).resolve().parents[1] / ".pipeline" / "state"
STATE.mkdir(parents=True, exist_ok=True)


def _get(url, params):
    q = urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(f"{url}?{q}", timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:  # noqa
            return {"error": f"HTTP {e.code}"}


def main():
    p = STATE / "ig_token.txt"
    cur = (p.read_text(encoding="utf-8").strip() if p.exists() else "") \
        or os.environ.get("INSTAGRAM_TOKEN", "")
    if not cur:
        print("[ig-refresh] no token to refresh (no cache, no INSTAGRAM_TOKEN seed)")
        return
    r = _get("https://graph.instagram.com/refresh_access_token",
             {"grant_type": "ig_refresh_token", "access_token": cur})
    new = r.get("access_token")
    if not new:
        print("[ig-refresh] refresh FAILED:", json.dumps(r))
        sys.exit(1)
    p.write_text(new + "\n", encoding="utf-8")
    print(f"[ig-refresh] token refreshed; valid ~{r.get('expires_in', 0) // 86400} days "
          f"(stored in state cache, self-renewing)")


if __name__ == "__main__":
    main()

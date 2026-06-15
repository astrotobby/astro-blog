"""Daily: refresh the Instagram long-lived token and keep it in the pipeline state
cache so it lasts FOREVER — no Personal Access Token, no secret writes.

Reads the current token from STATE/ig_token.txt (or the INSTAGRAM_TOKEN secret seed
on the very first run), calls ig_refresh_token (extends it ~60 days), and writes the
new token back to STATE/ig_token.txt. The state dir is cached across Action runs, and
the daily schedule keeps that cache warm, so the chain never breaks.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from common import STATE, env, log


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
    cur = (p.read_text(encoding="utf-8").strip() if p.exists() else "") or env("INSTAGRAM_TOKEN")
    if not cur:
        log("no Instagram token available to refresh (no cache, no INSTAGRAM_TOKEN seed)")
        return
    r = _get("https://graph.instagram.com/refresh_access_token",
             {"grant_type": "ig_refresh_token", "access_token": cur})
    new = r.get("access_token")
    if not new:
        log("IG refresh failed: " + json.dumps(r))
        raise SystemExit(1)
    p.write_text(new + "\n", encoding="utf-8")
    log(f"IG token refreshed; valid ~{r.get('expires_in', 0) // 86400} days "
        f"(stored in state cache, self-renewing)")


if __name__ == "__main__":
    main()

"""Daily: roll the Threads and Pinterest tokens in the pipeline state cache.

Same idea as refresh_ig_token.py: the secret is only the seed; each day the current
token is exchanged for a fresh one and written to .pipeline/state, so it never
reaches its expiry. Platforms without credentials are skipped. Stdlib only.

- Threads: long-lived token (60 days) -> th_refresh_token.
- Pinterest: access token (30 days) from the refresh token (PINTEREST_REFRESH_TOKEN +
  PINTEREST_APP_ID + PINTEREST_APP_SECRET); Pinterest may also rotate the refresh token.
"""
import base64
import hashlib
import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request

STATE = pathlib.Path(__file__).resolve().parents[1] / ".pipeline" / "state"
STATE.mkdir(parents=True, exist_ok=True)


def _call(url, params=None, data=None, headers=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = urllib.parse.urlencode(data).encode() if data else None
    request = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode())
        except Exception:  # noqa
            return {"error": f"HTTP {exc.code}"}


def _current(filename, secret):
    path = STATE / filename
    cached = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    return cached or os.environ.get(secret, "")


def refresh_threads():
    token = _current("threads_token.txt", "THREADS_ACCESS_TOKEN")
    if not token:
        print("[threads] no token configured; skipped")
        return True
    result = _call("https://graph.threads.net/refresh_access_token",
                   params={"grant_type": "th_refresh_token", "access_token": token})
    if not result.get("access_token"):
        print("[threads] refresh FAILED:", result.get("error") or result)
        return False
    (STATE / "threads_token.txt").write_text(result["access_token"] + "\n", encoding="utf-8")
    print(f"[threads] token refreshed; valid ~{int(result.get('expires_in', 0)) // 86400} days")
    return True


def refresh_pinterest():
    # A refreshed token keeps the scopes of its original grant, so when the seed secret is
    # replaced (e.g. re-authorized with more scopes) the cached tokens must be dropped.
    seed = os.environ.get("PINTEREST_REFRESH_TOKEN", "")
    seed_path = STATE / "pinterest_seed.txt"
    fingerprint = hashlib.sha256(seed.encode()).hexdigest()[:16] if seed else ""
    stored = seed_path.read_text(encoding="utf-8").strip() if seed_path.exists() else ""
    if fingerprint and fingerprint != stored:
        for name in ("pinterest_token.txt", "pinterest_refresh.txt"):
            (STATE / name).unlink(missing_ok=True)
        seed_path.write_text(fingerprint + "\n", encoding="utf-8")
        print("[pinterest] new seed secret; cached tokens discarded")
    refresh = _current("pinterest_refresh.txt", "PINTEREST_REFRESH_TOKEN")
    app_id, app_secret = os.environ.get("PINTEREST_APP_ID"), os.environ.get("PINTEREST_APP_SECRET")
    if not (refresh and app_id and app_secret):
        print("[pinterest] no refresh token/app credentials; using PINTEREST_ACCESS_TOKEN as is")
        return True
    basic = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    result = _call("https://api.pinterest.com/v5/oauth/token",
                   data={"grant_type": "refresh_token", "refresh_token": refresh},
                   headers={"Authorization": f"Basic {basic}",
                            "Content-Type": "application/x-www-form-urlencoded"})
    if not result.get("access_token"):
        print("[pinterest] refresh FAILED:", result.get("message") or result)
        return False
    (STATE / "pinterest_token.txt").write_text(result["access_token"] + "\n", encoding="utf-8")
    if result.get("refresh_token"):
        (STATE / "pinterest_refresh.txt").write_text(result["refresh_token"] + "\n", encoding="utf-8")
    print(f"[pinterest] token refreshed; valid ~{int(result.get('expires_in', 0)) // 86400} days")
    return True


if __name__ == "__main__":
    ok = [refresh_threads(), refresh_pinterest()]
    raise SystemExit(0 if all(ok) else 1)

"""Daily: check every posting credential WITHOUT posting, and alert on Telegram if any is dead.

Uses the same tokens the pipeline uses (state cache first, secret seed second). Never
prints tokens. Exits 1 if a credential is broken so the workflow run shows red too.
Stdlib only.
"""
import base64
import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request

STATE = pathlib.Path(__file__).resolve().parents[1] / ".pipeline" / "state"
REPO = "https://github.com/astrotobby/astro-blog"


def _call(url, params=None, data=None, headers=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:  # noqa
            return {"error": f"HTTP {e.code}"}
    except Exception as e:  # noqa
        return {"error": str(e)}


def _cached(filename, secret):
    p = STATE / filename
    t = p.read_text(encoding="utf-8").strip() if p.exists() else ""
    return t or os.environ.get(secret, "")


def _err(r):
    e = r.get("error")
    if isinstance(e, dict):
        return e.get("message", "error")
    return str(e or r.get("message") or r)[:200]


def check_instagram():
    tok = _cached("ig_token.txt", "INSTAGRAM_TOKEN")
    if not tok:
        return None
    r = _call("https://graph.instagram.com/v21.0/me", {"fields": "id,username", "access_token": tok})
    return (True, f"@{r['username']}") if r.get("id") else (
        False, _err(r) + " | fix: Meta app dashboard > Instagram API setup > Generate token, "
                         "then update the INSTAGRAM_TOKEN secret")


def check_facebook():
    tok = os.environ.get("FACEBOOK_PAGE_TOKEN", "")
    if not tok:
        return None
    r = _call("https://graph.facebook.com/v21.0/me", {"fields": "id,name", "access_token": tok})
    return (True, r["name"]) if r.get("id") else (
        False, _err(r) + " | fix: Graph API Explorer > page access token, then update FACEBOOK_PAGE_TOKEN")


def check_threads():
    tok = _cached("threads_token.txt", "THREADS_ACCESS_TOKEN")
    if not tok:
        return None
    r = _call("https://graph.threads.net/v1.0/me", {"fields": "id,username", "access_token": tok})
    return (True, f"@{r['username']}") if r.get("id") else (
        False, _err(r) + " | fix: Threads use case > User Token Generator, then update THREADS_ACCESS_TOKEN")


def check_pinterest():
    tok = _cached("pinterest_token.txt", "PINTEREST_ACCESS_TOKEN")
    if not tok:
        return None
    r = _call("https://api.pinterest.com/v5/user_account", headers={"Authorization": f"Bearer {tok}"})
    return (True, r["username"]) if r.get("username") else (
        False, _err(r) + f" | fix: run the pinterest-reauth flow ({REPO}/actions/workflows/pinterest-reauth.yml)")


def check_youtube():
    cid, sec = os.environ.get("YOUTUBE_CLIENT_ID"), os.environ.get("YOUTUBE_CLIENT_SECRET")
    ref = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (cid and sec and ref):
        return None
    r = _call("https://oauth2.googleapis.com/token",
              data={"client_id": cid, "client_secret": sec, "refresh_token": ref,
                    "grant_type": "refresh_token"})
    return (True, "refresh ok") if r.get("access_token") else (
        False, _err(r) + " | fix: re-run the YouTube OAuth consent and update YOUTUBE_REFRESH_TOKEN")


def notify(text):
    bot, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (bot and chat):
        print("[health] no Telegram credentials; alert not sent")
        return
    r = _call(f"https://api.telegram.org/bot{bot}/sendMessage",
              data={"chat_id": chat, "text": text, "disable_web_page_preview": "true"})
    print("[health] Telegram alert", "sent" if r.get("ok") else f"failed: {_err(r)}")


def main():
    checks = {"Instagram": check_instagram, "Facebook Page": check_facebook,
              "Threads": check_threads, "Pinterest": check_pinterest, "YouTube": check_youtube}
    broken = []
    for name, fn in checks.items():
        res = fn()
        if res is None:
            print(f"[health] {name}: not configured")
            continue
        ok, info = res
        print(f"[health] {name}: {'OK' if ok else 'BROKEN'} - {info}")
        if not ok:
            broken.append(f"- {name}: {info}")
    if broken:
        notify("Astro Signal pipeline: a posting login stopped working.\n\n" + "\n".join(broken)
               + f"\n\nRuns: {REPO}/actions")
        raise SystemExit(1)
    print("[health] all configured credentials OK")


if __name__ == "__main__":
    main()

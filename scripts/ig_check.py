"""Diagnostic: list the Instagram account's recent media + real permalinks, to check
whether API-published reels actually exist and what their correct URLs are.
Self-contained (stdlib). Uses the cached refreshed token, else INSTAGRAM_TOKEN."""
import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request

tokfile = pathlib.Path(".pipeline/state/ig_token.txt")
tok = (tokfile.read_text().strip() if tokfile.exists() else "") or os.environ.get("INSTAGRAM_TOKEN", "")
uid = os.environ.get("INSTAGRAM_USER_ID", "")
base = "https://graph.instagram.com/v21.0"


def g(u, p):
    try:
        with urllib.request.urlopen(u + "?" + urllib.parse.urlencode(p), timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:  # noqa
            return {"error": "HTTP %d" % e.code}


print("ACCOUNT:", json.dumps(g(f"{base}/me",
      {"fields": "username,account_type,media_count", "access_token": tok})))
r = g(f"{base}/{uid}/media",
      {"fields": "id,permalink,media_product_type,timestamp", "access_token": tok, "limit": "12"})
if "data" in r:
    print("recent media (%d):" % len(r["data"]))
    for m in r["data"]:
        print("  ", m.get("timestamp"), "|", m.get("media_product_type"),
              "| id", m.get("id"), "|", m.get("permalink"))
else:
    print("media error:", json.dumps(r))

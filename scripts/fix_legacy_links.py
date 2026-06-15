"""One-off: replace TinyURL links in ALREADY-published YouTube + Facebook posts
with the full destination URL.

For each video description, find any tinyurl.com link, follow it to its final
destination (the real post URL), and swap it in. No guesswork/title-matching —
the redirect target IS the correct URL. Runs in GitHub Actions where the YouTube
and Facebook secrets are available. Safe to re-run (idempotent).
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

TINY = re.compile(r"https?://tinyurl\.com/[A-Za-z0-9]+")


def resolve(u):
    """Follow redirects to the final URL (the real post)."""
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.url
    except urllib.error.HTTPError as e:
        return getattr(e, "url", None)
    except Exception:  # noqa
        return None


def fix_text(text):
    changed = False
    for short in set(TINY.findall(text or "")):
        full = resolve(short)
        if full and "tinyurl.com" not in full:
            text = text.replace(short, full)
            changed = True
    return text, changed


def fix_youtube():
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    csec = os.environ.get("YOUTUBE_CLIENT_SECRET")
    rtok = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not (cid and csec and rtok):
        print("YT: no creds, skipping")
        return
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(None, refresh_token=rtok,
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=cid, client_secret=csec)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    vids, page = [], None
    while True:
        pl = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                     maxResults=50, pageToken=page).execute()
        vids += [it["contentDetails"]["videoId"] for it in pl["items"]]
        page = pl.get("nextPageToken")
        if not page:
            break
    print(f"YT: {len(vids)} uploads to scan")
    fixed = 0
    for i in range(0, len(vids), 50):
        vr = yt.videos().list(part="snippet", id=",".join(vids[i:i + 50])).execute()
        for v in vr["items"]:
            sn = v["snippet"]
            new, changed = fix_text(sn.get("description", ""))
            if not changed:
                continue
            sn["description"] = new
            try:
                yt.videos().update(part="snippet", body={"id": v["id"], "snippet": sn}).execute()
                fixed += 1
                print("YT fixed", v["id"])
            except Exception as e:  # noqa
                print("YT update FAILED", v["id"], str(e)[:200])
    print(f"YT: {fixed} description(s) updated")


def fix_facebook():
    pid = os.environ.get("FACEBOOK_PAGE_ID")
    tok = os.environ.get("FACEBOOK_PAGE_TOKEN")
    if not (pid and tok):
        print("FB: no creds, skipping")
        return
    base = "https://graph.facebook.com/v21.0"
    url = f"{base}/{pid}/videos?fields=id,description&limit=100&access_token={urllib.parse.quote(tok)}"
    fixed = scanned = 0
    while url:
        data = json.load(urllib.request.urlopen(url, timeout=40))
        for v in data.get("data", []):
            scanned += 1
            new, changed = fix_text(v.get("description", ""))
            if not changed:
                continue
            body = urllib.parse.urlencode({"description": new, "access_token": tok}).encode()
            try:
                urllib.request.urlopen(urllib.request.Request(f"{base}/{v['id']}", data=body, method="POST"), timeout=40)
                fixed += 1
                print("FB fixed", v["id"])
            except urllib.error.HTTPError as e:
                print("FB update FAILED", v["id"], e.read().decode()[:200])
        url = data.get("paging", {}).get("next")
    print(f"FB: scanned {scanned}, {fixed} description(s) updated")


if __name__ == "__main__":
    try:
        fix_youtube()
    except Exception as e:  # noqa
        print("YT pass errored:", str(e)[:300])
    try:
        fix_facebook()
    except Exception as e:  # noqa
        print("FB pass errored:", str(e)[:300])

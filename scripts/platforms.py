"""Direct, free official-API posters — no Postiz, no server.

Each poster returns a dict: {"ok": bool, "url"/"error"/"skipped": ...}.
Missing credentials -> {"ok": False, "skipped": "no creds"} so the pipeline
soft-fails one platform without blocking the rest.

AUTOMATED NOW (free, no app review): YouTube, Tumblr, Reddit, X, Pinterest.
DEFERRED (need platform app review): Instagram, Facebook, LinkedIn
— see HONEST-LIMITS.md. The workflow saves the rendered Reels as artifacts so
you can hand-upload those until their apps are approved.
"""
from common import (OUT, env, ig_token, log, save_tiktok_refresh,
                    tiktok_refresh_token)


def _has(*keys) -> bool:
    return all(env(k) for k in keys)


# --------------------------------------------------------------------------
# YouTube — Data API v3 (own channel upload needs NO review)
# --------------------------------------------------------------------------
def _yt_client():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    # No scopes= here on purpose: the refresh token may have been granted
    # youtube.upload OR youtube.force-ssl. Passing a scope that wasn't granted makes
    # Google reject the refresh ("invalid_scope"). Omitting it uses the granted scopes
    # (force-ssl covers uploads), so it works regardless of how the token was minted.
    creds = Credentials(
        None,
        refresh_token=env("YOUTUBE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env("YOUTUBE_CLIENT_ID"),
        client_secret=env("YOUTUBE_CLIENT_SECRET"),
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def _yt_upload(yt, video, title, desc, tags, cfg):
    from googleapiclient.http import MediaFileUpload
    body = {
        "snippet": {"title": title[:95], "description": desc[:4900],
                    "tags": [t.lstrip("#") for t in tags][:15],
                    "categoryId": cfg["platforms"]["youtube"]["category_id"]},
        "status": {"privacyStatus": cfg["platforms"]["youtube"]["privacy"]},
    }
    media = MediaFileUpload(video, chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return f"https://youtu.be/{resp['id']}"


def post_youtube(render, cfg, dry):
    if not _has("YOUTUBE_REFRESH_TOKEN", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"):
        return {"youtube": {"ok": False, "skipped": "no creds"}}
    p = render["platform"]
    out = {}
    main_video = render["videos"].get("horizontal") or render["videos"]["vertical"]
    if dry:
        out["youtube"] = {"ok": True, "dry": True, "url": "(dry) " + p["yt_title"]}
        if cfg["platforms"]["youtube"].get("also_short"):
            out["youtube_short"] = {"ok": True, "dry": True}
        return out
    yt = _yt_client()
    try:
        _url = _yt_upload(
            yt, main_video, p["yt_title"], p["yt_desc"], p["hashtags"], cfg)
        out["youtube"] = {"ok": True, "url": _url}
        try:
            from thumbnail import set_thumbnail_for
            _vid = _url.rstrip("/").split("/")[-1]
            out["youtube"]["thumbnail"] = set_thumbnail_for(yt, _vid, p["yt_title"])
            log("youtube thumbnail set for " + _vid)
        except Exception as _te:  # noqa  (never let a thumbnail error break the upload)
            log("youtube thumbnail failed: " + str(_te)[:200])
            out["youtube"]["thumbnail"] = {"ok": False, "error": str(_te)[:200]}
    except Exception as e:  # noqa
        out["youtube"] = {"ok": False, "error": str(e)}
    if cfg["platforms"]["youtube"].get("also_short") and render["videos"].get("vertical"):
        try:
            out["youtube_short"] = {"ok": True, "url": _yt_upload(
                yt, render["videos"]["vertical"], p["yt_title"][:85] + " #Shorts",
                p["yt_desc"] + "\n#Shorts", p["hashtags"], cfg)}
        except Exception as e:  # noqa
            out["youtube_short"] = {"ok": False, "error": str(e)}
    return out


# --------------------------------------------------------------------------
# Tumblr — API v2 via pytumblr (OAuth1, no review)
# --------------------------------------------------------------------------
def post_tumblr(render, cfg, dry):
    if not _has("TUMBLR_CONSUMER_KEY", "TUMBLR_CONSUMER_SECRET",
                "TUMBLR_OAUTH_TOKEN", "TUMBLR_OAUTH_SECRET", "TUMBLR_BLOG"):
        return {"ok": False, "skipped": "no creds"}
    if dry:
        return {"ok": True, "dry": True}
    try:
        import pytumblr
        client = pytumblr.TumblrRestClient(
            env("TUMBLR_CONSUMER_KEY"), env("TUMBLR_CONSUMER_SECRET"),
            env("TUMBLR_OAUTH_TOKEN"), env("TUMBLR_OAUTH_SECRET"))
        blog = env("TUMBLR_BLOG")
        p = render["platform"]
        res = client.create_video(
            blog, data=render["videos"]["vertical"],
            caption=p["caption"],
            tags=[h.lstrip("#") for h in p["hashtags"]])
        pid = res.get("id") or (res.get("response") or {}).get("id")
        if pid:
            return {"ok": True, "url": f"https://{blog}/post/{pid}"}
        return {"ok": False, "error": str(res)[:300]}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Facebook Page — Graph API. Posts a video to a Page you admin using a
# long-lived Page access token (works in dev mode for your own page; no review).
# --------------------------------------------------------------------------
def post_facebook(render, cfg, dry):
    if not _has("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN"):
        return {"ok": False, "skipped": "no creds"}
    if dry:
        return {"ok": True, "dry": True}
    try:
        import requests
        page_id = env("FACEBOOK_PAGE_ID")
        token = env("FACEBOOK_PAGE_TOKEN")
        p = render["platform"]
        video = render["videos"].get("vertical") or render["videos"]["horizontal"]
        url = f"https://graph.facebook.com/v21.0/{page_id}/videos"
        with open(video, "rb") as fh:
            r = requests.post(url,
                              data={"description": p["caption"], "access_token": token},
                              files={"source": ("video.mp4", fh, "video/mp4")},
                              timeout=600)
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        vid = j.get("id")
        if r.status_code < 300 and vid:
            return {"ok": True, "url": f"https://www.facebook.com/{vid}"}
        return {"ok": False, "error": str(j or r.text)[:300]}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Public-URL hosting (for APIs that require a video_url, not a file upload):
# upload the rendered mp4 to a GitHub Release on the public repo -> public link.
# --------------------------------------------------------------------------
def _host_public_url(video_path, slug):
    import os
    import re
    import subprocess
    import time
    repo = env("GITHUB_REPOSITORY")
    if not (repo and (env("GH_TOKEN") or env("GITHUB_TOKEN"))):
        log("host: no GITHUB_REPOSITORY/token -> cannot create a public URL")
        return None
    # Slice THEN strip so the tag never ends in a hyphen (a trailing '-' broke
    # `gh release create`). Fall back to "video" if the slug slugifies to nothing.
    tag = "vid-" + (re.sub(r"[^a-z0-9]+", "-", slug.lower())[:60].strip("-") or "video")
    fn = os.path.basename(str(video_path))

    def _gh(args):
        return subprocess.run(["gh", *args], capture_output=True, text=True)

    last = ""
    for _ in range(3):                       # retry: tolerate transient gh/API hiccups
        cr = _gh(["release", "create", tag, "--repo", repo, "--title", tag,
                  "--notes", "auto-generated video"])
        if cr.returncode != 0 and "exists" not in (cr.stderr or "").lower():
            last = "create: " + (cr.stderr or "").strip()[:200]
            time.sleep(3)
            continue
        up = _gh(["release", "upload", tag, str(video_path), "--repo", repo, "--clobber"])
        if up.returncode == 0:
            return f"https://github.com/{repo}/releases/download/{tag}/{fn}"
        last = "upload: " + (up.stderr or "").strip()[:200]
        time.sleep(3)
    log(f"host: could not host video after retries ({last})")
    return None


# --------------------------------------------------------------------------
# Threads — Graph API (graph.threads.net). Needs a Threads user id + access
# token. Video must be a PUBLIC url (hosted above). 3-step: container -> wait -> publish.
# --------------------------------------------------------------------------
def post_threads(render, cfg, dry):
    if not _has("THREADS_USER_ID", "THREADS_ACCESS_TOKEN"):
        return {"ok": False, "skipped": "no creds"}
    if dry:
        return {"ok": True, "dry": True}
    try:
        import time

        import requests
        uid = env("THREADS_USER_ID")
        token = env("THREADS_ACCESS_TOKEN")
        p = render["platform"]
        video = render["videos"].get("vertical") or render["videos"]["horizontal"]
        video_url = _host_public_url(video, render["post"]["slug"])
        if not video_url:
            return {"ok": False, "error": "could not host a public video URL"}
        base = "https://graph.threads.net/v1.0"
        # 1) create media container
        r = requests.post(f"{base}/{uid}/threads",
                          data={"media_type": "VIDEO", "video_url": video_url,
                                "text": p["caption"], "access_token": token}, timeout=120)
        cid = (r.json() or {}).get("id")
        if not cid:
            return {"ok": False, "error": str(r.json())[:300]}
        # 2) wait for Threads to fetch + process the video
        for _ in range(25):
            time.sleep(6)
            st = requests.get(f"{base}/{cid}",
                              params={"fields": "status", "access_token": token},
                              timeout=60).json().get("status")
            if st == "FINISHED":
                break
            if st == "ERROR":
                return {"ok": False, "error": "Threads media processing failed"}
        # 3) publish
        pub = requests.post(f"{base}/{uid}/threads_publish",
                            data={"creation_id": cid, "access_token": token}, timeout=120)
        pid = (pub.json() or {}).get("id")
        if pid:
            return {"ok": True, "url": f"https://www.threads.net/t/{pid}"}
        return {"ok": False, "error": str(pub.json())[:300]}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Instagram — "Instagram API with Instagram Login" (graph.instagram.com). Uses a
# dedicated Instagram token + IG user id. Reels need a public url (hosted above).
# --------------------------------------------------------------------------
def post_instagram(render, cfg, dry):
    ig_id = env("INSTAGRAM_USER_ID")
    token = ig_token()   # auto-refreshed token from state cache, else INSTAGRAM_TOKEN seed
    if not (ig_id and token):
        return {"ok": False, "skipped": "no creds"}
    if dry:
        return {"ok": True, "dry": True}
    try:
        import time

        import requests
        p = render["platform"]
        video = render["videos"].get("vertical") or render["videos"]["horizontal"]
        video_url = _host_public_url(video, render["post"]["slug"])
        if not video_url:
            return {"ok": False, "error": "could not host a public video URL"}
        base = "https://graph.instagram.com/v21.0"   # Instagram-Login API
        # 1) create a Reels container
        caption = p.get("ig_caption") or p["caption"]   # IG: "link in bio" (links aren't clickable)
        r = requests.post(f"{base}/{ig_id}/media",
                          data={"media_type": "REELS", "video_url": video_url,
                                "caption": caption, "access_token": token}, timeout=120)
        cid = (r.json() or {}).get("id")
        if not cid:
            return {"ok": False, "error": str(r.json())[:300]}
        # 2) wait for Instagram to fetch + process
        for _ in range(25):
            time.sleep(6)
            st = requests.get(f"{base}/{cid}",
                              params={"fields": "status_code", "access_token": token},
                              timeout=60).json().get("status_code")
            if st == "FINISHED":
                break
            if st == "ERROR":
                return {"ok": False, "error": "Instagram media processing failed"}
        # 3) publish
        pub = requests.post(f"{base}/{ig_id}/media_publish",
                            data={"creation_id": cid, "access_token": token}, timeout=120)
        mid = (pub.json() or {}).get("id")
        if mid:
            # media_publish returns a NUMERIC media id, not the /reel/<shortcode> URL.
            # Fetch the real permalink so the reported link actually opens the reel
            # (using /reel/<numeric id> gives "post no longer available").
            try:
                perm = requests.get(f"{base}/{mid}",
                                    params={"fields": "permalink", "access_token": token},
                                    timeout=60).json().get("permalink")
            except Exception:  # noqa
                perm = None
            return {"ok": True, "url": perm or f"https://www.instagram.com/p/{mid}/"}
        return {"ok": False, "error": str(pub.json())[:300]}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Instagram Story — same Graph API, media_type=STORIES. Uses the <=58s story cut
# (Stories reject >60s). Independent of the Reel post (soft-fails on its own).
# --------------------------------------------------------------------------
def post_instagram_story(render, cfg, dry):
    ig_id = env("INSTAGRAM_USER_ID")
    token = ig_token()
    if not (ig_id and token):
        return {"ok": False, "skipped": "no creds"}
    if dry:
        return {"ok": True, "dry": True}
    try:
        import time

        import requests
        video = render["videos"].get("story") or render["videos"].get("vertical")
        if not video:
            return {"ok": False, "error": "no story/vertical video"}
        video_url = _host_public_url(video, render["post"]["slug"] + "-story")
        if not video_url:
            return {"ok": False, "error": "could not host a public video URL"}
        base = "https://graph.instagram.com/v21.0"
        # Stories take no caption; just the media. media_type=STORIES.
        r = requests.post(f"{base}/{ig_id}/media",
                          data={"media_type": "STORIES", "video_url": video_url,
                                "access_token": token}, timeout=120)
        cid = (r.json() or {}).get("id")
        if not cid:
            return {"ok": False, "error": str(r.json())[:300]}
        for _ in range(25):
            time.sleep(6)
            st = requests.get(f"{base}/{cid}",
                              params={"fields": "status_code", "access_token": token},
                              timeout=60).json().get("status_code")
            if st == "FINISHED":
                break
            if st == "ERROR":
                return {"ok": False, "error": "Instagram story processing failed"}
        pub = requests.post(f"{base}/{ig_id}/media_publish",
                            data={"creation_id": cid, "access_token": token}, timeout=120)
        mid = (pub.json() or {}).get("id")
        if mid:
            return {"ok": True, "url": f"ig-story:{mid}"}
        return {"ok": False, "error": str(pub.json())[:300]}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Facebook Page Story — video_stories API: start -> upload (by file_url) -> finish.
# Uses the <=58s story cut. Independent of the Page video post (soft-fails alone).
# --------------------------------------------------------------------------
def post_facebook_story(render, cfg, dry):
    if not _has("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN"):
        return {"ok": False, "skipped": "no creds"}
    if dry:
        return {"ok": True, "dry": True}
    try:
        import requests
        page_id = env("FACEBOOK_PAGE_ID")
        token = env("FACEBOOK_PAGE_TOKEN")
        video = render["videos"].get("story") or render["videos"].get("vertical")
        if not video:
            return {"ok": False, "error": "no story/vertical video"}
        video_url = _host_public_url(video, render["post"]["slug"] + "-story")
        if not video_url:
            return {"ok": False, "error": "could not host a public video URL"}
        base = "https://graph.facebook.com/v21.0"
        # 1) start -> video_id + a resumable upload_url
        start = requests.post(f"{base}/{page_id}/video_stories",
                              data={"upload_phase": "start", "access_token": token},
                              timeout=60).json()
        vid = start.get("video_id")
        upload_url = start.get("upload_url")
        if not (vid and upload_url):
            return {"ok": False, "error": "fb story start: " + str(start)[:250]}
        # 2) upload -> let FB fetch the hosted file via the file_url header
        up = requests.post(upload_url, timeout=300,
                           headers={"Authorization": f"OAuth {token}", "file_url": video_url})
        if up.status_code >= 300:
            return {"ok": False, "error": f"fb story upload HTTP {up.status_code}: {up.text[:160]}"}
        # 3) finish -> publishes the story
        fin = requests.post(f"{base}/{page_id}/video_stories",
                            data={"upload_phase": "finish", "video_id": vid,
                                  "access_token": token}, timeout=120).json()
        if fin.get("success") or fin.get("post_id"):
            return {"ok": True, "url": f"fb-story:{fin.get('post_id') or vid}"}
        return {"ok": False, "error": "fb story finish: " + str(fin)[:250]}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Reddit — PRAW (script app, no review). Posts ONE video to ONE subreddit.
# --------------------------------------------------------------------------
def post_reddit(render, cfg, dry):
    subs = cfg["limits"].get("reddit_subreddits") or []
    if not subs:
        return {"ok": False, "skipped": "no subreddit configured"}
    if not _has("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
                "REDDIT_USERNAME", "REDDIT_PASSWORD"):
        return {"ok": False, "skipped": "no creds"}
    if dry:
        return {"ok": True, "dry": True, "url": f"(dry) r/{subs[0]}"}
    try:
        import praw
        reddit = praw.Reddit(
            client_id=env("REDDIT_CLIENT_ID"),
            client_secret=env("REDDIT_CLIENT_SECRET"),
            username=env("REDDIT_USERNAME"),
            password=env("REDDIT_PASSWORD"),
            user_agent="blog-to-video/1.0 by u/" + env("REDDIT_USERNAME"))
        sub = reddit.subreddit(subs[0])
        submission = sub.submit_video(
            title=render["post"]["title"][:300],
            video_path=render["videos"]["vertical"],
            timeout=120)
        return {"ok": True, "url": "https://reddit.com" + submission.permalink}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# X / Twitter — tweepy (free tier; chunked video upload via v1.1 + v2 tweet)
# --------------------------------------------------------------------------
def post_twitter(render, cfg, dry):
    if not _has("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"):
        return {"ok": False, "skipped": "no creds"}
    if dry:
        return {"ok": True, "dry": True}
    def _twerr(e):
        detail = str(e)
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                detail += " | " + resp.text[:400]
            except Exception:  # noqa
                pass
        return detail
    try:
        import time

        import tweepy
        auth = tweepy.OAuth1UserHandler(
            env("X_API_KEY"), env("X_API_SECRET"),
            env("X_ACCESS_TOKEN"), env("X_ACCESS_SECRET"))
        api_v1 = tweepy.API(auth)
        # Video upload uses the v1.1 endpoint, which is blocked/flaky on X's free
        # tier (400). Don't let that kill the post — fall back to a text+link tweet,
        # which posts reliably and still drives traffic to the site.
        media_ids = None
        try:
            media = api_v1.media_upload(
                render["videos"]["vertical"], media_category="tweet_video", chunked=True)
            # wait out async video processing
            info = getattr(media, "processing_info", None)
            waited = 0
            while info and info.get("state") in ("pending", "in_progress") and waited < 120:
                time.sleep(info.get("check_after_secs", 5))
                waited += info.get("check_after_secs", 5)
                status = api_v1.get_media_upload_status(media.media_id)
                info = getattr(status, "processing_info", None)
            media_ids = [media.media_id]
        except Exception as e:  # noqa
            log("x: video upload failed (%s); posting text+link only" % _twerr(e)[:120])
        p = render["platform"]
        # X caps text at 280; build a tight one (short link drives traffic + saves chars)
        link = p.get("short_url") or render["post"]["url"]
        text = f"{render['post']['title'][:120]}\n{link}\n" \
               + " ".join(p["hashtags"][:3])
        client = tweepy.Client(
            consumer_key=env("X_API_KEY"), consumer_secret=env("X_API_SECRET"),
            access_token=env("X_ACCESS_TOKEN"), access_token_secret=env("X_ACCESS_SECRET"))
        kwargs = {"text": text[:280]}
        if media_ids:
            kwargs["media_ids"] = media_ids
        try:
            resp = client.create_tweet(**kwargs)
        except Exception as e:  # noqa
            return {"ok": False, "error": "create_tweet: " + _twerr(e)}
        tid = resp.data["id"]
        return {"ok": True, "url": f"https://x.com/i/web/status/{tid}",
                "note": "text+link (no video)" if not media_ids else "with video"}
    except Exception as e:  # noqa
        return {"ok": False, "error": _twerr(e)}


# --------------------------------------------------------------------------
# TikTok — Content Posting API, DRAFT/INBOX mode (no app review needed). The
# rendered video is pushed to the user's TikTok inbox; they tap "Post" in the app
# (caption is added there). Tokens auto-refresh (rotating) via the state cache.
# --------------------------------------------------------------------------
def post_tiktok(render, cfg, dry):
    ck, cs = env("TIKTOK_CLIENT_KEY"), env("TIKTOK_CLIENT_SECRET")
    refresh = tiktok_refresh_token()
    if not (ck and cs and refresh):
        return {"ok": False, "skipped": "no creds"}
    if dry:
        return {"ok": True, "dry": True}
    try:
        import os

        import requests
        # 1) refresh -> short-lived access token (TikTok rotates the refresh token)
        tr = requests.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"client_key": ck, "client_secret": cs,
                  "grant_type": "refresh_token", "refresh_token": refresh},
            timeout=60).json()
        access = tr.get("access_token")
        if not access:
            return {"ok": False, "error": "tiktok token refresh: " + str(tr)[:200]}
        if tr.get("refresh_token"):
            save_tiktok_refresh(tr["refresh_token"])    # persist the rotated token

        # 2) init an inbox (draft) upload via direct FILE_UPLOAD (no domain verify)
        video = render["videos"].get("vertical") or render["videos"]["horizontal"]
        size = os.path.getsize(video)
        init = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
            headers={"Authorization": f"Bearer {access}",
                     "Content-Type": "application/json"},
            json={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                  "chunk_size": size, "total_chunk_count": 1}},
            timeout=60).json()
        data = init.get("data") or {}
        upload_url = data.get("upload_url")
        if not upload_url:
            return {"ok": False, "error": "tiktok init: " + str(init)[:200]}

        # 3) upload the bytes (single chunk; our videos are well under 64MB)
        with open(video, "rb") as f:
            blob = f.read()
        put = requests.put(upload_url, data=blob, timeout=300, headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}"})
        if put.status_code not in (200, 201, 206):
            return {"ok": False, "error": f"tiktok upload HTTP {put.status_code}: {put.text[:160]}"}
        return {"ok": True, "url": "https://www.tiktok.com/",
                "note": "sent to TikTok inbox/drafts — tap Post in the app",
                "publish_id": data.get("publish_id")}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


# --------------------------------------------------------------------------
# Rumble — NO official upload API, so we drive the real upload page with a
# headless browser (Playwright/Chromium). Logs in with RUMBLE_EMAIL/PASSWORD,
# uploads the 16:9 video, fills title + description (with the blog link), sets
# visibility, accepts the rights/terms, and submits. Soft-fails like the others:
# if Rumble challenges the login (CAPTCHA) or the form selectors drift, it returns
# an error, a debug screenshot is saved to .pipeline/out/ (uploaded as an artifact),
# and the video is already in the artifacts for a 2-tap manual upload.
#
# NOTE: the SELECTORS below are best-effort and are the FIRST thing to check if a
# real run fails — Rumble's upload page changes; patch the lists here. Each helper
# tries every selector in order so a single redesign rarely breaks everything.
# --------------------------------------------------------------------------
# login.php 302-redirects to auth.rumble.com (verified 2026-06-29); Playwright
# follows the redirect, so navigating to login.php is fine. The auth form uses
# styled-components with RANDOMIZED ids, but stable name="username"/"password"
# attributes — so target by name, NOT id. Button text is "Sign In".
RUMBLE_LOGIN_URL = "https://rumble.com/login.php"
RUMBLE_UPLOAD_URL = "https://rumble.com/upload.php"
# field selectors (first match wins; verified ones first to avoid wasted waits)
_RB_USER = ['input[name="username"]', 'input[type="email"]', "#login-username"]
_RB_PASS = ['input[name="password"]', 'input[type="password"]', "#login-password"]
_RB_LOGIN_BTN = ['button:has-text("Sign In")', 'button[type="submit"]',
                 'input[type="submit"]', 'button:has-text("Log in")']
# Upload form (verified against the live logged-in form 2026-06-29):
_RB_FILE = ['#Filedata', 'input[type="file"]']
_RB_TITLE = ['#title', 'input[name="title"]']
_RB_DESC = ['#description', 'textarea[name="description"]']
_RB_CATEGORY = 'input[name="primary-category"]'   # filter-then-click custom dropdown
# Visibility + rights/terms are CUSTOM-STYLED inputs: the real <input> is
# display:none, so .check() and visibility-waits fail. They're toggled via the
# associated <label for="..."> (verified 2026-06-29). Click the label, not the input.
_RB_VIS_LABEL = {"public": 'label[for="visibility_public"]',
                 "unlisted": 'label[for="visibility_unlisted"]',
                 "private": 'label[for="visibility_private"]'}
_RB_RIGHTS_LABEL = 'label[for="crights"]'   # also the step-2 "we're on rights" signal
_RB_TERMS_LABEL = 'label[for="cterms"]'


def _rb_fill(page, selectors, value, timeout=15000):
    """Fill the first selector that exists. Returns True on success."""
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                el.fill(value)
                return True
        except Exception:  # noqa
            continue
    return False


def _rb_click(page, selectors, timeout=15000):
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                el.click()
                return True
        except Exception:  # noqa
            continue
    return False


def post_rumble(render, cfg, dry):
    if not _has("RUMBLE_EMAIL", "RUMBLE_PASSWORD"):
        return {"ok": False, "skipped": "no creds"}
    if dry:
        return {"ok": True, "dry": True}

    import os

    rb_cfg = (cfg.get("platforms", {}).get("rumble") or {})
    visibility = str(rb_cfg.get("visibility", "public")).lower()
    # Rumble REQUIRES a primary category; "Finance & Crypto" fits the blog's niche.
    primary_category = rb_cfg.get("primary_category", "Finance & Crypto")
    # 16:9 main cut (Rumble is YouTube-style/landscape); fall back to vertical.
    video = render["videos"].get("horizontal") or render["videos"]["vertical"]
    p = render["platform"]
    post = render["post"]
    link = p.get("short_url") or post["url"]
    title = (post["title"] or "Untitled")[:100]
    desc_body = p.get("yt_desc") or p.get("caption") or post.get("description", "")
    tags = " ".join(p.get("hashtags", [])[:8])
    description = f"{desc_body}\n\nRead the full post: {link}\n\n{tags}".strip()

    shot = str(OUT / f"rumble_fail_{post['slug'][:40]}.png")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa
        return {"ok": False, "error": f"playwright not installed: {e}"}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0 Safari/537.36"))
            page = ctx.new_page()
            page.set_default_timeout(30000)

            # ---- 1) log in ----
            page.goto(RUMBLE_LOGIN_URL, wait_until="domcontentloaded")
            if not _rb_fill(page, _RB_USER, env("RUMBLE_EMAIL")):
                page.screenshot(path=shot)
                return {"ok": False, "error": "rumble: username field not found "
                        "(login page changed or CAPTCHA challenge)"}
            _rb_fill(page, _RB_PASS, env("RUMBLE_PASSWORD"))
            _rb_click(page, _RB_LOGIN_BTN)
            page.wait_for_timeout(6000)   # let the session cookie settle
            # A still-visible password field == login was rejected/challenged.
            for sel in _RB_PASS:
                if page.query_selector(sel):
                    page.screenshot(path=shot)
                    return {"ok": False, "error": "rumble: login failed/challenged "
                            "(check creds, disable 2FA, or CAPTCHA on CI IP)"}

            # ---- 2) open the upload form + attach the file (starts the upload) ----
            page.goto(RUMBLE_UPLOAD_URL, wait_until="domcontentloaded")
            file_set = False
            for sel in _RB_FILE:
                try:
                    page.set_input_files(sel, video, timeout=15000)
                    file_set = True
                    break
                except Exception:  # noqa
                    continue
            if not file_set:
                page.screenshot(path=shot)
                return {"ok": False, "error": "rumble: file input not found "
                        "(not logged in, or upload page changed)"}

            # ---- 3) details: title + description (fillable while the upload runs) ----
            if not _rb_fill(page, _RB_TITLE, title):
                page.screenshot(path=shot)
                return {"ok": False, "error": "rumble: title field not found"}
            _rb_fill(page, _RB_DESC, description)

            # ---- 4) primary category (REQUIRED): filter then click the matching option ----
            try:
                page.fill(_RB_CATEGORY, primary_category)
                page.wait_for_timeout(1200)   # let the options list filter
                page.locator(".select-options-container") \
                    .get_by_text(primary_category, exact=True).first.click(timeout=6000)
            except Exception:  # noqa
                # fallback: pick the first option that appears for the typed text
                try:
                    page.locator(".select-options-container div").first.click(timeout=4000)
                    log(f"rumble: exact category '{primary_category}' not found; took first match")
                except Exception:  # noqa
                    page.screenshot(path=shot)
                    return {"ok": False, "error": "rumble: could not set required "
                            f"primary category '{primary_category}'"}

            # ---- 5) visibility: click the LABEL (the real radio is display:none) ----
            vis_sel = _RB_VIS_LABEL.get(visibility, _RB_VIS_LABEL["public"])
            try:
                page.click(vis_sel, timeout=5000)
            except Exception:  # noqa
                log(f"rumble: could not set visibility '{visibility}'; using default")

            # ---- 6) step 1 submit ("Upload") -> advances to the rights/terms step.
            # The button only advances once the video upload finishes, so re-click while
            # we're still on step 1. Detect step 2 by the rights LABEL becoming visible
            # (the #crights INPUT is display:none, so we must watch the label instead). ----
            advanced = False
            for _ in range(40):                 # ~40 * 6s = up to 4 min for the upload
                # only (re)click step-1 submit while the rights step isn't up yet
                if not page.locator(_RB_RIGHTS_LABEL).is_visible():
                    try:
                        page.click("#submitForm", timeout=4000)
                    except Exception:  # noqa
                        pass
                try:
                    page.wait_for_selector(_RB_RIGHTS_LABEL, state="visible", timeout=6000)
                    advanced = True
                    break
                except Exception:  # noqa
                    continue
            if not advanced:
                page.screenshot(path=shot)
                return {"ok": False, "error": "rumble: never reached the rights/terms step "
                        "(upload still processing or #submitForm changed)"}

            # ---- 7) accept the two required rights/terms boxes via their labels ----
            for lab in (_RB_RIGHTS_LABEL, _RB_TERMS_LABEL):
                try:
                    page.click(lab, timeout=5000)
                except Exception:  # noqa
                    pass

            # ---- 8) step 2 submit ("Submit") -> publishes ----
            try:
                page.click("#submitForm2", timeout=10000)
            except Exception:  # noqa
                page.screenshot(path=shot)
                return {"ok": False, "error": "rumble: final submit (#submitForm2) failed"}
            page.wait_for_timeout(10000)        # let the publish request complete
            final = page.url
            ctx.close()
            browser.close()
            return {"ok": True, "url": final,
                    "note": f"uploaded via browser automation "
                            f"(visibility={visibility}, category={primary_category})"}
    except Exception as e:  # noqa
        try:
            page.screenshot(path=shot)  # noqa
        except Exception:  # noqa
            pass
        return {"ok": False, "error": str(e)[:300]}


# --------------------------------------------------------------------------
# Pinterest — API v5. Creates a Pin on the specified board using the post's
# hero image (image_url) and links back to the blog post. No app review needed
# for personal use with your own access token (standard OAuth flow).
# Requires: PINTEREST_ACCESS_TOKEN, PINTEREST_BOARD_ID
# --------------------------------------------------------------------------
def post_pinterest(render, cfg, dry):
    if not _has("PINTEREST_ACCESS_TOKEN", "PINTEREST_BOARD_ID"):
        return {"ok": False, "skipped": "no creds"}
    post = render["post"]
    image_url = post.get("image_url", "")
    if not image_url:
        return {"ok": False, "error": "post has no image_url; set 'image' in frontmatter"}
    if dry:
        return {"ok": True, "dry": True, "url": f"(dry) pin for {post['slug']}"}
    try:
        import requests
        token = env("PINTEREST_ACCESS_TOKEN")
        board_id = env("PINTEREST_BOARD_ID")
        p = render["platform"]
        note = p.get("caption") or post["description"]
        # Pinterest description cap is 500 chars; strip hashtags (not allowed in desc)
        description = " ".join(
            w for w in note.split() if not w.startswith("#")
        )[:500]
        body = {
            "link": post["url"],
            "title": post["title"][:100],
            "description": description,
            "board_id": board_id,
            "media_source": {
                "source_type": "image_url",
                "url": image_url,
            },
        }
        r = requests.post(
            "https://api.pinterest.com/v5/pins",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        pin_id = j.get("id")
        if r.status_code < 300 and pin_id:
            return {"ok": True, "url": f"https://www.pinterest.com/pin/{pin_id}/"}
        return {"ok": False, "error": str(j or r.text)[:300]}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


# registry used by crosspost.py
DIRECT_POSTERS = {
    "tumblr": post_tumblr,
    "reddit": post_reddit,
    "x": post_twitter,
    "rumble": post_rumble,
}

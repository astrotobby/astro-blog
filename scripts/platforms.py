"""Direct, free official-API posters — no Postiz, no server.

Each poster returns a dict: {"ok": bool, "url"/"error"/"skipped": ...}.
Missing credentials -> {"ok": False, "skipped": "no creds"} so the pipeline
soft-fails one platform without blocking the rest.

AUTOMATED NOW (free, no app review): YouTube, Tumblr, Reddit, X.
DEFERRED (need platform app review): Instagram, Facebook, LinkedIn, Pinterest
— see HONEST-LIMITS.md. The workflow saves the rendered Reels as artifacts so
you can hand-upload those until their apps are approved.
"""
from common import env, log


def _has(*keys) -> bool:
    return all(env(k) for k in keys)


# --------------------------------------------------------------------------
# YouTube — Data API v3 (own channel upload needs NO review)
# --------------------------------------------------------------------------
def _yt_client():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(
        None,
        refresh_token=env("YOUTUBE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env("YOUTUBE_CLIENT_ID"),
        client_secret=env("YOUTUBE_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
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
        out["youtube"] = {"ok": True, "url": _yt_upload(
            yt, main_video, p["yt_title"], p["yt_desc"], p["hashtags"], cfg)}
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
    repo = env("GITHUB_REPOSITORY")
    if not (repo and (env("GH_TOKEN") or env("GITHUB_TOKEN"))):
        log("host: no GITHUB_REPOSITORY/token -> cannot create a public URL")
        return None
    tag = "vid-" + re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:60]
    fn = os.path.basename(str(video_path))
    try:
        subprocess.run(["gh", "release", "create", tag, str(video_path), "--repo", repo,
                        "--title", tag, "--notes", "auto-generated video"],
                       check=True, capture_output=True, text=True)
    except Exception:  # noqa  release likely exists -> just (re)upload the asset
        subprocess.run(["gh", "release", "upload", tag, str(video_path), "--repo", repo,
                        "--clobber"], check=True, capture_output=True, text=True)
    return f"https://github.com/{repo}/releases/download/{tag}/{fn}"


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
# Instagram — same Graph API as Facebook. Reuses your FB Page token (with IG
# scopes) + the IG Business account id. Reels need a public url (hosted above).
# --------------------------------------------------------------------------
def post_instagram(render, cfg, dry):
    ig_id = env("INSTAGRAM_USER_ID")
    token = env("INSTAGRAM_TOKEN") or env("FACEBOOK_PAGE_TOKEN")  # one token for FB+IG
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
        base = "https://graph.facebook.com/v21.0"
        # 1) create a Reels container
        r = requests.post(f"{base}/{ig_id}/media",
                          data={"media_type": "REELS", "video_url": video_url,
                                "caption": p["caption"], "access_token": token}, timeout=120)
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
            return {"ok": True, "url": f"https://www.instagram.com/reel/{mid}/"}
        return {"ok": False, "error": str(pub.json())[:300]}
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
    try:
        import time

        import tweepy
        auth = tweepy.OAuth1UserHandler(
            env("X_API_KEY"), env("X_API_SECRET"),
            env("X_ACCESS_TOKEN"), env("X_ACCESS_SECRET"))
        api_v1 = tweepy.API(auth)
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
        p = render["platform"]
        # X caps text at 280; build a tight one
        text = f"{render['post']['title'][:120]}\n{render['post']['url']}\n" \
               + " ".join(p["hashtags"][:3])
        client = tweepy.Client(
            consumer_key=env("X_API_KEY"), consumer_secret=env("X_API_SECRET"),
            access_token=env("X_ACCESS_TOKEN"), access_token_secret=env("X_ACCESS_SECRET"))
        resp = client.create_tweet(text=text[:280], media_ids=[media.media_id])
        tid = resp.data["id"]
        return {"ok": True, "url": f"https://x.com/i/web/status/{tid}"}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}


# registry used by crosspost.py
DIRECT_POSTERS = {
    "tumblr": post_tumblr,
    "reddit": post_reddit,
    "x": post_twitter,
}

#!/usr/bin/env python3
"""Publish a transparent, time-limited LeadsLeap information campaign.

This script only posts ordinary educational content to configured external
social accounts. It never logs into LeadsLeap, surfs ads, clicks ads, opens
Co-op links to manufacture visits, or simulates human activity on LeadsLeap.
Default mode is preview-only; pass --publish to send social posts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGN = ROOT / "config" / "leadsleap-campaign.json"
DEFAULT_STATE = ROOT / ".pipeline" / "state" / "leadsleap-campaign.json"
EAT = timezone(timedelta(hours=3))


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def local_today() -> date:
    return datetime.now(timezone.utc).astimezone(EAT).date()


def campaign_day(cfg: dict, today: date) -> tuple[int, dict]:
    start = date.fromisoformat(cfg["start_date"])
    posts = cfg.get("posts") or []
    if not posts:
        raise ValueError("Campaign has no post variants.")
    offset = (today - start).days
    index = offset % len(posts)
    return index, posts[index]


def campaign_active(cfg: dict, today: date) -> bool:
    start = date.fromisoformat(cfg["start_date"])
    end = date.fromisoformat(cfg["end_date"])
    return start <= today <= end


def tracked_url(base_url: str, platform: str, campaign_id: str) -> str:
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({
        "utm_source": platform,
        "utm_medium": "social",
        "utm_campaign": campaign_id,
    })
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query), parts.fragment))


def load_state(path: Path, today: date) -> dict:
    """Reset daily post records, but retain destination blocks until credentials change."""
    if path.exists():
        try:
            previous = load_json(path)
            if isinstance(previous, dict):
                blocked = previous.get("blocked")
                if not isinstance(blocked, dict):
                    blocked = {}
                posted = previous.get("posted", {}) if previous.get("date") == today.isoformat() else {}
                if not isinstance(posted, dict):
                    posted = {}
                return {"date": today.isoformat(), "posted": posted, "blocked": blocked}
        except (OSError, ValueError, TypeError):
            pass
    return {"date": today.isoformat(), "posted": {}, "blocked": {}}


def _platform_credential_fingerprint(platform: str) -> str:
    """Return a non-reversible fingerprint so blocks clear automatically when keys rotate."""
    keys = {
        "facebook": ("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN"),
        "threads": ("THREADS_USER_ID", "THREADS_ACCESS_TOKEN"),
        "x": ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"),
    }.get(platform, ())
    values = [os.getenv(key, "") or "" for key in keys]
    return hashlib.sha256("\\0".join(values).encode("utf-8")).hexdigest()


def _permanent_block_reason(platform: str, result: dict) -> str | None:
    error = str(result.get("error") or "")
    if platform == "facebook" and (
        re.search(r"""(?:\bcode['"]?\s*:\s*190\b|error_subcode['"]?\s*:\s*460\b)""", error)
        or "session has been invalidated" in error.lower()
        or "error validating access token" in error.lower()
    ):
        return "Facebook Page token was invalidated by Meta; replace FACEBOOK_PAGE_TOKEN before retrying."
    if platform == "x" and (
        "402 payment required" in error.lower() or "credits depleted" in error.lower()
    ):
        return "X API returned 402 because API credits are depleted; restore billing/credits before retrying."
    return None


def _threads_result(response) -> tuple[int, dict]:
    try:
        body = response.json() if response.content else {}
    except (TypeError, ValueError):
        body = {}
    return int(response.status_code), body if isinstance(body, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp.replace(path)


def publish_facebook(message: str, link: str) -> dict:
    page_id, token = os.getenv("FACEBOOK_PAGE_ID"), os.getenv("FACEBOOK_PAGE_TOKEN")
    if not (page_id and token):
        return {"ok": False, "skipped": "Facebook credentials not configured"}
    import requests

    response = requests.post(
        f"https://graph.facebook.com/v27.0/{page_id}/feed",
        data={"message": message, "link": link, "access_token": token},
        timeout=45,
    )
    body = response.json() if response.content else {}
    post_id = body.get("id")
    if response.ok and post_id:
        return {"ok": True, "url": f"https://www.facebook.com/{post_id}"}
    return {"ok": False, "error": f"Facebook API HTTP {response.status_code}: {str(body)[:240]}"}


def publish_threads(message: str, link: str) -> dict:
    user_id, token = os.getenv("THREADS_USER_ID"), os.getenv("THREADS_ACCESS_TOKEN")
    if not (user_id and token):
        return {"ok": False, "skipped": "Threads credentials not configured"}
    import requests

    base = "https://graph.threads.net/v1.0"
    created = requests.post(
        f"{base}/{user_id}/threads",
        data={"media_type": "TEXT", "text": f"{message}\n\n{link}",
              "access_token": token},
        timeout=45,
    )
    status_code, data = _threads_result(created)
    creation_id = data.get("id")
    if status_code >= 300 or not creation_id:
        return {"ok": False, "error": f"Threads create HTTP {status_code}: {str(data)[:300]}"}

    def container_status(max_attempts: int = 12) -> tuple[str | None, dict]:
        """Wait for Meta's container index/processing state before publishing."""
        last_body: dict = {}
        for attempt in range(1, max_attempts + 1):
            response = requests.get(
                f"{base}/{creation_id}",
                params={"fields": "id,status,error_message", "access_token": token},
                timeout=30,
            )
            code, body = _threads_result(response)
            last_body = body
            if code == 404 or (
                str(body.get("error", {}).get("code", "")) == "24"
                if isinstance(body.get("error"), dict) else False
            ):
                # A newly-created container can take a short time to become readable.
                if attempt < max_attempts:
                    time.sleep(5)
                    continue
                return None, body
            if code >= 300:
                return None, body
            state = str(body.get("status") or "").upper()
            if state in {"FINISHED", "PUBLISHED", "ERROR", "EXPIRED"}:
                return state, body
            if attempt < max_attempts:
                time.sleep(5)
        return None, last_body

    state, status_body = container_status()
    if state == "PUBLISHED":
        # The create/publish response can be lost after Meta has already published.
        permalink = status_body.get("permalink") or f"https://www.threads.net/t/{creation_id}"
        return {"ok": True, "url": permalink, "recovered": True}
    if state != "FINISHED":
        return {
            "ok": False,
            "error": f"Threads container {creation_id} did not reach FINISHED "
                     f"(status={state or 'unavailable'}): {str(status_body)[:260]}",
        }

    # Retry only Meta's explicit 'container not found' propagation error, and
    # re-check the same container before retrying so we never create duplicate posts.
    for attempt in range(1, 4):
        try:
            published = requests.post(
                f"{base}/{user_id}/threads_publish",
                data={"creation_id": creation_id, "access_token": token},
                timeout=45,
            )
        except requests.RequestException:
            # A network timeout has an ambiguous publish outcome. Inspect the same
            # container rather than creating a second one or blindly reposting.
            state, status_body = container_status(max_attempts=6)
            if state == "PUBLISHED":
                return {
                    "ok": True,
                    "url": status_body.get("permalink") or f"https://www.threads.net/t/{creation_id}",
                    "recovered": True,
                }
            return {"ok": False, "error": "Threads publish outcome is uncertain; container status "
                    f"is {state or 'unavailable'}. Manual status check required."}

        code, result = _threads_result(published)
        post_id = result.get("id")
        if code < 300 and post_id:
            return {"ok": True, "url": f"https://www.threads.net/t/{post_id}"}

        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        is_propagation_race = (
            str(error.get("code", "")) == "24"
            and str(error.get("error_subcode", "")) == "4279009"
        )
        if not is_propagation_race:
            return {"ok": False, "error": f"Threads publish HTTP {code}: {str(result)[:300]}"}

        state, status_body = container_status(max_attempts=6)
        if state == "PUBLISHED":
            return {
                "ok": True,
                "url": status_body.get("permalink") or f"https://www.threads.net/t/{creation_id}",
                "recovered": True,
            }
        if state != "FINISHED" or attempt == 3:
            return {"ok": False, "error": f"Threads publish HTTP {code}: {str(result)[:240]}; "
                    f"container status is {state or 'unavailable'}."}
        time.sleep(5)

    return {"ok": False, "error": "Threads publish did not complete after bounded retries."}


def publish_x(message: str, link: str) -> dict:
    keys = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")
    values = [os.getenv(key) for key in keys]
    if not all(values):
        return {"ok": False, "skipped": "X credentials not configured"}
    try:
        import tweepy
    except ImportError:
        return {"ok": False, "error": "tweepy is not installed"}

    max_message = 245 - len(link)
    text = f"{message[:max(40, max_message)].rstrip()}\n{link}"
    try:
        client = tweepy.Client(
            consumer_key=values[0], consumer_secret=values[1],
            access_token=values[2], access_token_secret=values[3],
        )
        response = client.create_tweet(text=text[:280])
        post_id = response.data["id"]
        return {"ok": True, "url": f"https://x.com/i/web/status/{post_id}"}
    except Exception as exc:
        return {"ok": False, "error": f"X publish failed: {type(exc).__name__}: {str(exc)[:180]}"}


PUBLISHERS = {
    "facebook": publish_facebook,
    "threads": publish_threads,
    "x": publish_x,
}


def run(args: argparse.Namespace) -> int:
    cfg = load_json(args.campaign)
    today = date.fromisoformat(args.date) if args.date else local_today()

    if not campaign_active(cfg, today):
        print(
            f"Campaign inactive on {today.isoformat()}; active window is "
            f"{cfg['start_date']} through {cfg['end_date']} ({cfg.get('timezone', 'local time')})."
        )
        return 0

    index, variant = campaign_day(cfg, today)
    state = load_state(args.state, today)
    state.setdefault("blocked", {})
    if args.retry_blocked:
        state["blocked"] = {}
        print("[RETRY] Cleared saved destination blocks at operator request.")
    campaign_id = cfg["campaign_id"]
    landing_url = cfg["landing_url"]
    errors = 0

    print(
        f"Campaign: {cfg['name']} | local date: {today.isoformat()} | "
        f"variant {index + 1}/{len(cfg['posts'])}"
    )
    for platform in cfg.get("platforms", []):
        if platform not in PUBLISHERS:
            print(f"[SKIP] {platform}: no publisher configured")
            continue
        message = (variant.get(platform) or "").strip()
        if not message:
            print(f"[SKIP] {platform}: no copy for this day")
            continue
        link = tracked_url(landing_url, platform, campaign_id)
        fingerprint = _platform_credential_fingerprint(platform)
        blocked = state["blocked"].get(platform)
        if blocked and blocked.get("fingerprint") == fingerprint:
            print(f"[PAUSED] {platform}: {blocked.get('reason', 'destination is blocked')}")
            continue
        if blocked:
            # Credentials changed since the block was recorded; allow this destination again.
            state["blocked"].pop(platform, None)
        prior = state["posted"].get(platform, {})
        if prior.get("ok"):
            print(f"[SKIP] {platform}: already published successfully today ({prior.get('url', 'link saved')})")
            continue
        print(f"\n[{platform.upper()}] {message}\nLink: {link}")
        if not args.publish:
            print("[DRY RUN] No post was sent.")
            continue

        try:
            result = PUBLISHERS[platform](message, link)
        except Exception as exc:
            result = {"ok": False, "error": f"{platform} unexpected error: {type(exc).__name__}: {str(exc)[:180]}"}
        if result.get("ok"):
            state["posted"][platform] = {
                "ok": True,
                "url": result.get("url", ""),
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
            save_state(args.state, state)
            print(f"[POSTED] {platform}: {result.get('url', 'success')}")
        elif result.get("skipped"):
            print(f"[SKIPPED] {platform}: {result['skipped']}")
        else:
            block_reason = _permanent_block_reason(platform, result)
            if block_reason:
                state["blocked"][platform] = {
                    "fingerprint": fingerprint,
                    "reason": block_reason,
                    "blocked_at": datetime.now(timezone.utc).isoformat(),
                }
                print(f"[PAUSED] {platform}: {block_reason}")
                if args.publish:
                    save_state(args.state, state)
            else:
                errors += 1
                print(f"[FAILED] {platform}: {result.get('error', 'unknown error')}")

    if args.publish:
        save_state(args.state, state)
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--date", help="override local campaign date (YYYY-MM-DD), for testing")
    parser.add_argument("--publish", action="store_true",
                        help="actually publish; without this flag the script only previews")
    parser.add_argument("--retry-blocked", action="store_true",
                        help="clear saved permanent destination blocks; use only after fixing credentials/billing")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

"""One-time: get a TikTok refresh token for the Content Posting API. Run locally.

Prereqs: TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in .env (or the environment), and a
redirect URI registered on your TikTok app that matches --redirect exactly (default:
your verified site root). TikTok requires an HTTPS redirect URI, so we don't use a
localhost capture flow — you copy the ?code=... back from the browser.

Usage:
  1) python scripts/tiktok_auth.py                 # prints the authorize URL to open
  2) <approve in browser; you land on REDIRECT/?code=XXXX  -> copy the code>
  3) python scripts/tiktok_auth.py XXXX            # exchanges the code -> refresh token

Prints TIKTOK_REFRESH_TOKEN — paste it into .env and the repo's GitHub secrets.
The pipeline auto-rotates it from then on, so this is a one-time step.
"""
import argparse
import urllib.parse

import requests

from common import env, log

SCOPE = "video.upload"            # inbox/draft mode (no full app review needed)
DEFAULT_REDIRECT = "https://astrotobby.site/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code", nargs="?", help="the ?code=... value from the redirect URL")
    ap.add_argument("--redirect", default=env("TIKTOK_REDIRECT_URI") or DEFAULT_REDIRECT,
                    help="redirect URI registered on the TikTok app (must match exactly)")
    args = ap.parse_args()

    ck, cs = env("TIKTOK_CLIENT_KEY"), env("TIKTOK_CLIENT_SECRET")
    if not (ck and cs):
        raise SystemExit("Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in .env first.")

    if not args.code:
        url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
            "client_key": ck,
            "scope": SCOPE,
            "response_type": "code",
            "redirect_uri": args.redirect,
            "state": "blog2video",
        })
        log("Open this URL, approve, then re-run with the ?code=... value:")
        print("\n" + url + "\n")
        return

    # TikTok hands back a url-encoded code; it must be decoded before exchange.
    code = urllib.parse.unquote(args.code)
    r = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"client_key": ck, "client_secret": cs, "code": code,
              "grant_type": "authorization_code", "redirect_uri": args.redirect},
        timeout=60).json()
    refresh = r.get("refresh_token")
    if not refresh:
        raise SystemExit("No refresh_token returned (code may be expired/used). "
                         "Re-authorize for a fresh code. Response: " + str(r)[:300])
    log("SUCCESS — add this to your .env and GitHub secrets:")
    print("\nTIKTOK_REFRESH_TOKEN=" + refresh + "\n")


if __name__ == "__main__":
    main()

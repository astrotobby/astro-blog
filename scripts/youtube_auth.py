"""One-time: get a YouTube refresh token. Run locally once.

Prereqs: YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET in .env (Desktop OAuth client).
Prints YOUTUBE_REFRESH_TOKEN — paste it into .env and GitHub secrets.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

from common import env, log

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    cid, secret = env("YOUTUBE_CLIENT_ID"), env("YOUTUBE_CLIENT_SECRET")
    if not (cid and secret):
        raise SystemExit("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first.")
    cfg = {
        "installed": {
            "client_id": cid,
            "client_secret": secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
    creds = flow.run_local_server(port=0)
    log("SUCCESS — add this to your secrets:")
    print("\nYOUTUBE_REFRESH_TOKEN=" + creds.refresh_token + "\n")


if __name__ == "__main__":
    main()

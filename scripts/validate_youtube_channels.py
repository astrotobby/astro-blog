"""Validate existing YouTube channel refresh tokens without uploading anything.

Run in GitHub Actions with channel-specific credentials supplied as environment variables.
Only channel names, IDs, and credential-variable names are reported; token values are never printed.
"""
import sys

from common import env, log
from platforms import _yt_client_for_token, _yt_verify_channel, _youtube_channel_profile


CHANNEL_KEYS = ("digital_nomad", "astrotobbyc")


def validate_channel(channel_key):
    profile = _youtube_channel_profile({"channel_key": channel_key})
    token = env(profile["token_env"])
    if not token:
        return {
            "ok": False,
            "channel": profile["expected_title"],
            "error": f"missing environment credential {profile['token_env']}",
        }

    yt, client_label = _yt_client_for_token(token)
    identity = _yt_verify_channel(yt, profile)
    return {
        "ok": True,
        "channel": identity["title"],
        "channel_id": identity["id"],
        "oauth_client_pair": client_label,
    }


def main():
    failures = 0
    for channel_key in CHANNEL_KEYS:
        try:
            result = validate_channel(channel_key)
            if result["ok"]:
                log(
                    f"VERIFIED {channel_key}: {result['channel']} "
                    f"({result['channel_id'] or 'channel ID unavailable'}); "
                    f"OAuth pair={result['oauth_client_pair']}"
                )
            else:
                failures += 1
                log(f"NOT VERIFIED {channel_key}: {result['error']}")
        except Exception as exc:  # noqa: report reason, never credential values
            failures += 1
            log(f"NOT VERIFIED {channel_key}: {str(exc)[:300]}")

    if failures:
        log(f"YouTube channel authentication validation failed for {failures} channel(s). No uploads were attempted.")
        return 1
    log("Both YouTube channel credentials validated successfully. No uploads were attempted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

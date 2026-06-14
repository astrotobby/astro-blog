"""Auto-refresh the Instagram long-lived token and write it back to the
INSTAGRAM_TOKEN GitHub secret. Runs on a schedule from
.github/workflows/refresh-ig-token.yml — keeps the ~60-day token from ever lapsing.

Env it needs (provided by the workflow):
  INSTAGRAM_TOKEN   - the current long-lived token (the secret to roll)
  GH_PAT            - a fine-grained PAT with repo "Secrets: Read and write"
  GITHUB_REPOSITORY - owner/repo (auto-set by Actions)

The token is never printed; only the new expiry (in days) is logged.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def _get(url, params):
    q = urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(f"{url}?{q}", timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:  # noqa
            return {"error": f"HTTP {e.code}"}


def _gh(method, path, pat, body=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}",
        data=json.dumps(body).encode() if body else None, method=method)
    req.add_header("Authorization", "token " + pat)
    req.add_header("Accept", "application/vnd.github+json")
    r = urllib.request.urlopen(req, timeout=60)
    return r.status, (json.loads(r.read().decode()) if r.length else {})


def main():
    cur = os.environ.get("INSTAGRAM_TOKEN", "")
    pat = os.environ.get("GH_PAT", "")
    if not cur or not pat:
        print("missing INSTAGRAM_TOKEN or GH_PAT env; nothing to do")
        sys.exit(1)

    # 1) refresh (extends another ~60 days from today)
    r = _get("https://graph.instagram.com/refresh_access_token",
             {"grant_type": "ig_refresh_token", "access_token": cur})
    new = r.get("access_token")
    if not new:
        print("refresh failed:", json.dumps(r))
        sys.exit(1)
    print("refreshed OK; new token valid ~%d days" % (r.get("expires_in", 0) // 86400))

    # 2) write it back to the INSTAGRAM_TOKEN secret (encrypted sealed box)
    from nacl import encoding, public
    _, pk = _gh("GET", "/actions/secrets/public-key", pat)
    box = public.SealedBox(public.PublicKey(pk["key"].encode(), encoding.Base64Encoder()))
    enc = base64.b64encode(box.encrypt(new.encode())).decode()
    st, _ = _gh("PUT", "/actions/secrets/INSTAGRAM_TOKEN", pat,
                {"encrypted_value": enc, "key_id": pk["key_id"]})
    print("INSTAGRAM_TOKEN secret update status:", st, "(201/204 = ok)")
    if st not in (201, 204):
        sys.exit(1)


if __name__ == "__main__":
    main()

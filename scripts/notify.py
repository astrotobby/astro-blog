"""Stage 5: Telegram summary of the run.

Usage:
  python scripts/notify.py .pipeline/results.json
  python scripts/notify.py --test
"""
import argparse

import requests

from common import env, log, read_json


def send(text):
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not (token and chat):
        log("no Telegram creds; printing instead:\n" + text)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": False},
        timeout=30,
    )
    log(f"telegram status {r.status_code}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_json", nargs="?")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    if args.test:
        send("✅ <b>blog-to-video</b> test message — your bot works.")
        return

    data = read_json(args.results_json)
    post = data["post"]
    lines = [f"🎬 <b>{post['title']}</b>", post["url"], ""]
    for plat, r in data["results"].items():
        if r.get("skipped"):
            lines.append(f"⏭️ {plat}: {r['skipped']}")
        elif r.get("ok"):
            lines.append(f"✅ {plat}: {r.get('url', 'posted')}")
        else:
            lines.append(f"❌ {plat}: {str(r.get('error', 'failed'))[:120]}")
    send("\n".join(lines))


if __name__ == "__main__":
    main()

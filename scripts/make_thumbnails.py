"""Generate + set catchy YouTube thumbnails for already-published videos.

For each upload: build a 1280x720 thumbnail = topic AI background (free HF Inference,
gradient fallback) + dark gradient for legibility + bold punchy title + a niche tag
pill + brand strip, then call thumbnails().set(). Runs in GitHub Actions (YouTube
force-ssl + HF_TOKEN). Custom thumbnails need a phone-verified channel (else 403).

Env: YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN, HF_TOKEN.
Optional arg: --only <videoId>  (do a single video).
"""
import os
import sys
import time

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
ACCENT = (255, 209, 0)          # punchy yellow
_BOLD_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
               "/Library/Fonts/Arial Bold.ttf"]


def load_bold(size):
    for p in _BOLD_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:  # noqa
            continue
    return ImageFont.load_default()

NICHE = [
    ("AI", ["ai", "llm", "gpt", "agent", "model", "neural", "prompt", "claude", "gemini", "openai"]),
    ("CRYPTO", ["crypto", "web3", "blockchain", "defi", "gamefi", "nft", "token", "bitcoin", "ethereum"]),
    ("DEV", ["code", "coding", "developer", "github", "copilot", "programming", "software", "api"]),
    ("AI VIDEO", ["video", "sora", "runway", "veo", "reels", "footage", "render"]),
    ("AUTOMATION", ["automation", "automate", "workflow", "nocode", "agent"]),
    ("TECH", []),  # default
]


def niche_tag(title):
    low = title.lower()
    for tag, sig in NICHE:
        if any(s in low for s in sig):
            return tag
    return "TECH"


def hf_bg(prompt, token):
    if not token:
        return None
    models = ["black-forest-labs/FLUX.1-schnell", "stabilityai/sdxl-turbo"]
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"inputs": prompt, "parameters": {"width": 1280, "height": 720}}
    for model in models:
        url = f"https://api-inference.huggingface.co/models/{model}"
        for _ in range(3):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=120)
                if r.status_code == 200 and r.content[:2] in (b"\xff\xd8", b"\x89P"):
                    from io import BytesIO
                    return Image.open(BytesIO(r.content)).convert("RGB")
                if r.status_code == 503:
                    time.sleep(10); continue
                break
            except Exception:  # noqa
                break
    return None


def gradient_bg(seed):
    base = [(18, 22, 50), (45, 18, 60), (10, 45, 55), (55, 30, 18)][seed % 4]
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        for_t = y / H
        for x in range(W):
            t = (for_t + x / W) / 2
            px[x, y] = tuple(int(base[c] * (1 - t) + min(255, base[c] + 90) * t) for c in range(3))
    return img


def cover(img):
    iw, ih = img.size
    scale = max(W / iw, H / ih)
    img = img.resize((int(iw * scale), int(ih * scale)))
    x = (img.width - W) // 2
    y = (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def fit_font(draw, text, max_w, start, min_size=44):
    size = start
    while size > min_size:
        f = load_bold(size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return load_bold(min_size)


def wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_thumb(title, token, seed, out_path, avatar=None):
    prompt = (f"cinematic dramatic thumbnail background about {title}, vibrant, high "
              f"contrast, bold colors, professional, no text, no words")
    bg = hf_bg(prompt, token) or gradient_bg(seed)
    bg = cover(bg).filter(ImageFilter.GaussianBlur(1))

    # darken + bottom gradient for text legibility
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rectangle([0, 0, W, H], fill=(0, 0, 0, 70))
    for y in range(H):
        a = int(235 * max(0, (y - H * 0.35) / (H * 0.65)))
        od.line([(0, y), (W, y)], fill=(0, 0, 0, min(235, a)))
    img = Image.alpha_composite(bg.convert("RGBA"), ov)
    d = ImageDraw.Draw(img)

    # niche tag pill (top-left)
    tag = niche_tag(title)
    tf = load_bold(40)
    tw = d.textlength(tag, font=tf)
    d.rounded_rectangle([56, 50, 56 + tw + 56, 50 + 64], radius=14, fill=ACCENT)
    d.text((56 + 28, 50 + 10), tag, font=tf, fill=(15, 15, 20))

    # title (bottom-left, big, wrapped) — reserve the right side so it never
    # collides with the avatar bubble; pick the biggest size that fits <=3 lines.
    headline = title.strip()
    if len(headline) > 88:
        headline = headline[:88].rsplit(" ", 1)[0] + "…"
    reserve = 300 if (avatar and os.path.exists(avatar)) else 0
    max_w = W - 112 - reserve
    size = 90
    font = load_bold(size)
    lines = wrap(d, headline, font, max_w)
    while size > 52 and len(lines) > 3:
        size -= 4
        font = load_bold(size)
        lines = wrap(d, headline, font, max_w)
    lines = lines[:4]
    lh = int(font.size * 1.14)
    total = lh * len(lines)
    y = H - 60 - total
    d.rectangle([58, y - 18, 58 + 130, y - 8], fill=ACCENT)   # accent bar above title
    for ln in lines:
        d.text((58, y), ln, font=font, fill=(255, 255, 255),
               stroke_width=6, stroke_fill=(0, 0, 0))
        y += lh

    # brand strip (top-right)
    bf = load_bold(34)
    brand = "ASTROTOBBY.SITE"
    bw = d.textlength(brand, font=bf)
    d.text((W - bw - 56, 60), brand, font=bf, fill=(255, 255, 255),
           stroke_width=3, stroke_fill=(0, 0, 0))

    # optional avatar circle (bottom-right)
    if avatar and os.path.exists(avatar):
        try:
            av = Image.open(avatar).convert("RGBA")
            d_av = 220
            av = cover_sq(av, d_av)
            mask = Image.new("L", (d_av, d_av), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, d_av - 1, d_av - 1], fill=255)
            img.paste(av, (W - d_av - 48, H - d_av - 40), mask)
            ring = Image.new("RGBA", (d_av, d_av), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse([3, 3, d_av - 4, d_av - 4], outline=ACCENT, width=8)
            img.paste(ring, (W - d_av - 48, H - d_av - 40), ring)
        except Exception:  # noqa
            pass

    img.convert("RGB").save(out_path, "JPEG", quality=88)
    return out_path


def cover_sq(img, d):
    s = min(img.size)
    img = img.crop(((img.width - s) // 2, (img.height - s) // 2,
                    (img.width - s) // 2 + s, (img.height - s) // 2 + s))
    return img.resize((d, d))


def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    cid = os.environ.get("YOUTUBE_CLIENT_ID")
    csec = os.environ.get("YOUTUBE_CLIENT_SECRET")
    rtok = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    token = os.environ.get("HF_TOKEN")
    if not (cid and csec and rtok):
        raise SystemExit("missing YouTube creds")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=rtok, token_uri="https://oauth2.googleapis.com/token",
                        client_id=cid, client_secret=csec)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    up = yt.channels().list(part="contentDetails", mine=True).execute()
    pl_id = up["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    vids, page = [], None
    while True:
        pl = yt.playlistItems().list(part="contentDetails,snippet", playlistId=pl_id,
                                     maxResults=50, pageToken=page).execute()
        for it in pl["items"]:
            sn = it["snippet"]
            vids.append((it["contentDetails"]["videoId"], sn["title"], sn.get("description", "")))
        page = pl.get("nextPageToken")
        if not page:
            break
    if only:
        vids = [v for v in vids if v[0] == only]
    elif "--all" not in sys.argv:
        # ONLY the blog-pipeline videos (their description links to the site) — never
        # touch the user's personal uploads. Pass --all to override.
        vids = [v for v in vids if "astrotobby.site" in (v[2] or "").lower()]
    print(f"{len(vids)} video(s) to thumbnail")
    os.makedirs(".pipeline/thumbs", exist_ok=True)
    done = blocked = 0
    for i, (vid, title, _desc) in enumerate(vids):
        path = f".pipeline/thumbs/{vid}.jpg"
        try:
            make_thumb(title, token, i, path, avatar="assets/avatar.png")
        except Exception as e:  # noqa
            print("THUMB GEN FAILED", vid, str(e)[:160]); continue
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(path)).execute()
            done += 1
            print("SET", vid, "|", title[:50])
        except Exception as e:  # noqa
            msg = str(e)
            if "403" in msg or "forbidden" in msg.lower():
                blocked += 1
                print("BLOCKED (channel not verified for custom thumbnails?)", vid, msg[:140])
            else:
                print("SET FAILED", vid, msg[:160])
    print(f"DONE: {done} thumbnails set, {blocked} blocked")


if __name__ == "__main__":
    main()

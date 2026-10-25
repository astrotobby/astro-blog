"""Animated stat and key-point scenes rendered with HyperFrames (HTML -> MP4).

The blog post's own facts become branded motion graphics in place of a few generic
stock clips:
  * stat card   - a DATA scene's headline number counts up, with its claim beneath
  * key points  - the payoff scene lists three takeaways from the post's headings

Each card is an HTML composition (GSAP timeline) rendered once per format by the
HyperFrames CLI (headless Chrome + FFmpeg, see scripts/setup_hyperframes.sh).
apply_cards() swaps the rendered MP4s into the scene asset list; generate_video plays
a card as one continuous shot from its first frame. Any failure keeps the stock clip.
"""
import html
import re
import shutil
import subprocess

from common import OUT, ROOT, log

CARD_SECONDS = 8.0
HF_DIR = ROOT / ".hyperframes"          # npm project with the hyperframes CLI
SKIP_HEADINGS = re.compile(r"^(introduction|conclusion|faq|faqs|frequently asked|summary|"
                           r"final thoughts|table of contents|references|sources)\b", re.I)
_UNITS = r"(?:\s?(?:%|percent|per cent|x|times|million|billion|trillion|[kKmMbB]\b))"
STAT_RE = re.compile(r"(?<![\w.])([$€£]?\d[\d,]*(?:\.\d+)?)" + _UNITS + r"?")


# ---------- 1. facts from the post ----------
def _segments(narration, n):
    """The same word-count split build_script.make_scenes uses for scene i."""
    words = narration.split()
    base, rem = divmod(len(words), n)
    out, idx = [], 0
    for i in range(n):
        count = base + (1 if i < rem else 0)
        out.append(" ".join(words[idx:idx + count]))
        idx += count
    return out


def find_stat(text):
    """Most headline-worthy number in a narration beat, as (value, unit, claim) or
    None. Prefers %, money and big units; ignores bare years and tiny counts."""
    best = None
    for m in STAT_RE.finditer(text or ""):
        raw, whole = m.group(1), m.group(0)
        unit = whole[len(raw):].strip()
        digits = raw.lstrip("$€£").replace(",", "")
        try:
            value = float(digits)
        except ValueError:
            continue
        is_year = not unit and raw[0].isdigit() and 1900 <= value <= 2100 and "." not in digits
        if is_year or (not unit and raw[0].isdigit() and value < 10):
            continue
        score = (3 if unit in ("%", "percent", "per cent") else 0) + (3 if raw[0] in "$€£" else 0) \
            + (2 if unit.lower() in ("million", "billion", "trillion") else 0) + (1 if unit else 0) \
            + (2 if value >= 1000 else 0)
        if best is None or score > best[0]:
            best = (score, raw, unit, m)
    if best is None:
        return None
    _, raw, unit, m = best
    sentence = re.split(r"(?<=[.!?])\s+", text)
    claim = next((s for s in sentence if m.group(0) in s), text)
    claim = " ".join(claim.replace(m.group(0), "", 1).split()).strip(" ,;:-.")
    if len(claim) > 70:
        claim = claim[:70].rsplit(" ", 1)[0] + "…"
    unit = {"percent": "%", "per cent": "%", "times": "x", "million": "M", "billion": "B",
            "trillion": "T"}.get(unit.lower(), unit)
    return raw, unit, claim


def key_points(body, n=3):
    """Up to n short takeaways from the post's H2/H3 headings."""
    points = []
    for line in (body or "").splitlines():
        m = re.match(r"^#{2,3}\s+(.+)$", line.strip())
        if not m:
            continue
        text = re.sub(r"[*_`#\[\]]|\(http\S+\)", "", m.group(1)).strip(" :?.")
        text = re.sub(r"^\d+[.)]\s*", "", text)
        if not text or SKIP_HEADINGS.match(text) or text in points:
            continue
        if len(text) > 44:
            text = text[:44].rsplit(" ", 1)[0] + "…"
        points.append(text)
        if len(points) == n:
            break
    return points if len(points) == n else []


# ---------- 2. compositions ----------
_STYLE = """
:root{--gold:#E8C27A;--ink:#0B0B0F}
*{margin:0;padding:0;box-sizing:border-box}
#stage{position:relative;overflow:hidden;background:radial-gradient(120% 80% at 50% 35%,#1d1a14 0%,#0d0c10 55%,#060608 100%);
 font-family:'Inter','Helvetica Neue',Arial,sans-serif;color:#fff}
.glow{position:absolute;border-radius:50%;filter:blur(120px);background:radial-gradient(circle,#c99a4a 0%,transparent 70%)}
.kicker{color:var(--gold);letter-spacing:.32em;font-weight:700;text-transform:uppercase}
.num{font-family:'Anton','Impact',sans-serif;line-height:.9;letter-spacing:-.01em;
 background:linear-gradient(180deg,#fff 0%,#f3dfb3 60%,var(--gold) 100%);-webkit-background-clip:text;color:transparent}
.bar{height:6px;background:linear-gradient(90deg,var(--gold),#fff3d6);border-radius:3px;transform-origin:left center}
.claim{font-weight:600;line-height:1.25;color:#f2efe8}
.brand{position:absolute;color:rgba(255,255,255,.55);letter-spacing:.2em;font-weight:600;text-transform:uppercase}
.item{display:flex;align-items:center;gap:.7em;font-weight:700;color:#f6f2ea;line-height:1.15}
.dot{flex:none;display:flex;align-items:center;justify-content:center;border-radius:50%;
 background:var(--gold);color:var(--ink);font-family:'Anton','Impact',sans-serif}
"""


def _page(card_id, w, h, body, script):
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@600;700&display=block" rel="stylesheet">
<style>{_STYLE} #stage{{width:{w}px;height:{h}px}}</style></head>
<body>
<div id="stage" data-composition-id="{card_id}" data-start="0" data-width="{w}" data-height="{h}">
{body}
<script src="https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"></script>
<script>
const tl = gsap.timeline({{paused: true}});
{script}
window.__timelines = window.__timelines || {{}};
window.__timelines["{card_id}"] = tl;
</script>
</div></body></html>"""


def _clip(inner, cls="", style="", duration=CARD_SECONDS):
    return (f'<div class="clip {cls}" data-start="0" data-duration="{duration}" '
            f'data-track-index="0" style="{style}">{inner}</div>')


def stat_html(card_id, w, h, value, unit, claim, brand):
    vertical = h > w
    s = w / 1080 if vertical else h / 1080           # scale relative to 1080 short side
    top = int(h * (0.20 if vertical else 0.16))
    digits = value.lstrip("$€£").replace(",", "")
    prefix = value[:len(value) - len(value.lstrip("$€£"))]
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    num_size = int((300 if len(value + unit) <= 5 else 230) * s)
    body = _clip(
        f'<div class="glow" style="width:{int(900*s)}px;height:{int(900*s)}px;left:50%;top:{int(top+150*s)}px;'
        f'margin-left:-{int(450*s)}px;opacity:.35" id="glow"></div>'
        f'<div style="position:absolute;left:0;right:0;top:{top}px;text-align:center;padding:0 {int(80*s)}px">'
        f'<div class="kicker" id="kick" style="font-size:{int(34*s)}px">The number</div>'
        f'<div class="num" id="num" style="font-size:{num_size}px;margin-top:{int(30*s)}px">'
        f'{html.escape(prefix)}<span id="val">0</span>{html.escape(unit)}</div>'
        f'<div class="bar" id="bar" style="width:{int(260*s)}px;margin:{int(36*s)}px auto 0"></div>'
        f'<div class="claim" id="claim" style="font-size:{int(54*s)}px;margin-top:{int(40*s)}px">'
        f'{html.escape(claim)}</div></div>'
        f'<div class="brand" style="font-size:{int(26*s)}px;left:0;right:0;text-align:center;'
        f'top:{int(top - 90*s)}px">{html.escape(brand)}</div>',
        style="position:absolute;inset:0")
    target = float(digits)
    script = f"""
const counter = {{v: 0}};
const fmt = v => v.toLocaleString('en-US', {{minimumFractionDigits: {decimals}, maximumFractionDigits: {decimals}}});
tl.from("#kick", {{y: 30, opacity: 0, duration: 0.5, ease: "power3.out"}}, 0.1)
  .from("#num", {{scale: 0.6, opacity: 0, duration: 0.7, ease: "back.out(1.6)"}}, 0.25)
  .to(counter, {{v: {target}, duration: 1.4, ease: "power2.out",
     onUpdate: () => {{ document.getElementById("val").textContent = fmt(counter.v); }}}}, 0.25)
  .from("#bar", {{scaleX: 0, duration: 0.6, ease: "power3.inOut"}}, 0.9)
  .from("#claim", {{y: 40, opacity: 0, duration: 0.6, ease: "power3.out"}}, 1.2)
  .to("#num", {{scale: 1.04, duration: {CARD_SECONDS - 1.6}, ease: "none"}}, 1.6)
  .to("#glow", {{opacity: 0.55, scale: 1.15, duration: {CARD_SECONDS}, ease: "sine.inOut"}}, 0);
document.getElementById("val").textContent = fmt(0);
"""
    return _page(card_id, w, h, body, script)


def points_html(card_id, w, h, points, brand):
    vertical = h > w
    s = w / 1080 if vertical else h / 1080
    top = int(h * (0.18 if vertical else 0.14))
    items = "".join(
        f'<div class="item" id="p{i}" style="font-size:{int(54*s)}px;margin-top:{int(44*s)}px">'
        f'<span class="dot" style="width:{int(78*s)}px;height:{int(78*s)}px;font-size:{int(44*s)}px">{i + 1}</span>'
        f'<span>{html.escape(p)}</span></div>' for i, p in enumerate(points))
    body = _clip(
        f'<div class="glow" style="width:{int(800*s)}px;height:{int(800*s)}px;left:-{int(200*s)}px;'
        f'top:{int(top)}px;opacity:.3" id="glow"></div>'
        f'<div style="position:absolute;left:{int(90*s)}px;right:{int(90*s)}px;top:{top}px">'
        f'<div class="brand" style="position:static;font-size:{int(26*s)}px">{html.escape(brand)}</div>'
        f'<div class="kicker" id="kick" style="font-size:{int(40*s)}px;margin-top:{int(24*s)}px">Key takeaways</div>'
        f'<div class="bar" id="bar" style="width:{int(220*s)}px;margin-top:{int(24*s)}px"></div>'
        f'{items}</div>',
        style="position:absolute;inset:0")
    script = """
tl.from("#kick", {y: 30, opacity: 0, duration: 0.5, ease: "power3.out"}, 0.1)
  .from("#bar", {scaleX: 0, duration: 0.6, ease: "power3.inOut"}, 0.3)
""" + "".join(
        f'  .from("#p{i}", {{x: -60, opacity: 0, duration: 0.6, ease: "power3.out"}}, {0.7 + i * 0.9:.1f})\n'
        for i in range(len(points))) + f"""  .to("#glow", {{x: 120, opacity: 0.5, duration: {CARD_SECONDS}, ease: "sine.inOut"}}, 0);
"""
    return _page(card_id, w, h, body, script)


# ---------- 3. render ----------
def _cli():
    exe = HF_DIR / "node_modules" / ".bin" / "hyperframes"
    return exe if exe.exists() else None


def render_card(card_id, page_html, out_path):
    """Render one composition to MP4 with the HyperFrames CLI. Returns out_path or None."""
    cli = _cli()
    if cli is None:
        log("motion cards: HyperFrames not set up (.hyperframes missing)")
        return None
    project = OUT / f"_card_{card_id}"
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir(parents=True)
    (project / "index.html").write_text(page_html, encoding="utf-8")
    cmd = [str(cli), "render", "-c", "index.html", "-o", str(out_path)]
    r = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 10000:
        log(f"motion card {card_id} failed (rc={r.returncode}): "
            f"{((r.stderr or '') + (r.stdout or ''))[-600:]}")
        return None
    log(f"motion card {card_id} -> {out_path.name}")
    return out_path


def apply_cards(script, cfg, assets, variant):
    """Replace up to `max_stat_cards` DATA scenes with stat cards and the PAYOFF scene
    with a key-points card. `assets` is [(path, meta)] from fetch_scene_assets."""
    mc = cfg.get("motion_cards", {})
    if not mc.get("enabled") or not assets:
        return assets
    size = cfg["video"][variant]
    w, h = size["w"], size["h"]
    brand = mc.get("brand", "astrotobby")
    segments = _segments(script.get("narration", ""), len(assets))
    out = list(assets)
    stats_left = int(mc.get("max_stat_cards", 2))
    for i, (asset, meta) in enumerate(assets):
        kind = (meta or {}).get("scene_type")
        page = None
        if kind == "DATA" and stats_left > 0:
            stat = find_stat(segments[i])
            if stat:
                page = stat_html(f"stat{i}", w, h, *stat, brand)
                stats_left -= 1
        elif kind == "PAYOFF" and mc.get("key_points", True):
            points = key_points(script["post"].get("body", ""))
            if points:
                page = points_html(f"points{i}", w, h, points, brand)
        if page is None:
            continue
        card = render_card(f"{variant}_{i}", page, OUT / f"card_{variant}_{i:02d}.mp4")
        if card:
            out[i] = (card, dict(meta or {}, card=True))
    return out


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["--sample"]:
        sys.exit("usage: python scripts/motion_cards.py --sample")
    for name, (w, h) in {"9x16": (1080, 1920), "16x9": (1920, 1080)}.items():
        render_card(f"sample_stat_{name}", stat_html(f"s{name}", w, h, "72", "%",
                    "of companies now use AI agents every day", "astrotobby"),
                    OUT / f"sample_stat_{name}.mp4")
        render_card(f"sample_points_{name}", points_html(f"p{name}", w, h,
                    ["Agents now run whole workflows", "Costs dropped 10x in a year",
                     "Start with one repeatable task"], "astrotobby"),
                    OUT / f"sample_points_{name}.mp4")

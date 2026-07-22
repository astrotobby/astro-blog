"""Stage 2: turn the post into a narration script + per-scene image prompts.

Extractive + template based (no paid LLM needed). If ANTHROPIC_API_KEY is set
it will optionally polish the hook, but it is NOT required.

Usage: python scripts/build_script.py .pipeline/post.json
"""
import argparse
import re

from common import load_config, log, read_json, write_json

# Niche -> (signal words that detect it in the post, curated relevant hashtags).
# Hashtags are chosen to MATCH the content niche instead of dumping a fixed set.
NICHE_TAGS = {
    "ai": (["ai", "a.i", "llm", "gpt", "model", "agent", "machine learning", "neural",
            "prompt", "openai", "anthropic", "claude", "gemini", "chatbot", "inference",
            "multiagent", "multi-agent"],
           ["#AI", "#ArtificialIntelligence", "#MachineLearning", "#LLM", "#AIagents",
            "#GenAI", "#AItools", "#FutureOfAI"]),
    "crypto": (["crypto", "web3", "blockchain", "defi", "gamefi", "nft", "token",
                "ethereum", "bitcoin", "wallet", "dao", "staking", "altcoin"],
               ["#crypto", "#web3", "#blockchain", "#DeFi", "#GameFi", "#NFT",
                "#cryptocurrency", "#CryptoNews"]),
    "dev": (["code", "coding", "developer", "programming", "software", "github",
             "copilot", "framework", "api", "open-source", "open source", "python",
             "javascript", "devtools"],
            ["#coding", "#developer", "#programming", "#softwaredevelopment",
             "#opensource", "#devtools"]),
    "video": (["video", "sora", "reels", "footage", "render", "animation",
               "filmmaking", "veo", "runway", "midjourney"],
              ["#AIvideo", "#contentcreation", "#videomarketing", "#creators"]),
    "automation": (["automation", "automate", "workflow", "no-code", "nocode",
                    "zapier", "make.com", "productivity"],
                   ["#automation", "#nocode", "#productivity", "#AIautomation"]),
    "business": (["startup", "founder", "saas", "marketing", "growth", "revenue",
                  "business", "entrepreneur"],
                 ["#startup", "#SaaS", "#marketing", "#growth", "#entrepreneur"]),
}

_TERM_STOP = set(
    "the a an and or of to in for with on is are be this that it as at by from your "
    "you why what how when where who which 2026 2025 year new best top guide ways "
    "things into about will can your most free secret secretly system real big huge "
    "quietly dominating shifts everything nobody secretly using becoming".split()
)

# ---------------------------------------------------------------------------
# Topic category detection — drives the visual language per post
# ---------------------------------------------------------------------------
# Each category maps to a visual grammar: a set of image-prompt modifiers that
# produce footage matching the post's world, not generic "AI face" stock tropes.
TOPIC_VISUAL_PROFILES = {
    "security": {
        "signals": ["security", "cyber", "threat", "breach", "attack", "vulnerability",
                    "risk", "hack", "malware", "ransomware", "firewall", "encryption"],
        "visual_language": [
            "dark server room with red warning lights, cinematic surveillance aesthetic",
            "digital lock and shield hologram, deep shadow, high contrast",
            "cybersecurity operations center, analysts at screens, dramatic blue light",
            "abstract data breach visualization, red particle streams on black",
            "encrypted data tunnel, glowing green matrix-style, documentary style",
        ],
        "grade": "eq=contrast=1.18:saturation=1.10:brightness=-0.02:gamma=0.95,"
                 "colorbalance=rs=0.06:bs=-0.04:rh=0.04:bh=-0.05,"
                 "vignette=PI/4,unsharp=5:5:0.7:5:5:0.0,noise=alls=4:allf=t",
    },
    "healthcare": {
        "signals": ["healthcare", "health", "medical", "hospital", "patient", "clinical",
                    "doctor", "diagnosis", "treatment", "pharma", "biotech", "surgery"],
        "visual_language": [
            "modern hospital corridor with soft blue light, clean clinical aesthetic",
            "doctor reviewing AI diagnostic interface, warm professional lighting",
            "medical data visualization on holographic display, teal and white",
            "human hands and technology interface, shallow depth of field, editorial",
            "research laboratory with scientists, cool desaturated documentary style",
        ],
        "grade": "eq=contrast=1.10:saturation=0.95:brightness=0.03:gamma=1.02,"
                 "colorbalance=rs=-0.05:bs=0.07:rh=-0.03:bh=0.04,"
                 "vignette=PI/6,unsharp=5:5:0.5:5:5:0.0,noise=alls=3:allf=t",
    },
    "finance": {
        "signals": ["finance", "payment", "fintech", "banking", "transaction", "revenue",
                    "investment", "trading", "stock", "currency", "crypto", "wallet",
                    "accounting", "invoice", "budget", "financial"],
        "visual_language": [
            "trading floor with real-time data screens, warm amber and gold tones",
            "financial data dashboard with charts, sharp editorial photography",
            "hands exchanging digital payment, close-up, warm cinematic light",
            "bank vault or secure server room, deep shadow, gold accent lighting",
            "global financial network visualization, aerial perspective, warm tones",
        ],
        "grade": "eq=contrast=1.15:saturation=1.20:brightness=0.01:gamma=0.98,"
                 "colorbalance=rs=0.05:bs=-0.06:rh=0.07:bh=-0.04,"
                 "vignette=PI/5,unsharp=5:5:0.6:5:5:0.0,noise=alls=4:allf=t",
    },
    "automation": {
        "signals": ["automation", "automate", "workflow", "no-code", "nocode",
                    "pipeline", "zapier", "make.com", "productivity", "process",
                    "robotic", "rpa", "orchestration"],
        "visual_language": [
            "clean modern workspace with multiple monitors showing workflow diagrams",
            "robotic arm in factory with precision motion, industrial cinematic style",
            "software interface with connected nodes and automation flows, clean UI",
            "person at laptop with holographic workflow overlay, editorial style",
            "time-lapse of automated assembly, dynamic motion, high contrast",
        ],
        "grade": "eq=contrast=1.12:saturation=1.18:brightness=0.02:gamma=0.97,"
                 "colorbalance=rs=-0.03:bs=0.04:rh=0.04:bh=-0.05,"
                 "vignette=PI/5,unsharp=5:5:0.6:5:5:0.0,noise=alls=5:allf=t",
    },
    "llm_model": {
        "signals": ["llm", "gpt", "claude", "gemini", "model", "language model",
                    "transformer", "neural network", "inference", "training", "weights",
                    "parameter", "benchmark", "multimodal"],
        "visual_language": [
            "neural network architecture visualization, glowing nodes, deep space background",
            "GPU server cluster with dramatic lighting, data center cinematic style",
            "human and AI interface, split-screen documentary, cool blue tones",
            "abstract language model token flow, particle streams, dark background",
            "researcher at workstation with model output on screen, warm editorial",
        ],
        "grade": "eq=contrast=1.13:saturation=1.24:brightness=0.02:gamma=0.97,"
                 "colorbalance=rs=-0.04:bs=0.05:rh=0.05:bh=-0.06,"
                 "vignette=PI/5,unsharp=5:5:0.6:5:5:0.0,noise=alls=5:allf=t",
    },
    "general_ai": {
        "signals": ["ai", "artificial intelligence", "machine learning", "agent",
                    "chatbot", "openai", "anthropic", "deepmind", "algorithm"],
        "visual_language": [
            "futuristic AI research lab with scientists, cinematic documentary style",
            "human and robot collaboration, warm natural light, editorial photography",
            "AI chip close-up with dramatic macro photography, teal-orange grade",
            "city skyline with AI infrastructure overlay, aerial cinematic shot",
            "person interacting with AI interface, shallow depth of field, warm tones",
        ],
        "grade": "eq=contrast=1.13:saturation=1.24:brightness=0.02:gamma=0.97,"
                 "colorbalance=rs=-0.04:bs=0.05:rh=0.05:bh=-0.06,"
                 "vignette=PI/5,unsharp=5:5:0.6:5:5:0.0,noise=alls=5:allf=t",
    },
}

# Scene type modifiers — applied on top of the topic visual language.
# Each type shapes the composition and energy of the image prompt.
SCENE_TYPE_MODIFIERS = {
    "HOOK":      "extreme close-up, dramatic reveal, maximum visual impact, scroll-stopping",
    "ESTABLISH": "wide establishing shot, context-setting, world-building, cinematic scope",
    "EXPLAIN":   "medium shot, clear and readable, documentary style, informative composition",
    "TENSION":   "high contrast, dramatic shadows, pattern interrupt, visceral energy",
    "DATA":      "clean data visualization, infographic aesthetic, sharp typography, clarity",
    "PAYOFF":    "warm resolution, golden hour, cinematic wide, satisfying composition",
    "CTA":       "bold brand identity, strong typography, clean minimalist, call to action",
}

# Ken Burns preset tags — passed to generate_video.py via scene metadata.
# The renderer maps these to specific zoompan expressions.
SCENE_TYPE_KENBURNS = {
    "HOOK":      "punch_in",      # hard fast zoom in — maximum energy
    "ESTABLISH": "pull_out",      # slow pull-out — reveals the world
    "EXPLAIN":   "pan_right",     # steady pan — clarity and flow
    "TENSION":   "diagonal",      # fast diagonal push — pattern interrupt
    "DATA":      "static",        # near-static — let the data breathe
    "PAYOFF":    "pull_back",     # slow pull-back — resolution
    "CTA":       "gentle_zoom",   # gentle zoom in — inviting
}

# Scene duration multipliers relative to the base per-scene duration.
SCENE_TYPE_DURATION = {
    "HOOK":      0.60,   # shortest — high energy, fast cut
    "ESTABLISH": 1.00,   # baseline
    "EXPLAIN":   1.10,   # slightly longer — comprehension
    "TENSION":   0.70,   # short — abrupt pattern interrupt
    "DATA":      1.20,   # longer — let the stat land
    "PAYOFF":    1.30,   # longest — breathing room
    "CTA":       1.20,   # longer — let the CTA register
}


def _brandify(term: str) -> str:
    """Turn a word into a hashtag, preserving brand casing (NFT, GameFi, DeFi)."""
    core = re.sub(r"[^A-Za-z0-9]", "", term)
    if not core:
        return ""
    if core.isupper() or any(c.isupper() for c in core[1:]):  # NFT / GameFi / dApp
        return "#" + core
    return "#" + core[0].upper() + core[1:]


def _title_terms(title: str, n: int = 2):
    """A couple of meaningful, specific terms from the headline (casing preserved)."""
    out, seen = [], set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", title):
        lw = w.lower()
        if lw in _TERM_STOP or lw in seen:
            continue
        seen.add(lw)
        out.append(w)
        if len(out) >= n:
            break
    return out


def relevant_hashtags(post, cfg):
    """Content-matched hashtags: the post's own tags + a couple of specific title
    terms + curated tags for the 1-2 niches the text actually scores on. Falls back
    to config 'base' only if nothing matches."""
    text = (post.get("title", "") + " " + post.get("description", "") + " "
            + (post.get("body", "") or "")[:2000]).lower()
    scored = []
    for niche, (signals, tags) in NICHE_TAGS.items():
        score = sum(text.count(s) for s in signals)
        if score:
            scored.append((score, niche, tags))
    scored.sort(reverse=True)

    out, seen = [], set()

    def add(h):
        h = (h or "").strip()
        if len(h) > 1 and h.lower() not in seen:
            seen.add(h.lower())
            out.append(h)

    for t in (post.get("tags") or []):          # 1) the post's own tags (most relevant)
        add(_brandify(t))
    for kw in _title_terms(post.get("title", "")):  # 2) specific terms from the headline
        add(_brandify(kw))
    for _, _, tags in scored[:2]:               # 3) curated tags for top matched niches
        for h in tags:
            add(h)
    if not out:                                  # 4) nothing matched -> config base
        for h in cfg["hashtags"]["base"]:
            add(h)
    return out[: cfg["hashtags"]["max"]]


def sentences(text: str):
    """Split prose into speakable sentences. Markdown tables, heading runs, HTML
    entities and symbol-soup survive upstream stripping in some posts — TTS would
    read them aloud ('pipe pipe dash dash') — so anything that isn't mostly prose
    is dropped here."""
    text = (text.replace("&amp;", "&").replace("&#39;", "'")
                .replace("&quot;", '"').replace("→", " ").replace("`", ""))
    out = []
    for s in re.split(r"(?<=[.!?])\s+", text):
        s = " ".join(s.split())
        if len(s) <= 25:
            continue
        if s.count("|") >= 2 or "---" in s or s.count("#") > 1:
            continue
        prose = sum(1 for c in s if c.isalpha() or c.isspace() or c in ".,'%$&-()")
        if prose / len(s) < 0.85:
            continue
        out.append(s)
    return out


def keywords(text: str, n=6):
    stop = set("the a an and or of to in for with on is are be this that it as at by from your you".split())
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", text.lower())
    freq = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:n]]


# Stripped only when they make the clause ungrammatical. "How" is kept on purpose
# ("how to stake a token" reads fine; "to stake a token" does not).
INTERROGATIVES = ("why ", "what ", "when ", "where ", "who ", "which ",
                  "is ", "are ", "does ", "do ")


def _smart_lower(word: str) -> str:
    """Lower-case normal Title-Case words, but keep ALL-CAPS (NFT) and
    CamelCase / mixed brand tokens (GameFi, DeFi, Web3, dApp) intact."""
    if not word:
        return word
    core = word.strip(".,!?:;")
    if core.isupper():                      # NFT, DAO, API
        return word
    if any(c.isupper() for c in core[1:]):  # GameFi, DeFi, dApp
        return word
    return word.lower()


def clean_topic(title: str) -> str:
    """Turn a headline into a clause that slots into a hook template cleanly.
    'Why GameFi Is Quietly Eating Web2 Gaming' -> 'GameFi is quietly eating web2 gaming'.
    Two-part SEO headlines are cut at '?', ':' or ' — ' so the hook stays punchy:
    'What Is AEO? The 2026 Guide to...' -> 'AEO' (not the whole 20-word title).
    Interrogatives are stripped repeatedly ('What Is X' sheds both 'what' and 'is')."""
    t = title.strip()
    head = re.split(r"[?:]|\s+[—–|]\s+", t, maxsplit=1)[0].strip()
    if len(head.split()) >= 2 or len(t.split()) > 8:
        t = head or t
    t = t.rstrip(" ?.!")
    low = t.lower()
    stripped = True
    while stripped:
        stripped = False
        for q in INTERROGATIVES + ("will ", "can ", "could ", "should "):
            if low.startswith(q) and len(low) > len(q) + 3:
                t = t[len(q):]
                low = t.lower()
                stripped = True
                break
    return " ".join(_smart_lower(w) for w in t.split())


def _specificity(s: str) -> float:
    """Score a sentence by how concrete/quotable it is. Numbers, money, percentages,
    named tools/brands, and comparisons are what stop the scroll; vague filler
    ('in today's fast-paced world...') scores ~0 and gets skipped."""
    score = 0.0
    score += 3.0 * len(re.findall(r"\d[\d,.]*", s))          # numbers / versions / dates
    score += 2.0 * len(re.findall(r"[$%]|\bper cent\b", s))  # money & percentages
    # capitalised tokens mid-sentence = named entities (Claude, TikTok, Make.com)
    words = s.split()
    score += 1.0 * sum(1 for w in words[1:] if w[:1].isupper() and len(w) > 2)
    score += 1.5 * len(re.findall(r"\b(vs\.?|versus|instead of|faster|cheaper|beats?|"
                                  r"replac\w+|kill\w+|nobody|never|first|only)\b", s, re.I))
    n = len(words)
    if n > 32:                                # rambling sentences read badly aloud
        score *= 0.55
    elif n < 6:
        score *= 0.6
    return score


def build_narration(post, cfg):
    """Retention-structured narration:
        HOOK -> context line -> punchiest facts -> RE-HOOK (~40%) -> more facts
        -> MID-CTA (~65%) -> final facts -> closing CTA.
    The re-hook re-opens the curiosity loop right where short-form drop-off peaks,
    and the mid-CTA plants the blog link before viewers who bail early are gone."""
    sc = cfg["script"]
    target = sc["target_seconds"]
    wpm = sc["words_per_minute"]
    budget = int(target * wpm / 60)  # total words

    topic = clean_topic(post["title"])
    seed = hash(post["slug"])
    hook_tpl = sc["hook_styles"][seed % len(sc["hook_styles"])]
    hook = hook_tpl.format(topic=topic)
    hook = hook[0].upper() + hook[1:] if hook else hook  # capitalise sentence start

    rehooks = sc.get("rehooks") or []
    rehook = rehooks[seed % len(rehooks)] if rehooks else ""
    mid_cta = sc.get("mid_cta", "")

    # ---- pick body sentences: keep the opening 1-2 for context, then fill the
    # budget with the most SPECIFIC sentences, replayed in original order so the
    # narration still flows as a story instead of a highlight salad.
    sents = sentences(post["description"] + " " + post["body"])
    overhead = (len(hook.split()) + len(rehook.split()) + len(mid_cta.split()) + 14)
    body_budget = budget - overhead
    lead = sents[:2]
    used = sum(len(s.split()) for s in lead)
    rest = sents[2:]
    ranked = sorted(range(len(rest)), key=lambda i: -_specificity(rest[i]))
    chosen_idx = []
    for i in ranked:
        w = len(rest[i].split())
        if used + w > body_budget:
            continue
        chosen_idx.append(i)
        used += w
    picked = lead + [rest[i] for i in sorted(chosen_idx)]
    if not picked:
        picked = [post["description"]]

    # ---- weave in the re-hook (~40% of body words) and mid-CTA (~65%)
    total_words = sum(len(s.split()) for s in picked)
    woven, acc = [], 0
    rehook_done, midcta_done = not rehook, not mid_cta
    for s in picked:
        woven.append(s)
        acc += len(s.split())
        if not rehook_done and acc >= total_words * 0.40:
            woven.append(rehook)
            rehook_done = True
        elif not midcta_done and rehook_done and acc >= total_words * 0.65:
            woven.append(mid_cta)
            midcta_done = True

    # Per-platform CTA verb: YouTube watches the HORIZONTAL cut ("subscribe"); every
    # other platform (TikTok/IG/FB/X/Threads) watches the VERTICAL cut ("follow"). The
    # body is identical — only the closing verb differs — so we emit both narrations and
    # generate_video renders each cut with its matching voiceover/captions.
    body = [hook] + woven
    def _with_cta(verb):
        return " ".join(body + [sc["cta"].format(sub_or_follow=verb)])
    narration = _with_cta("follow")        # vertical -> TikTok / IG / FB / X / Threads
    narration_yt = _with_cta("subscribe")  # horizontal -> YouTube
    return hook, narration, narration_yt


# ---------------------------------------------------------------------------
# Topic category detection
# ---------------------------------------------------------------------------

def detect_topic_category(post) -> str:
    """Detect the dominant topic category for this post. Returns a key from
    TOPIC_VISUAL_PROFILES. Falls back to 'general_ai' if nothing matches."""
    text = (post.get("title", "") + " " + post.get("description", "") + " "
            + (post.get("body", "") or "")[:3000]).lower()
    best_cat, best_score = "general_ai", 0
    for cat, profile in TOPIC_VISUAL_PROFILES.items():
        score = sum(text.count(sig) for sig in profile["signals"])
        if score > best_score:
            best_score = score
            best_cat = cat
    log(f"topic category: {best_cat} (score={best_score})")
    return best_cat


# ---------------------------------------------------------------------------
# Cinematic scene generation — the core of the redesign
# ---------------------------------------------------------------------------

def _has_stat(text: str) -> bool:
    """True if the text contains a number, percentage, or dollar figure."""
    return bool(re.search(r"\d[\d,.]*\s*[%$kKmMbB]?|\bper cent\b", text))


def _segment_narration(narration: str, n: int) -> list:
    """Split the narration into n segments proportional to word count.
    Returns a list of (segment_text, word_count) tuples."""
    words = narration.split()
    total = len(words)
    base = total // n
    remainder = total % n
    segments = []
    idx = 0
    for i in range(n):
        count = base + (1 if i < remainder else 0)
        seg = " ".join(words[idx:idx + count])
        segments.append(seg)
        idx += count
    return segments


def _classify_scene(i: int, n: int, segment: str, narration: str) -> str:
    """Classify a scene by its position and content into a semantic type.

    Position-based rules (primary):
      0         -> HOOK   (always — first impression, scroll-stopper)
      1         -> ESTABLISH (second scene sets the world)
      n-2       -> PAYOFF (penultimate — resolution beat)
      n-1       -> CTA    (last — call to action)

    Content-based rules (override EXPLAIN for middle scenes):
      ~40% mark -> TENSION (re-hook beat, pattern interrupt)
      has stat  -> DATA
      else      -> EXPLAIN
    """
    if i == 0:
        return "HOOK"
    if i == 1:
        return "ESTABLISH"
    if i == n - 1:
        return "CTA"
    if i == n - 2:
        return "PAYOFF"
    # Middle scenes: check content
    tension_idx = max(2, int(n * 0.40))
    if i == tension_idx:
        return "TENSION"
    if _has_stat(segment):
        return "DATA"
    return "EXPLAIN"


def _scene_keywords(segment: str, post_title: str, n_kw: int = 3) -> str:
    """Extract the most relevant keywords from a narration segment for the prompt."""
    stop = set("the a an and or of to in for with on is are be this that it as at "
               "by from your you here now just really very quite also but here's "
               "that's what's it's don't won't can't isn't aren't we're they're".split())
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", segment.lower())
    freq = {}
    for w in words:
        if w not in stop:
            freq[w] = freq.get(w, 0) + 1
    # Also pull key terms from the post title for grounding
    title_words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", post_title.lower())
    for w in title_words:
        if w not in stop:
            freq[w] = freq.get(w, 0) + 0.5  # lower weight than segment words
    top = [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:n_kw]]
    return " ".join(top) if top else post_title.lower()


def make_scenes(post, cfg):
    """Generate cinematic, semantically-typed scene prompts.

    Each scene prompt is built from:
      1. The topic visual language (category-specific, not generic "AI face")
      2. The scene type modifier (HOOK / ESTABLISH / EXPLAIN / TENSION / DATA / PAYOFF / CTA)
      3. Keywords extracted from the narration segment spoken during that scene
      4. Aspect ratio and quality suffix

    The prompt also embeds metadata (type, kb_preset, duration_mult) so
    generate_video.py can apply the correct Ken Burns motion and pacing.
    """
    n = cfg["visuals"]["scenes"]
    # Build narration for segmentation (use the vertical/follow cut as reference)
    hook, narration, _ = build_narration(post, cfg)
    full_narration = hook + " " + narration

    # Detect topic category and load its visual profile
    cat = detect_topic_category(post)
    profile = TOPIC_VISUAL_PROFILES[cat]
    visual_pool = profile["visual_language"]

    # Segment the narration into n parts
    segments = _segment_narration(full_narration, n)

    prompts = []
    for i, segment in enumerate(segments):
        scene_type = _classify_scene(i, n, segment, full_narration)
        type_modifier = SCENE_TYPE_MODIFIERS[scene_type]
        kb_preset = SCENE_TYPE_KENBURNS[scene_type]
        dur_mult = SCENE_TYPE_DURATION[scene_type]

        # Pick a visual from the topic pool, cycling through them
        base_visual = visual_pool[i % len(visual_pool)]

        # Extract segment-specific keywords for grounding
        seg_kws = _scene_keywords(segment, post["title"])

        # Build the full prompt
        # Format: [base visual], [scene keywords], [type modifier], [quality suffix]
        prompt = (
            f"{base_visual}, {seg_kws}, {type_modifier}, "
            f"photorealistic, ultra detailed, film grain, 9:16, "
            f"scene_type:{scene_type}|kb:{kb_preset}|dur:{dur_mult:.2f}"
        )
        prompts.append(prompt)
        log(f"scene {i} [{scene_type}] kb={kb_preset} dur={dur_mult:.2f} kws={seg_kws[:40]}")

    return prompts


def platform_text(post, cfg):
    out = relevant_hashtags(post, cfg)
    # Use the FULL post URL (not a shortener). URL shorteners (TinyURL/is.gd) showed
    # an interstitial/preview page for script-created links, confusing visitors; the
    # real domain is trustworthy, clean, and resolves straight to the post.
    link = post["url"]
    store = cfg["site"].get("products_url", "")
    store_line = f"\n🧰 AI Starter Pack (guides + templates): {store}" if store else ""
    log(f"{len(out)} matched hashtags; link {link}")
    caption = (f"{post['title']}\n\n{post['description'][:200]}\n\n"
               f"Full post: {link}{store_line}\n\n" + " ".join(out))
    # Instagram strips links in captions (only the bio link is clickable), so a raw URL
    # is dead text — use a "link in bio" CTA there instead.
    ig_caption = (f"{post['title']}\n\n{post['description'][:200]}\n\n"
                  f"🔗 Full breakdown + AI Starter Pack — link in bio\n\n" + " ".join(out))
    yt_title = post["title"][:95]
    yt_desc = (f"{post['description']}\n\nRead more: {link}{store_line}"
               f"\n\n{' '.join(out)}")
    return {"caption": caption, "ig_caption": ig_caption, "hashtags": out, "short_url": link,
            "yt_title": yt_title, "yt_desc": yt_desc}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("post_json")
    args = ap.parse_args()
    cfg = load_config()
    post = read_json(args.post_json)

    hook, narration, narration_yt = build_narration(post, cfg)
    scenes = make_scenes(post, cfg)
    ptext = platform_text(post, cfg)

    out = {
        "post": post,
        "hook": hook,
        "narration": narration,          # vertical cut (TikTok/IG/FB/X) -> "follow"
        "narration_yt": narration_yt,    # horizontal cut (YouTube) -> "subscribe"
        "scene_prompts": scenes,
        "platform": ptext,
        "est_words": len(narration.split()),
    }
    log(f"narration ~{out['est_words']} words, {len(scenes)} scenes")
    write_json("script.json", out)


if __name__ == "__main__":
    main()

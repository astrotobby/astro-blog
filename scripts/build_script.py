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
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in parts if len(s.strip()) > 25]


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
    'Why GameFi Is Quietly Eating Web2 Gaming' -> 'GameFi is quietly eating web2 gaming'."""
    t = title.strip().rstrip(" ?.!")
    low = t.lower()
    for q in INTERROGATIVES:
        if low.startswith(q):
            t = t[len(q):]
            break
    return " ".join(_smart_lower(w) for w in t.split())


def build_narration(post, cfg):
    target = cfg["script"]["target_seconds"]
    wpm = cfg["script"]["words_per_minute"]
    budget = int(target * wpm / 60)  # total words

    topic = clean_topic(post["title"])
    hook_tpl = cfg["script"]["hook_styles"][hash(post["slug"]) % len(cfg["script"]["hook_styles"])]
    hook = hook_tpl.format(topic=topic)
    hook = hook[0].upper() + hook[1:] if hook else hook  # capitalise sentence start

    # body: take the most informative sentences until we hit the word budget
    sents = sentences(post["description"] + " " + post["body"])
    picked, used = [], len(hook.split())
    for s in sents:
        w = len(s.split())
        if used + w > budget - 12:  # leave room for CTA
            break
        picked.append(s)
        used += w
    if not picked:
        picked = [post["description"]]

    # Per-platform CTA verb: YouTube watches the HORIZONTAL cut ("subscribe"); every
    # other platform (TikTok/IG/FB/X/Threads) watches the VERTICAL cut ("follow"). The
    # body is identical — only the closing verb differs — so we emit both narrations and
    # generate_video renders each cut with its matching voiceover/captions.
    body = [hook] + picked
    def _with_cta(verb):
        return " ".join(body + [cfg["script"]["cta"].format(sub_or_follow=verb)])
    narration = _with_cta("follow")        # vertical -> TikTok / IG / FB / X / Threads
    narration_yt = _with_cta("subscribe")  # horizontal -> YouTube
    return hook, narration, narration_yt


def make_scenes(post, cfg):
    n = cfg["visuals"]["scenes"]
    suffix = cfg["visuals"]["style_suffix"]
    kws = keywords(post["title"] + " " + post["body"], n=max(3, n))
    base = post["title"]
    prompts = []
    for i in range(n):
        focus = kws[i % len(kws)] if kws else base
        prompts.append(f"{base}, theme: {focus}, {suffix}")
    return prompts


def platform_text(post, cfg):
    out = relevant_hashtags(post, cfg)
    # Use the FULL post URL (not a shortener). URL shorteners (TinyURL/is.gd) showed
    # an interstitial/preview page for script-created links, confusing visitors; the
    # real domain is trustworthy, clean, and resolves straight to the post.
    link = post["url"]
    log(f"{len(out)} matched hashtags; link {link}")
    caption = f"{post['title']}\n\n{post['description'][:200]}\n\nFull post: {link}\n\n" + " ".join(out)
    # Instagram strips links in captions (only the bio link is clickable), so a raw URL
    # is dead text — use a "link in bio" CTA there instead.
    ig_caption = (f"{post['title']}\n\n{post['description'][:200]}\n\n"
                  f"🔗 Full breakdown — link in bio\n\n" + " ".join(out))
    yt_title = post["title"][:95]
    yt_desc = f"{post['description']}\n\nRead more: {link}\n\n{' '.join(out)}"
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

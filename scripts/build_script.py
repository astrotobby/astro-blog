"""Stage 2: turn the post into a narration script + per-scene image prompts.

Extractive + template based (no paid LLM needed). If ANTHROPIC_API_KEY is set
it will optionally polish the hook, but it is NOT required.

Usage: python scripts/build_script.py .pipeline/post.json
"""
import argparse
import re

from common import load_config, log, read_json, write_json


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

    cta = cfg["script"]["cta"]
    narration = " ".join([hook] + picked + [cta])
    return hook, narration


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
    tags = post.get("tags", []) or []
    htags = cfg["hashtags"]["base"] + [f"#{re.sub(r'[^A-Za-z0-9]', '', t)}" for t in tags]
    seen, out = set(), []
    for h in htags:
        if h.lower() not in seen and len(h) > 1:
            seen.add(h.lower())
            out.append(h)
    out = out[: cfg["hashtags"]["max"]]
    caption = f"{post['title']}\n\n{post['description'][:200]}\n\nFull post: {post['url']}\n\n" + " ".join(out)
    yt_title = post["title"][:95]
    yt_desc = f"{post['description']}\n\nRead more: {post['url']}\n\n{' '.join(out)}"
    return {"caption": caption, "hashtags": out, "yt_title": yt_title, "yt_desc": yt_desc}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("post_json")
    args = ap.parse_args()
    cfg = load_config()
    post = read_json(args.post_json)

    hook, narration = build_narration(post, cfg)
    scenes = make_scenes(post, cfg)
    ptext = platform_text(post, cfg)

    out = {
        "post": post,
        "hook": hook,
        "narration": narration,
        "scene_prompts": scenes,
        "platform": ptext,
        "est_words": len(narration.split()),
    }
    log(f"narration ~{out['est_words']} words, {len(scenes)} scenes")
    write_json("script.json", out)


if __name__ == "__main__":
    main()

"""Offline regression tests for the blog-to-video pipeline improvements."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_script import make_scenes  # noqa: E402
from common import load_config  # noqa: E402
from crosspost import _prior_ok  # noqa: E402
from voice_clone import _reference_key  # noqa: E402


def sample_post():
    return {
        "title": "How workflow automation connects every social platform",
        "description": "A practical automation workflow connects publishing tools and social platforms.",
        "body": (
            "The pipeline sends one rendered video to YouTube, TikTok, Instagram, Facebook, and Rumble. "
            "A central workflow coordinates API credentials, retries, and publishing status. "
            "The dashboard shows processing data and the final public result. "
            "Creators can use a software interface to monitor each destination."
        ),
        "slug": "workflow-automation",
        "tags": ["automation", "video"],
    }


def main():
    cfg = load_config()
    scenes = make_scenes(sample_post(), cfg)
    assert len(scenes) == cfg["visuals"]["scenes"]
    assert len({scene.split("|broll:", 1)[1].split("|", 1)[0] for scene in scenes}) >= 5
    assert any("dramatic close-up" in scene for scene in scenes)
    assert any("wide establishing shot" in scene for scene in scenes)

    prior = {"hash": "abc", "results": {"youtube": {"ok": True},
                                             "rumble": {"ok": False, "error": "timeout"}}}
    assert _prior_ok(prior, "abc", "youtube", False, False)
    assert not _prior_ok(prior, "abc", "rumble", False, False)
    assert not _prior_ok(prior, "different", "youtube", False, False)

    cfg["voice"] = dict(cfg["voice"])
    cfg["voice"]["reference_url"] = "https://youtu.be/5jOagO2w4_0"
    assert _reference_key(cfg) == _reference_key(cfg)
    print("pipeline improvement tests: OK")


if __name__ == "__main__":
    main()

"""Generate missing AI-influencer look stills from assets/avatar.png with FLUX.1 Kontext.

Kontext edits the reference photo instead of inventing a new person, so every look keeps
the same face. For each look in assets/influencer/looks.yaml whose `image` file is
missing and that has a `prompt`, this renders the still and saves it to that path.

  HF_TOKEN=... python scripts/gen_influencer_looks.py [look_id ...]

Uses the free FLUX.1-Kontext-Dev Hugging Face Space (ZeroGPU). Anonymous use stops after
a few runs a day; a token raises the quota. Existing images are never overwritten.
"""
import os
import sys

import yaml
from PIL import Image

from common import OUT, ROOT, log

SPACE = "black-forest-labs/FLUX.1-Kontext-Dev"
KEEP = ("Keep the exact same man: identical face, facial features, skin tone and short "
        "hair. ")
STYLE = (" He is a muscular, athletic 26-year-old African man with a broad chest and strong "
         "arms, looking straight into the camera and talking. Photorealistic, natural skin "
         "texture with pores, shot on 50mm, shallow depth of field, vertical framing from the "
         "waist up, no text, no watermark.")
# assets/avatar.png is shot through a keyhole; crop to just the man (head to knees)
REF_CROP = (190, 330, 760, 1150)


def main():
    from gradio_client import Client, handle_file

    only = set(sys.argv[1:])
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    looks_file = ROOT / cfg.get("influencer", {}).get("looks_file", "assets/influencer/looks.yaml")
    looks = yaml.safe_load(looks_file.read_text(encoding="utf-8"))["looks"]
    todo = [lk for lk in looks if lk.get("prompt") and lk.get("image")
            and not (ROOT / lk["image"]).exists() and (not only or lk["id"] in only)]
    if not todo:
        log("influencer looks: nothing to generate")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    ref = OUT / "_influencer_ref.jpg"
    Image.open(ROOT / "assets" / "avatar.png").convert("RGB").crop(REF_CROP).save(ref, quality=90)
    client = Client(SPACE, hf_token=os.environ.get("HF_TOKEN") or None)
    failed = []
    for lk in todo:
        prompt = KEEP + " ".join(lk["prompt"].split()) + STYLE
        try:
            result, _seed = client.predict(handle_file(str(ref)), prompt, 0, True, 2.5, 28,
                                           api_name="/infer")
        except Exception as e:  # noqa  quota / busy Space: keep the looks we already have
            log(f"look {lk['id']}: generation failed ({str(e)[:200]})")
            failed.append(lk["id"])
            continue
        path = result["path"] if isinstance(result, dict) else result
        dst = ROOT / lk["image"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        Image.open(path).convert("RGB").save(dst)
        log(f"look {lk['id']} -> {lk['image']}")
    if failed:
        log(f"influencer looks not generated: {failed}")


if __name__ == "__main__":
    main()

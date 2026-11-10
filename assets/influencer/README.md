# AI influencer: adding looks

The presenter is **one person**: the man in `assets/avatar.png`. Every look is that
same man in a new outfit and location. To keep him identical across videos, **always
generate a new look from `assets/avatar.png` as the reference image**. Never use
text-only generation, because free text-to-image models invent a different face every time.

## 1. Make the still (identity-locked)

**Automatic (free):** add the look to `looks.yaml` with an `image:` path and a `prompt:`
written as a scene edit ("Change the scene to ..."), then run

    HF_TOKEN=... python scripts/gen_influencer_looks.py [look_id]

It edits `assets/avatar.png` with FLUX.1 Kontext on a free Hugging Face Space, so the
face stays his. Anonymous use stops after about 3 images a day; a Hugging Face token
raises that. The `influencer-test` workflow runs it on the `feat/ai-influencer` branch
with the repo's `HF_TOKEN` secret and commits any new stills.

**By hand:** use a reference/edit image model with `assets/avatar.png` attached
(Higgsfield needs a paid plan for this; Kling, Hailuo or Google AI Studio image edit
have free daily credits). Prompt:

> **Consistency lock:** Same exact man as the reference photo: identical face,
> facial structure, eyes, nose, lips, skin tone and buzz-cut hairline. 26 years old,
> clean-shaven (no beard, no stubble), deep brown skin with natural visible pores and
> texture, no airbrushing. Muscular gym physique, broad shoulders. Looking at the
> camera, relaxed confident expression, mouth slightly open as if mid-sentence.
> Vertical 9:16, head-to-waist framing, face in the upper third. Shot on a full-frame
> camera, 35mm, f/2, natural light, photorealistic editorial.
>
> **Scene:** *(paste the look's `prompt` from `looks.yaml`)*

Save it as `assets/influencer/<id>.png`. That alone activates the look: the pipeline
animates the still and lip-syncs it.

## 2. Make it move (recommended)

Animate the still with image-to-video (Kling, Hailuo, Higgsfield or Seedance), 5–10 s, 9:16:

> The man talks to the camera like a confident influencer explaining something
> exciting: natural expressive hand gestures, small head nods, eyebrow raises,
> occasional smile, blinking, slight body sway. The camera is static, at eye level.
> He stays in frame, mouth clearly visible, no cuts, no text.

Save it as `assets/influencer/<id>.mp4`. Wav2Lip replaces the mouth movement with
perfect sync to each video's narration, and the gestures loop seamlessly
(forward then reverse).

## 3. Check framing

If a punch-in crops his head, adjust that look's `face_cy` (face height as a fraction
of the frame, 0 = top) in `looks.yaml`. Commit the files, and the next video rotates
the new look in.

## Tips for realism
- Keep the mouth visible and unobstructed (no hands over the face, no mic in front).
- Head-to-waist framing gives the punch-in room to work.
- Avoid clips with tool watermarks, or set `avatar.watermark_logo` to mask them.
- 4+ looks with clips = no two consecutive videos look the same.

# Free MuseTalk 1.5 test workflow (Kaggle)

## Budget rule

The lip-sync production budget for this project is **USD 0**. This workflow uses the open-source MuseTalk 1.5 model in a Kaggle notebook with a free GPU session. It does not use Sync Labs, a hosted inference API, a paid GPU instance, or a paid Hugging Face endpoint. Do not add paid-service API keys or enable paid billing.

Kaggle free GPU access is quota-limited and not guaranteed to be available on demand. If the free GPU is unavailable or the weekly/session quota is exhausted, pause and retry later. Never fall back to a paid provider.

## First test

Notebook: [notebooks/musetalk_free_kaggle_test.ipynb](notebooks/musetalk_free_kaggle_test.ipynb)

1. Sign in to Kaggle and open the notebook from this repository. Download the .ipynb file and use Kaggle's Import Notebook option if needed.
2. In Notebook Settings, choose GPU as the accelerator and enable Internet.
3. Create a **private Kaggle Dataset** with exactly one existing Kling presenter video (.mp4, preferably a clean 4–8 second front-facing shot) and the exact matching narration excerpt (.wav preferred; .mp3 also accepted).
4. Add that private dataset as the notebook input. Do not place credentials, API keys, or private account information in the dataset.
5. Run notebook cells from top to bottom. It checks for a GPU before downloading model weights or starting inference.
6. Download the resulting MP4 from Kaggle's notebook output and inspect it before using it anywhere.

The notebook expects exactly one video and one audio file in /kaggle/input. This is intentionally strict to prevent accidentally syncing the wrong voice track to the wrong presenter shot.

## Quality acceptance checklist

Do not accept or publish the output until it passes all of these checks:

- Mouth movements follow the spoken words, including pauses and sentence endings.
- No visible mouth drift or delayed lip movement.
- Eyes remain stable; no eye sliding, flicker, or face warping.
- Presenter identity, skin tone, hairstyle, and facial proportions remain consistent with the source Kling clip.
- No duplicated frames, looping/boomerang behavior, or unexpected cuts.
- Audio is unchanged, clear, and aligned to the rendered video duration.
- The face remains natural during closed-mouth sounds and silence.

If it fails, retain the original source and report the failure. Do not publish a bad render and do not use an unsynchronized fallback for a presenter shot. The existing B-roll/voiceover structure can be retained while the lip-sync issue is investigated.

## Production integration is deliberately gated

This is a **manual proof-of-quality stage**, not yet a fully unattended daily GPU service. Kaggle free sessions have quotas and can disconnect. After the first preview is accepted, the next engineering step is to integrate a Kaggle-compatible batch handoff for short A-roll segments and keep the pipeline fail-closed when free GPU capacity is unavailable.

The test notebook uses the official MuseTalk repository and its documented MuseTalk 1.5 inference entry point. See the official MuseTalk repository: https://github.com/TMElyralab/MuseTalk

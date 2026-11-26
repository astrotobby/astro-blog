# Free MuseTalk 1.5 test workflow (Kaggle)

## Budget rule

The lip-sync budget for this project is **USD 0**. The workflow uses the open-source MuseTalk 1.5 model on Kaggle's free GPU quota. It does not use Sync Labs, any paid inference API, a paid GPU instance, a paid subscription, or a paid fallback.

Kaggle free GPU access is quota-limited and is not guaranteed to be available on demand. The workflow checks the account's reported quota and the notebook checks that a GPU is actually attached. If free capacity is unavailable, the run fails/stops; retry later. Never switch to a paid provider.

## Automated preview (manual trigger only)

Workflow: [MuseTalk free Kaggle preview](.github/workflows/musetalk-kaggle-preview.yml)

Before running it:

1. In GitHub repository **Settings → Secrets and variables → Actions**, add the Kaggle personal API token as the secret named **`KAGGLE_API_TOKEN`**. Never commit the token or paste it into a workflow input.
2. Complete Kaggle **phone verification** in Account Settings before requesting a GPU. The API token can authenticate and create datasets without this step, but Kaggle may refuse to attach an NVIDIA device.
3. The workflow is manual-only and can be launched from **Actions → MuseTalk free Kaggle preview → Run workflow**. Code edits do not start GPU sessions; launch a preview deliberately after the code is ready. For a manual run, choose an existing Kling presenter video in the repository and provide a brief narration sentence. The workflow discovers your Kaggle username from the authenticated API token, so there is no need to enter it. A free Edge TTS voice creates the sample narration; no paid voice API is used.
4. The workflow trims the chosen video to the speech duration, creates a private Kaggle Dataset containing just the video and narration, and submits this notebook as a private Kaggle GPU kernel with Internet enabled.
5. After the notebook finishes, the GitHub Actions run summary contains a link to the private Kaggle notebook. Sign in to Kaggle to watch or download its MP4 output.

The repository is public, so the workflow deliberately does **not** upload the rendered preview as a public GitHub Actions artifact or commit media to GitHub. The source Kling videos already present in this repository are public; the workflow's newly generated narration and the Kaggle input dataset/output notebook are private to the Kaggle account.

Each run creates a private, run-specific Kaggle Dataset and notebook so inputs from separate tests cannot be mixed. They remain in your Kaggle account for review and can be deleted there when no longer needed.

The workflow does not start on code pushes. This avoids duplicate GPU sessions and Kaggle API rate-limit contention. It runs only when deliberately dispatched. It has no schedule, does not alter the channel publishing workflows, and does not publish or upload anything to YouTube. A completed technical run is only a preview; human review of mouth timing, eye stability, identity consistency, frame continuity, and audio alignment is still required.

## Manual notebook use

Notebook: [notebooks/musetalk_free_kaggle_test.ipynb](notebooks/musetalk_free_kaggle_test.ipynb)

If using Kaggle's notebook UI directly, create a **private Kaggle Dataset** containing exactly one existing presenter MP4 and its matching narration WAV or MP3. Attach it as notebook input, set Accelerator to GPU, enable Internet, and run cells in order. Use a 4–8 second test clip first. Do not upload secrets in the dataset.

The notebook requires exactly one video and one audio file under `/kaggle/input`. This strict check prevents accidental pairing of the wrong speaker footage and narration. The first run downloads model checkpoints and dependencies, so it consumes Kaggle's free session/quota.

## Quality acceptance checklist

Do not accept or publish output until all of the following pass:

- Mouth movements follow the spoken words, including pauses and sentence endings.
- No visible mouth drift or delayed lip movement.
- Eyes remain stable; no eye sliding, flicker, or face warping.
- Presenter identity, skin tone, hairstyle, and facial proportions remain consistent with the source Kling clip.
- No duplicated frames, looping/boomerang behavior, or unexpected cuts.
- Audio remains clear and aligned to the rendered video duration.
- The face remains natural during closed-mouth sounds and silence.

If it fails, retain the original source and report the failure. Do not publish a bad render or use an unsynchronized presenter fallback. The existing B-roll/voiceover structure can remain in place while lip-sync is investigated.

## Production integration remains gated

This automated job is a repeatable **preview pipeline**, not yet an unattended daily production service. Kaggle can deny a GPU or disconnect when free quota/capacity is unavailable. The current task therefore stops safely rather than queueing paid compute. After the first accepted preview, integration into short A-roll segments in the two-channel production workflow must be separately tested and reviewed.

The notebook creates a seeded Python 3.10 virtual environment (including `pip`), installs the pinned PyTorch CUDA 11.8 build, MuseTalk requirements, and documented OpenMMLab components. The upstream `musetalk/whisper` source folder has no Python package metadata, so the workflow does not attempt an editable pip install; inference uses `transformers.WhisperModel`. It adds `musetalk/utils` to `PYTHONPATH` for MuseTalk's bundled `face_detection` module, and validates CUDA and imports before downloading weights or starting inference.

The notebook uses the official MuseTalk repository and MuseTalk 1.5 inference entry point: https://github.com/TMElyralab/MuseTalk

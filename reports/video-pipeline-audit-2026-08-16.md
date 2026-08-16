# Blog-to-video pipeline audit

**Repository:** `astrotobby/astro-blog`  
**Latest pushed commit:** `28234db`  
**Reference video:** [I Connected This Tool to Every Social Platform. The Result is Powercode.](https://youtu.be/5jOagO2w4_0)

## Editorial findings

The reference video is a 3-minute-26-second technical walkthrough with deliberate 15–30-second conceptual and practical beats. It alternates developer/live-action footage, animated system diagrams, and crisp UI walkthroughs. Its repetition is intentional: the connection-hub idea returns to reinforce the story, then is grounded in the actual interface. The generated dry-run output had no exact duplicate frames, but it did repeat the same visual grammar—generic coding screens appeared at multiple narration beats, and a generic office/server sequence weakened the connection to the video-tool and pricing claims. The horizontal cut averaged roughly eight seconds per shot, while the vertical cut moved faster at roughly three-to-five seconds per shot.

The generated audio mix was already strong: the voice was crisp and prominent, the music sat below it, and synchronization was tight. The main short-form issue was caption placement: captions were anchored too close to the bottom edge, where TikTok, Instagram, Facebook, and similar interfaces place account and control overlays. Bright footage also reduced caption contrast in places.

## Changes applied

| Area | Change | Result |
|---|---|---|
| Footage repetition | Added 30-day persistent clip history in `.pipeline/state/footage_history.json`, bounded to recent IDs, with per-scene exact-ID avoidance and contributor diversity. | The same stock clip and contributor are less likely to recur across scenes or consecutive posts. |
| Shot variety | Reduced the default 75-second edit from 15 to 10 scenes and added shot-specific search modifiers for hooks, establishing shots, explanations, data, tension, payoff, and CTA beats. | Fewer disposable cuts and more purposeful visual grammar. |
| Relevance | Added high-priority search briefs for AI video interfaces and video-production pricing. | Claims about Veo, Kling, Runway, rendering, and cost are less likely to fall back to generic code or office footage. |
| Captions | Added a vertical safe-zone margin of 220 px, a horizontal margin setting, and a black border around white text. | Captions clear common short-form UI chrome and remain legible over bright footage. |
| Voice path | Production config now records the reference URL and supports reference-specific OpenVoice embeddings, YouTube audio download, and automatic fallback to Edge TTS. | The requested voice can be tested and enabled consistently once authorization is confirmed. Production cloning is intentionally still disabled. |
| Rumble | Added fallback selectors, visible-login checks, rights/terms verification, confirmation polling, diagnostic screenshots, and guaranteed browser cleanup. | A final button click is no longer recorded as success without a Rumble confirmation or redirect. |
| Retries | Cross-posting now preserves successful destination results and retries destinations that previously returned an error. | A failed Rumble attempt no longer freezes the entire post as permanently complete. |
| Workflow safety | Added optional voice provisioning and made targeted file/sweep dry runs honor `mode=dry`. | CI can test a selected post without accidental publication. |

## Validation

Local Python compilation, YAML parsing, the new offline regression tests, and the existing FFmpeg renderer smoke test all passed. A GitHub Actions dry run completed successfully. A targeted dry render of the latest AI-video-generator post produced both a horizontal MP4 and a vertical MP4, and the dry cross-post stage completed without publishing. The generated masters were then reviewed editorially for pacing, scene repetition, crop safety, caption placement, relevance, transitions, and audio balance.

The Rumble path was not live-tested against the account because that would create a real external post. The implementation is designed to fail closed with a screenshot and an actionable error when Rumble presents a CAPTCHA, changed selector, rejected login, missing required field, or no post-submit confirmation. Rumble’s own support documentation also distinguishes upload visibility from later processing/encoding, so the pipeline now reports “submitted for processing” rather than claiming that the video is already publicly discoverable.[1] [2]

## Remaining authorization gate

The reference video URL is configured, but `voice.clone` remains `false`. Before enabling the clone path, the channel owner must confirm that they own the voice or have explicit permission to reproduce it. Once confirmed, the isolated `test-voice-clone.yml` workflow can generate a sample artifact for listening before production cloning is enabled.

## References

[1]: [Rumble Support — Set Video Visibility: Public/unlisted mode](https://rumble.support/help/set-video-visibility-public-unlisted-mode)

[2]: [Rumble Support — How To Upload Videos to Rumble](https://rumble.support/help/upload-process)

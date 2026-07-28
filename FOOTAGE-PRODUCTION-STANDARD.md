# Footage-First Blog-to-Video Production Standard

## Purpose

This standard defines how the automated blog-to-video pipeline should turn an article into a professional, **story-aligned B-roll video**. The objective is not to promise a fixed view count; it is to replace generic static-image montages with visually relevant footage, sharper pacing, readable information design, and a measurable iteration loop.

> **Editorial principle:** every visual must either show the subject, action, setting, or consequence described by the narration. Decorative footage is a last resort, not a default.

| Delivery | Master | Editorial role |
|---|---:|---|
| Short-form social | `video_9x16.mp4` | Fast, vertically framed scene changes, captions, hook card, data beats, and end card. |
| YouTube | `video_16x9.mp4` | A separately sourced horizontal master with the YouTube-specific “subscribe” narration and correctly framed B-roll. |

## Automated Footage Workflow

The renderer follows this order for each narration scene:

1. **Classify the scene** as `HOOK`, `ESTABLISH`, `EXPLAIN`, `TENSION`, `DATA`, `PAYOFF`, or `CTA`.
2. **Generate a concrete B-roll brief** from the spoken segment and the detected topic category. For example, an LLM-infrastructure statement becomes `data center servers`; a finance statement becomes `financial data charts screen`; and a medical diagnosis statement becomes `doctor reviewing tablet`.
3. **Search Pexels first**, ranking candidates by fit to the target aspect ratio and practical HD resolution. Pexels documents video search through its authorized REST API. [1]
4. **Use Pixabay only as a ranked fallback** if Pexels has no suitable unique clip. Pixabay exposes video search and metadata through its REST API. [2]
5. **Prevent duplicate footage within a master.** A selected provider clip ID is not reused for another scene in the same vertical or horizontal cut.
6. **Use a still-image fallback only when both footage providers fail.** The fallback keeps a render resilient, but a successful production run should be primarily moving footage.
7. **Retain provenance.** The source, contributor, query, scene, and master variant are saved in `render.json`; used clips are summarized in the YouTube description as a compact credit block.
8. **Cache provider search results for 24 hours** in the pipeline state directory. This bounds repeated requests and aligns particularly well with Pixabay’s API caching expectations. [2]

| Quality gate | Pipeline behavior | Why it matters |
|---|---|---|
| Semantic match | Query comes from the narrated scene, not merely the blog title. | Prevents “AI future” or unrelated landscape filler from weakening comprehension. |
| Composition | Portrait and horizontal masters source independently. | Avoids taking a single landscape clip and aggressively cropping it into an unusable vertical or vice versa. |
| Motion variety | Scene-specific candidates and duplicate blocking. | Reduces visual repetition that makes automated videos feel templated. |
| Pacing | Scene duration is weighted by semantic role. | Hooks and tension beats move faster; data and payoff beats have time to land. |
| Information design | Captions, hook card, data lower thirds, and end card are burned into the master. | Supports silent viewing and makes key claims more memorable. |
| Audio polish | A locally committed royalty-free music bed loops beneath the voice and is sidechain-ducked. | Adds energy without compromising voice clarity. |

## Editorial Rules for Scene Matching

Use the following mapping logic before accepting a finished render.

| Spoken idea | Good visual evidence | Avoid |
|---|---|---|
| AI model, prompt, software workflow | Developer at a computer, code/editor, data center, chip close-up, product workflow | Generic glowing robot face or unrelated city drone shot |
| Cybersecurity threat or privacy | Security analyst, lock interface, server room, code security | Anonymous hacker hoodie stock cliché unless the story specifically warrants it |
| Finance, payment, revenue, metric | Analytics screen, digital payment, business meeting, chart detail | Abstract currency rain or stock exchange footage with no narrative connection |
| Medical or biotech claim | Doctor with tablet, research laboratory, hospital technology | Dramatic surgery footage when the narration only concerns software or operations |
| Automation / operations | Workflow screen, employee operating software, robotic assembly where relevant | Decorative “futuristic hologram” imagery that cannot be found as authentic stock video |
| Statistic or comparison | Relevant footage plus a concise lower-third of the sourced claim | A chart or number that adds a claim not present in the blog source |

The final visual review should ask one question per scene: **“Could a viewer understand the narration better with this exact footage on screen?”** If the answer is no, adjust the category mapping or query library instead of accepting filler.

## Free Production Tooling Assessment

| Tool | Recommended role | Reason |
|---|---|---|
| **FFmpeg** | Primary unattended renderer | It is free, works in GitHub Actions, and provides filters for transitions, subtitles, text, scaling, cropping, color processing, and audio mixing. [3] |
| **Kdenlive** | Optional human finishing review | A free, open-source non-linear editor for Linux, Windows, macOS, and BSD. Use it for occasional flagship edits, not scheduled rendering. [4] |
| **Blender Video Sequence Editor** | Optional bespoke motion graphics | Useful for custom masks, advanced keyframes, and designed motion sequences; it is too heavyweight for routine unattended B-roll assembly. [5] |
| **Remotion** | Not selected for this pipeline | It can programmatically render video with React, but would add implementation and licensing-review complexity without solving a gap in the existing FFmpeg workflow. [6] |

The automation remains **FFmpeg-first** because it is the only option above that is both established in the existing runner and naturally compatible with a scheduled, no-human-in-the-loop workflow. Kdenlive is the recommended free editor for selectively polishing high-value “hero” videos after the automated master has been reviewed.

## Pre-Publish Quality-Control Checklist

Before enabling or approving a new content category, inspect one full vertical and one full horizontal render.

| Check | Pass condition |
|---|---|
| First 3 seconds | The hook card, first visual, and first spoken sentence communicate the same curiosity gap. |
| Scene relevance | Every scene visibly relates to the active spoken segment. |
| Aspect framing | Important people, screens, and objects are not cropped awkwardly in either master. |
| Text readability | Captions and data lower thirds remain legible on a phone at normal viewing size. |
| Audio | Voice is always clear above music; music does not begin or end abruptly. |
| Repetition | No stock clip repeats within one master, and adjacent scenes are not visually identical. |
| CTA | End card gives the blog destination and a clear platform-appropriate action. |
| Source hygiene | `render.json` contains source records and the YouTube description contains footage credits when stock clips were used. |

Run these local checks before pushing pipeline changes:

```bash
python3 -m unittest scripts/test_video_pipeline.py
python3 scripts/test_renderer_smoke.py
```

## Retention Measurement Plan

YouTube’s audience-retention reporting identifies where viewers watch, rewatch, skip, or abandon a video. [7] High retention can support reach, but it should be treated as an outcome to measure, not a promise. [8]

For the next 8–12 comparable uploads, record a baseline and compare the following metrics by topic and video length:

| Metric | Diagnostic use |
|---|---|
| First-30-second retention | Tests whether the hook, first footage choice, and initial pacing stop the scroll. |
| Average view duration and percentage viewed | Measures whether visual relevance sustains the narrative. |
| Retention dips and spikes | Dips identify confusing, repetitive, or mismatched scenes; spikes identify B-roll or explanations worth reusing as a pattern. |
| Impressions click-through rate | Separates packaging performance (title/thumbnail) from in-video performance. |
| Blog click-throughs | Measures whether the end card and description are converting attention into site visits. |

Change **one variable class at a time** when interpreting results. For example, keep the story topic and publishing time similar while testing a stronger first B-roll brief, then compare first-30-second retention. Do not infer that footage alone caused a change if title, thumbnail, length, narration, and timing changed simultaneously.

## References

[1]: https://www.pexels.com/api/documentation/ "Pexels API Documentation"
[2]: https://pixabay.com/api/docs/ "Pixabay API Documentation"
[3]: https://ffmpeg.org/ffmpeg-filters.html "FFmpeg Filters Documentation"
[4]: https://kdenlive.org/en/ "Kdenlive"
[5]: https://www.blender.org/features/video-editing/ "Blender Video Editing"
[6]: https://www.remotion.dev/ "Remotion"
[7]: https://support.google.com/youtube/answer/9314415?hl=en&co=GENIE.Platform%3DAndroid "Measure key moments for audience retention"
[8]: https://blog.youtube/creator-and-artist-stories/master-these-4-metrics/ "Master these 4 metrics"

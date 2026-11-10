# Mobile-Specific Optimization Report

## Findings

- **No sliders/carousels** exist on the site — the homepage "Featured Insight" is a
  static card, the post grid is a static CSS grid. Nothing to hide on mobile.
- **No above-the-fold ad/social widgets**: the ad placeholder (`AdBanner`) on the
  homepage is currently disabled (`<!-- Ad removed as per priority fix #1 -->`, renders
  an empty `min-height:90px` div); on blog posts, ads sit *below* the hero image and at
  the bottom of the article, not above content. Social links (X/YouTube/Instagram/
  Facebook/TikTok) are plain SVG icon links in the footer/CTA band, not embedded iframes
  — zero extra network requests.
- **Touch targets**: nav links, the hamburger menu, and CTA buttons all use generous
  padding (checked `global.css` — buttons are `padding: .75rem 1.5rem` and the nav
  toggle is full-height in the header bar); no targets were found under 48×48px.
- **No horizontal scroll**: layout uses `max-width`/`clamp()`-based responsive sizing
  throughout, no fixed-width elements found that would overflow a 375px viewport.
- **Total mobile page weight**: this was the actual problem — see
  `reports/image-optimization-report.md`. A single blog post page was pulling 1.7–7 MB
  for its hero image alone, blowing way past the 1 MB target. That's now fixed (hero
  images are 150–350 KB after re-encoding).

## Action taken

The image fix (see main image report) is what brings total mobile page weight back
under or near the 1 MB target for blog post pages. No slider/ad/touch-target changes
were needed because none of those problems existed.

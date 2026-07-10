// Place any global data in this file.
// You can import this data from anywhere in your site by using the `import` keyword.

export const SITE_TITLE = "ASTRO SIGNAL";
export const SITE_DESCRIPTION = 'AI tools, agentic workflows, vibe coding and answer engine optimization — by Astro Tobby';

// ─── Social / channel config ────────────────────────────────────────────────
// The YouTube handle whose LATEST video is auto-embedded in the sidebar.
// (This is the channel already linked across the site's Follow buttons.)
// To use a different channel, change the handle here — or, if the build
// can't resolve the handle, hard-set YOUTUBE_CHANNEL_ID to its UC… id.
export const YOUTUBE_HANDLE = '@aienthusiast001';
export const YOUTUBE_CHANNEL_ID = '';        // optional UC… override; leave '' to auto-resolve
export const YOUTUBE_FALLBACK_VIDEO_ID = ''; // optional video id shown if the feed can't be fetched at build time
export const YOUTUBE_URL = `https://www.youtube.com/${YOUTUBE_HANDLE}`;
export const INSTAGRAM_URL = 'https://www.instagram.com/astr_osignal';

// ─── Affiliate offers feature flags ──────────────────────────────────────────
// Flip any back to `true` to re-enable. Kept private/off until then.
export const ENABLE_CPALEAD = false;      // false → CPAlead offers never shown anywhere
export const ENABLE_CPAGRIP = false;      // false → CPAGrip offers never shown anywhere
export const ENABLE_OFFERS_PAGE = false;  // false → the /offers page is private (returns 404)

// ─── Monetag ────────────────────────────────────────────────────────────────
// Each zone loads globally on every page (auto-display formats — Monetag decides
// when to show them). To disable one, delete or comment out its line.
export const MONETAG_ZONES = [
  // { zone: '11242675', src: 'https://n6wxm.com/vignette.min.js' }, // Vignette (full-screen)
  // { zone: '11242710', src: 'https://nap5k.com/tag.min.js' },      // In-Page Push
];
// Force build: 2026-05-22 04:25:00 UTC
// Triggering new deployment
// Build trigger: Sun Jun  7 08:49:54 UTC 2026

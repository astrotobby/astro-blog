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
export const YOUTUBE_CHANNEL_ID = 'UCE_cklDludc6nkU1_4K6JzA';        // optional UC… override; leave '' to auto-resolve
export const YOUTUBE_FALLBACK_VIDEO_ID = '-Jxg6Y9K74o'; // optional video id shown if the feed can't be fetched at build time
export const YOUTUBE_URL = `https://www.youtube.com/${YOUTUBE_HANDLE}`;
export const INSTAGRAM_URL = 'https://www.instagram.com/astr_osignal';

// ─── Affiliate offers feature flags ──────────────────────────────────────────
// Flip any back to `true` to re-enable. Kept private/off until then.
export const ENABLE_CPALEAD = true;       // CPAlead offers enabled
export const ENABLE_CPAGRIP = true;       // CPAGrip offers enabled
export const ENABLE_OFFERS_PAGE = true;   // /affiliate-offers page is live

// ─── Adsterra Global Ad Units ────────────────────────────────────────────────
// These auto-display formats load globally on every page (Adsterra decides when
// to show them). Replaces previous Monetag vignette + in-page push zones.
// - Popunder (ID: 29380103): replaces Monetag vignette/interstitial (zone 11242675)
// - Social Bar (ID: 29285384): replaces Monetag in-page push (zone 11242710)
export const ADSTERRA_GLOBAL_UNITS = [
  { src: 'https://pl29480602.effectivecpmnetwork.com/2f/00/d4/2f00d442ca749f4254cbcdcdfa851714.js' }, // Popunder
  { src: 'https://pl29385883.effectivecpmnetwork.com/11/db/e0/11dbe0be7216618b728113b9bf654a59.js' }, // Social Bar
];

// Build trigger: ${new Date().toUTCString()}

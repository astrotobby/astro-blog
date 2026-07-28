// Build-time SEO rule: decide which blog posts should be `noindex`ed.
//
// Why: the Make.com autoblogger continuously publishes thin, fast-decaying
// "news" posts (slugs ending in a 13-digit timestamp). For a small site, dozens
// of thin off-niche pages DILUTE topical authority and waste crawl budget,
// hurting the evergreen money pages we actually want ranked + cited.
//
// What this does: posts whose slug ends in a 13-digit timestamp (the autoblog
// news signature) are noindexed by default — they stay live and linkable, but
// tell search/AI engines "don't index this," concentrating authority on the
// evergreen AEO/automation/agents/coding pillars. Reversible: delete this file's
// wiring or move a slug into FORCE_INDEX.
//
// Tuning (no code logic changes needed):
//   - Rescue a specific timestamped post  -> add its slug to FORCE_INDEX
//   - Noindex a specific evergreen post    -> add its slug to FORCE_NOINDEX

/** Timestamped autoblog "news" signature, e.g. `...-1782712806009`. */
const AUTONEWS_SLUG = /-\d{13}$/;

/** Slugs to ALWAYS index, even if they match the autonews pattern. */
export const FORCE_INDEX: string[] = [
  // e.g. '2026-06-27-google-shares-seo-insights-for-optimizing-content-for-ai-agents-...'
];

/** Slugs to ALWAYS noindex, even if evergreen. */
export const FORCE_NOINDEX: string[] = [];

export function shouldNoindex(slug: string): boolean {
  if (!slug) return false;
  // High-conversion / Transactional pages (we want these indexed, but maybe no ads)
  const isHighConversion = ['products', 'affiliate-offers', 'checkout', 'thank-you'].some(s => slug.includes(s));
  
  if (FORCE_INDEX.includes(slug)) return false;
  if (FORCE_NOINDEX.includes(slug)) return true;
  
  // For the sake of the MonetagAds gating, we return true for high-conversion pages
  // so they don't get intrusive popunders/social-bars.
  if (isHighConversion) return true;

  return AUTONEWS_SLUG.test(slug);
}

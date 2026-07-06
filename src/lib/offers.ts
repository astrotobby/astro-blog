// Unified offer wall — blends CPAlead + CPAGrip into one geo/device-matched list.
// Both networks are fetched in parallel and either can fail without breaking the wall.

import { pickOffersFor, withSubid, type CpaOffer } from './cpalead';
import { fetchCpagripOffers } from './cpagrip';
import { ENABLE_CPALEAD, ENABLE_CPAGRIP } from '../consts';

export interface BlendOptions {
  /** Visitor country (Cloudflare cf-ipcountry) — drives CPAlead's API filter. */
  country?: string | null;
  /** Visitor IP (CF-Connecting-IP) — forwarded to CPAGrip for geo matching. */
  ip?: string | null;
  /** Visitor User-Agent — device detection (CPAlead) + forwarded to CPAGrip. */
  userAgent?: string | null;
  /** Detected device bucket: 'ios' | 'android' | 'desktop'. */
  device?: string | null;
  /** Max offers returned after blending. */
  limit?: number;
  /** Tracking subid — appended to CPAlead links; sent as CPAGrip tracking_id. */
  subid?: string;
  /** CPAGrip public key (Cloudflare secret). Omit → CPAlead-only. */
  cpagripPubkey?: string | null;
  /** Guarantee up to this many CPAGrip offers in the visible set (if available), even
   *  when value-ranking would bury them. Keeps both networks visible. Default 3. */
  reserveCpagrip?: number;
}

export interface BlendResult {
  offers: CpaOffer[];
  matchedCountry: string | null;
  networks: Array<'cpalead' | 'cpagrip'>;
}

export async function getBlendedOffers(opts: BlendOptions): Promise<BlendResult> {
  const {
    country, ip, userAgent, device,
    limit = 24, subid = 'astroblog', cpagripPubkey,
    reserveCpagrip = 3,
  } = opts;

  // Each network sits behind a feature flag — when disabled it is never fetched or shown.
  // (OfferStrip removes itself client-side when the API returns no offers, so turning
  // both off makes every offer strip disappear site-wide.)
  const wantCpagrip = ENABLE_CPAGRIP && !!cpagripPubkey;

  const [cpaRes, cgRes] = await Promise.allSettled([
    ENABLE_CPALEAD
      ? pickOffersFor({ country, device, limit })
      : Promise.resolve({ offers: [], matchedCountry: null } as Awaited<ReturnType<typeof pickOffersFor>>),
    wantCpagrip
      ? fetchCpagripOffers({ pubkey: cpagripPubkey, ip, userAgent, subid, limit })
      : Promise.resolve([] as CpaOffer[]),
  ]);

  const matchedCountry = cpaRes.status === 'fulfilled' ? cpaRes.value.matchedCountry : null;

  const cpalead: CpaOffer[] =
    cpaRes.status === 'fulfilled'
      ? cpaRes.value.offers.map((o) => ({
          ...o,
          network: 'cpalead' as const,
          link: withSubid(o.link, subid), // CPAlead needs subid appended
        }))
      : [];

  const cpagrip: CpaOffer[] = cgRes.status === 'fulfilled' ? cgRes.value : [];

  // Merge, de-dupe by title, rank by value (payout, then EPC).
  const byValue = (a: CpaOffer, b: CpaOffer) => b.amount - a.amount || (b.epc ?? 0) - (a.epc ?? 0);

  // De-dupe by title, keep highest-value instance.
  const seen = new Set<string>();
  const merged = [...cpalead, ...cpagrip].sort(byValue).filter((o) => {
    const key = o.title.trim().toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  // Value-ranked top N.
  let visible = merged.slice(0, limit);

  // Guarantee CPAGrip visibility: if fewer than `reserveCpagrip` CPAGrip offers made the
  // natural top, swap out the lowest-value CPAlead offers to make room for the best CPAGrip ones.
  const want = Math.min(reserveCpagrip, cpagrip.length);
  const have = visible.filter((o) => o.network === 'cpagrip').length;
  if (want > have) {
    const inVisible = new Set(visible);
    const extraCg = merged
      .filter((o) => o.network === 'cpagrip' && !inVisible.has(o))
      .slice(0, want - have);
    let need = extraCg.length;
    for (let i = visible.length - 1; i >= 0 && need > 0; i--) {
      if (visible[i].network === 'cpalead') { visible.splice(i, 1); need--; }
    }
    visible = [...visible, ...extraCg].sort(byValue);
  }

  const networks = [...new Set(visible.map((o) => o.network ?? 'cpalead'))] as Array<'cpalead' | 'cpagrip'>;
  return { offers: visible, matchedCountry, networks };
}

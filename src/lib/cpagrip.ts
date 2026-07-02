// CPAGrip offers — SSR data layer. Normalizes CPAGrip's feed into the same
// CpaOffer shape as CPAlead so both networks render on one wall.
//
// CPAGrip geo/device-matches from the REQUEST's IP + User-Agent, so we forward
// the visitor's real IP (CF-Connecting-IP) and UA — otherwise it would match to
// Cloudflare's edge location instead of the visitor.
//
// The pubkey is a credential → read it from a Cloudflare secret (CPAGRIP_PUBKEY),
// never hard-code it. user_id is public (it appears in every offer link).

import type { CpaOffer } from './cpalead';

const CPAGRIP_USER_ID = '1040633';
const FEED = 'https://www.cpagrip.com/common/offer_feed_json.php';

export interface CpagripFetchOptions {
  /** CPAGrip public key (from Cloudflare secret CPAGRIP_PUBKEY). */
  pubkey?: string | null;
  /** Visitor's real IP — forwarded so CPAGrip geo-matches the visitor. */
  ip?: string | null;
  /** Visitor's User-Agent — forwarded so CPAGrip device-matches the visitor. */
  userAgent?: string | null;
  /** Tracking id (subid) — baked into every offerlink; drives the CPAGrip postback. */
  subid?: string;
  minPayout?: number;
  limit?: number;
}

function normalizeCpagrip(o: any): CpaOffer {
  const countries = String(o.accepted_countries || '')
    .split(/[,\s]+/)
    .map((c) => c.trim().toUpperCase())
    .filter(Boolean);
  const epc = Number(o.netepc);
  return {
    network: 'cpagrip',
    id: `cg_${o.offer_id}`,
    title: o.title || 'Offer',
    description: o.description || '',
    device: 'all_devices', // CPAGrip already pre-filters to the device UA we pass
    amount: Number(o.payout) || 0,
    payout_currency: 'USD',
    payout_type: (o.type || 'CPA').toString().toUpperCase(),
    countries,
    epc: Number.isFinite(epc) && epc > 0 ? epc : undefined,
    is_fast_pay: false,
    link: o.offerlink, // already carries our tracking_id (subid)
    image: o.offerphoto,
    category: o.category,
  };
}

/** Fetch CPAGrip offers matched to the visitor. Returns [] (never throws) if unavailable. */
export async function fetchCpagripOffers(opts: CpagripFetchOptions): Promise<CpaOffer[]> {
  const { pubkey, ip, userAgent, subid = 'astroblog', minPayout = 0, limit = 24 } = opts;
  if (!pubkey) return []; // CPAGrip not configured → wall falls back to CPAlead only

  const params = new URLSearchParams({
    user_id: CPAGRIP_USER_ID,
    pubkey,
    tracking_id: subid,
  });
  if (ip) params.set('ip', ip);
  if (userAgent) params.set('useragent', userAgent);

  try {
    const res = await fetch(`${FEED}?${params.toString()}`, {
      signal: AbortSignal.timeout(9000),
    } as RequestInit);
    if (!res.ok) return [];
    const data = await res.json();
    const offers = Array.isArray(data?.offers) ? data.offers : [];
    return offers
      .map(normalizeCpagrip)
      .filter((o: CpaOffer) => o.link && o.amount >= minPayout)
      .slice(0, limit);
  } catch {
    return [];
  }
}

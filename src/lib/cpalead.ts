// CPAlead offers — SSR data layer (mirrors lib/shopify.ts).
// Fetched at the edge (Cloudflare Worker) so no CORS, no exposed secrets.
// Publisher ID is public (it appears in every offer link anyway).

export interface CpaOffer {
  id: number;
  title: string;
  description?: string;
  conversion?: string;
  device: string;
  amount: number;
  payout_currency: string;
  payout_type: string;
  countries: string[];
  epc?: number;
  is_fast_pay?: boolean;
  daily_cap?: number;
  link: string;
  image?: string;
}

const PUBLISHER_ID = '2716424';
const API = 'https://www.cpalead.com/api/offers';

export interface FetchOffersOptions {
  /** Max offers to return after filtering/sorting (default 24). */
  limit?: number;
  /** Keep only offers paying at least this (USD). Default 1. */
  minPayout?: number;
  /** Keep offers whose countries intersect this list. Empty/undefined = all geos. */
  geos?: string[];
  /** Single ISO country — filtered server-side by the API (best for per-visitor geo matching). */
  country?: string;
  /** Visitor device ('ios' | 'android' | 'desktop') — hides offers that target other devices. */
  device?: string;
  /** Restrict to a payout type: CPA / CPI / CPC. */
  type?: string;
  /** Ranking: 'epc' (earnings per click — best for revenue) or 'payout'. Default 'epc'. */
  sort?: 'epc' | 'payout';
  /** How many rows to pull from the API before filtering (default 400). */
  sampleSize?: number;
}

/** ISO-3166 alpha-2 → English country name (e.g. "KE" → "Kenya"). */
export function countryName(code?: string): string {
  if (!code) return '';
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' }).of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

/** ISO-3166 alpha-2 → flag emoji (e.g. "KE" → 🇰🇪). */
export function countryFlag(code?: string): string {
  if (!code || !/^[A-Za-z]{2}$/.test(code)) return '';
  const base = 0x1f1e6;
  const cc = code.toUpperCase();
  return String.fromCodePoint(base + cc.charCodeAt(0) - 65, base + cc.charCodeAt(1) - 65);
}

/** Classify the visitor's device from the User-Agent string. */
export function detectDevice(ua?: string | null): 'ios' | 'android' | 'desktop' {
  const s = (ua || '').toLowerCase();
  if (/iphone|ipad|ipod/.test(s)) return 'ios';
  if (/android/.test(s)) return 'android';
  return 'desktop';
}

/** True if an offer's device targeting is compatible with the visitor's device. */
export function deviceMatches(offerDevice: string, visitor: string): boolean {
  const d = (offerDevice || '').toLowerCase();
  if (!d || d.includes('all')) return true; // all_devices
  if (visitor === 'ios') return d.includes('ios') || d.includes('iphone') || d.includes('ipad');
  if (visitor === 'android') return d.includes('android');
  return d.includes('desktop') || d.includes('web') || d.includes('windows') || d.includes('mac');
}

/**
 * Shared geo+device offer selection used by both the /offers page and the /api/offers.json endpoint.
 * Tiered: quality country offers → any country offers → best global offers → bundled fallback. Never empty.
 */
export async function pickOffersFor(opts: {
  country?: string | null;
  device?: string | null;
  limit?: number;
  fallbackGeos?: string[];
}): Promise<{ offers: CpaOffer[]; matchedCountry: string | null }> {
  const { country, device, limit = 24, fallbackGeos = ['US', 'CA', 'GB', 'AU', 'DE'] } = opts;
  let offers: CpaOffer[] = [];
  let matchedCountry: string | null = null;

  try {
    if (country) {
      offers = await fetchOffers({ limit, minPayout: 1, country, device: device ?? undefined, sort: 'epc' });
      if (offers.length < 3) {
        offers = await fetchOffers({ limit, minPayout: 0, country, device: device ?? undefined, sort: 'payout' });
      }
      if (offers.length) matchedCountry = country;
    }
    if (!offers.length) {
      offers = await fetchOffers({ limit, minPayout: 1, geos: fallbackGeos, device: device ?? undefined, sort: 'epc' });
    }
  } catch {
    // fall through to bundled fallback
  }
  if (!offers.length) offers = FALLBACK_OFFERS.slice(0, limit);
  return { offers, matchedCountry };
}

/** Append a subid to a CPAlead tracking link — this is what drives the postback {subid}. */
export function withSubid(link: string, subid?: string): string {
  if (!subid || !link) return link;
  const sep = link.includes('?') ? '&' : '?';
  return `${link}${sep}subid=${encodeURIComponent(subid)}`;
}

function normalize(o: any): CpaOffer {
  return {
    id: o.id,
    title: o.title ?? 'Offer',
    description: o.description ?? '',
    conversion: o.conversion ?? '',
    device: o.device ?? 'all_devices',
    amount: Number(o.amount) || 0,
    payout_currency: o.payout_currency ?? 'USD',
    payout_type: (o.payout_type ?? 'CPA').toUpperCase(),
    countries: Array.isArray(o.countries) ? o.countries : [],
    epc: o.epc != null ? Number(o.epc) : undefined,
    is_fast_pay: !!o.is_fast_pay,
    daily_cap: o.daily_cap,
    link: o.link,
    image: o.creatives?.og_image || o.creatives?.url || o.image,
  };
}

/** Bundled safety net so the page never renders empty if the live fetch fails. */
export const FALLBACK_OFFERS: CpaOffer[] = [
  {
    id: 5545519, title: 'CardCrush: Win This Week!', device: 'all_devices',
    amount: 39, payout_currency: 'USD', payout_type: 'CPA', countries: ['US'],
    epc: 0.3, is_fast_pay: true,
    link: 'https://www.lnksforyou.com/view.php?id=5545519&pub=2716424&_src=api&_src_sig=09eaa454e3d16e579563278092e6ccf1270c5a34e49b207ad196fea4287a3af2',
    image: 'https://cdndn.s3.us-west-1.amazonaws.com/offers/ogimage/cardcrush-5545519-6419.jpg',
  },
  {
    id: 5543850, title: 'Scrambly: First Withdrawal Bonus', device: 'android',
    amount: 8.58, payout_currency: 'USD', payout_type: 'CPA', countries: ['US'],
    epc: 0.3, is_fast_pay: false,
    link: 'https://www.qckclk.com/view.php?id=5543850&pub=2716424&_src=api&_src_sig=a32b3b401eeb1bb946ff555cc69ef93ee1af4718a3bcb3d05ca1917740c58192',
    image: 'https://cdndn.s3.us-west-1.amazonaws.com/offers/ogimage/scrambly-us-cpe-incent-5543850-1465.jpg',
  },
  {
    id: 5545748, title: 'Cash Giraffe: Collect 15 Coins', device: 'android',
    amount: 6.24, payout_currency: 'USD', payout_type: 'CPA', countries: ['US'],
    epc: 0.3, is_fast_pay: false,
    link: 'https://www.fastsvr.com/view.php?id=5545748&pub=2716424&_src=api&_src_sig=5937c1ef928289cd77218f69121acc72fec07c2f0a1610df4cdf596627e5106b',
    image: 'https://cdndn.s3.us-west-1.amazonaws.com/offers/ogimage/cash-giraffe-collect-15-coins-5545748-1567.jpg',
  },
];

export async function fetchOffers(opts: FetchOffersOptions = {}): Promise<CpaOffer[]> {
  const {
    limit = 24, minPayout = 1, geos, country, device, type,
    sort = 'epc', sampleSize = 400,
  } = opts;

  // No `fields` param on purpose — we need the full objects (link + creatives image).
  // `country` filters server-side at the API (efficient for per-visitor geo matching).
  const countryParam = country ? `&country=${encodeURIComponent(country)}` : '';
  const url = `${API}?id=${PUBLISHER_ID}&limit=${sampleSize}${countryParam}`;
  // `cf` caches the upstream API JSON per URL at the Cloudflare edge (ignored off-Cloudflare),
  // so we stay fast without edge-caching the personalized HTML.
  const init: any = { signal: AbortSignal.timeout(9000), cf: { cacheTtl: 900, cacheEverything: true } };
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`CPAlead API ${res.status}`);
  const data = await res.json();
  if (data?.status !== 'success' || !Array.isArray(data.offers)) {
    throw new Error('CPAlead API returned no offers');
  }

  const geoSet = geos && geos.length ? new Set(geos.map((g) => g.toUpperCase())) : null;
  const wantType = type ? type.toUpperCase() : null;

  const filtered = data.offers.map(normalize).filter((o: CpaOffer) => {
    if (!o.link) return false;
    if (o.amount < minPayout) return false;
    if (wantType && o.payout_type !== wantType) return false;
    if (geoSet && !o.countries.some((c) => geoSet.has(c.toUpperCase()))) return false;
    if (device && !deviceMatches(o.device, device)) return false;
    return true;
  });

  filtered.sort((a: CpaOffer, b: CpaOffer) =>
    sort === 'payout'
      ? b.amount - a.amount
      : (b.epc ?? 0) - (a.epc ?? 0) || b.amount - a.amount,
  );

  return filtered.slice(0, limit);
}

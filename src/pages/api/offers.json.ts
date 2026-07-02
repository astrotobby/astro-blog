import type { APIRoute } from 'astro';
import { detectDevice, countryName, countryFlag } from '../../lib/cpalead';
import { getBlendedOffers } from '../../lib/offers';

// SSR endpoint — reads the visitor's country (Cloudflare header), IP and device,
// blends CPAlead + CPAGrip offers, and returns them as JSON. Lets prerendered
// (static) pages show personalized offers via a client-side fetch.
export const prerender = false;

export const GET: APIRoute = async ({ request, url, locals }) => {
  const limit = Math.min(Math.max(Number(url.searchParams.get('limit')) || 6, 1), 24);
  const subid = (url.searchParams.get('subid') || 'astroblog').slice(0, 60);

  const cf = (request.headers.get('cf-ipcountry') || '').toUpperCase();
  const visitorCountry =
    /^[A-Z]{2}$/.test(cf) && !['XX', 'T1', 'A1', 'A2'].includes(cf) ? cf : null;
  const ip = request.headers.get('cf-connecting-ip');
  const userAgent = request.headers.get('user-agent');
  const device = detectDevice(userAgent);

  // CPAGrip pubkey lives in a Cloudflare secret; absent → CPAlead-only (graceful).
  const cpagripPubkey =
    (locals as any)?.runtime?.env?.CPAGRIP_PUBKEY ?? import.meta.env.CPAGRIP_PUBKEY ?? null;

  const { offers, matchedCountry, networks } = await getBlendedOffers({
    country: visitorCountry, ip, userAgent, device, limit, subid, cpagripPubkey,
  });

  const payload = {
    matchedCountry,
    geoLabel: matchedCountry ? `${countryFlag(matchedCountry)} ${countryName(matchedCountry)}` : '',
    device,
    networks,
    offers: offers.map((o) => ({
      id: o.id,
      network: o.network ?? 'cpalead',
      title: o.title,
      amount: o.amount,
      payout_type: o.payout_type,
      device: o.device,
      countries: o.countries.slice(0, 4),
      is_fast_pay: !!o.is_fast_pay,
      image: o.image,
      link: o.link, // already finalized with subid / tracking_id
    })),
  };

  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'private, no-store',
    },
  });
};

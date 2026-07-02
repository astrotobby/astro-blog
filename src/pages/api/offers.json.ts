import type { APIRoute } from 'astro';
import {
  pickOffersFor,
  detectDevice,
  withSubid,
  countryName,
  countryFlag,
} from '../../lib/cpalead';

// SSR endpoint — reads the visitor's country (Cloudflare header) + device (User-Agent)
// and returns geo/device-matched offers as JSON. Lets prerendered (static) pages show
// personalized offers via a client-side fetch.
export const prerender = false;

export const GET: APIRoute = async ({ request, url }) => {
  const limit = Math.min(Math.max(Number(url.searchParams.get('limit')) || 6, 1), 24);
  const subid = (url.searchParams.get('subid') || 'astroblog').slice(0, 60);

  const cf = (request.headers.get('cf-ipcountry') || '').toUpperCase();
  const visitorCountry =
    /^[A-Z]{2}$/.test(cf) && !['XX', 'T1', 'A1', 'A2'].includes(cf) ? cf : null;
  const device = detectDevice(request.headers.get('user-agent'));

  const { offers, matchedCountry } = await pickOffersFor({ country: visitorCountry, device, limit });

  const payload = {
    matchedCountry,
    geoLabel: matchedCountry ? `${countryFlag(matchedCountry)} ${countryName(matchedCountry)}` : '',
    device,
    offers: offers.map((o) => ({
      id: o.id,
      title: o.title,
      amount: o.amount,
      payout_type: o.payout_type,
      device: o.device,
      countries: o.countries.slice(0, 4),
      is_fast_pay: !!o.is_fast_pay,
      image: o.image,
      link: withSubid(o.link, subid),
    })),
  };

  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      // Personalized per visitor — never share across visitors.
      'Cache-Control': 'private, no-store',
    },
  });
};

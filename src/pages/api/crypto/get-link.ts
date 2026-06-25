import type { APIRoute } from 'astro';
import { readCryptoEnv, resolveInvoiceLink } from '../../../lib/crypto-pay';

// Serves the crypto pay-link for an order to the Checkout UI Extension on the
// Thank you / Order status page. Read-only and low-sensitivity (a payment link
// the buyer is entitled to), gated by verifying the order is a real pending
// crypto order via the Admin API. CORS-open so the sandboxed extension can call it.
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS },
  });
}

export const OPTIONS: APIRoute = () => new Response(null, { status: 204, headers: CORS });

export const GET: APIRoute = async ({ request }) => {
  const env = await readCryptoEnv();
  const raw = new URL(request.url).searchParams.get('orderId') ?? '';
  const numeric = raw.replace(/\D/g, ''); // accepts a gid or a bare numeric id
  if (!numeric) return json({ ok: false });

  try {
    const invoiceUrl = await resolveInvoiceLink(env, `gid://shopify/Order/${numeric}`);
    return json(invoiceUrl ? { ok: true, invoiceUrl } : { ok: false });
  } catch (err) {
    console.error('[crypto/get-link]', (err as Error).message);
    // 200 with ok:false — the extension just hides itself; the order may not be
    // queryable yet (creation in progress) and the extension will retry.
    return json({ ok: false });
  }
};

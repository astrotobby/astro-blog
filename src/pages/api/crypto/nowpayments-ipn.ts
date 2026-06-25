import type { APIRoute } from 'astro';
import { readCryptoEnv, verifyNowPaymentsIpn, markOrderPaid } from '../../../lib/crypto-pay';

// NOWPayments IPN webhook target. This is the money-moving trigger, so the
// HMAC-SHA512 signature is verified before we touch the order. On a fully-paid
// status we mark the Shopify order paid, which fires Shopify's automatic
// digital-product delivery.
const PAID_STATUSES = new Set(['finished', 'confirmed']);

export const POST: APIRoute = async ({ request }) => {
  const env = await readCryptoEnv();
  const raw = await request.text();
  const signature = request.headers.get('x-nowpayments-sig');

  let body: { payment_status?: string; order_id?: string };
  try {
    body = JSON.parse(raw);
  } catch {
    return new Response('bad json', { status: 400 });
  }

  const valid = await verifyNowPaymentsIpn(env, body, signature);
  if (!valid) {
    console.warn('[crypto/ipn] invalid signature');
    return new Response('invalid signature', { status: 401 });
  }

  const status = body.payment_status ?? '';
  const orderId = body.order_id ?? '';
  if (!PAID_STATUSES.has(status) || !orderId) {
    return new Response(JSON.stringify({ ok: true, ignored: status }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    await markOrderPaid(env, `gid://shopify/Order/${orderId}`);
  } catch (err) {
    // Already-paid orders raise a userError — treat as success (idempotent).
    const msg = (err as Error).message;
    if (!/already|cannot be marked|paid/i.test(msg)) {
      console.error('[crypto/ipn] markOrderPaid failed:', msg);
      return new Response('error', { status: 500 });
    }
  }

  return new Response(JSON.stringify({ ok: true, paid: orderId }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
};

import type { APIRoute } from 'astro';
import {
  readCryptoEnv,
  fetchOrder,
  createNowPaymentsInvoice,
  recordInvoiceOnOrder,
  emailPayLink,
  CRYPTO_GATEWAY_NAME,
  CRYPTO_INVOICE_TAG,
} from '../../../lib/crypto-pay';

// Shopify `orders/create` webhook target. We don't trust the webhook payload
// for anything sensitive — we re-fetch the order via the authenticated Admin
// API and only act on real, pending, crypto-gateway orders. Returns 200 for
// every "ignore" case so Shopify doesn't retry; 500 only on transient errors.
export const POST: APIRoute = async ({ request }) => {
  const env = await readCryptoEnv();
  // TEMP: reproduce a real send to the BUYER address to surface Resend's exact
  // response (e.g. "can only send to your own email until you verify a domain").
  // Remove after diagnosis.
  if (new URL(request.url).searchParams.get('buyertest') === '1' && env.RESEND_API_KEY) {
    const r = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${env.RESEND_API_KEY}` },
      body: JSON.stringify({
        from: 'Astro Signal <orders@astrotobby.site>',
        to: ['tototee64@gmail.com'],
        subject: 'Crypto pay-link delivery test',
        html: '<p>Buyer-address delivery test.</p>',
      }),
    });
    return new Response(
      JSON.stringify({ resendStatus: r.status, resendBody: (await r.text()).slice(0, 400) }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    );
  }
  let payload: { id?: number | string };
  try {
    payload = await request.json();
  } catch {
    return new Response('bad json', { status: 200 });
  }

  const numericId = payload?.id != null ? String(payload.id) : '';
  if (!numericId) return new Response('no order id', { status: 200 });
  const orderGid = `gid://shopify/Order/${numericId}`;

  try {
    const order = await fetchOrder(env, orderGid);
    if (!order) return new Response('order not found', { status: 200 });
    if (order.financialStatus !== 'PENDING') return new Response('not pending', { status: 200 });
    if (!order.gateways.includes(CRYPTO_GATEWAY_NAME)) return new Response('not crypto', { status: 200 });
    if (order.tags.includes(CRYPTO_INVOICE_TAG)) return new Response('already invoiced', { status: 200 });

    const invoice = await createNowPaymentsInvoice(env, {
      orderId: numericId,
      amount: order.amount,
      currency: order.currency,
      description: `Order ${order.name}`,
      email: order.email,
      ipnCallbackUrl: 'https://astrotobby.site/api/crypto/nowpayments-ipn',
      successUrl: order.orderStatusUrl,
    });

    await recordInvoiceOnOrder(env, orderGid, invoice.invoice_url);
    if (order.email) await emailPayLink(env, order.email, order.name, invoice.invoice_url);

    return new Response(JSON.stringify({ ok: true, invoice_url: invoice.invoice_url }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    console.error('[crypto/order-created]', (err as Error).message);
    // 500 -> Shopify retries the webhook later (handles transient API hiccups).
    return new Response('error', { status: 500 });
  }
};

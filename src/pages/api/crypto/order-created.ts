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
  // TEMP diagnostic: if the admin token isn't visible, report which runtime env
  // KEYS the Worker can see (names only, never values) so we can tell a
  // naming/environment mismatch from "cloudflare:workers env not exposing Pages
  // secrets at all" (empty list). Remove once secrets are confirmed wired.
  if (!env.SHOPIFY_ADMIN_TOKEN) {
    return new Response(
      JSON.stringify({ error: 'SHOPIFY_ADMIN_TOKEN not visible', visibleEnvKeys: Object.keys(env) }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
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
    const detail = (err as Error).message;
    console.error('[crypto/order-created]', detail);
    // Temporary diagnostic: surface the failure reason so we can tell a missing
    // secret ("Missing SHOPIFY_ADMIN_TOKEN") apart from an invalid token/scope
    // ("Shopify Admin API 401/403"). Revert once verified.
    // 500 -> Shopify retries the webhook later (handles transient API hiccups).
    return new Response(JSON.stringify({ error: 'error', detail }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};

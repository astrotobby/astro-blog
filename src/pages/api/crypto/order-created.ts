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
  // TEMP Resend wiring test (?emailtest=1): sends one email to the store owner
  // and returns Resend's status/message so we can confirm the key + domain
  // verification + from-address all work. Fixed recipient (no open relay).
  // Remove once verified.
  if (new URL(request.url).searchParams.get('emailtest') === '1') {
    if (!env.RESEND_API_KEY) {
      let emailKeyNames: string[] = [];
      try {
        const m = await import('cloudflare:workers');
        emailKeyNames = Object.keys((m.env ?? {}) as Record<string, unknown>).filter((k) =>
          /resend|mail|email/i.test(k)
        );
      } catch {
        emailKeyNames = [];
      }
      return new Response(JSON.stringify({ hasKey: false, emailKeyNames }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    const r = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
      },
      body: JSON.stringify({
        from: 'Astro Signal <orders@astrotobby.site>',
        to: ['chanzeratobias@gmail.com'],
        subject: 'Resend wiring test — crypto automation',
        html: '<p>If you received this, your crypto pay-link emails are working.</p>',
      }),
    });
    const body = await r.text();
    return new Response(
      JSON.stringify({ hasKey: true, resendStatus: r.status, resendBody: body.slice(0, 400) }),
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

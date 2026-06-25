// Crypto-payment automation for the "pay in crypto with NOWPayments" manual
// payment method in Shopify.
//
// Flow:
//   1. Shopify `orders/create` webhook  -> /api/crypto/order-created
//      Verifies the order via the Admin API, creates a NOWPayments invoice,
//      and stores the pay link on the order (tag + note) for idempotency.
//   2. NOWPayments IPN webhook          -> /api/crypto/nowpayments-ipn
//      Verifies the HMAC-SHA512 signature, then marks the Shopify order paid
//      (which triggers Shopify's automatic digital-product delivery).
//
// All secrets are read from the Cloudflare runtime env (Astro v6 +
// @astrojs/cloudflare). They MUST be set as encrypted secrets in the
// Cloudflare dashboard — never committed:
//   NOWPAYMENTS_API_KEY     - NOWPayments API key (create invoices)
//   NOWPAYMENTS_IPN_SECRET  - NOWPayments IPN secret (verify webhooks)
//   SHOPIFY_ADMIN_TOKEN     - Shopify Admin API token (shpat_…, write_orders)
//   SHOPIFY_STORE_DOMAIN    - optional, defaults to chainztobby.myshopify.com

const STORE_DOMAIN_DEFAULT = 'chainztobby.myshopify.com';
const ADMIN_API_VERSION = '2025-10';
// Must match the manual payment method name created in Shopify admin.
export const CRYPTO_GATEWAY_NAME = 'pay in crypto with NOWPayments';
export const CRYPTO_INVOICE_TAG = 'crypto-invoice-sent';

export interface CryptoEnv {
  NOWPAYMENTS_API_KEY?: string;
  NOWPAYMENTS_IPN_SECRET?: string;
  SHOPIFY_ADMIN_TOKEN?: string;
  SHOPIFY_STORE_DOMAIN?: string;
  RESEND_API_KEY?: string; // optional: email the pay link to the buyer
}

/** Read Cloudflare runtime vars/secrets (see lib/shopify.ts for the rationale). */
export async function readCryptoEnv(): Promise<CryptoEnv> {
  try {
    const mod = await import('cloudflare:workers');
    return (mod.env ?? {}) as unknown as CryptoEnv;
  } catch {
    return {};
  }
}

/** Lowercase hex HMAC-SHA512 of `message` keyed by `secret` (Web Crypto). */
export async function hmacSha512Hex(secret: string, message: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    enc.encode(secret),
    { name: 'HMAC', hash: 'SHA-512' },
    false,
    ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Recursively sort object keys — NOWPayments signs the key-sorted JSON body. */
export function sortDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortDeep);
  if (value && typeof value === 'object') {
    return Object.keys(value as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((acc, k) => {
        acc[k] = sortDeep((value as Record<string, unknown>)[k]);
        return acc;
      }, {});
  }
  return value;
}

/** Constant-time string compare to avoid signature timing leaks. */
export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** Verify a NOWPayments IPN `x-nowpayments-sig` header against the raw body. */
export async function verifyNowPaymentsIpn(
  env: CryptoEnv,
  parsedBody: unknown,
  signature: string | null
): Promise<boolean> {
  if (!env.NOWPAYMENTS_IPN_SECRET || !signature) return false;
  const sorted = JSON.stringify(sortDeep(parsedBody));
  const expected = await hmacSha512Hex(env.NOWPAYMENTS_IPN_SECRET, sorted);
  return timingSafeEqual(expected, signature.trim());
}

function storeDomain(env: CryptoEnv): string {
  return env.SHOPIFY_STORE_DOMAIN ?? STORE_DOMAIN_DEFAULT;
}

/** Call the Shopify Admin GraphQL API with the shpat_ token. */
export async function adminGraphQL<T = unknown>(
  env: CryptoEnv,
  query: string,
  variables?: Record<string, unknown>
): Promise<T> {
  if (!env.SHOPIFY_ADMIN_TOKEN) throw new Error('Missing SHOPIFY_ADMIN_TOKEN');
  const res = await fetch(
    `https://${storeDomain(env)}/admin/api/${ADMIN_API_VERSION}/graphql.json`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Shopify-Access-Token': env.SHOPIFY_ADMIN_TOKEN,
      },
      body: JSON.stringify({ query, variables }),
    }
  );
  if (!res.ok) throw new Error(`Shopify Admin API ${res.status}`);
  return (await res.json()) as T;
}

export interface ShopifyOrderInfo {
  gid: string;
  name: string;
  email: string | null;
  financialStatus: string;
  amount: string;
  currency: string;
  gateways: string[];
  tags: string[];
  orderStatusUrl: string | null;
}

/** Fetch the authoritative order state (don't trust the webhook payload). */
export async function fetchOrder(env: CryptoEnv, orderGid: string): Promise<ShopifyOrderInfo | null> {
  const query = `query($id: ID!) {
    order(id: $id) {
      id name email displayFinancialStatus
      paymentGatewayNames tags statusPageUrl
      totalPriceSet { shopMoney { amount currencyCode } }
    }
  }`;
  const json = await adminGraphQL<{ data?: { order?: any } }>(env, query, { id: orderGid });
  const o = json?.data?.order;
  if (!o) return null;
  return {
    gid: o.id,
    name: o.name,
    email: o.email ?? null,
    financialStatus: o.displayFinancialStatus,
    amount: o.totalPriceSet?.shopMoney?.amount ?? '0',
    currency: o.totalPriceSet?.shopMoney?.currencyCode ?? 'USD',
    gateways: o.paymentGatewayNames ?? [],
    tags: o.tags ?? [],
    orderStatusUrl: o.statusPageUrl ?? null,
  };
}

export interface NowInvoice {
  id: string;
  invoice_url: string;
}

/** Create a hosted NOWPayments invoice; the buyer pays at invoice_url. */
export async function createNowPaymentsInvoice(
  env: CryptoEnv,
  args: {
    orderId: string;
    amount: string;
    currency: string;
    description: string;
    email: string | null;
    ipnCallbackUrl: string;
    successUrl: string | null;
  }
): Promise<NowInvoice> {
  if (!env.NOWPAYMENTS_API_KEY) throw new Error('Missing NOWPAYMENTS_API_KEY');
  const body: Record<string, unknown> = {
    price_amount: Number(args.amount),
    price_currency: args.currency.toLowerCase(),
    order_id: args.orderId,
    order_description: args.description,
    ipn_callback_url: args.ipnCallbackUrl,
    is_fixed_rate: true,
  };
  if (args.email) body.customer_email = args.email;
  if (args.successUrl) body.success_url = args.successUrl;

  const res = await fetch('https://api.nowpayments.io/v1/invoice', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-api-key': env.NOWPAYMENTS_API_KEY },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`NOWPayments invoice ${res.status}: ${await res.text()}`);
  return (await res.json()) as NowInvoice;
}

/** Tag the order + store the pay link in the order note (idempotency marker). */
export async function recordInvoiceOnOrder(
  env: CryptoEnv,
  orderGid: string,
  invoiceUrl: string
): Promise<void> {
  await adminGraphQL(
    env,
    `mutation($id: ID!, $tags: [String!]!, $note: String!) {
      tagsAdd(id: $id, tags: $tags) { userErrors { message } }
      orderUpdate(input: { id: $id, note: $note }) { userErrors { message } }
    }`,
    { id: orderGid, tags: [CRYPTO_INVOICE_TAG], note: `Crypto payment link: ${invoiceUrl}` }
  );
}

/** Mark the Shopify order paid → triggers automatic digital delivery. */
export async function markOrderPaid(env: CryptoEnv, orderGid: string): Promise<void> {
  const json = await adminGraphQL<{ data?: { orderMarkAsPaid?: { userErrors?: { message: string }[] } } }>(
    env,
    `mutation($input: OrderMarkAsPaidInput!) {
      orderMarkAsPaid(input: $input) {
        order { id displayFinancialStatus }
        userErrors { field message }
      }
    }`,
    { input: { id: orderGid } }
  );
  const errs = json?.data?.orderMarkAsPaid?.userErrors ?? [];
  if (errs.length) throw new Error(`orderMarkAsPaid: ${errs.map((e) => e.message).join('; ')}`);
}

/** Optional: email the buyer the pay link via Resend (only if RESEND_API_KEY set). */
export async function emailPayLink(
  env: CryptoEnv,
  to: string,
  orderName: string,
  invoiceUrl: string
): Promise<boolean> {
  if (!env.RESEND_API_KEY) return false;
  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${env.RESEND_API_KEY}` },
    body: JSON.stringify({
      from: 'Astro Signal <orders@astrotobby.site>',
      to: [to],
      subject: `Complete your crypto payment for order ${orderName}`,
      html: `<p>Thanks for your order <strong>${orderName}</strong>.</p>
        <p>Pay securely with Bitcoin, USDT, ETH or 300+ coins here:</p>
        <p><a href="${invoiceUrl}">${invoiceUrl}</a></p>
        <p>Your download is sent automatically once the payment is confirmed on-chain.</p>`,
    }),
  });
  return res.ok;
}

export { STORE_DOMAIN_DEFAULT };

import type { APIRoute } from 'astro';
import { fetchShopifyProducts } from '../../lib/shopify';

export const GET: APIRoute = async ({ locals }) => {
  try {
    const env = (locals as { runtime?: { env?: Record<string, string | undefined> } })?.runtime?.env;
    const products = await fetchShopifyProducts(env);
    return new Response(JSON.stringify({ products }), {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=300' },
    });
  } catch (err) {
    console.error('[shopify-products]', err);
    return new Response(
      JSON.stringify({
        error: 'Failed to fetch products',
        detail: (err as Error)?.message ?? String(err),
        products: [],
      }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};

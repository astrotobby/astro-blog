import type { APIRoute } from 'astro';
import { fetchShopifyProducts } from '../../lib/shopify';

export const GET: APIRoute = async () => {
  try {
    const products = await fetchShopifyProducts();
    return new Response(JSON.stringify({ products }), {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=300' },
    });
  } catch (err) {
    console.error('[shopify-products]', err);
    return new Response(
      JSON.stringify({ error: 'Failed to fetch products', products: [] }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};

export interface ShopifyProduct {
  id: string;
  title: string;
  status: string;
  vendor: string;
  productType: string;
  totalVariants: number;
  totalInventory: number;
  createdAt: string;
  updatedAt: string;
  handle: string;
  variantId: string;
  price: string;
  description: string;
}

// Maps post tag keywords → product handles to surface first
const TAG_PRIORITY: Record<string, string> = {
  video:      'ai-video-freelancer-toolkit-2026',
  freelance:  'ai-video-freelancer-toolkit-2026',
  automation: 'make-com-autoblogging-blueprint-2026-build-a-full-ai-content-pipeline',
  autoblog:   'make-com-autoblogging-blueprint-2026-build-a-full-ai-content-pipeline',
  make:       'make-com-autoblogging-blueprint-2026-build-a-full-ai-content-pipeline',
  seo:        'aeo-masterguide-2026-rank-in-ai-search-chatgpt-perplexity-google-ai-overviews',
  aeo:        'aeo-masterguide-2026-rank-in-ai-search-chatgpt-perplexity-google-ai-overviews',
  search:     'aeo-masterguide-2026-rank-in-ai-search-chatgpt-perplexity-google-ai-overviews',
  agent:      'agentic-ai-workflow-pack-2026-build-amp-deploy-multi-agent-systems-without-code',
  prompt:     'ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation',
  llm:        'ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation',
};

export async function fetchShopifyProducts(): Promise<ShopifyProduct[]> {
  const domain = import.meta.env.SHOPIFY_STORE_DOMAIN ?? 'chainztobby.myshopify.com';
  const token = import.meta.env.SHOPIFY_ADMIN_API_ACCESS_TOKEN as string | undefined;

  if (!token) throw new Error('Missing SHOPIFY_ADMIN_API_ACCESS_TOKEN');

  const res = await fetch(
    `https://${domain}/admin/api/2024-01/products.json?status=active&limit=10`,
    { headers: { 'X-Shopify-Access-Token': token, 'Content-Type': 'application/json' } }
  );

  if (!res.ok) throw new Error(`Shopify API responded with ${res.status}`);

  const { products } = (await res.json()) as { products: any[] };

  return products.map((p) => ({
    id: `gid://shopify/Product/${p.id}`,
    title: p.title as string,
    status: (p.status as string).toUpperCase(),
    vendor: p.vendor as string,
    productType: (p.product_type as string) || 'Digital Download',
    totalVariants: (p.variants as any[]).length,
    totalInventory: 0,
    createdAt: p.created_at as string,
    updatedAt: p.updated_at as string,
    handle: p.handle as string,
    variantId: `gid://shopify/ProductVariant/${(p.variants as any[])[0]?.id}`,
    price: `$${parseFloat((p.variants as any[])[0]?.price ?? '0').toFixed(2)}`,
    description: ((p.body_html as string) ?? '')
      .replace(/<[^>]+>/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 140) || (p.title as string),
  }));
}

export function prioritizeProducts(
  products: ShopifyProduct[],
  tags: string[]
): ShopifyProduct[] {
  if (!tags.length) return products;

  const lowerTags = tags.map((t) => t.toLowerCase());
  const priorityHandle = lowerTags.reduce<string | undefined>((found, tag) => {
    if (found) return found;
    for (const [key, handle] of Object.entries(TAG_PRIORITY)) {
      if (tag.includes(key)) return handle;
    }
    return undefined;
  }, undefined);

  if (!priorityHandle) return products;

  const priority = products.filter((p) => p.handle === priorityHandle);
  const rest = products.filter((p) => p.handle !== priorityHandle);
  return [...priority, ...rest];
}

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
  image?: string;
}

const TAG_PRIORITY: Record<string, string> = {
  video: 'ai-video-freelancer-toolkit-2026',
  freelance: 'ai-video-freelancer-toolkit-2026',
  runway: 'ai-video-freelancer-toolkit-2026',
  kling: 'ai-video-freelancer-toolkit-2026',
  automation: 'make-com-autoblogging-blueprint-2026-build-a-full-ai-content-pipeline',
  autoblog: 'make-com-autoblogging-blueprint-2026-build-a-full-ai-content-pipeline',
  make: 'make-com-autoblogging-blueprint-2026-build-a-full-ai-content-pipeline',
  pipeline: 'make-com-autoblogging-blueprint-2026-build-a-full-ai-content-pipeline',
  seo: 'aeo-masterguide-2026-rank-in-ai-search-chatgpt-perplexity-google-ai-overviews',
  aeo: 'aeo-masterguide-2026-rank-in-ai-search-chatgpt-perplexity-google-ai-overviews',
  search: 'aeo-masterguide-2026-rank-in-ai-search-chatgpt-perplexity-google-ai-overviews',
  perplexity: 'aeo-masterguide-2026-rank-in-ai-search-chatgpt-perplexity-google-ai-overviews',
  chatgpt: 'aeo-masterguide-2026-rank-in-ai-search-chatgpt-perplexity-google-ai-overviews',
  agent: 'agentic-ai-workflow-pack-2026-build-amp-deploy-multi-agent-systems-without-code',
  agentic: 'agentic-ai-workflow-pack-2026-build-amp-deploy-multi-agent-systems-without-code',
  prompt: 'ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation',
  prompts: 'ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation',
  llm: 'ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation',
};

export const FALLBACK_PRODUCTS: ShopifyProduct[] = [
  {
    id: 'gid://shopify/Product/10365512286487',
    title: 'The AI Video Freelancer Toolkit 2026 — Land Clients, Deliver AI Videos, Get Paid',
    status: 'ACTIVE',
    vendor: 'Astro Tobby',
    productType: 'Digital Download',
    totalVariants: 1,
    totalInventory: 0,
    createdAt: '2026-06-09T09:05:47Z',
    updatedAt: '2026-06-11T15:42:51Z',
    handle: 'ai-video-freelancer-toolkit-2026',
    variantId: 'gid://shopify/ProductVariant/53517875675415',
    price: '$24.00',
    description: 'Everything you need to land AI video clients, deliver professional results with Runway ML and Kling AI, and get paid — in one toolkit.',
    image: 'https://cdn.shopify.com/s/files/1/1009/9716/9431/files/product_cover.jpg',
  },
  {
    id: 'gid://shopify/Product/10365578838295',
    title: 'Make.com Autoblogging Blueprint 2026 — Build a Full AI Content Pipeline',
    status: 'ACTIVE',
    vendor: 'Astro Tobby',
    productType: 'Digital Download',
    totalVariants: 1,
    totalInventory: 0,
    createdAt: '2026-06-09T10:22:51Z',
    updatedAt: '2026-06-19T04:13:49Z',
    handle: 'make-com-autoblogging-blueprint-2026-build-a-full-ai-content-pipeline',
    variantId: 'gid://shopify/ProductVariant/53518038434071',
    price: '$22.00',
    description: 'Build a fully automated blog content pipeline that writes, publishes, and distributes posts while you sleep — no coding required.',
    image: 'https://cdn.shopify.com/s/files/1/1009/9716/9431/files/cover_product2.jpg',
  },
  {
    id: 'gid://shopify/Product/10365579297047',
    title: 'AI Prompt Vault 2026 — 500+ Categorized Prompts for Video, Content, Code & Automation',
    status: 'ACTIVE',
    vendor: 'Astro Tobby',
    productType: 'Digital Download',
    totalVariants: 1,
    totalInventory: 0,
    createdAt: '2026-06-09T10:23:15Z',
    updatedAt: '2026-06-19T04:19:31Z',
    handle: 'ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation',
    variantId: 'gid://shopify/ProductVariant/53518038892823',
    price: '$12.00',
    description: '500+ battle-tested AI prompts across 10 categories — video, content, code, automation and more. Copy, paste, and produce.',
    image: 'https://cdn.shopify.com/s/files/1/1009/9716/9431/files/cover_product3.jpg',
  },
  {
    id: 'gid://shopify/Product/10365579821335',
    title: 'AEO Masterguide 2026 — Rank in AI Search (ChatGPT, Perplexity, Google AI Overviews)',
    status: 'ACTIVE',
    vendor: 'Astro Tobby',
    productType: 'Digital Download',
    totalVariants: 1,
    totalInventory: 0,
    createdAt: '2026-06-09T10:23:38Z',
    updatedAt: '2026-06-10T19:43:36Z',
    handle: 'aeo-masterguide-2026-rank-in-ai-search-chatgpt-perplexity-google-ai-overviews',
    variantId: 'gid://shopify/ProductVariant/53518039417111',
    price: '$14.00',
    description: 'SEO is dead for AI search. This guide shows you exactly how to get featured in ChatGPT, Perplexity, and Google AI Overviews.',
    image: 'https://cdn.shopify.com/s/files/1/1009/9716/9431/files/cover_product4.jpg',
  },
  {
    id: 'gid://shopify/Product/10365580312855',
    title: 'Agentic AI Workflow Pack 2026 — Build & Deploy Multi-Agent Systems Without Code',
    status: 'ACTIVE',
    vendor: 'Astro Tobby',
    productType: 'Digital Download',
    totalVariants: 1,
    totalInventory: 0,
    createdAt: '2026-06-09T10:23:59Z',
    updatedAt: '2026-06-10T19:43:39Z',
    handle: 'agentic-ai-workflow-pack-2026-build-amp-deploy-multi-agent-systems-without-code',
    variantId: 'gid://shopify/ProductVariant/53518039908631',
    price: '$32.00',
    description: 'Multi-agent AI systems are rewriting how work gets done. This pack gives non-coders a plug-and-play toolkit to build and deploy them.',
    image: 'https://cdn.shopify.com/s/files/1/1009/9716/9431/files/cover_product5.jpg',
  },
];

export async function fetchShopifyProducts(): Promise<ShopifyProduct[]> {
  const domain: string =
    (import.meta.env.SHOPIFY_STORE_DOMAIN as string | undefined) ?? 'chainztobby.myshopify.com';
  const token: string | undefined = import.meta.env.SHOPIFY_STOREFRONT_API_TOKEN as
    | string
    | undefined;

  if (!token) throw new Error('Missing SHOPIFY_STOREFRONT_API_TOKEN');

  const query = `{
    products(first: 10, query: "available_for_sale:true") {
      edges {
        node {
          id title handle vendor productType createdAt updatedAt description
          featuredImage { url }
          priceRange { minVariantPrice { amount currencyCode } }
          variants(first: 1) { edges { node { id } } }
        }
      }
    }
  }`;

  const res = await fetch(`https://${domain}/api/2025-10/graphql.json`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Shopify-Storefront-Access-Token': token,
    },
    body: JSON.stringify({ query }),
  });

  if (!res.ok) throw new Error(`Shopify Storefront API ${res.status}`);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const json = (await res.json()) as any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const edges: any[] = json?.data?.products?.edges ?? [];

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return edges.map((edge: any): ShopifyProduct => {
    const p = edge.node;
    return {
      id: String(p.id),
      title: String(p.title),
      status: 'ACTIVE',
      vendor: String(p.vendor),
      productType: String(p.productType || 'Digital Download'),
      totalVariants: 1,
      totalInventory: 0,
      createdAt: String(p.createdAt),
      updatedAt: String(p.updatedAt),
      handle: String(p.handle),
      variantId: String(p.variants?.edges?.[0]?.node?.id ?? ''),
      price: `$${parseFloat(String(p.priceRange?.minVariantPrice?.amount ?? '0')).toFixed(2)}`,
      description: String(p.description ?? '').slice(0, 160) || String(p.title),
      image: p.featuredImage?.url ? String(p.featuredImage.url) : undefined,
    };
  });
}

// Deterministic string hash -> seed for a simple PRNG (mulberry32).
// Same seed always produces the same shuffle, so a given page's product
// order stays stable across requests (no flicker on refresh/back-button),
// while different pages/seeds produce different orders.
function hashSeed(seed: string): number {
  let h = 1779033703 ^ seed.length;
  for (let i = 0; i < seed.length; i++) {
    h = Math.imul(h ^ seed.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function seededShuffle<T>(items: T[], seed: string): T[] {
  const rand = mulberry32(hashSeed(seed));
  const arr = [...items];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

export function prioritizeProducts(
  products: ShopifyProduct[],
  tags: string[],
  rotationSeed?: string
): ShopifyProduct[] {
  let priorityHandle: string | undefined;

  if (tags.length) {
    const lowerTags = tags.map((t) => t.toLowerCase());
    outer: for (const tag of lowerTags) {
      for (const [key, handle] of Object.entries(TAG_PRIORITY)) {
        if (tag.includes(key) || key.includes(tag)) {
          priorityHandle = handle;
          break outer;
        }
      }
    }
  }

  const featured = priorityHandle
    ? products.filter((p) => p.handle === priorityHandle)
    : [];
  const rest = priorityHandle
    ? products.filter((p) => p.handle !== priorityHandle)
    : products;

  // Rotate daily so the order isn't frozen forever, but different pages
  // (different seeds) still show a different mix from each other today.
  const today = new Date().toISOString().slice(0, 10);
  const shuffled = rotationSeed ? seededShuffle(rest, `${rotationSeed}:${today}`) : rest;

  return [...featured, ...shuffled];
}

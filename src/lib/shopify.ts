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
  video: 'ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation',
  freelance: 'ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation',
  runway: 'ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation',
  kling: 'ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation',
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
    price: '$15.40',
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
    price: '$8.40',
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
    price: '$9.80',
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
    price: '$22.40',
    description: 'Multi-agent AI systems are rewriting how work gets done. This pack gives non-coders a plug-and-play toolkit to build and deploy them.',
    image: 'https://cdn.shopify.com/s/files/1/1009/9716/9431/files/cover_product5.jpg',
  },
  {
    id: 'gid://shopify/Product/10377882206487',
    title: 'AI Agent Automation Pipeline Pack',
    status: 'ACTIVE',
    vendor: 'Astro Tobby',
    productType: 'Digital Download',
    totalVariants: 1,
    totalInventory: 0,
    createdAt: '2026-06-23T05:02:12Z',
    updatedAt: '2026-06-23T17:32:32Z',
    handle: 'ai-agent-automation-pipeline-pack',
    variantId: 'gid://shopify/ProductVariant/53564040282391',
    price: '$13.30',
    description: 'Three production-tested automation blueprints for AI-driven content and commerce pipelines — a zero-budget Blog-to-Video autopilot plus Make.com & n8n flows.',
    image: 'https://cdn.shopify.com/s/files/1/1009/9716/9431/files/InstagramPost-AUTOMATIONPIPELINEPACK.png',
  },
  {
    id: 'gid://shopify/Product/10377883877655',
    title: 'AEO Audit & Optimization Toolkit',
    status: 'ACTIVE',
    vendor: 'Astro Tobby',
    productType: 'Digital Download',
    totalVariants: 1,
    totalInventory: 0,
    createdAt: '2026-06-23T05:02:39Z',
    updatedAt: '2026-06-23T17:33:49Z',
    handle: 'aeo-audit-optimization-toolkit',
    variantId: 'gid://shopify/ProductVariant/53564042019095',
    price: '$10.50',
    description: 'Search is splitting in two — blue links vs. citations inside AI answers (ChatGPT, Gemini, Perplexity, AI Overviews). Audit and optimize for both.',
    image: 'https://cdn.shopify.com/s/files/1/1009/9716/9431/files/InstagramPost-AEOAuditToolkit_1.png',
  },
  {
    id: 'gid://shopify/Product/10377883943191',
    title: 'The Agentic Coding Playbook',
    status: 'ACTIVE',
    vendor: 'Astro Tobby',
    productType: 'Digital Download',
    totalVariants: 1,
    totalInventory: 0,
    createdAt: '2026-06-23T05:02:43Z',
    updatedAt: '2026-06-23T17:33:45Z',
    handle: 'the-agentic-coding-playbook',
    variantId: 'gid://shopify/ProductVariant/53564042084631',
    price: '$11.90',
    description: 'A working decision system for developers using AI coding agents: which agent for which job, and when a multi-agent framework (AutoGen, CrewAI, LangGraph) pays off.',
    image: 'https://cdn.shopify.com/s/files/1/1009/9716/9431/files/InstagramPost-AGENTICCODINGPLAYBOOK.png',
  },
];

export interface ShopifyEnv {
  SHOPIFY_STORE_DOMAIN?: string;
  SHOPIFY_STOREFRONT_API_TOKEN?: string;
}

/**
 * Read Cloudflare runtime vars/secrets. In Astro v6 the old
 * `Astro.locals.runtime.env` was removed — accessing it now THROWS — so we read
 * from the `cloudflare:workers` virtual module instead. Wrapped defensively so it
 * resolves to {} during local dev / prerender (node) where it isn't available.
 */
async function readCloudflareEnv(): Promise<Record<string, string | undefined>> {
  try {
    const mod = await import('cloudflare:workers');
    return (mod.env ?? {}) as unknown as Record<string, string | undefined>;
  } catch {
    return {};
  }
}

export async function fetchShopifyProducts(envOverride?: ShopifyEnv): Promise<ShopifyProduct[]> {
  // Precedence: explicit override -> Cloudflare runtime env (dashboard var/secret)
  // -> build-time env (local dev) -> baked-in public token (final guarantee).
  const cfEnv = await readCloudflareEnv();
  const buildEnv = import.meta.env as unknown as Record<string, string | undefined>;
  const domain: string =
    envOverride?.SHOPIFY_STORE_DOMAIN ??
    cfEnv.SHOPIFY_STORE_DOMAIN ??
    buildEnv.SHOPIFY_STORE_DOMAIN ??
    'chainztobby.myshopify.com';
  const token: string | undefined =
    envOverride?.SHOPIFY_STOREFRONT_API_TOKEN ??
    cfEnv.SHOPIFY_STOREFRONT_API_TOKEN ??
    buildEnv.SHOPIFY_STOREFRONT_API_TOKEN ??
    // Public Storefront access token (read-only, server-side, safe to ship). The
    // runtime env above takes precedence; this baked-in default guarantees the blog
    // reads live data even when no Cloudflare env var is set. To retire it: set
    // SHOPIFY_STOREFRONT_API_TOKEN in the Cloudflare dashboard, rotate this token in
    // Shopify, then delete this line.
    '27429cf8e2f2e9e6a191721481de15a4';

  if (!token) throw new Error('Missing SHOPIFY_STOREFRONT_API_TOKEN');

  const query = `{
    products(first: 50, query: "available_for_sale:true") {
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

// API endpoint to fetch Shopify products
// This endpoint can be called from the frontend to get live product data

import type { APIRoute } from 'astro';

// Mock data - in production, this would call the actual Shopify MCP connector
const SHOPIFY_PRODUCTS = [
  {
    id: "gid://shopify/Product/10365512286487",
    title: "The AI Video Freelancer Toolkit 2026 — Land Clients, Deliver AI Videos, Get Paid",
    status: "ACTIVE",
    vendor: "Astro Tobby",
    productType: "Digital Download",
    totalVariants: 1,
    totalInventory: 0,
    createdAt: "2026-06-09T09:05:47Z",
    updatedAt: "2026-06-09T21:34:21Z",
    handle: "ai-video-freelancer-toolkit-2026",
    variantId: "53517875675415",
    price: "$29.00",
    description: "Master AI video creation and land high-paying clients with this comprehensive toolkit."
  },
  {
    id: "gid://shopify/Product/10365578838295",
    title: "Make.com Autoblogging Blueprint 2026 — Build a Full AI Content Pipeline",
    status: "ACTIVE",
    vendor: "Astro Tobby",
    productType: "Digital Download",
    totalVariants: 1,
    totalInventory: 0,
    createdAt: "2026-06-09T10:22:51Z",
    updatedAt: "2026-06-10T03:58:42Z",
    handle: "make-com-autoblogging-blueprint-2026-build-a-full-ai-content-pipeline",
    variantId: "53518038434071",
    price: "$27.00",
    description: "Build an automated content creation pipeline using Make.com and AI."
  },
  {
    id: "gid://shopify/Product/10365579297047",
    title: "AI Prompt Vault 2026 — 500+ Categorized Prompts for Video, Content, Code & Automation",
    status: "ACTIVE",
    vendor: "Astro Tobby",
    productType: "Digital Download",
    totalVariants: 1,
    totalInventory: 0,
    createdAt: "2026-06-09T10:23:15Z",
    updatedAt: "2026-06-10T03:58:43Z",
    handle: "ai-prompt-vault-2026-500-categorized-prompts-for-video-content-code-automation",
    variantId: "53518038892823",
    price: "$17.00",
    description: "Access 500+ expertly crafted prompts for AI video, content creation, coding, and automation."
  },
  {
    id: "gid://shopify/Product/10365579821335",
    title: "AEO Masterguide 2026 — Rank in AI Search (ChatGPT, Perplexity, Google AI Overviews)",
    status: "ACTIVE",
    vendor: "Astro Tobby",
    productType: "Digital Download",
    totalVariants: 1,
    totalInventory: 0,
    createdAt: "2026-06-09T10:23:38Z",
    updatedAt: "2026-06-10T03:58:43Z",
    handle: "aeo-masterguide-2026-rank-in-ai-search-chatgpt-perplexity-google-ai-overviews",
    variantId: "53518039417111",
    price: "$19.00",
    description: "Learn Answer Engine Optimization to rank your content in AI search engines."
  },
  {
    id: "gid://shopify/Product/10365580312855",
    title: "Agentic AI Workflow Pack 2026 — Build & Deploy Multi-Agent Systems Without Code",
    status: "ACTIVE",
    vendor: "Astro Tobby",
    productType: "Digital Download",
    totalVariants: 1,
    totalInventory: 0,
    createdAt: "2026-06-09T10:23:59Z",
    updatedAt: "2026-06-10T03:58:43Z",
    handle: "agentic-ai-workflow-pack-2026-build-amp-deploy-multi-agent-systems-without-code",
    variantId: "53518039908631",
    price: "$37.00",
    description: "Build and deploy multi-agent AI systems without writing any code."
  }
];

export const GET: APIRoute = async ({ request }) => {
  try {
    // In production, you would:
    // 1. Call the Shopify MCP connector via your backend
    // 2. Fetch live product data from Shopify Admin API
    // 3. Cache the results for performance
    
    // For now, return the mock data
    return new Response(
      JSON.stringify({
        success: true,
        data: SHOPIFY_PRODUCTS,
        timestamp: new Date().toISOString()
      }),
      {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'Cache-Control': 'public, max-age=3600' // Cache for 1 hour
        }
      }
    );
  } catch (error) {
    console.error('Error fetching Shopify products:', error);
    return new Response(
      JSON.stringify({
        success: false,
        error: 'Failed to fetch products'
      }),
      {
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      }
    );
  }
};

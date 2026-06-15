'''
interface Env {
  SHOPIFY_KV: KVNamespace;
  PRODUCT_IDS: string;
  DEFAULT_PRODUCT_ID: string;
}

const KENYA_PRIORITY_PRODUCT = "product-ke-001";
const INTERNATIONAL_PRODUCTS = ["product-int-001", "product-int-002", "product-int-003"];

// Helper to get a random product ID based on geo-location
function getRandomProductId(country: string, productIds: string[]): string {
  let availableProducts = [...productIds];

  if (["KE", "TZ", "UG", "RW"].includes(country)) {
    // Prioritize Kenya product if available
    if (productIds.includes(KENYA_PRIORITY_PRODUCT)) {
      return KENYA_PRIORITY_PRODUCT;
    }
  }

  // Fallback to international products if no specific geo-product or if geo-product not in list
  if (availableProducts.length === 0) {
    availableProducts = INTERNATIONAL_PRODUCTS; // Use a default set if PRODUCT_IDS is empty
  }

  const randomIndex = Math.floor(Math.random() * availableProducts.length);
  return availableProducts[randomIndex];
}

// HTMLRewriter handler to replace product IDs
class ProductIdRewriter {
  selectedProductId: string;
  defaultProductId: string;

  constructor(selectedProductId: string, defaultProductId: string) {
    this.selectedProductId = selectedProductId;
    this.defaultProductId = defaultProductId;
  }

  element(element: Element) {
    // Target the buy button link and modify its href
    if (element.tagName === "a" && element.getAttribute("class") === "product-btn") {
      const currentHref = element.getAttribute("href");
      if (currentHref) {
        // Assuming the variantId is the last part of the path in the href
        const newHref = currentHref.replace(/variant\/\d+/, `variant/${this.selectedProductId.split("/").pop()}`);
        element.setAttribute("href", newHref);
      }
    }
    // Target the product card and modify its data-product-id (if it existed, or add it)
    if (element.tagName === "div" && element.getAttribute("class") === "product-card") {
      element.setAttribute("data-product-id", this.selectedProductId);
    }
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // Handle analytics endpoint
    if (url.pathname === "/analytics") {
      const analyticsKeyPrefix = "analytics:";
      const list = await env.SHOPIFY_KV.list({ prefix: analyticsKeyPrefix });
      const analyticsData: { [key: string]: any } = {};

      for (const key of list.keys) {
        const value = await env.SHOPIFY_KV.get(key.name, "json");
        if (value) {
          analyticsData[key.name] = value;
        }
      }
      return new Response(JSON.stringify(analyticsData), { headers: { "Content-Type": "application/json" } });
    }

    // Fetch the original HTML response from Astro Pages
    const response = await fetch(request);
    let html = await response.text();

    const country = request.headers.get("cf-ipcountry") || "US";
    const productIds = env.PRODUCT_IDS ? env.PRODUCT_IDS.split(",") : [];
    const defaultProductId = env.DEFAULT_PRODUCT_ID || KENYA_PRIORITY_PRODUCT; // Fallback if not set

    let selectedProductId: string;
    let sessionKey: string | null = null;

    try {
      // Generate a simple hash for the visitor session (e.g., based on IP and User-Agent)
      const visitorHash = btoa(country + request.headers.get("User-Agent") || "").substring(0, 32); // Simple hash
      sessionKey = `session:${visitorHash}`;

      const storedSession = await env.SHOPIFY_KV.get(sessionKey, "json");

      if (storedSession && storedSession.product_id && (Date.now() - new Date(storedSession.selected_at).getTime() < 24 * 60 * 60 * 1000)) {
        selectedProductId = storedSession.product_id;
      } else {
        selectedProductId = getRandomProductId(country, productIds);
        // Store for 24 hours
        await env.SHOPIFY_KV.put(sessionKey, JSON.stringify({ product_id: selectedProductId, selected_at: new Date().toISOString() }), { expirationTtl: 86400 });
      }
    } catch (kvError) {
      console.error("KV operation failed, falling back to random selection:", kvError);
      selectedProductId = getRandomProductId(country, productIds);
      // If KV fails, we don't store anything, so session consistency is lost for this request
    }

    // Fallback if selectedProductId is empty or invalid
    if (!selectedProductId || !productIds.includes(selectedProductId)) {
      selectedProductId = defaultProductId;
    }

    // Log product clicks (this would typically be triggered by a client-side event, but for demonstration, we'll log on page load)
    // A more robust solution would involve a separate endpoint for click tracking.
    // For now, let's assume a click happens on page load for analytics purposes.
    // The actual click tracking will be handled by the client-side script that triggers a separate worker endpoint.
    // For now, we will add a simple logging mechanism that increments a counter in KV for each product shown.
    ctx.waitUntil(async () => {
      const today = new Date().toISOString().split("T")[0];
      const analyticsKey = `analytics:${today}:${selectedProductId}`;
      try {
        const currentAnalytics = await env.SHOPIFY_KV.get(analyticsKey, "json") || { click_count: 0, last_updated: new Date().toISOString() };
        currentAnalytics.click_count++;
        currentAnalytics.last_updated = new Date().toISOString();
        await env.SHOPIFY_KV.put(analyticsKey, JSON.stringify(currentAnalytics), { expirationTtl: 2592000 }); // 30 days
      } catch (analyticsError) {
        console.error("Failed to log analytics to KV:", analyticsError);
      }
    });

    // Apply HTML rewriter
    const rewriter = new HTMLRewriter()
      .on("a.product-btn", new ProductIdRewriter(selectedProductId, defaultProductId))
      .on("div.product-card", new ProductIdRewriter(selectedProductId, defaultProductId));

    return rewriter.transform(new Response(html, response));
  },
};
'''

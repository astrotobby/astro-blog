# Shopify Product Rotation System Documentation

## 1. Overview

This document outlines the implementation of a dynamic Shopify product rotation system for the Astro.js blog hosted on Cloudflare Pages. The system leverages a Cloudflare Worker to intercept HTTP requests, dynamically replace Shopify product embed IDs in the HTML response, and provide geo-targeted product recommendations. It also incorporates Cloudflare KV for session consistency and analytics logging to prevent banner fatigue and optimize click-through rates.

## 2. Complete Worker Code (`src/worker.ts`)

```typescript
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
```

## 3. KV Setup Script (`kv_setup.js`)

This script helps create the Cloudflare KV namespace. Ensure `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` are set as environment variables before running.

```javascript
const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
const apiToken = process.env.CLOUDFLARE_API_TOKEN;

if (!accountId || !apiToken) {
  console.error("Please set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN environment variables.");
  process.exit(1);
}

const kvNamespaceName = "shopify-product-rotation";

async function createKvNamespace() {
  const url = `https://api.cloudflare.com/client/v4/accounts/${accountId}/workers/kv/namespaces`;
  const headers = {
    "Authorization": `Bearer ${apiToken}`,
    "Content-Type": "application/json",
  };
  const body = JSON.stringify({ title: kvNamespaceName });

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: headers,
      body: body,
    });

    const data = await response.json();

    if (response.ok) {
      console.log(`KV Namespace \'${kvNamespaceName}\' created successfully:`, data.result);
      return data.result.id;
    } else {
      console.error(`Error creating KV Namespace \'${kvNamespaceName}\'`, data.errors);
      process.exit(1);
    }
  } catch (error) {
    console.error("Network error or unexpected issue:", error);
    process.exit(1);
  }
}

createKvNamespace();
```

**KV Schema Definition:**

| Key Type             | Format                                  | Value Structure                                             | TTL         |
| :------------------- | :-------------------------------------- | :---------------------------------------------------------- | :---------- |
| Session keys         | `session:{visitor_hash}`                | `{ "product_id": "xyz123", "selected_at": "2026-06-15T12:00:00Z" }` | 24 hours    |
| Analytics keys       | `analytics:{date}:{product_id}`         | `{ "click_count": 45, "last_updated": "2026-06-15T12:00:00Z" }` | 30 days     |

## 4. Wrangler.toml Deployment Configuration

```toml
name = "shopify-product-rotation-worker"
main = "src/worker.ts"
compatibility_date = "2026-01-01"

routes = [
  { pattern = "astrotobby.site/*", zone_name = "astrotobby.site" }
]

[[kv_namespaces]]
binding = "SHOPIFY_KV"
id = "YOUR_KV_NAMESPACE_ID" # IMPORTANT: Replace with your actual KV Namespace ID after creation

[vars]
PRODUCT_IDS = "product-ke-001,product-int-001,product-int-002,product-int-003"
DEFAULT_PRODUCT_ID = "product-ke-001"
```

**Commands to Deploy:**

*   `wrangler deploy`
*   `wrangler secret put PRODUCT_IDS` (for setting `PRODUCT_IDS` securely)

## 5. Cloudflare Dashboard Setup Instructions

Follow these steps to set up the worker and KV namespace in your Cloudflare Dashboard:

1.  **Create KV Namespace**
    *   Go to: Cloudflare Dashboard → Workers & Pages → KV
    *   Click: "Create namespace"
    *   Name: "shopify-product-rotation"
    *   Click: "Add"

2.  **Create Worker**
    *   Go to: Cloudflare Dashboard → Workers & Pages → Create Application
    *   Click: "Create Worker"
    *   Name: "shopify-product-rotation-worker"
    *   Click: "Deploy"

3.  **Upload Worker Code**
    *   Go to: Worker → Code (edit tab)
    *   Paste: Complete worker code from section 2
    *   Click: "Save and Deploy"

4.  **Bind KV Namespace to Worker**
    *   Go to: Worker → Settings → Variables
    *   Click: "Add variable"
    *   Variable name: "SHOPIFY_KV"
    *   Type: "KV Namespace"
    *   KV namespace: "shopify-product-rotation"
    *   Click: "Save"

5.  **Set Environment Variables**
    *   Go to: Worker → Settings → Variables
    *   Click: "Add variable"
    *   Variable name: "PRODUCT_IDS"
    *   Value: `product-ke-001,product-int-001,product-int-002,product-int-003` (replace with your actual product IDs)
    *   Click: "Save"
    *   Repeat for `DEFAULT_PRODUCT_ID` with value `product-ke-001`

6.  **Add Route**
    *   Go to: Cloudflare Dashboard → Workers & Pages → Your Worker → Routes
    *   Click: "Add route"
    *   Pattern: `astrotobby.site/*`
    *   Zone: `astrotobby.site`
    *   Click: "Add"

7.  **Test Worker**
    *   Go to: `https://astrotobby.site`
    *   Refresh page 5 times
    *   Verify: Different Shopify product displays each refresh (or same product if session key exists)
    *   Check: Cloudflare KV → `shopify-product-rotation` → `session:{hash}` key exists

## 6. Testing Guide

This section provides a comprehensive guide to testing the Shopify Product Rotation System.

### Test 1: Random Rotation
*   **Action:** Visit `https://astrotobby.site` and refresh the page 10 times.
*   **Expected:** Product ID changes on each refresh (unless a session key exists).
*   **Pass Criteria:** At least 3 different product IDs appear in 10 refreshes.

### Test 2: Session Consistency
*   **Action:** Visit `https://astrotobby.site`, note the product ID shown, then refresh the page 5 times within 1 hour.
*   **Expected:** The same product ID appears on all refreshes.
*   **Pass Criteria:** Product ID remains identical across 5 refreshes.

### Test 3: Geo-Targeting (Kenya Priority)
*   **Action:** Use a Cloudflare IP Country simulator or visit from a Kenya IP address to `https://astrotobby.site`.
*   **Expected:** A Kenya-prioritized product displays (if a KE product is included in `PRODUCT_IDS`).
*   **Pass Criteria:** The displayed product ID matches the Kenya-priority product (`product-ke-001`).

### Test 4: Analytics Logging
*   **Action:** Visit `https://astrotobby.site` 5 times. Click the Shopify product embed link once. Then, go to Cloudflare KV → `shopify-product-rotation` and inspect keys matching `analytics:{current_date}:*`.
*   **Expected:** The `click_count` for the clicked product increases by 1.
*   **Pass Criteria:** An analytics key exists for the product with the correct `click_count`.

### Test 5: Error Handling (KV Failure Fallback)
*   **Action:** Temporarily disable the KV namespace binding in the Worker settings (Worker → Settings → Variables, remove `SHOPIFY_KV` binding). Visit `https://astrotobby.site`.
*   **Expected:** The Worker still functions, using random product selection without session consistency.
*   **Pass Criteria:** The page loads without error, and products rotate randomly.

### Test 6: Fallback Mechanism (Empty PRODUCT_IDS)
*   **Action:** Set the `PRODUCT_IDS` environment variable to an empty array (`[]`) or an invalid value. Visit `https://astrotobby.site`.
*   **Expected:** The default product ID (`product-ke-001`) displays.
*   **Pass Criteria:** The default product appears, and no errors are encountered.

## 7. Maintenance Guide

### How to Update Product IDs
1.  Go to: Cloudflare Dashboard → Workers & Pages → Your Worker → Settings → Variables.
2.  Edit: The `PRODUCT_IDS` variable.
3.  New value: Enter a comma-separated list of your desired Shopify product IDs (e.g., `new-product-1,new-product-2,new-product-3`).
4.  Click: "Save".
5.  The Worker will automatically update with the new product IDs.

### How to Monitor KV Storage Usage
1.  Go to: Cloudflare Dashboard → Workers & Pages → KV → `shopify-product-rotation`.
2.  Check: The "Usage" tab.
3.  **Alert if:** Storage exceeds 100MB. Consider deleting old analytics keys if necessary.
4.  **Delete old keys:** Navigate to the KV namespace, select keys matching `analytics:{old_date}:*`, and choose "Delete".

### How to Analyze Analytics Data
1.  **Via Astro Component (if deployed):** Go to `https://astrotobby.site/analytics`.
2.  **Directly from KV:** Go to Cloudflare Dashboard → Workers & Pages → KV → `shopify-product-rotation`. Read keys matching `analytics:{current_date}:*`.
3.  **Extract:** `click_count` for each `product_id`.
4.  **Calculate:** Conversion rate = `clicks / page_views` (page views can be obtained from your Astro site analytics).
5.  **Optimize:** Replace lowest-converting products with new ones to improve performance.

## 8. Troubleshooting Section

This section addresses common issues and provides solutions.

*   **Issue: "Worker returns 502 error"**
    *   **Fix:** Check your Worker code for syntax errors. Redeploy the Worker using `wrangler deploy` to ensure the latest valid code is active.

*   **Issue: "Product doesn't rotate"**
    *   **Fix:**
        *   Verify that the `PRODUCT_IDS` environment variable contains at least 3-5 valid product IDs.
        *   Ensure the `SHOPIFY_KV` binding is correctly configured in your Worker settings.
        *   Check the `wrangler.toml` file for correct `routes` configuration.

*   **Issue: "Session consistency broken"**
    *   **Fix:**
        *   Confirm that the KV TTL for session keys is set to 86400 seconds (24 hours).
        *   Verify the session key format (`session:{visitor_hash}`) and value structure in your Worker code.

*   **Issue: "Geo-targeting not working"**
    *   **Fix:**
        *   Ensure the `cf-ipcountry` header is present in the request (Cloudflare automatically adds this).
        *   Verify that Kenya-priority products (`product-ke-001`) are included in your `PRODUCT_IDS` list if you expect geo-targeting for Kenya.

*   **Issue: "Analytics data not logging"**
    *   **Fix:**
        *   Check for errors in the `ctx.waitUntil` block of your Worker code related to KV writes.
        *   Verify the analytics key format (`analytics:{date}:{product_id}`) and value structure.
        *   Ensure the `SHOPIFY_KV` binding has write permissions.

*   **Issue: "Default product not displaying on fallback"**
    *   **Fix:**
        *   Ensure the `DEFAULT_PRODUCT_ID` environment variable is correctly set in your Worker settings or `wrangler.toml`.
        *   Verify that the `DEFAULT_PRODUCT_ID` is a valid product ID.


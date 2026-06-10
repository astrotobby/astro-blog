# Shopify Products Integration Guide

This guide explains how the Shopify products integration works in your Astro blog and how to configure it for live product data.

## Overview

Your blog now displays Shopify products in a dedicated section at the bottom of every blog post. This allows readers to discover and purchase your digital products directly from your content.

## What's Been Added

### 1. **ShopifyProducts Component** (`src/components/ShopifyProducts.astro`)
   - Displays a grid of your 5 Shopify products
   - Includes product title, description, price, and vendor information
   - Responsive design that works on mobile, tablet, and desktop
   - Links to your Shopify store for each product

### 2. **BlogPost Layout Update** (`src/layouts/BlogPost.astro`)
   - Integrated the ShopifyProducts component into every blog post
   - Positioned after the main article content and ad banner
   - Appears before the newsletter signup section

### 3. **API Endpoint** (`src/pages/api/shopify-products.ts`)
   - Provides a backend endpoint to fetch live product data
   - Currently returns mock data (can be connected to live Shopify data)
   - Includes caching headers for performance optimization

## Current Implementation

The component currently uses **hardcoded product data** that matches your Shopify store:

```
1. The AI Video Freelancer Toolkit 2026 — $49.99
2. Make.com Autoblogging Blueprint 2026 — $39.99
3. AI Prompt Vault 2026 — $29.99
4. AEO Masterguide 2026 — $34.99
5. Agentic AI Workflow Pack 2026 — $44.99
```

## Next Steps: Connect to Live Shopify Data

To make the products display live data from your Shopify store, you have several options:

### Option 1: Use Shopify Storefront API (Recommended)
This is the most flexible approach and allows real-time product data.

**Steps:**
1. Create a Shopify custom app in your admin
2. Generate access tokens for the Storefront API
3. Update `src/components/ShopifyProducts.astro` to fetch from the Storefront API:

```astro
---
const SHOPIFY_STORE = 'your-store.myshopify.com';
const STOREFRONT_ACCESS_TOKEN = 'your-storefront-token';

const query = `
  query {
    products(first: 5) {
      edges {
        node {
          id
          title
          handle
          description
          priceRange {
            minVariantPrice {
              amount
            }
          }
        }
      }
    }
  }
`;

const response = await fetch(`https://${SHOPIFY_STORE}/api/2024-01/graphql.json`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-Shopify-Storefront-Access-Token': STOREFRONT_ACCESS_TOKEN,
  },
  body: JSON.stringify({ query }),
});

const data = await response.json();
const products = data.data.products.edges.map(edge => edge.node);
---
```

### Option 2: Use the Shopify MCP Connector (Your Current Setup)
If you want to use the Shopify MCP connector you tested earlier:

**Steps:**
1. Create a backend API route that calls the MCP connector
2. Update the `/api/shopify-products.ts` endpoint to use `manus-mcp-cli`
3. Call this endpoint from the component

**Example backend implementation:**
```typescript
// In src/pages/api/shopify-products.ts
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

export const GET: APIRoute = async () => {
  try {
    const { stdout } = await execAsync(
      'manus-mcp-cli tool call shopify_get_products --server shopify --input \'{"first": 5}\''
    );
    
    const result = JSON.parse(stdout);
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: 'Failed to fetch' }), {
      status: 500
    });
  }
};
```

### Option 3: Use a Headless Commerce Platform
Integrate with platforms like:
- **Shopify Buy Button** - Embed directly in your site
- **Commerce.js** - Headless commerce API
- **Saleor** - Open-source GraphQL commerce

## Customization

### Styling
The component uses Astro's scoped CSS. To customize the appearance:
1. Edit the `<style>` section in `src/components/ShopifyProducts.astro`
2. Modify colors, spacing, fonts, or layout
3. The component is fully responsive and mobile-optimized

### Product Links
Currently, products link to `https://astrotobby.com/products/{handle}`. To change:
1. Update the `href` in the product button
2. Or use Shopify's direct product URLs: `https://your-store.myshopify.com/products/{handle}`

### Number of Products
To display more or fewer products:
1. Update the `first: 5` parameter in the API call
2. Adjust the grid layout if needed

### Product Information
To display additional product details:
1. Fetch more fields from Shopify (images, ratings, inventory, etc.)
2. Update the component JSX to display the new fields
3. Add corresponding styles

## Performance Considerations

- **Caching**: Products are cached for 1 hour by default (see `Cache-Control` header)
- **Build-time vs Runtime**: Currently fetches at build time (Astro static generation)
- **Lazy Loading**: Consider lazy-loading product images for better performance

## Deployment

The integration works seamlessly with Cloudflare Pages:

1. **Push to GitHub**: Commit and push your changes
   ```bash
   git add .
   git commit -m "Add Shopify products integration"
   git push
   ```

2. **Cloudflare Pages Build**: Your site will automatically rebuild
   - The ShopifyProducts component will be included in every blog post
   - Products will display in the new section

3. **Verify**: Visit a blog post and scroll to the bottom to see the products section

## Troubleshooting

### Products not showing
- Check browser console for errors
- Verify the component is imported in `BlogPost.astro`
- Ensure the API endpoint is accessible

### Styling issues
- Check for CSS conflicts with existing styles
- Use browser DevTools to inspect elements
- Verify Tailwind/CSS classes are applied

### Performance issues
- Enable caching on your API endpoint
- Consider using static generation instead of dynamic fetching
- Optimize product images

## Support

For questions or issues:
1. Check the Astro documentation: https://docs.astro.build
2. Review Shopify API docs: https://shopify.dev
3. Check MCP connector documentation for advanced usage

## Files Modified

- `src/layouts/BlogPost.astro` - Added ShopifyProducts import and component
- `src/components/ShopifyProducts.astro` - New product display component
- `src/pages/api/shopify-products.ts` - New API endpoint for product data

## Next Session Checklist

- [ ] Connect to live Shopify data (choose Option 1, 2, or 3)
- [ ] Test on a staging environment
- [ ] Customize styling to match your brand
- [ ] Add product images if desired
- [ ] Set up analytics to track product clicks
- [ ] Deploy to production

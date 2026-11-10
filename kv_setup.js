
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
      console.log(`KV Namespace '${kvNamespaceName}' created successfully:`, data.result);
      return data.result.id;
    } else {
      console.error(`Error creating KV Namespace '${kvNamespaceName}':`, data.errors);
      process.exit(1);
    }
  } catch (error) {
    console.error("Network error or unexpected issue:", error);
    process.exit(1);
  }
}

createKvNamespace();

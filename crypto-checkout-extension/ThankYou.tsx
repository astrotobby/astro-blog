import {
  reactExtension,
  useApi,
  Banner,
  BlockStack,
  Button,
  Text,
} from '@shopify/ui-extensions-react/checkout';
import { useEffect, useState } from 'react';

// Renders on the Shopify "Thank you" page. Pulls the NOWPayments pay-link for
// this order from the Worker and shows a "Pay with crypto" button, so the buyer
// can pay immediately without relying on email.
export default reactExtension('purchase.thank-you.block.render', () => <CryptoPayLink />);

const GET_LINK_URL = 'https://astrotobby.site/api/crypto/get-link';

function CryptoPayLink() {
  // On the Thank you page the order id is available via orderConfirmation even
  // though the order may still be finalizing. Access defensively across versions.
  const api = useApi() as unknown as {
    orderConfirmation?: { current?: { order?: { id?: string } } };
  };
  const orderId = api.orderConfirmation?.current?.order?.id;

  const [url, setUrl] = useState<string | null>(null);
  const [tries, setTries] = useState(0);

  useEffect(() => {
    // Retry up to ~1 minute: the invoice may not exist the instant the page loads
    // (the order is still being created / the webhook is in flight).
    if (!orderId || url || tries > 20) return;
    let cancelled = false;
    const delay = tries === 0 ? 0 : 3000;
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`${GET_LINK_URL}?orderId=${encodeURIComponent(orderId)}`);
        const data = (await res.json()) as { ok?: boolean; invoiceUrl?: string };
        if (cancelled) return;
        if (data.ok && data.invoiceUrl) setUrl(data.invoiceUrl);
        else setTries((n) => n + 1);
      } catch {
        if (!cancelled) setTries((n) => n + 1);
      }
    }, delay);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [orderId, url, tries]);

  if (!url) return null;

  return (
    <Banner status="info" title="Complete your crypto payment">
      <BlockStack spacing="base">
        <Text>
          Pay with Bitcoin, USDT, ETH or 300+ coins. Your download is delivered automatically
          once the payment is confirmed on-chain (usually a few minutes).
        </Text>
        <Button to={url}>Pay with crypto</Button>
      </BlockStack>
    </Banner>
  );
}

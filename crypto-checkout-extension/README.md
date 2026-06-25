# Crypto Pay Link — Checkout UI Extension

Shows a **"Pay with crypto"** button on the Shopify **Thank you** page. It reads
the order id, calls `https://astrotobby.site/api/crypto/get-link?orderId=…`, and
renders the NOWPayments pay-link button — so buyers can pay on-page instead of
relying on the email.

The backend (`/api/crypto/get-link`) is already deployed in this repo. These
files are the front-end extension, which must be deployed through a Shopify app
using the Shopify CLI (extensions can't be a code snippet).

## Prerequisites
- Node 18+ and the Shopify CLI: `npm i -g @shopify/cli@latest`
- A Shopify app to host it — use your existing dev-dashboard app (e.g. "CRYPO
  PAYMENTS") or create a new one with `shopify app init`.

## Deploy steps
1. **Get an app project locally**
   - Existing app: `shopify app config link` (pick your app)
   - or new: `shopify app init` then `cd` into it
2. **Scaffold the extension**
   ```
   shopify app generate extension --template checkout_ui --name crypto-pay-link
   ```
3. **Drop in these files** (under `extensions/crypto-pay-link/`)
   - Copy `ThankYou.tsx` → `src/ThankYou.tsx` (delete the generated `Checkout.*`)
   - Replace `shopify.extension.toml` with `shopify.extension.toml.example`
     (rename to `shopify.extension.toml`; keep the scaffold's `api_version` if newer)
4. **Test live**
   ```
   shopify app dev
   ```
   Open the preview store, place a test order with "pay in crypto with NOWPayments",
   and confirm the button appears on the Thank you page. (The CLI console shows any
   API errors — if the order-id access needs a tweak for your CLI version, fix it here.)
5. **Ship it**
   ```
   shopify app deploy
   ```
6. **Place the block**: Shopify admin → **Settings → Checkout → Customize** → pick
   **Thank you** from the page dropdown → **Add app block** → **Crypto Pay Link** → Save.

## Notes
- The button only renders for **pending crypto orders** — `get-link` returns
  nothing for paid/non-crypto orders, so the extension hides itself.
- The Thank you page may still be finalizing the order on first load; the
  extension retries every 3s (up to ~1 min) until the link is ready.
- To also show it on the **Order status** page (revisits), add a second target
  `customer-account.order-status.block.render` with a component built from
  `@shopify/ui-extensions-react/customer-account` (different package, same fetch).

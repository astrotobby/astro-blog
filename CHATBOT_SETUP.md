# Chatbot Setup & Deployment Guide

## Overview

The site-wide **Tobby's Assistant** widget is rendered by `src/components/Footer.astro` and implemented in `src/components/ChatWidget.astro`. Replies stream from `src/pages/api/chat.ts` using Cloudflare Workers AI. Optional sponsored suggestions are served by `src/pages/api/chat-ad.ts` through `@idlen/chat-sdk`.

## Data and privacy behavior

- The widget stores up to 20 recent user/assistant messages in the visitor's browser `localStorage`. The **Clear** button clears that local chat history.
- User messages are sent to the site's `/api/chat` endpoint and processed by Cloudflare Workers AI to generate replies.
- The widget requests an Idlen sponsored suggestion after chatbot replies; there is no visitor toggle.
- For each request, the browser classifies only the latest question into one of four broad categories. The site sends that category and a random browser-session ID to `/api/chat-ad`; it does not send the question text or assistant reply to Idlen.
- The publisher API key is read only by the server route. Never place it in frontend code or commit it to the repository.
- The ad endpoint applies best-effort, in-memory request limits using the session ID and Cloudflare-provided client IP. Worker memory is isolate-local, so this is not a substitute for Cloudflare's managed rate-limiting rules for a high-traffic or abuse-sensitive deployment.

## Configure Idlen

1. Create a publisher API key in [Idlen Ads Manager](https://adsmanager.idlen.io/publisher/api-keys).
2. For local development, add the key to the ignored `.dev.vars` file:

   ```dotenv
   IDLEN_API_KEY=idl_pk_your_key_here
   ```

3. For production, configure the secret and deploy:

   ```bash
   npx wrangler secret put IDLEN_API_KEY
   npm run deploy
   ```

Without the key, chat replies continue to work and the ad endpoint returns no ad. Check publisher analytics in Idlen Ads Manager to confirm impressions and clicks after deployment.

## Development and deployment

Install dependencies with `npm ci`. Use `npm run dev` for the Astro development server. Use `npm run preview` to build and run the Cloudflare Worker locally when testing Cloudflare bindings. The deployed Worker requires the `AI` binding configured in `wrangler.jsonc` and Cloudflare Workers AI enabled for the account.

Deploy with `npm run deploy`. After deployment, test ordinary chat replies and confirm the ad endpoint is requested after each reply. An ad may not be returned if Idlen has no suitable campaign, the API key is missing, or the endpoint is rate-limited.

## Relevant files

- `src/components/ChatWidget.astro` — widget UI, local history, sponsored-ad disclosure, topic classification, and ad rendering.
- `src/components/Footer.astro` — mounts the widget site-wide.
- `src/pages/api/chat.ts` — streams replies from Cloudflare Workers AI.
- `src/pages/api/chat-ad.ts` — validates ad requests, calls Idlen, and reports clicks.
- `src/pages/privacy-policy.astro` — public disclosures about chatbot and ad data handling.
- `.env.example` — example environment variables; do not put real secrets in this file.

## Troubleshooting

**Chat replies fail:** confirm the Cloudflare `AI` binding is enabled and check Worker logs and the browser console.

**No sponsored ad appears:** confirm `IDLEN_API_KEY` is configured as a Worker secret and the response is not rate-limited. Idlen may also return no suitable ad for a topic.

**Local key is missing:** verify `.dev.vars` is at the project root and restart the local development process after editing it.

// @ts-ignore
import { env as cfEnv } from 'cloudflare:workers';
import type { APIRoute } from 'astro';
import { IdlenChatAds } from '@idlen/chat-sdk/server';

export const prerender = false;

// Sponsored message for the chat widget, served by Idlen (https://idlen.io).
// The publisher key stays server-side: `wrangler secret put IDLEN_API_KEY`.
//
// POST { action: 'ad', sessionId, text }                  -> { ad } | { ad: null }
// POST { action: 'click', adId, publisherId, requestId }  -> 204
//
// Idlen counts an impression when getAd() returns an ad, so the widget only
// calls this right before it renders the ad under a reply.

let client: IdlenChatAds | null = null;
const recentRequests = new Map<string, number>();
const REQUEST_COOLDOWN_MS = 4_000;

function getClient(): IdlenChatAds | null {
  const apiKey = (cfEnv as any).IDLEN_API_KEY as string | undefined;
  if (!apiKey) return null;
  if (!client) client = new IdlenChatAds({ apiKey });
  return client;
}

export const POST: APIRoute = async ({ request }) => {
  let body: any;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'Invalid request body' }, 400);
  }

  const ads = getClient();
  if (!ads) {
    console.error('[chat-ad] Missing IDLEN_API_KEY');
    return json({ ad: null });
  }

  try {
    if (body.action === 'click') {
      const { adId, publisherId, requestId } = body;
      if (typeof adId !== 'string' || typeof publisherId !== 'string' || typeof requestId !== 'string') {
        return json({ error: 'Missing click fields' }, 400);
      }
      await ads.trackClick(adId, publisherId, requestId);
      return new Response(null, { status: 204 });
    }

    const sessionId = String(body.sessionId || '').slice(0, 100);
    const text = String(body.text || '').slice(0, 2000);
    if (!sessionId || !text) return json({ error: 'Missing sessionId or text' }, 400);

    const now = Date.now();
    const previous = recentRequests.get(sessionId);
    if (previous && now - previous < REQUEST_COOLDOWN_MS) return json({ ad: null });
    recentRequests.set(sessionId, now);
    if (recentRequests.size > 2_000) {
      for (const [key, timestamp] of recentRequests) {
        if (now - timestamp > REQUEST_COOLDOWN_MS * 10) recentRequests.delete(key);
      }
    }

    const ad = await ads.getAd({ sessionId, rawText: text });
    if (!ad) return json({ ad: null });

    return json({
      ad: {
        adId: ad.adId,
        publisherId: ad.publisherId,
        requestId: ad.requestId,
        title: ad.title,
        body: ad.body,
        ctaText: ad.ctaText,
        ctaUrl: ad.ctaUrl,
        advertiserName: ad.advertiserName,
        imageUrl: ad.imageUrl,
      },
    });
  } catch (err) {
    console.error('[chat-ad] Idlen error:', err);
    return json({ ad: null });
  }
};

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

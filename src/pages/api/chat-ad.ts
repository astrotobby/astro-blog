// @ts-ignore
import { env as cfEnv } from 'cloudflare:workers';
import type { APIRoute } from 'astro';
import { IdlenChatAds } from '@idlen/chat-sdk/server';

export const prerender = false;

// The publisher key stays server-side: `wrangler secret put IDLEN_API_KEY`.
// The browser sends only an allowlisted broad topic, never the chat text.
// POST { action: 'ad', sessionId, topic } -> { ad } | { ad: null }
// POST { action: 'click', adId, publisherId, requestId } -> 204

const MAX_BODY_BYTES = 8 * 1024;
const RATE_WINDOW_MS = 60_000;
const SESSION_COOLDOWN_MS = 4_000;
const SESSION_REQUESTS_PER_MINUTE = 15;
const IP_REQUESTS_PER_MINUTE = 120;
const CLICK_REQUESTS_PER_MINUTE = 90;
const TOPIC_CONTEXTS = {
  ai_tools: 'Broad topic: AI tools and assistants.',
  software_development: 'Broad topic: software development.',
  technology: 'Broad topic: technology.',
  general: 'Broad topic: general information.',
} as const;
type AdTopic = keyof typeof TOPIC_CONTEXTS;
type RateWindow = { startedAt: number; lastAt: number; count: number };

let client: IdlenChatAds | null = null;
const rateWindows = new Map<string, RateWindow>();

function getClient(): IdlenChatAds | null {
  const apiKey = (cfEnv as any).IDLEN_API_KEY as string | undefined;
  if (!apiKey) return null;
  if (!client) client = new IdlenChatAds({ apiKey });
  return client;
}

export const POST: APIRoute = async ({ request }) => {
  const origin = request.headers.get('Origin');
  if (origin && origin !== new URL(request.url).origin) return json({ error: 'Invalid origin' }, 403);

  const contentType = request.headers.get('Content-Type') || '';
  if (!contentType.toLowerCase().includes('application/json')) return json({ error: 'Expected application/json' }, 415);

  const declaredLength = Number(request.headers.get('Content-Length') || 0);
  if (declaredLength > MAX_BODY_BYTES) return json({ error: 'Request body too large' }, 413);

  let rawBody: string;
  try {
    rawBody = await request.text();
  } catch {
    return json({ error: 'Invalid request body' }, 400);
  }
  if (new TextEncoder().encode(rawBody).byteLength > MAX_BODY_BYTES) return json({ error: 'Request body too large' }, 413);

  let body: any;
  try {
    body = JSON.parse(rawBody);
  } catch {
    return json({ error: 'Invalid request body' }, 400);
  }
  if (!body || typeof body !== 'object' || Array.isArray(body)) return json({ error: 'Invalid request body' }, 400);

  const ads = getClient();
  if (!ads) {
    console.error('[chat-ad] Missing IDLEN_API_KEY');
    return json({ ad: null });
  }

  try {
    if (body.action === 'click') {
      const { adId, publisherId, requestId } = body;
      if (![adId, publisherId, requestId].every((value) => typeof value === 'string' && value.length > 0 && value.length <= 256)) {
        return json({ error: 'Invalid click fields' }, 400);
      }
      if (isRateLimited(request, undefined, true)) return json({ error: 'Too many requests' }, 429);
      await ads.trackClick(adId, publisherId, requestId);
      return new Response(null, { status: 204, headers: { 'Cache-Control': 'no-store' } });
    }

    if (body.action !== 'ad') return json({ error: 'Unknown action' }, 400);
    const sessionId = typeof body.sessionId === 'string' ? body.sessionId : '';
    const topic = body.topic as AdTopic;
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sessionId)) {
      return json({ error: 'Invalid sessionId' }, 400);
    }
    if (!Object.prototype.hasOwnProperty.call(TOPIC_CONTEXTS, topic)) return json({ error: 'Invalid topic' }, 400);
    if (isRateLimited(request, sessionId, false)) return json({ ad: null }, 429);

    const ad = await ads.getAd({ sessionId, rawText: TOPIC_CONTEXTS[topic] });
    if (!ad || !isHttpsUrl(ad.ctaUrl)) return json({ ad: null });

    return json({
      ad: {
        adId: safeString(ad.adId, 256),
        publisherId: safeString(ad.publisherId, 256),
        requestId: safeString(ad.requestId, 256),
        title: safeString(ad.title, 200),
        body: safeString(ad.body, 500),
        ctaText: safeString(ad.ctaText, 80),
        ctaUrl: ad.ctaUrl,
        advertiserName: safeString(ad.advertiserName, 100),
        imageUrl: isHttpsUrl(ad.imageUrl) ? ad.imageUrl : '',
      },
    });
  } catch (err) {
    console.error('[chat-ad] Idlen error:', err);
    return json({ ad: null });
  }
};

function safeString(value: unknown, maxLength: number): string {
  return typeof value === 'string' ? value.slice(0, maxLength) : '';
}

function isHttpsUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value.length > 2_048) return false;
  try {
    return new URL(value).protocol === 'https:';
  } catch {
    return false;
  }
}

function isRateLimited(request: Request, sessionId: string | undefined, isClick: boolean): boolean {
  const now = Date.now();
  const ip = request.headers.get('CF-Connecting-IP')?.trim().slice(0, 64);
  const checks: Array<{ key: string; limit: number; cooldown: number }> = [];
  if (sessionId) checks.push({ key: `session:${sessionId}`, limit: SESSION_REQUESTS_PER_MINUTE, cooldown: SESSION_COOLDOWN_MS });
  if (ip) checks.push({ key: `ip:${ip}`, limit: isClick ? CLICK_REQUESTS_PER_MINUTE : IP_REQUESTS_PER_MINUTE, cooldown: 0 });

  const limited = checks.some(({ key, limit, cooldown }) => {
    const entry = rateWindows.get(key);
    if (!entry || now - entry.startedAt >= RATE_WINDOW_MS) return false;
    return entry.count >= limit || (cooldown > 0 && now - entry.lastAt < cooldown);
  });
  if (limited) return true;

  for (const { key } of checks) {
    const entry = rateWindows.get(key);
    if (!entry || now - entry.startedAt >= RATE_WINDOW_MS) {
      rateWindows.set(key, { startedAt: now, lastAt: now, count: 1 });
    } else {
      entry.lastAt = now;
      entry.count += 1;
    }
  }

  if (rateWindows.size > 2_000) {
    for (const [key, entry] of rateWindows) {
      if (now - entry.startedAt >= RATE_WINDOW_MS) rateWindows.delete(key);
    }
    while (rateWindows.size > 2_500) rateWindows.delete(rateWindows.keys().next().value!);
  }
  return false;
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

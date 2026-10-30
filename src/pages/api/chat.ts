// @ts-ignore
import { env as cfEnv } from 'cloudflare:workers';
import type { APIRoute } from 'astro';

export const prerender = false;

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

type RateWindow = { startedAt: number; count: number };
const MAX_BODY_BYTES = 64 * 1024;
const MAX_MESSAGES = 20;
const MAX_MESSAGE_LENGTH = 4_000;
const RATE_WINDOW_MS = 60_000;
const MAX_REQUESTS_PER_IP_PER_MINUTE = 30;
const requestWindows = new Map<string, RateWindow>();

const SYSTEM_PROMPT = "You are Tobby's Assistant, a helpful AI on the AstroSignal blog. Help visitors with questions about AI, technology, and the blog content. Keep every reply brief: 2-4 short sentences, plain text, no long step-by-step lists or headings. Be friendly and informative, and offer to go deeper only if asked.";

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

  const messages: Message[] = [];
  if (Array.isArray(body.messages)) {
    if (body.messages.length === 0 || body.messages.length > MAX_MESSAGES) {
      return json({ error: `messages must contain between 1 and ${MAX_MESSAGES} entries` }, 400);
    }
    for (const item of body.messages) {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return json({ error: 'Invalid message' }, 400);
      if (item.role !== 'user' && item.role !== 'assistant') return json({ error: 'Invalid message role' }, 400);
      if (typeof item.content !== 'string' || item.content.length === 0 || item.content.length > MAX_MESSAGE_LENGTH) {
        return json({ error: 'Invalid message content' }, 400);
      }
      messages.push({ role: item.role, content: item.content });
    }
  } else {
    const directContent = body.message ?? body.content;
    if (typeof directContent !== 'string' || directContent.trim().length === 0 || directContent.length > MAX_MESSAGE_LENGTH) {
      return json({ error: 'Invalid message content' }, 400);
    }
    messages.push({ role: 'user', content: directContent });
  }

  if (isRateLimited(request)) return json({ error: 'Too many requests' }, 429);

  try {
    const ai = (cfEnv as any).AI;
    if (!ai) return json({ error: 'Cloudflare AI binding not found.' }, 500);

    const stream = await ai.run('@cf/meta/llama-3.1-8b-instruct-fp8', {
      messages: [{ role: 'system', content: SYSTEM_PROMPT }, ...messages],
      stream: true,
      max_tokens: 400,
    });

    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });
  } catch (err) {
    console.error('Cloudflare AI Streaming Error:', err);
    return json({ error: 'The assistant could not generate a reply.' }, 500);
  }
};

function isRateLimited(request: Request): boolean {
  const ip = request.headers.get('CF-Connecting-IP')?.trim().slice(0, 64);
  if (!ip) return false;

  const now = Date.now();
  const entry = requestWindows.get(ip);
  if (entry && now - entry.startedAt < RATE_WINDOW_MS && entry.count >= MAX_REQUESTS_PER_IP_PER_MINUTE) return true;
  if (!entry || now - entry.startedAt >= RATE_WINDOW_MS) requestWindows.set(ip, { startedAt: now, count: 1 });
  else entry.count += 1;

  if (requestWindows.size > 2_000) {
    for (const [key, window] of requestWindows) {
      if (now - window.startedAt >= RATE_WINDOW_MS) requestWindows.delete(key);
    }
    while (requestWindows.size > 2_500) requestWindows.delete(requestWindows.keys().next().value!);
  }
  return false;
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

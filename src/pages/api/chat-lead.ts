// @ts-ignore
import { env as cfEnv } from 'cloudflare:workers';
import type { APIRoute } from 'astro';

export const prerender = false;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type LeadBody = {
  action?: 'lead' | 'event';
  email?: string;
  sessionId?: string;
  path?: string;
  event?: string;
  intent?: string;
  messages?: Array<{ role?: string; content?: string }>;
};

export const POST: APIRoute = async ({ request }) => {
  let body: LeadBody;
  try { body = await request.json() as LeadBody; } catch { return json({ error: 'Invalid request body' }, 400); }
  const action = body.action === 'event' ? 'event' : 'lead';
  const sessionId = String(body.sessionId || '').slice(0, 100);
  const path = String(body.path || '/').slice(0, 160);
  const runtimeEnv = (cfEnv || {}) as Record<string, string | undefined>;
  const webhook = (runtimeEnv.CHAT_LEAD_WEBHOOK || runtimeEnv.MAKE_LEAD_WEBHOOK || import.meta.env.CHAT_LEAD_WEBHOOK || import.meta.env.MAKE_LEAD_WEBHOOK) as string | undefined;

  if (action === 'lead') {
    const email = String(body.email || '').trim().toLowerCase();
    if (!EMAIL_RE.test(email)) return json({ error: 'Please enter a valid email address.' }, 400);
    const messages = Array.isArray(body.messages) ? body.messages.slice(-12).map((m) => ({ role: String(m.role || '').slice(0, 20), content: String(m.content || '').slice(0, 1000) })) : [];
    const payload = { type: 'ai_growth_advisor_lead', email, sessionId, path, intent: String(body.intent || '').slice(0, 1600), messages, createdAt: new Date().toISOString() };
    if (webhook) await deliver(webhook, payload);
    return json({ ok: true });
  }

  const event = String(body.event || '').replace(/[^a-z0-9_\-]/gi, '').slice(0, 60);
  if (!event) return json({ error: 'Missing event' }, 400);
  if (webhook) await deliver(webhook, { type: 'ai_growth_advisor_event', event, sessionId, path, createdAt: new Date().toISOString() });
  return json({ ok: true });
};

async function deliver(url: string, payload: unknown) {
  if (!/^https:\/\//i.test(url)) throw new Error('Lead webhook must use HTTPS');
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  if (!res.ok) throw new Error(`Lead webhook returned ${res.status}`);
}

function json(body: object, status = 200) { return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }); }

// @ts-ignore
import { env as cfEnv } from 'cloudflare:workers';
import type { APIRoute } from 'astro';

export const prerender = false;

function cleanMessageHistory(messages: Array<{ role: 'user' | 'assistant'; content: string }>): Array<{ role: 'user' | 'assistant'; content: string }> {
  if (messages.length === 0) return [];
  const cleaned: Array<{ role: 'user' | 'assistant'; content: string }> = [];
  let lastRole: 'user' | 'assistant' | null = null;
  for (const msg of messages) {
    if (!msg.content || msg.content.trim() === '') continue;
    const role = msg.role === 'assistant' ? 'assistant' : 'user';
    if (lastRole === role) {
      cleaned[cleaned.length - 1].content += "\n" + msg.content.trim();
      continue;
    }
    cleaned.push({ role, content: msg.content.trim() });
    lastRole = role;
  }
  while (cleaned.length > 0 && cleaned[0].role !== 'user') cleaned.shift();
  while (cleaned.length > 0 && cleaned[cleaned.length - 1].role !== 'user') cleaned.pop();
  return cleaned;
}

export const POST: APIRoute = async (context) => {
  try {
    const apiKey = (cfEnv as any).ANTHROPIC_API_KEY;
    if (!apiKey) {
      return new Response(JSON.stringify({ error: 'ANTHROPIC_API_KEY not configured.' }), { status: 500 });
    }

    const body = await context.request.json() as any;
    let messages: Array<{ role: 'user' | 'assistant'; content: string }> = [];
    if (Array.isArray(body.messages)) {
      messages = body.messages.map((m: any) => ({
        role: (m.role === 'assistant' || m.role === 'bot') ? 'assistant' : 'user',
        content: String(m.content),
      }));
    } else {
      messages = [{ role: 'user', content: String(body.message || body.content || body) }];
    }

    messages = cleanMessageHistory(messages);
    if (messages.length === 0) {
      return new Response(JSON.stringify({ error: 'No valid messages.' }), { status: 400 });
    }

    const anthropicRes = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-3-5-haiku-20241022', // Reverting to Haiku for safety
        max_tokens: 1024,
        system: "You are Tobby's Assistant, a helpful AI on the AstroSignal blog. Help visitors with questions about AI. Be concise.",
        messages,
      }),
    });

    if (!anthropicRes.ok) {
      const errText = await anthropicRes.text();
      // Return the raw error from Anthropic to see what's wrong
      return new Response(errText, { 
        status: anthropicRes.status,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const data = await anthropicRes.json() as any;
    const text = data.content?.find((b: any) => b.type === 'text')?.text ?? '';
    return new Response(text, { status: 200 });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
  }
};

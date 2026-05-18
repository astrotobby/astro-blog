// @ts-ignore
import { env as cfEnv } from 'cloudflare:workers';
import type { APIRoute } from 'astro';

export const prerender = false;

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

function cleanMessageHistory(messages: Message[]): Message[] {
  if (messages.length === 0) return [];
  const cleaned: Message[] = [];
  let lastRole: 'user' | 'assistant' | null = null;

  for (const msg of messages) {
    if (!msg.content || msg.content.trim() === '') continue;
    
    // Normalize role: 'bot' becomes 'assistant'
    const role = msg.role === 'assistant' || msg.role === 'bot' ? 'assistant' : 'user';
    
    if (lastRole === role) {
      cleaned[cleaned.length - 1].content += "\n" + msg.content.trim();
      continue;
    }
    
    cleaned.push({ role, content: msg.content.trim() });
    lastRole = role;
  }

  // Ensure conversation starts with user and ends with user
  while (cleaned.length > 0 && cleaned[0].role !== 'user') cleaned.shift();
  while (cleaned.length > 0 && cleaned[cleaned.length - 1].role !== 'user') cleaned.pop();

  return cleaned;
}

export const POST: APIRoute = async (context) => {
  try {
    const apiKey = (cfEnv as any).ANTHROPIC_API_KEY;
    if (!apiKey) {
      return new Response(
        JSON.stringify({ error: 'ANTHROPIC_API_KEY not configured on Cloudflare.' }),
        { status: 500, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const body = await context.request.json() as any;
    let messages: Message[] = [];

    if (Array.isArray(body.messages)) {
      messages = body.messages.map((m: any) => ({
        role: (m.role === 'assistant' || m.role === 'bot') ? 'assistant' : 'user',
        content: String(m.content || ''),
      }));
    } else {
      messages = [{ role: 'user', content: String(body.message || body.content || '') }];
    }

    messages = cleanMessageHistory(messages);
    if (messages.length === 0) {
      return new Response(
        JSON.stringify({ error: 'No valid messages provided.' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    }

    // Call Anthropic API with streaming
    const anthropicRes = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-3-5-haiku-20241022',
        max_tokens: 1024,
        system: "You are Tobby's Assistant, a helpful AI on the AstroSignal blog. Help visitors with questions about AI, technology, and the blog content. Be concise, friendly, and informative.",
        messages,
        stream: false, // We'll handle streaming manually
      }),
    });

    if (!anthropicRes.ok) {
      const errText = await anthropicRes.text();
      console.error('Anthropic API Error:', errText);
      return new Response(
        JSON.stringify({ error: `Anthropic API error: ${anthropicRes.status}` }),
        { status: anthropicRes.status, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const data = await anthropicRes.json() as any;
    const botResponse = data.content?.find((b: any) => b.type === 'text')?.text ?? '';

    if (!botResponse) {
      return new Response(
        JSON.stringify({ error: 'No response from AI model.' }),
        { status: 500, headers: { 'Content-Type': 'application/json' } }
      );
    }

    // Return the response as plain text for streaming consumption
    return new Response(botResponse, {
      status: 200,
      headers: {
        'Content-Type': 'text/plain; charset=utf-8',
        'Transfer-Encoding': 'chunked',
      },
    });

  } catch (err) {
    console.error('Chat API Error:', err);
    return new Response(
      JSON.stringify({ error: `Server error: ${String(err)}` }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};

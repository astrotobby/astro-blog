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
    const content = String(msg.content || '').trim();
    if (!content) continue;
    
    // Normalize role: 'bot' becomes 'assistant'
    const role = msg.role === 'assistant' || msg.role === 'bot' ? 'assistant' : 'user';
    
    if (lastRole === role) {
      cleaned[cleaned.length - 1].content += "\n" + content;
      continue;
    }
    
    cleaned.push({ role, content });
    lastRole = role;
  }

  // Anthropic requires the conversation to start with 'user'
  while (cleaned.length > 0 && cleaned[0].role !== 'user') {
    cleaned.shift();
  }

  // Anthropic requires the conversation to end with 'user' if we want a response
  // (or it can end with assistant if we are continuing, but for a new prompt it must be user)
  while (cleaned.length > 0 && cleaned[cleaned.length - 1].role !== 'user') {
    cleaned.pop();
  }

  return cleaned;
}

export const POST: APIRoute = async (context) => {
  try {
    const apiKey = (cfEnv as any).ANTHROPIC_API_KEY;
    if (!apiKey) {
      return new Response(
        JSON.stringify({ error: 'ANTHROPIC_API_KEY is missing. Please set it in Cloudflare Secrets.' }),
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
      const directContent = body.message || body.content || body;
      messages = [{ role: 'user', content: String(directContent || '') }];
    }

    const cleanedMessages = cleanMessageHistory(messages);
    
    if (cleanedMessages.length === 0) {
      return new Response(
        JSON.stringify({ error: 'No valid message history found. Try clearing your chat.' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    }

    // Call Anthropic API
    // Using Claude 3.5 Sonnet for better reliability and reasoning
    const anthropicRes = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-3-5-sonnet-20241022',
        max_tokens: 1024,
        system: "You are Tobby's Assistant, a helpful AI on the AstroSignal blog. Help visitors with questions about AI, technology, and the blog content. Be concise, friendly, and informative.",
        messages: cleanedMessages,
      }),
    });

    if (!anthropicRes.ok) {
      const errData = await anthropicRes.json().catch(() => ({}));
      const errorDetail = errData.error?.message || `HTTP ${anthropicRes.status}`;
      console.error('Anthropic API Error:', errData);
      
      return new Response(
        JSON.stringify({ 
          error: `Anthropic Error: ${errorDetail}`,
          type: errData.error?.type || 'api_error'
        }),
        { status: anthropicRes.status, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const data = await anthropicRes.json() as any;
    const botResponse = data.content?.find((b: any) => b.type === 'text')?.text ?? '';

    if (!botResponse) {
      return new Response(
        JSON.stringify({ error: 'The AI returned an empty response.' }),
        { status: 500, headers: { 'Content-Type': 'application/json' } }
      );
    }

    return new Response(botResponse, {
      status: 200,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });

  } catch (err) {
    console.error('Chat API Exception:', err);
    return new Response(
      JSON.stringify({ error: `Server Exception: ${String(err)}` }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};

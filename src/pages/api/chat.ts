// @ts-ignore
import { env as cfEnv } from 'cloudflare:workers';
import type { APIRoute } from 'astro';

export const prerender = false;

export const POST: APIRoute = async (context) => {
  try {
    const apiKey = (cfEnv as any).ANTHROPIC_API_KEY;

    if (!apiKey) {
      return new Response(
        JSON.stringify({ error: 'ANTHROPIC_API_KEY not configured.' }),
        { status: 500, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const body = await context.request.json() as any;

    // Handle ALL possible formats the frontend might send
    let messages: Array<{ role: 'user' | 'assistant'; content: string }> = [];

    if (Array.isArray(body.messages)) {
      // Format: { messages: [{role, content}] }
      messages = body.messages;
    } else if (typeof body.message === 'string') {
      // Format: { message: "hello" }
      messages = [{ role: 'user', content: body.message }];
    } else if (typeof body.content === 'string') {
      // Format: { content: "hello" }
      messages = [{ role: 'user', content: body.content }];
    } else if (typeof body === 'string') {
      // Format: plain string
      messages = [{ role: 'user', content: body }];
    } else {
      return new Response(
        JSON.stringify({ error: 'Invalid request format.' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    }

    // Ensure all messages have valid roles (convert 'bot' to 'assistant')
    messages = messages.map(m => ({
      role: (m.role === 'assistant' || m.role === 'bot') ? 'assistant' : 'user',
      content: String(m.content),
    })) as Array<{ role: 'user' | 'assistant'; content: string }>;

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
        system: "You are Tobby's Assistant, a helpful AI on the AstroSignal blog (astrotobby.site). Help visitors with questions about AI video creation, AI tools, content creation, and topics on this blog. Be concise and friendly.",
        messages,
      }),
    });

    if (!anthropicRes.ok) {
      const errText = await anthropicRes.text();
      console.error('Anthropic API error:', anthropicRes.status, errText);
      return new Response(
        JSON.stringify({ error: `Anthropic API error: ${anthropicRes.status}`, detail: errText }),
        { status: anthropicRes.status, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const data = await anthropicRes.json() as any;
    const text = data.content?.find((b: any) => b.type === 'text')?.text ?? '';

    // Return streaming response for compatibility with frontend
    // The frontend expects to stream the response text character by character
    return new Response(text, {
      status: 200,
      headers: {
        'Content-Type': 'text/plain; charset=utf-8',
        'Transfer-Encoding': 'chunked',
      },
    });

  } catch (err) {
    console.error('Chat API error:', err);
    return new Response(
      JSON.stringify({ error: `Internal error: ${String(err)}` }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};

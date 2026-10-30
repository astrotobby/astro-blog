// @ts-ignore
import { env as cfEnv } from 'cloudflare:workers';
import type { APIRoute } from 'astro';

export const prerender = false;

interface Message {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export const POST: APIRoute = async (context) => {
  try {
    const ai = (cfEnv as any).AI;
    
    if (!ai) {
      return new Response(
        JSON.stringify({ error: 'Cloudflare AI binding not found.' }),
        { status: 500, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const body = await context.request.json() as any;
    let messages: Message[] = [];

    messages.push({
      role: 'system',
      content: "You are Tobby's Assistant, a helpful AI on the AstroSignal blog. Help visitors with questions about AI, technology, and the blog content. Keep every reply brief: 2-4 short sentences, plain text, no long step-by-step lists or headings. Be friendly and informative, and offer to go deeper only if asked."
    });

    if (Array.isArray(body.messages)) {
      body.messages.forEach((m: any) => {
        messages.push({
          role: (m.role === 'assistant' || m.role === 'bot') ? 'assistant' : 'user',
          content: String(m.content || ''),
        });
      });
    } else {
      const directContent = body.message || body.content || body;
      messages.push({ role: 'user', content: String(directContent || '') });
    }

    // Call Cloudflare Workers AI with streaming enabled
    // llama-3.1-8b-instruct was deprecated on 2026-05-30; fp8 is its current replacement.
    const stream = await ai.run('@cf/meta/llama-3.1-8b-instruct-fp8', {
      messages,
      stream: true,
      // Replies are meant to be brief (see system prompt); this cap is headroom so
      // they finish their sentence instead of hitting the 256-token default.
      max_tokens: 400
    });

    // Return the stream directly to the client
    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });

  } catch (err) {
    console.error('Cloudflare AI Streaming Error:', err);
    return new Response(
      JSON.stringify({ error: `AI Error: ${String(err)}` }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};

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
      content: "You are Tobby's Assistant, a helpful AI on the AstroSignal blog. Help visitors with questions about AI, technology, and the blog content. Be concise, friendly, and informative."
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
    const stream = await ai.run('@cf/meta/llama-3.1-8b-instruct', {
      messages,
      stream: true
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

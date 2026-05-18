import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request, locals }) => {
  try {
    const { messages } = await request.json();

    if (!messages || !Array.isArray(messages)) {
      return new Response(JSON.stringify({ error: 'Invalid messages' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Access the Cloudflare runtime
    const runtime = locals.runtime;
    if (!runtime) {
      return new Response(JSON.stringify({ error: 'Cloudflare Runtime not found in Astro locals' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (!runtime.env || !runtime.env.AI) {
      return new Response(JSON.stringify({ error: 'AI binding not found in environment' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const ai = runtime.env.AI;

    // System prompt for the blog assistant
    const systemPrompt = {
      role: 'system',
      content: 'You are Tobby\'s Assistant, a helpful and welcoming AI for Tobby\'s blog. Your goal is to help visitors navigate the blog, answer questions about AI and technology content, and provide a friendly experience. Keep your responses concise and engaging.'
    };

    const chatMessages = [systemPrompt, ...messages];

    // Call Cloudflare Workers AI with streaming
    const response = await ai.run('@cf/meta/llama-3-8b-instruct', {
      messages: chatMessages,
      stream: true,
    });

    // Return the stream directly
    return new Response(response, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });

  } catch (error: any) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};

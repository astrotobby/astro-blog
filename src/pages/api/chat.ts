import type { APIRoute } from 'astro';

export const prerender = false;

interface CloudflareEnv {
  ANTHROPIC_API_KEY: string;
}

export const POST: APIRoute = async (context) => {
  try {
    // Astro v6 fix: access env through context.locals.runtime (NOT Astro.locals)
    const runtime = (context.locals as { runtime?: { env?: CloudflareEnv } }).runtime;
    const apiKey = runtime?.env?.ANTHROPIC_API_KEY;

    if (!apiKey) {
      return new Response(
        JSON.stringify({ error: 'ANTHROPIC_API_KEY not configured. Set it in Cloudflare Pages → Settings → Environment Variables.' }),
        { status: 500, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const body = await context.request.json() as {
      messages: Array<{ role: string; content: string }>;
    };

    const { messages } = body;

    if (!messages || !Array.isArray(messages)) {
      return new Response(
        JSON.stringify({ error: 'Invalid request: messages array required.' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    }

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
        system: "You are Tobby's Assistant, a helpful AI on the AstroSignal blog (astrotobby.site). Help visitors with questions about AI video creation, AI tools, content creation, and topics covered on this blog. Be concise and friendly.",
        messages,
      }),
    });

    if (!anthropicRes.ok) {
      const errText = await anthropicRes.text();
      console.error('Anthropic API error:', errText);
      return new Response(
        JSON.stringify({ error: `Anthropic API error: ${anthropicRes.status}` }),
        { status: anthropicRes.status, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const data = await anthropicRes.json() as {
      content: Array<{ type: string; text: string }>;
    };

    const text = data.content?.find(b => b.type === 'text')?.text ?? '';

    return new Response(
      JSON.stringify({ message: text }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    );

  } catch (err) {
    console.error('Chat API error:', err);
    return new Response(
      JSON.stringify({ error: 'Internal server error. Check Cloudflare logs.' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};

// @ts-ignore
import { env as cfEnv } from 'cloudflare:workers';
import type { APIRoute } from 'astro';

export const prerender = false;

/**
 * Cleans and normalizes the message history to meet Anthropic API requirements:
 * - Alternating user/assistant pattern
 * - No consecutive messages from the same role
 * - Starts with a user message
 * - Removes empty messages
 */
function cleanMessageHistory(messages: Array<{ role: 'user' | 'assistant'; content: string }>): Array<{ role: 'user' | 'assistant'; content: string }> {
  if (messages.length === 0) return [];

  const cleaned: Array<{ role: 'user' | 'assistant'; content: string }> = [];
  let lastRole: 'user' | 'assistant' | null = null;

  for (const msg of messages) {
    // Skip empty messages
    if (!msg.content || msg.content.trim() === '') continue;

    const role = msg.role === 'assistant' ? 'assistant' : 'user';

    // Skip consecutive messages from the same role
    if (lastRole === role) continue;

    cleaned.push({ role, content: msg.content.trim() });
    lastRole = role;
  }

  // Ensure the first message is from the user
  if (cleaned.length > 0 && cleaned[0].role !== 'user') {
    cleaned.shift();
  }

  // Ensure the last message is from the user (the API will respond with assistant)
  if (cleaned.length > 0 && cleaned[cleaned.length - 1].role !== 'user') {
    cleaned.pop();
  }

  return cleaned;
}

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

    // Normalize roles (convert 'bot' to 'assistant')
    messages = messages.map(m => ({
      role: (m.role === 'assistant' || m.role === 'bot') ? 'assistant' : 'user',
      content: String(m.content),
    })) as Array<{ role: 'user' | 'assistant'; content: string }>;

    // Clean and validate message history
    messages = cleanMessageHistory(messages);

    // Ensure we have at least one message
    if (messages.length === 0) {
      return new Response(
        JSON.stringify({ error: 'No valid messages provided.' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    }

    // Log for debugging
    console.log('Cleaned messages:', JSON.stringify(messages, null, 2));

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

import type { APIRoute } from 'astro';

export const prerender = false;

export const POST: APIRoute = async ({ request }) => {
  try {
    const body = await request.json();
    const { email } = body;

    if (!email || !email.includes('@')) {
      return new Response(
        JSON.stringify({ error: 'Invalid email address.' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    }

    // Since we don't have a database set up yet, we'll simulate success.
    // In a real scenario, you would save this to a database (like Cloudflare D1)
    // or send it to an email service (like Mailchimp, ConvertKit, etc.)
    
    // For now, we'll log it (Cloudflare logs) and return success.
    console.log(`New subscriber: ${email}`);

    return new Response(
      JSON.stringify({ message: 'Successfully subscribed!' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    );

  } catch (err) {
    console.error('Subscription Error:', err);
    return new Response(
      JSON.stringify({ error: 'Failed to process subscription.' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};

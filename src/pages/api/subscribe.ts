import type { APIRoute } from 'astro';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Lazily resolved audience ID — fetched once per worker instance if env var not set
let resolvedListId: string | null = null;

async function getListId(apiKey: string, dc: string): Promise<string> {
  if (resolvedListId) return resolvedListId;

  const envId = import.meta.env.MAILCHIMP_LIST_ID as string | undefined;
  if (envId) { resolvedListId = envId; return envId; }

  // Auto-discover the first audience in the account
  const res = await fetch(`https://${dc}.api.mailchimp.com/3.0/lists?count=1`, {
    headers: { Authorization: `Basic ${btoa(`anystring:${apiKey}`)}` },
  });
  const data = (await res.json()) as { lists?: { id: string }[] };
  const id = data.lists?.[0]?.id;
  if (!id) throw new Error('No Mailchimp audience found');
  resolvedListId = id;
  return id;
}

export const POST: APIRoute = async ({ request }) => {
  let body: { email?: string };
  try {
    body = await request.json();
  } catch {
    return json({ error: 'Invalid request body' }, 400);
  }

  const email = (body.email ?? '').trim().toLowerCase();
  if (!EMAIL_RE.test(email)) {
    return json({ error: 'Please enter a valid email address' }, 400);
  }

  const apiKey = import.meta.env.MAILCHIMP_API_KEY as string | undefined;
  if (!apiKey) {
    console.error('[subscribe] Missing MAILCHIMP_API_KEY');
    return json({ error: 'Server configuration error' }, 500);
  }

  const dc = apiKey.split('-')[1]; // e.g. 'us8'

  try {
    const listId = await getListId(apiKey, dc);

    const res = await fetch(`https://${dc}.api.mailchimp.com/3.0/lists/${listId}/members`, {
      method: 'POST',
      headers: {
        Authorization: `Basic ${btoa(`anystring:${apiKey}`)}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email_address: email, status: 'subscribed' }),
    });

    const data = (await res.json()) as { title?: string; detail?: string };

    // Mailchimp returns 400 + title "Member Exists" for already-subscribed — treat as success
    if (res.ok || data.title === 'Member Exists') {
      return json({ message: "You're subscribed! Check your inbox." }, 200);
    }

    throw new Error(data.detail ?? `Mailchimp error ${res.status}`);
  } catch (err) {
    console.error('[subscribe]', err);
    const msg = err instanceof Error ? err.message : 'Failed to subscribe';
    return json({ error: msg }, 500);
  }
};

function json(body: object, status: number) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

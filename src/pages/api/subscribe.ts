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
  if (!dc) {
    console.error('[subscribe] MAILCHIMP_API_KEY has no datacenter suffix (expected key-usXX)');
    return json({ error: 'Server configuration error' }, 500);
  }

  try {
    const listId = await getListId(apiKey, dc);

    const res = await fetch(`https://${dc}.api.mailchimp.com/3.0/lists/${listId}/members`, {
      method: 'POST',
      headers: {
        Authorization: `Basic ${btoa(`anystring:${apiKey}`)}`,
        'Content-Type': 'application/json',
      },
      // Tag the subscriber so the welcome automation can target "free-pack" leads.
      body: JSON.stringify({ email_address: email, status: 'subscribed', tags: ['free-pack'] }),
    });

    const data = (await res.json()) as { title?: string; detail?: string };

    // Success, or already-on-the-list — both are wins for the user.
    if (res.ok || data.title === 'Member Exists') {
      return json({ message: "You're in! Your free pack link is below." }, 200);
    }

    // Map Mailchimp's known rejections to friendly, correct-status responses instead of
    // leaking raw internals as a 500 (which made a working form look broken).
    const detail = (data.detail ?? '').toLowerCase();
    if (detail.includes('looks fake') || data.title === 'Invalid Resource') {
      return json({ error: 'Please enter a real email address.' }, 400);
    }
    if (detail.includes('signed up to a lot') || detail.includes('compliance state')) {
      return json({ error: "This address can't be subscribed automatically. Try another, or contact us." }, 400);
    }
    if (data.title === 'Forgotten Email Not Subscribed' || detail.includes('cannot be subscribed')) {
      return json({ error: 'You previously unsubscribed. Please re-subscribe from your last Mailchimp email.' }, 400);
    }

    // Genuine upstream problem — log the detail, but never expose Mailchimp internals.
    console.error('[subscribe] Mailchimp error', res.status, data.title, data.detail);
    return json({ error: "We couldn't subscribe you right now. Please try again in a moment." }, 502);
  } catch (err) {
    console.error('[subscribe]', err);
    return json({ error: "We couldn't subscribe you right now. Please try again in a moment." }, 502);
  }
};

function json(body: object, status: number) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

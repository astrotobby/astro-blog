// Resolve the channel's LATEST video at build time from its public RSS feed.
// No API key required. The result is memoized so the network work happens once
// per build even though the sidebar renders on every page.
//
// Flow:  handle (@name)  ──►  channelId (UC…)  ──►  RSS feed  ──►  newest videoId
// Any failure degrades gracefully to YOUTUBE_FALLBACK_VIDEO_ID (or null, in
// which case the component shows a "watch on YouTube" card instead of an iframe).

import {
  YOUTUBE_CHANNEL_ID,
  YOUTUBE_FALLBACK_VIDEO_ID,
  YOUTUBE_URL,
} from '../consts';

export interface LatestVideo {
  id: string;
  title: string;
}

let cached: Promise<LatestVideo | null> | null = null;

function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}

async function resolveChannelId(): Promise<string | null> {
  if (YOUTUBE_CHANNEL_ID) return YOUTUBE_CHANNEL_ID;
  try {
    const html = await fetch(YOUTUBE_URL, {
      headers: { 'accept-language': 'en-US,en;q=0.9' },
    }).then((r) => r.text());
    const m =
      html.match(/"externalId":"(UC[\w-]+)"/) ||
      html.match(/"channelId":"(UC[\w-]+)"/) ||
      html.match(/channel_id=(UC[\w-]+)/);
    return m ? m[1] : null;
  } catch {
    return null;
  }
}

function fallback(): LatestVideo | null {
  return YOUTUBE_FALLBACK_VIDEO_ID ? { id: YOUTUBE_FALLBACK_VIDEO_ID, title: '' } : null;
}

async function fetchLatest(): Promise<LatestVideo | null> {
  try {
    const channelId = await resolveChannelId();
    if (!channelId) return fallback();

    const feed = await fetch(
      `https://www.youtube.com/feeds/videos.xml?channel_id=${channelId}`,
    ).then((r) => r.text());

    // First <entry> in the feed is the most recent upload.
    const entry = (feed.match(/<entry>[\s\S]*?<\/entry>/) || [])[0] || '';
    const id = (entry.match(/<yt:videoId>([\w-]+)<\/yt:videoId>/) || [])[1];
    if (!id) return fallback();

    const rawTitle = (entry.match(/<title>([\s\S]*?)<\/title>/) || [])[1] || '';
    return { id, title: decodeEntities(rawTitle).trim() };
  } catch {
    return fallback();
  }
}

/** Memoized: fetch the newest video once per build. */
export function getLatestVideo(): Promise<LatestVideo | null> {
  if (!cached) cached = fetchLatest();
  return cached;
}

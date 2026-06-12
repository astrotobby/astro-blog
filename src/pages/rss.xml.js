import { getCollection } from 'astro:content';
import rss from '@astrojs/rss';
import { SITE_DESCRIPTION, SITE_TITLE } from '../consts';

const orderKey = (p) => {
	const id = p.id || '';
	const ms = id.match(/-(\d{13})$/);
	if (ms) return Number(ms[1]);
	const d = id.match(/^(\d{4})-(\d{2})-(\d{2})/);
	if (d) return Date.parse(`${d[1]}-${d[2]}-${d[3]}T00:00:00Z`);
	return p.data.pubDate ? p.data.pubDate.valueOf() : 0;
};

export async function GET(context) {
	const posts = (await getCollection('blog')).sort((a, b) => orderKey(b) - orderKey(a));
	return rss({
		title: SITE_TITLE,
		description: SITE_DESCRIPTION,
		site: context.site,
			items: posts.map((post) => ({
				...post.data,
				pubDate: new Date(post.data.pubDate),
				link: `/blog/${post.id}/`,
			})),
	});
}

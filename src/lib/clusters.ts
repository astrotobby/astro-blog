// Topic-cluster definitions — the SEO/AEO pillar architecture for the site.
// Each cluster is a hub page (/topics/<slug>) that gathers every post whose tags
// match, leads with a buyer-intent answer, and points at the matching product.
// This turns the flat 100-post archive into 4 themed authority hubs that pass
// internal-link equity to the posts most likely to rank AND convert.
//
// `tags` are matched against post frontmatter tags (lowercase tokens like
// "aeo", "agent", "automation"). Keep them in sync with the tag vocabulary
// the posts actually use.

export interface Cluster {
  slug: string;
  /** Short nav/eyebrow label. */
  eyebrow: string;
  /** H1 / card title. */
  name: string;
  /** SEO <title> + meta description seed. */
  seoTitle: string;
  metaDescription: string;
  /** Buyer question this hub answers (used as the lead H2). */
  buyerQuestion: string;
  /** 1–2 sentence quotable answer rendered directly under the H1 (AEO lead). */
  answer: string;
  /** Tags that pull a post into this cluster. */
  tags: string[];
  /** CTA copy for the cluster's matching offer. */
  ctaHook: string;
}

export const CLUSTERS: Cluster[] = [
  {
    slug: 'ai-search-optimization',
    eyebrow: 'AEO',
    name: 'AI Search & Answer Engine Optimization',
    seoTitle: 'Answer Engine Optimization (AEO): Rank in ChatGPT, Perplexity & Google AI Overviews',
    metaDescription:
      'How to get your site cited by ChatGPT, Perplexity and Google AI Overviews in 2026. AEO strategy, audits, and the structure that wins AI citations.',
    buyerQuestion: 'How do I rank in AI search engines like ChatGPT and Perplexity?',
    answer:
      'Answer Engine Optimization (AEO) is the practice of structuring content so AI engines — ChatGPT, Perplexity, Google AI Overviews — quote it directly in their answers. You win citations by leading with the answer, using question-shaped headings, adding FAQ and Article schema, and naming specific tools, dates and numbers.',
    tags: ['aeo', 'seo'],
    ctaHook: 'Want the exact AEO playbook?',
  },
  {
    slug: 'ai-automation',
    eyebrow: 'Automation',
    name: 'AI Automation & Autoblogging',
    seoTitle: 'AI Automation & Autoblogging: Build a Content Engine on Autopilot (2026)',
    metaDescription:
      'Build automated content and workflow pipelines with Make.com, n8n and AI agents. The blueprints behind hands-off blogging and passive AI income in 2026.',
    buyerQuestion: 'How do I automate my content and workflows with AI?',
    answer:
      'AI automation chains tools like Make.com, n8n and AI models into pipelines that research, write, publish and repurpose content with little manual work. The fastest wins are autoblogging (idea → post → video → social) and back-office workflow automation.',
    tags: ['automation', 'make', 'pipeline'],
    ctaHook: 'Want the done-for-you automation blueprint?',
  },
  {
    slug: 'ai-agents',
    eyebrow: 'Agents',
    name: 'AI Agents & Agentic Workflows',
    seoTitle: 'AI Agents & Agentic AI in 2026: Multi-Agent Systems, Tools & Real Business Value',
    metaDescription:
      'What AI agents and agentic workflows actually are, how multi-agent systems work, and how to put them to work in a real business in 2026.',
    buyerQuestion: 'What are AI agents and how do I build agentic workflows?',
    answer:
      'AI agents are systems that plan, use tools, and take multi-step actions toward a goal with minimal supervision. Agentic workflows chain several specialized agents together so they can research, decide and execute — the shift from one-off prompts to autonomous, multi-agent systems.',
    tags: ['agent', 'agentic', 'multi-agent', 'frameworks'],
    ctaHook: 'Want the multi-agent workflow pack?',
  },
  {
    slug: 'ai-coding',
    eyebrow: 'Coding',
    name: 'AI Coding, Vibe Coding & Prompts',
    seoTitle: 'AI Coding & Vibe Coding in 2026: Claude Code, Agents, Prompts & Workflows',
    metaDescription:
      'The best AI coding agents, vibe-coding workflows and prompt techniques in 2026 — Claude Code, Codex and the prompts that ship real software faster.',
    buyerQuestion: 'What are the best AI coding agents and prompts in 2026?',
    answer:
      'AI coding tools like Claude Code and Codex let you build software by describing intent ("vibe coding") instead of writing every line. The leverage comes from agentic coding workflows and a tight library of reusable prompts.',
    tags: ['coding', 'prompt', 'prompt-engineering', 'llm'],
    ctaHook: 'Want the coding + prompt vault?',
  },
];

export function getCluster(slug: string): Cluster | undefined {
  return CLUSTERS.find((c) => c.slug === slug);
}

/** True if a post (by its tags) belongs in a cluster. */
export function postInCluster(postTags: string[] = [], cluster: Cluster): boolean {
  const set = new Set(postTags.map((t) => t.toLowerCase()));
  return cluster.tags.some((t) => set.has(t));
}

import { defineCollection, z } from 'astro:content';

const blog = defineCollection({
    type: 'content',
    schema: z.object({
        title: z.string().optional().default('Untitled Post'),
        date: z.coerce.date().optional(),
        pubDate: z.coerce.date().optional(),
        description: z.string().optional().default(''),
        tags: z.array(z.string()).optional().default([]),
        author: z.string().optional().default('Astro Tobby'),
        heroImage: z.string().optional(),
    }),
});

export const collections = { blog };

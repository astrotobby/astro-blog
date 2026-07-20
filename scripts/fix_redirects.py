"""
Regenerate public/_redirects to cover all posts with underscores in filenames.
The live Astro routes use the exact filename (with underscores), but external
links (social media, search engines) often use hyphens instead.
This script adds 301 redirects from hyphen-versions to underscore-versions.
"""
import os
import re
import glob

BLOG_DIR = 'src/content/blog'
REDIRECTS_FILE = 'public/_redirects'

def astro_slug(stem):
    """Match Astro 5 glob-loader id generation."""
    s = stem.lower()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'\s+', '-', s)
    s = re.sub(r'-{2,}', '-', s)
    return s.strip('-')

def hyphen_to_underscore_slug(stem):
    """Convert the Astro slug (hyphens) to the actual filename slug (underscores preserved)."""
    s = stem.lower()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'\s+', '-', s)
    s = re.sub(r'-{2,}', '-', s)
    s = s.strip('-')
    # Convert hyphens to underscores (the actual Astro route uses underscores)
    s = s.replace('-', '_')
    return s

def get_posts():
    """Get all blog post filenames."""
    posts = []
    for f in sorted(glob.glob(os.path.join(BLOG_DIR, '*.md'))):
        stem = os.path.basename(f).replace('.md', '')
        posts.append(stem)
    return posts

def needs_redirect(stem):
    """Check if a post slug needs a hyphen->underscore redirect."""
    actual_slug = astro_slug(stem)
    # If the slug contains underscores, we need a redirect from the hyphen version
    if '_' in actual_slug:
        return True
    return False

def main():
    posts = get_posts()
    redirects = []
    
    # Preserve existing non-blog redirects (sitemap, products)
    existing_nonblog = []
    if os.path.exists(REDIRECTS_FILE):
        with open(REDIRECTS_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('/blog/'):
                    existing_nonblog.append(line)
    
    for stem in posts:
        if needs_redirect(stem):
            actual_slug = astro_slug(stem)
            # Hyphen version (what external links use)
            hyphen_slug = actual_slug.replace('_', '-')
            
            if hyphen_slug != actual_slug:
                # Without trailing slash
                redirects.append(f'/blog/{hyphen_slug} /blog/{actual_slug} 301')
                # With trailing slash
                redirects.append(f'/blog/{hyphen_slug}/ /blog/{actual_slug}/ 301')
    
    # Write the new _redirects file
    with open(REDIRECTS_FILE, 'w') as f:
        # Static redirects first
        f.write('/sitemap.xml /sitemap-index.xml 301\n')
        # Retired product redirects
        f.write('# --- retired product: AI Video Freelancer Toolkit (deleted from Shopify) ---\n')
        f.write('/products/video-toolkit /products 301\n')
        f.write('/products/video-toolkit/ /products 301\n')
        f.write('\n')
        f.write('# --- legacy blog URL redirects (hyphen -> underscore) ---\n')
        for r in redirects:
            f.write(r + '\n')
    
    print(f"Generated {len(redirects)} redirects for {len(posts)} posts")
    print(f"Posts needing redirects: {sum(1 for p in posts if needs_redirect(p))}")

if __name__ == '__main__':
    main()

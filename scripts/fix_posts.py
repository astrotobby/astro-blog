import os
import re
import base64

BLOG_DIR = "src/content/blog"

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')

def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    if not content.strip():
        print(f"Deleting empty file: {filepath}")
        os.remove(filepath)
        return

    # Extract frontmatter and body
    # Support both correct and slightly broken frontmatter
    match = re.search(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
    if not match:
        # Try to find the first occurrence of --- if it's not at the start
        match = re.search(r'---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
        
    if match:
        frontmatter = match.group(1)
        body = match.group(2)
        
        # Clean up body from LLM chatter
        # Remove common LLM prefixes
        body = re.sub(r'^(Here is|Sure|I have generated|This is).*?\n', '', body, flags=re.IGNORECASE)
        body = body.strip()
        
        # Reconstruct content
        new_content = f"---\n{frontmatter.strip()}\n---\n\n{body}"
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Fixed formatting for: {filepath}")
    else:
        print(f"Could not find valid frontmatter in: {filepath}")

if __name__ == "__main__":
    if not os.path.exists(BLOG_DIR):
        print(f"Directory {BLOG_DIR} not found.")
    else:
        for filename in os.listdir(BLOG_DIR):
            if filename.endswith(".md"):
                fix_file(os.path.join(BLOG_DIR, filename))

import os
import re

BLOG_DIR = "src/content/blog"

def slugify(text):
    text = text.lower()
    # Replace non-alphanumeric with hyphen
    text = re.sub(r'[^a-z0-9]+', '-', text)
    # Remove leading/trailing hyphens
    return text.strip('-')

def fix_file(filepath):
    filename = os.path.basename(filepath)
    if not filename.endswith(".md"):
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    if not content.strip():
        print(f"Deleting empty file: {filepath}")
        os.remove(filepath)
        return

    # Extract date prefix if exists (YYYY-MM-DD-)
    date_match = re.match(r'^(\d{4}-\d{2}-\d{2}-)', filename)
    date_prefix = date_match.group(1) if date_match else ""
    
    # Extract frontmatter and body
    match = re.search(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
    if not match:
        # If no frontmatter, try to wrap the whole thing or skip
        print(f"Warning: No frontmatter found in {filename}")
        return

    frontmatter = match.group(1)
    body = match.group(2)
    
    # Clean up frontmatter
    fm_lines = frontmatter.split('\n')
    new_fm = {}
    for line in fm_lines:
        if ':' in line:
            parts = line.split(':', 1)
            key = parts[0].strip().lower()
            val = parts[1].strip().strip('"').strip("'")
            new_fm[key] = val

    # Use title from frontmatter for renaming if current filename is bad
    title = new_fm.get('title', filename.replace('.md', ''))
    
    # Clean up body (remove LLM conversational filler)
    body = re.sub(r'^(Here is|Sure|I have generated|This is|Title:).*?\n', '', body, flags=re.IGNORECASE)
    body = body.strip()
    
    # Reconstruct content
    fm_str = "---\n"
    for k, v in new_fm.items():
        if k == 'title':
            fm_str += f'title: "{v}"\n'
        else:
            fm_str += f'{k}: "{v}"\n'
    fm_str += "---\n"
    
    new_content = fm_str + "\n" + body
    
    # Determine new filename
    slug = slugify(title)
    # Avoid double date
    if slug.startswith(date_prefix.strip('-')):
        new_filename = f"{slug}.md"
    else:
        new_filename = f"{date_prefix}{slug}.md"
    
    new_path = os.path.join(BLOG_DIR, new_filename)
    
    # Write fixed content
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    # Rename if needed
    if filepath != new_path:
        if os.path.exists(new_path):
            print(f"Conflict: {new_path} already exists. Removing {filepath}")
            os.remove(filepath)
        else:
            print(f"Renaming: {filename} -> {new_filename}")
            os.rename(filepath, new_path)

if __name__ == "__main__":
    if not os.path.exists(BLOG_DIR):
        print(f"Directory {BLOG_DIR} not found.")
    else:
        # Sort files to process them consistently
        for filename in sorted(os.listdir(BLOG_DIR)):
            fix_file(os.path.join(BLOG_DIR, filename))

import os
import re

blog_dir = "src/content/blog"
for filename in os.listdir(blog_dir):
    if filename.endswith(".md"):
        filepath = os.path.join(blog_dir, filename)
        with open(filepath, 'r') as f:
            content = f.read()
        
        # 1. Fix the frontmatter
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        if match:
            frontmatter = match.group(1)
            body = content[match.end():]
            
            # Clean up frontmatter
            lines = frontmatter.split('\n')
            new_lines = []
            seen_keys = set()
            for line in lines:
                if ':' in line:
                    key = line.split(':')[0].strip()
                    if key not in seen_keys:
                        new_lines.append(line)
                        seen_keys.add(key)
            
            # 2. Fix the body: remove redundant image tags and clean up
            # Remove any line starting with image: "..."
            body = re.sub(r'^image: ".*?"\s*\n', '', body, flags=re.MULTILINE)
            # Remove leading empty paragraphs or spaces
            body = body.strip()
            # If the body starts with <p>&nbsp;</p>, remove it
            body = re.sub(r'^<p>\s*&nbsp;\s*</p>', '', body).strip()
            
            new_content = "---\n" + "\n".join(new_lines) + "\n---\n\n" + body
            
            with open(filepath, 'w') as f:
                f.write(new_content)

print("Blog posts fixed.")

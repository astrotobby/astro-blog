import os
import re

blog_dir = "src/content/blog"
for filename in os.listdir(blog_dir):
    if filename.endswith(".md"):
        old_path = os.path.join(blog_dir, filename)
        
        # 1. Generate new filename: slugify and remove special characters
        # Keep the date prefix if it exists
        date_match = re.match(r'^(\d{4}-\d{2}-\d{2}-)', filename)
        date_prefix = date_match.group(1) if date_match else ""
        
        name_part = filename[len(date_prefix):]
        name_part = name_part.replace(".md", "")
        # Replace spaces and special chars with underscores/hyphens
        new_name = re.sub(r'[^a-zA-Z0-9]', '_', name_part)
        new_name = re.sub(r'_+', '_', new_name).strip('_')
        new_filename = f"{date_prefix}{new_name}.md"
        new_path = os.path.join(blog_dir, new_filename)
        
        # Rename if necessary
        if old_path != new_path:
            print(f"Renaming: {filename} -> {new_filename}")
            os.rename(old_path, new_path)
            current_path = new_path
        else:
            current_path = old_path

        # 2. Fix content
        with open(current_path, 'r') as f:
            content = f.read()
            
        # Ensure frontmatter is clean
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        if match:
            frontmatter = match.group(1)
            body = content[match.end():]
            
            lines = frontmatter.split('\n')
            new_lines = []
            seen_keys = set()
            for line in lines:
                if ':' in line:
                    parts = line.split(':', 1)
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if key not in seen_keys:
                        # Ensure title doesn't have problematic quotes
                        if key == 'title':
                            val = val.strip('"').strip("'")
                            new_lines.append(f'title: "{val}"')
                        else:
                            new_lines.append(f"{key}: {val}")
                        seen_keys.add(key)
            
            new_content = "---\n" + "\n".join(new_lines) + "\n---\n\n" + body.strip()
            
            with open(current_path, 'w') as f:
                f.write(new_content)

print("Blog posts and filenames fixed.")

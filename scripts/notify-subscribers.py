import os
import json
import requests
import glob
from datetime import datetime

# Configuration
BLOG_CONTENT_DIR = "src/content/blog"
SENT_POSTS_FILE = "scripts/sent_posts.json"
WEBHOOK_URL = os.environ.get("NOTIFY_WEBHOOK_URL") # For future use

def get_blog_posts():
    posts = []
    for filepath in glob.glob(f"{BLOG_CONTENT_DIR}/*.md"):
        with open(filepath, 'r') as f:
            content = f.read()
            # Basic frontmatter parsing
            try:
                if content.startswith('---'):
                    parts = content.split('---')
                    frontmatter = parts[1]
                    data = {}
                    for line in frontmatter.strip().split('\n'):
                        if ':' in line:
                            k, v = line.split(':', 1)
                            data[k.strip()] = v.strip().strip('"').strip("'")
                    
                    posts.append({
                        "id": os.path.basename(filepath),
                        "title": data.get("title", "Untitled"),
                        "description": data.get("description", ""),
                        "pubDate": data.get("pubDate", ""),
                        "url": f"https://astrotobby.site/blog/{os.path.basename(filepath).replace('.md', '')}"
                    })
            except Exception as e:
                print(f"Error parsing {filepath}: {e}")
    return posts

def main():
    if not os.path.exists("scripts"):
        os.makedirs("scripts")

    if os.path.exists(SENT_POSTS_FILE):
        with open(SENT_POSTS_FILE, 'r') as f:
            sent_posts = json.load(f)
    else:
        sent_posts = []

    all_posts = get_blog_posts()
    new_posts = [p for p in all_posts if p['id'] not in sent_posts]

    if not new_posts:
        print("No new posts to notify.")
        return

    print(f"Found {len(new_posts)} new posts. Preparing notifications...")

    for post in new_posts:
        print(f"Notifying for: {post['title']}")
        # In a real scenario, you would trigger an email API here
        # Example: requests.post(WEBHOOK_URL, json=post)
        
        sent_posts.append(post['id'])

    with open(SENT_POSTS_FILE, 'w') as f:
        json.dump(sent_posts, f, indent=2)

    print("Notification process completed.")

if __name__ == "__main__":
    main()

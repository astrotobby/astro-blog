import requests
import xml.etree.ElementTree as ET
import os
import re
import sys

def fix_existing_posts(blog_dir):
    # Fetch the RSS feeds
    rss_urls = [
        "https://rss.app/feeds/tZDulmAgUZxm5gyl.xml",
        "https://rss.app/feeds/ckYDb9i5Ybm2T8xn.xml"
    ]
    
    image_map = {}
    for rss_url in rss_urls:
        try:
            response = requests.get(rss_url)
            root = ET.fromstring(response.content)
            for item in root.findall('.//item'):
                title_elem = item.find('title')
                if title_elem is None: continue
                title = title_elem.text
                
                # Try media:content first
                media_content = item.find('{http://search.yahoo.com/mrss/}content')
                image_url = None
                if media_content is not None:
                    image_url = media_content.get('url')
                
                # Try description if media:content is missing
                if not image_url:
                    desc_elem = item.find('description')
                    if desc_elem is not None and desc_elem.text:
                        img_match = re.search(r'<img src="(.*?)"', desc_elem.text)
                        if img_match:
                            image_url = img_match.group(1)
                
                if image_url:
                    image_map[title.lower().strip()] = image_url
        except Exception as e:
            print(f"Error fetching RSS {rss_url}: {e}")
    
    print(f"Mapped {len(image_map)} images from RSS feeds.")
            
    # Iterate through blog posts and fix them
    for filename in os.listdir(blog_dir):
        if filename.endswith(".md"):
            path = os.path.join(blog_dir, filename)
            with open(path, 'r') as f:
                content = f.read()
            
            # Match any image that is a pollinations URL or the placeholder
            if 'image: "https://image.pollinations.ai' in content or 'image: "/blog-placeholder-about.jpg"' in content:
                title_match = re.search(r'title: "(.*?)"', content)
                if title_match:
                    post_title = title_match.group(1).lower().strip()
                    
                    post_words = [w for w in re.findall(r'\w+', post_title) if len(w) > 3]
                    best_match = None
                    max_common = 0
                    
                    for rss_title, url in image_map.items():
                        rss_words = [w for w in re.findall(r'\w+', rss_title) if len(w) > 3]
                        common_words = set(post_words).intersection(set(rss_words))
                        
                        if len(common_words) > max_common:
                            max_common = len(common_words)
                            best_match = url
                    
                    if max_common >= 2:
                        # Replace either pollinations URL or placeholder
                        new_content = re.sub(r'image: "(https://image.pollinations.ai.*?|/blog-placeholder-about.jpg)"', f'image: "{best_match}"', content)
                        if new_content != content:
                            with open(path, 'w') as f:
                                f.write(new_content)
                            print(f"Fixed image for: {filename} (Match score: {max_common})")
                    else:
                        print(f"No match for title: {post_title}")

if __name__ == "__main__":
    fix_existing_posts("/home/ubuntu/astro-blog/src/content/blog")

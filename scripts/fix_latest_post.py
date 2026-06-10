import requests
import xml.etree.ElementTree as ET
import os
import re

def fix_latest_post():
    # Get the latest post filename
    blog_dir = "/home/ubuntu/astro-blog/src/content/blog"
    latest_file = max([os.path.join(blog_dir, f) for f in os.listdir(blog_dir) if f.endswith('.md')], key=os.path.getctime)
    
    print(f"Processing: {os.path.basename(latest_file)}")
    
    # Read the post
    with open(latest_file, 'r') as f:
        content = f.read()
    
    # Extract the title
    title_match = re.search(r'title: "(.*?)"', content)
    if not title_match:
        print("Could not find title in post")
        return
    
    post_title = title_match.group(1).lower().strip()
    print(f"Post title: {post_title}")
    
    # Fetch RSS feeds and build image map
    rss_urls = [
        "https://rss.app/feeds/tZDulmAgUZxm5gyl.xml",
        "https://rss.app/feeds/ckYDb9i5Ybm2T8xn.xml"
    ]
    
    image_map = {}
    for rss_url in rss_urls:
        try:
            response = requests.get(rss_url, timeout=10)
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
    
    # Find matching image
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
        # Replace the Pollinations URL
        new_content = re.sub(r'image: "https://image.pollinations.ai.*?"', f'image: "{best_match}"', content)
        with open(latest_file, 'w') as f:
            f.write(new_content)
        print(f"✓ Fixed image for latest post (Match score: {max_common})")
        print(f"New image URL: {best_match}")
        return True
    else:
        print(f"✗ No matching image found in RSS feeds (Match score: {max_common})")
        # Use a fallback image
        fallback_url = "https://loremflickr.com/800/600/bitcoin,cryptocurrency,finance"
        new_content = re.sub(r'image: "https://image.pollinations.ai.*?"', f'image: "{fallback_url}"', content)
        with open(latest_file, 'w') as f:
            f.write(new_content)
        print(f"✓ Applied fallback image")
        print(f"Fallback image URL: {fallback_url}")
        return True

if __name__ == "__main__":
    fix_latest_post()

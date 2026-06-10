import json
import subprocess

def update_module_11(scenario_id):
    # Fetch the latest blueprint
    cmd_get = [
        "manus-mcp-cli", "tool", "call", "scenarios_get",
        "--server", "make",
        "--input", json.dumps({"scenarioId": scenario_id})
    ]
    result_get = subprocess.run(cmd_get, capture_output=True, text=True)
    
    # Parse the output to get the blueprint
    content = result_get.stdout
    start = content.find('{')
    end = content.rfind('}')
    data = json.loads(content[start:end+1])
    
    blueprint = data.get('blueprint', {})
    flow = blueprint.get('flow', [])
    
    for module in flow:
        if module.get('id') == 11:
            mapper = module.get('mapper', {})
            body = mapper.get('jsonStringBodyContent', '')
            
            old_url = 'https://image.pollinations.ai/prompt/{{encodeURL(8.data.choices[1].message.content)}}'
            new_url = '{{if(1.image.url; 1.image.url; if(1.enclosures[1].url; 1.enclosures[1].url; "https://loremflickr.com/800/600/business,technology"))}}'
            
            if old_url in body:
                mapper['jsonStringBodyContent'] = body.replace(old_url, new_url)
                print("Updated Module 11 image logic in memory.")
            else:
                print("Old URL logic not found.")
                return
    
    # Now update the scenario with the modified blueprint
    update_payload = {
        "scenarioId": scenario_id,
        "blueprint": {
            "flow": flow,
            "metadata": blueprint.get('metadata', {})
        }
    }
    
    cmd_update = [
        "manus-mcp-cli", "tool", "call", "scenarios_update",
        "--server", "make",
        "--input", json.dumps(update_payload)
    ]
    
    print(f"Updating scenario {scenario_id}...")
    result_update = subprocess.run(cmd_update, capture_output=True, text=True)
    print("STDOUT:", result_update.stdout)
    print("STDERR:", result_update.stderr)

import requests
import xml.etree.ElementTree as ET

def fix_existing_posts(blog_dir):
    # Fetch the RSS feed
    rss_url = "https://rss.app/feeds/tZDulmAgUZxm5gyl.xml"
    response = requests.get(rss_url)
    root = ET.fromstring(response.content)
    
    # Create a mapping of titles to image URLs
    image_map = {}
    for item in root.findall('.//item'):
        title = item.find('title').text
        media_content = item.find('{http://search.yahoo.com/mrss/}content')
        if media_content is not None:
            image_url = media_content.get('url')
            image_map[title.lower().strip()] = image_url
    
    print(f"Mapped {len(image_map)} images from RSS feed.")
            
    # Iterate through blog posts and fix them
    import os
    for filename in os.listdir(blog_dir):
        if filename.endswith(".md"):
            path = os.path.join(blog_dir, filename)
            with open(path, 'r') as f:
                content = f.read()
            
            if 'image: "https://image.pollinations.ai' in content:
                # Try to find the title in the frontmatter
                title_match = re.search(r'title: "(.*?)"', content)
                if title_match:
                    post_title = title_match.group(1).lower().strip()
                    # Check if we have a match in the RSS feed
                    # Note: The post title might be slightly different from the RSS title
                    # because of the Groq processing. We'll do a fuzzy match.
                    found_url = None
                    
                    # Try to find a common word or phrase
                    post_words = set(re.findall(r'\w+', post_title))
                    for rss_title, url in image_map.items():
                        rss_words = set(re.findall(r'\w+', rss_title))
                        common_words = post_words.intersection(rss_words)
                        # If more than 3 significant words match, it's likely the same post
                        if len([w for w in common_words if len(w) > 3]) >= 3:
                            found_url = url
                            break
                    
                    if found_url:
                        new_content = re.sub(r'image: "https://image.pollinations.ai.*?"', f'image: "{found_url}"', content)
                        with open(path, 'w') as f:
                            f.write(new_content)
                        print(f"Fixed image for: {filename}")
                    else:
                        print(f"No match for title: {post_title}")

if __name__ == "__main__":
    import sys
    import re
    if len(sys.argv) > 1 and sys.argv[1] == "fix":
        fix_existing_posts("/home/ubuntu/astro-blog/src/content/blog")
    else:
        update_module_11(5001949)

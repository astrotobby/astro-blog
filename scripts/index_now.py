import requests
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# Configuration
HOST = "astrotobby.site"
SITEMAP_URL = f"https://{HOST}/sitemap-0.xml"
INDEXNOW_KEY = "35d54b615d6641adb934edfda54a7d78"
KEY_LOCATION = f"https://{HOST}/{INDEXNOW_KEY}.txt"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/IndexNow"

def get_recent_urls(days=7):
    """Fetch URLs from the sitemap that were updated in the last X days."""
    try:
        response = requests.get(SITEMAP_URL)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        
        # XML namespace
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        recent_urls = []
        cutoff_date = datetime.now() - timedelta(days=days)
        
        for url in root.findall('ns:url', ns):
            loc = url.find('ns:loc', ns).text
            lastmod_el = url.find('ns:lastmod', ns)
            
            if lastmod_el is not None:
                lastmod = datetime.fromisoformat(lastmod_el.text.replace('Z', '+00:00')).replace(tzinfo=None)
                if lastmod >= cutoff_date:
                    recent_urls.append(loc)
            else:
                # If no lastmod, include if it's a blog post (optional heuristic)
                if "/blog/" in loc:
                    recent_urls.append(loc)
                    
        return recent_urls
    except Exception as e:
        print(f"Error fetching sitemap: {e}")
        return []

def submit_to_indexnow(urls):
    """Submit a list of URLs to the IndexNow API."""
    if not urls:
        print("No recent URLs found to submit.")
        return
    
    payload = {
        "host": HOST,
        "key": INDEXNOW_KEY,
        "keyLocation": KEY_LOCATION,
        "urlList": urls
    }
    
    try:
        response = requests.post(
            INDEXNOW_ENDPOINT,
            headers={"Content-Type": "application/json; charset=utf-8"},
            data=json.dumps(payload)
        )
        if response.status_code == 200:
            print(f"Successfully submitted {len(urls)} URLs to IndexNow.")
            for url in urls:
                print(f"  - {url}")
        else:
            print(f"Failed to submit to IndexNow. Status: {response.status_code}, Response: {response.text}")
    except Exception as e:
        print(f"Error during IndexNow submission: {e}")

if __name__ == "__main__":
    print(f"--- Starting Daily Indexing Request: {datetime.now().isoformat()} ---")
    urls_to_index = get_recent_urls(days=1) # Daily check
    
    # Fallback: if no URLs found in last 24h, check last 3 days to be safe
    if not urls_to_index:
        print("No URLs found in last 24h, checking last 3 days...")
        urls_to_index = get_recent_urls(days=3)
        
    submit_to_indexnow(urls_to_index)
    print("--- Indexing Request Complete ---")

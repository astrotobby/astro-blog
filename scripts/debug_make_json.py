import json

def parse_make_file(path):
    with open(path, 'r') as f:
        content = f.read()
    
    # Find the first { and last }
    start = content.find('{')
    end = content.rfind('}')
    
    if start == -1 or end == -1:
        print("Could not find JSON boundaries")
        return None
        
    json_str = content[start:end+1]
    
    try:
        data = json.loads(json_str)
        return data
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {e}")
        # Try to fix common issues if any
        return None

if __name__ == "__main__":
    data = parse_make_file('/home/ubuntu/.mcp/tool-results/2026-06-10_17-41-46_make_scenarios_get.json')
    if data:
        print("Successfully parsed JSON")
        # The structure might be nested
        blueprint = data
        if 'blueprint' in data:
            blueprint = data['blueprint']
        
        flow = blueprint.get('flow', [])
        print(f"Module IDs: {[m.get('id') for m in flow]}")
        
        for module in flow:
            if module.get('id') == 11:
                content = module.get('mapper', {}).get('jsonStringBodyContent', '')
                print(f"Module 11 Content Length: {len(content)}")
                if 'IMAGE_URL_VALUE' in content:
                    print("Found IMAGE_URL_VALUE in Module 11")
                    # Print a bit of context around it
                    idx = content.find('IMAGE_URL_VALUE')
                    print(f"Context: {content[idx-50:idx+100]}")
                else:
                    print("IMAGE_URL_VALUE NOT found in Module 11")

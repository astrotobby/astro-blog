import json

def update_make_scenario(input_path, output_path):
    with open(input_path, 'r') as f:
        content = f.read()
    
    start = content.find('{')
    end = content.rfind('}')
    json_str = content[start:end+1]
    data = json.loads(json_str)
    
    blueprint = data
    if 'blueprint' in data:
        blueprint = data['blueprint']
    
    flow = blueprint.get('flow', [])
    updated = False
    
    for module in flow:
        if module.get('id') == 11:
            mapper = module.get('mapper', {})
            body_content = mapper.get('jsonStringBodyContent', '')
            
            # The exact string we found in the context
            # image: \"IMAGE_URL_VALUE\"
            # - IMAGE_URL_VALUE: https://image.pollinations.ai/prompt/{{encodeURL(8.data.choices[1].message.content)}}
            
            old_url_logic = 'https://image.pollinations.ai/prompt/{{encodeURL(8.data.choices[1].message.content)}}'
            new_url_logic = '{{if(1.image.url; 1.image.url; if(1.enclosures[1].url; 1.enclosures[1].url; "https://loremflickr.com/800/600/business,technology"))}}'
            
            if old_url_logic in body_content:
                new_body_content = body_content.replace(old_url_logic, new_url_logic)
                mapper['jsonStringBodyContent'] = new_body_content
                updated = True
                print("Successfully updated Module 11 image logic.")
            else:
                print("Could not find the old URL logic in Module 11.")
                # Let's try a partial match if the exact one fails
                if 'pollinations.ai' in body_content:
                    print("Found pollinations.ai, but not the exact string. Check escaping.")
    
    if updated:
        # Prepare the payload for scenarios_update
        # It needs the 'blueprint' object containing 'flow' and 'metadata'
        payload = {
            "blueprint": {
                "flow": flow,
                "metadata": blueprint.get('metadata', {})
            }
        }
        with open(output_path, 'w') as f:
            json.dump(payload, f, indent=2)
        print(f"Saved update payload to {output_path}")
        return True
    return False

if __name__ == "__main__":
    update_make_scenario(
        '/home/ubuntu/.mcp/tool-results/2026-06-10_17-41-46_make_scenarios_get.json',
        '/home/ubuntu/make_final_payload.json'
    )

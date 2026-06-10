import json
import re

def update_blueprint(blueprint_str):
    # Load the blueprint
    blueprint = json.loads(blueprint_str)
    
    # Find module 11 (Groq module that generates the markdown)
    found = False
    for module in blueprint.get('flow', []):
        if module.get('id') == 11:
            content = module.get('mapper', {}).get('jsonStringBodyContent', '')
            if 'IMAGE_URL_VALUE' in content:
                # Replace the pollinations URL with a more robust logic
                # We try to use the RSS image, then enclosure, then a keyword-based fallback
                new_image_logic = '{{if(1.image.url; 1.image.url; if(1.enclosures[1].url; 1.enclosures[1].url; "https://loremflickr.com/800/600/business,technology"))}}'
                
                # The content is a JSON string inside a JSON, so we need to be careful with escaping
                # Original: - IMAGE_URL_VALUE: https://image.pollinations.ai/prompt/{{encodeURL(8.data.choices[1].message.content)}}
                old_str = '- IMAGE_URL_VALUE: https://image.pollinations.ai/prompt/{{encodeURL(8.data.choices[1].message.content)}}'
                new_str = f'- IMAGE_URL_VALUE: {new_image_logic}'
                
                new_content = content.replace(old_str, new_str)
                module['mapper']['jsonStringBodyContent'] = new_content
                found = True
                print(f"Updated module 11 content.")
    
    if not found:
        print("Could not find module 11 or IMAGE_URL_VALUE pattern.")
        return None
        
    return blueprint

if __name__ == "__main__":
    with open('/home/ubuntu/make_scenario_5001949_raw.txt', 'r') as f:
        lines = f.readlines()
    
    # Skip the first few lines which are tool execution info
    json_start = 0
    for i, line in enumerate(lines):
        if line.strip() == '{':
            json_start = i
            break
    
    blueprint_raw = "".join(lines[json_start:])
    
    # Remove "Tool execution result:" and similar text if they are at the end
    if "Tool execution result:" in blueprint_raw:
         blueprint_raw = blueprint_raw.split("Tool execution result:")[0]

    updated_blueprint = update_blueprint(blueprint_raw)
    
    if updated_blueprint:
        # We only need the 'flow' and 'metadata' for the update call
        payload = {
            "blueprint": {
                "flow": updated_blueprint['flow'],
                "metadata": updated_blueprint['metadata']
            }
        }
        with open('/home/ubuntu/make_update_payload.json', 'w') as f:
            json.dump(payload, f)
        print("Saved update payload to /home/ubuntu/make_update_payload.json")

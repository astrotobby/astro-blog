import json
import subprocess

def apply_update(payload_path, scenario_id):
    with open(payload_path, 'r') as f:
        payload = json.load(f)
    
    # We only need flow and metadata inside blueprint
    blueprint = payload.get('blueprint', {})
    
    update_payload = {
        "scenarioId": scenario_id,
        "blueprint": {
            "flow": blueprint.get('flow'),
            "metadata": blueprint.get('metadata')
        }
    }
    
    input_data = json.dumps(update_payload)
    
    cmd = [
        "manus-mcp-cli", "tool", "call", "scenarios_update",
        "--server", "make",
        "--input", input_data
    ]
    
    # Run with a longer timeout if possible, or just capture the output
    print(f"Applying update for scenario {scenario_id}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)

if __name__ == "__main__":
    apply_update('/home/ubuntu/make_final_payload.json', 5001949)

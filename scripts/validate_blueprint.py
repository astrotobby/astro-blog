import json

def validate_blueprint(payload_path):
    with open(payload_path, 'r') as f:
        payload = json.load(f)
    
    blueprint = payload.get('blueprint', {})
    
    # We'll call the validate_blueprint_schema tool via shell
    import subprocess
    
    # The tool expects the blueprint directly
    input_data = json.dumps({"blueprint": blueprint})
    
    cmd = [
        "manus-mcp-cli", "tool", "call", "validate_blueprint_schema",
        "--server", "make",
        "--input", input_data
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)

if __name__ == "__main__":
    validate_blueprint('/home/ubuntu/make_final_payload.json')

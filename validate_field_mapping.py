"""
Validate custom field configurations in jira_field_mapping.json
Check if sourceFieldId and targetFieldId actually exist in the corresponding Jira projects
"""
import requests
import json
import os
import base64
from typing import List, Set, Dict, Tuple

# Configuration file paths
CONFIG_FILE = "jira_config.json"
MAPPING_FILE = "jira_field_mapping.json"

def get_auth_headers(auth_type: str, api_token: str, email: str = None) -> Dict:
    """Generate authentication headers based on authType"""
    if auth_type == "Basic":
        if not email:
            raise ValueError("Basic Auth requires email parameter")
        credentials = f"{email}:{api_token}"
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        return {
            "Authorization": f"Basic {encoded_credentials}",
            "Accept": "application/json"
        }
    elif auth_type == "Bearer":
        return {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
    else:
        raise ValueError(f"Unsupported authType: {auth_type}")

def get_base_url(config: Dict) -> str:
    """Build API URL based on configuration"""
    auth_type = config.get("authType", "Basic")
    
    if auth_type == "Basic":
        domain = config.get("domain")
        if not domain:
            raise ValueError("Basic Auth requires domain")
        if domain.startswith("http://") or domain.startswith("https://"):
            base_domain = domain.rstrip("/")
        else:
            base_domain = f"https://{domain}"
        return f"{base_domain}/rest/api/3"
    elif auth_type == "Bearer":
        cloud_id = config.get("cloudId")
        if not cloud_id:
            raise ValueError("Bearer Auth requires cloudId")
        return f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"
    else:
        raise ValueError(f"Unsupported authType: {auth_type}")

def get_all_fields(base_url: str, auth_type: str, api_token: str, email: str = None) -> Set[str]:
    """Get all available field IDs from Jira project"""
    url = f"{base_url}/field"
    headers = get_auth_headers(auth_type, api_token, email)
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            fields = response.json()
            # Extract all field IDs
            field_ids = set()
            for field in fields:
                field_id = field.get("id")
                if field_id:
                    field_ids.add(field_id)
            return field_ids
        else:
            print(f"  Warning: Failed to get field list (Status {response.status_code}): {response.text}")
            return set()
    except Exception as e:
        print(f"  Error: Failed to get field list: {str(e)}")
        return set()

def extract_custom_field_ids(mapping_file: str) -> Tuple[List[str], List[str]]:
    """Extract all sourceFieldId and targetFieldId of custom type from jira_field_mapping.json"""
    if not os.path.exists(mapping_file):
        raise FileNotFoundError(f"Error: Cannot find {mapping_file}")
    
    with open(mapping_file, "r", encoding="utf-8") as f:
        mappings = json.load(f)
    
    source_field_ids = []
    target_field_ids = []
    
    for mapping in mappings:
        if mapping.get("type") == "custom":
            source_field_id = mapping.get("sourceFieldId")
            target_field_id = mapping.get("targetFieldId")
            
            # Ignore null values
            if source_field_id is not None:
                source_field_ids.append(source_field_id)
            if target_field_id is not None:
                target_field_ids.append(target_field_id)
    
    return source_field_ids, target_field_ids

def validate_fields(
    field_ids: List[str],
    available_fields: Set[str],
    field_type: str,
    jira_name: str
) -> Tuple[List[str], List[str]]:
    """Validate if field IDs exist"""
    valid_fields = []
    invalid_fields = []
    
    for field_id in field_ids:
        if field_id in available_fields:
            valid_fields.append(field_id)
        else:
            invalid_fields.append(field_id)
    
    return valid_fields, invalid_fields

def main():
    """Main program"""
    print("=" * 80)
    print("Jira Field Mapping Validation Tool")
    print("=" * 80)
    print()
    
    # 1. Read configuration files
    print("Step 1: Reading configuration files...")
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Error: Cannot find {CONFIG_FILE}")
    
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    source_config = config.get("source", {})
    target_config = config.get("target", {})
    
    if not source_config:
        raise ValueError(f"Error: Cannot find source configuration in {CONFIG_FILE}")
    if not target_config:
        raise ValueError(f"Error: Cannot find target configuration in {CONFIG_FILE}")
    
    print("  ✓ Configuration files read successfully")
    print()
    
    # 2. Extract custom field IDs
    print("Step 2: Extracting custom field IDs from jira_field_mapping.json...")
    source_field_ids, target_field_ids = extract_custom_field_ids(MAPPING_FILE)
    
    print(f"  Found {len(source_field_ids)} sourceFieldId(s)")
    print(f"  Found {len(target_field_ids)} targetFieldId(s)")
    
    if not source_field_ids and not target_field_ids:
        print("  Warning: No custom field configurations found")
        return
    
    print()
    
    # 3. Connect to Source Jira and get all fields
    print("Step 3: Connecting to Source Jira and getting all fields...")
    source_base_url = get_base_url(source_config)
    source_auth_type = source_config.get("authType", "Basic")
    source_api_token = source_config.get("apiToken")
    source_email = source_config.get("email")
    
    print(f"  Source URL: {source_base_url}")
    print(f"  Auth Type: {source_auth_type}")
    
    source_available_fields = get_all_fields(
        source_base_url,
        source_auth_type,
        source_api_token,
        source_email
    )
    print(f"  ✓ Retrieved {len(source_available_fields)} available fields")
    print()
    
    # 4. Connect to Target Jira and get all fields
    print("Step 4: Connecting to Target Jira and getting all fields...")
    target_base_url = get_base_url(target_config)
    target_auth_type = target_config.get("authType", "Bearer")
    target_api_token = target_config.get("apiToken")
    target_email = target_config.get("email")
    
    print(f"  Target URL: {target_base_url}")
    print(f"  Auth Type: {target_auth_type}")
    
    target_available_fields = get_all_fields(
        target_base_url,
        target_auth_type,
        target_api_token,
        target_email
    )
    print(f"  ✓ Retrieved {len(target_available_fields)} available fields")
    print()
    
    # 5. Validate Source fields
    print("Step 5: Validating Source fields...")
    if source_field_ids:
        source_valid, source_invalid = validate_fields(
            source_field_ids,
            source_available_fields,
            "source",
            source_config.get("name", "Source")
        )
        
        print(f"  ✓ Valid fields: {len(source_valid)}")
        if source_valid:
            for field_id in source_valid:
                print(f"    - {field_id}")
        
        print(f"  ✗ Invalid fields: {len(source_invalid)}")
        if source_invalid:
            for field_id in source_invalid:
                print(f"    - {field_id} (not found)")
    else:
        print("  No sourceFieldId to validate")
        source_valid = []
        source_invalid = []
    print()
    
    # 6. Validate Target fields
    print("Step 6: Validating Target fields...")
    if target_field_ids:
        target_valid, target_invalid = validate_fields(
            target_field_ids,
            target_available_fields,
            "target",
            target_config.get("name", "Target")
        )
        
        print(f"  ✓ Valid fields: {len(target_valid)}")
        if target_valid:
            for field_id in target_valid:
                print(f"    - {field_id}")
        
        print(f"  ✗ Invalid fields: {len(target_invalid)}")
        if target_invalid:
            for field_id in target_invalid:
                print(f"    - {field_id} (not found)")
    else:
        print("  No targetFieldId to validate")
        target_valid = []
        target_invalid = []
    print()
    
    # 7. Summary
    print("=" * 80)
    print("Validation Summary")
    print("=" * 80)
    print(f"Source field validation:")
    print(f"  Total: {len(source_field_ids)}")
    print(f"  Valid: {len(source_valid)}")
    print(f"  Invalid: {len(source_invalid)}")
    print()
    print(f"Target field validation:")
    print(f"  Total: {len(target_field_ids)}")
    print(f"  Valid: {len(target_valid)}")
    print(f"  Invalid: {len(target_invalid)}")
    print()
    
    if source_invalid or target_invalid:
        print("❌ Validation failed: Invalid field IDs found")
        print("   Please check field configurations in jira_field_mapping.json")
        return 1
    else:
        print("✅ Validation successful: All field IDs exist")
        return 0

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)


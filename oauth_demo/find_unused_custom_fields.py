"""
檢查 Target Jira 專案中所有 issue 的 custom field 使用情況
找出每個 issue 都沒有使用的 custom field（選擇號碼最大的兩個）
"""
import requests
import json
import os
import base64
import re
from typing import Set, Dict, List

# Configuration file path
CONFIG_FILE = "jira_config.json"

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

def get_all_fields(base_url: str, auth_type: str, api_token: str, email: str = None) -> Dict[str, Dict[str, str]]:
    """Get all available custom field IDs, names, and data types from Jira project"""
    url = f"{base_url}/field"
    headers = get_auth_headers(auth_type, api_token, email)
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            fields = response.json()
            # Extract custom field IDs, names, and types (customfield_*)
            custom_fields = {}
            for field in fields:
                field_id = field.get("id")
                if field_id and field_id.startswith("customfield_"):
                    field_name = field.get("name", "Unknown")
                    # Extract data type from schema
                    schema = field.get("schema", {})
                    field_type = schema.get("type", "Unknown")
                    
                    # Get more specific type information
                    # Common types: string, number, date, datetime, option, array, user, project, etc.
                    custom_type = schema.get("custom", "")
                    if custom_type:
                        # For custom fields, the custom field type name is more descriptive
                        field_type = f"{field_type} ({custom_type})"
                    
                    custom_fields[field_id] = {
                        "name": field_name,
                        "type": field_type
                    }
            return custom_fields
        else:
            print(f"  Warning: Failed to get field list (Status {response.status_code}): {response.text}")
            return {}
    except Exception as e:
        print(f"  Error: Failed to get field list: {str(e)}")
        return {}

def get_all_issues(base_url: str, project_key: str, auth_type: str, api_token: str, email: str = None) -> List[Dict]:
    """Get all issues from the target project"""
    url = f"{base_url}/search/jql"
    headers = get_auth_headers(auth_type, api_token, email)
    
    all_issues = []
    start_at = 0
    max_results = 100
    
    print(f"  Fetching all issues from project {project_key}...")
    
    while True:
        jql_query = f"project = {project_key}"
        params = {
            "jql": jql_query,
            "maxResults": max_results,
            "startAt": start_at,
            "fields": "*all"  # Get all fields including custom fields
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code != 200:
                print(f"  Error: Failed to get issues (Status {response.status_code}): {response.text}")
                break
            
            data = response.json()
            issues = data.get("issues", [])
            
            if not issues:
                break
            
            all_issues.extend(issues)
            print(f"  Retrieved {len(all_issues)} issues...", end='\r')
            
            # Check if there are more issues
            # If returned issues count is less than max_results, we've got all issues
            if len(issues) < max_results:
                break
            
            start_at += max_results
            
        except Exception as e:
            print(f"  Error: Failed to get issues: {str(e)}")
            break
    
    print(f"  Retrieved {len(all_issues)} issues total")
    return all_issues

def extract_custom_field_ids_from_issue(issue: Dict) -> Set[str]:
    """Extract all custom field IDs used in an issue"""
    fields = issue.get("fields", {})
    custom_field_ids = set()
    
    for field_name, field_value in fields.items():
        if field_name.startswith("customfield_") and field_value is not None:
            # Check if the field has a value (not null/empty)
            if isinstance(field_value, dict):
                # For complex fields, check if they have meaningful content
                if field_value:
                    custom_field_ids.add(field_name)
            elif isinstance(field_value, list):
                # For array fields, check if not empty
                if field_value:
                    custom_field_ids.add(field_name)
            else:
                # For simple fields, check if not empty string
                if field_value != "":
                    custom_field_ids.add(field_name)
    
    return custom_field_ids

def extract_number_from_custom_field_id(field_id: str) -> int:
    """Extract the number from custom field ID (e.g., customfield_10229 -> 10229)"""
    match = re.search(r'customfield_(\d+)', field_id)
    if match:
        return int(match.group(1))
    return 0

def find_unused_custom_fields(
    all_available_custom_fields: Dict[str, Dict[str, str]],
    all_used_custom_fields: Set[str]
) -> Dict[str, Dict[str, str]]:
    """Find all custom fields that are not used by any issue"""
    unused_fields = {}
    for field_id, field_info in all_available_custom_fields.items():
        if field_id not in all_used_custom_fields:
            unused_fields[field_id] = field_info
    return unused_fields

def main():
    """Main program"""
    print("=" * 80)
    print("Find Unused Custom Fields in Target Jira Project")
    print("=" * 80)
    print()
    
    # 1. Read configuration
    print("Step 1: Reading configuration...")
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Error: Cannot find {CONFIG_FILE}")
    
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    target_config = config.get("target", {})
    
    if not target_config:
        raise ValueError(f"Error: Cannot find target configuration in {CONFIG_FILE}")
    
    project_key = target_config.get("projectKey")
    if not project_key:
        raise ValueError("Error: projectKey not found in target configuration")
    
    print(f"  ✓ Configuration read successfully")
    print(f"  Target Project: {project_key}")
    print()
    
    # 2. Connect to Target Jira and get all available custom fields
    print("Step 2: Getting all available custom fields from Target Jira...")
    target_base_url = get_base_url(target_config)
    target_auth_type = target_config.get("authType", "Bearer")
    target_api_token = target_config.get("apiToken")
    target_email = target_config.get("email")
    
    all_available_custom_fields = get_all_fields(
        target_base_url,
        target_auth_type,
        target_api_token,
        target_email
    )
    print(f"  ✓ Found {len(all_available_custom_fields)} available custom fields")
    print()
    
    # 3. Get all issues and extract used custom fields
    print("Step 3: Analyzing custom field usage in all issues...")
    all_issues = get_all_issues(
        target_base_url,
        project_key,
        target_auth_type,
        target_api_token,
        target_email
    )
    
    if not all_issues:
        print("  Warning: No issues found in the project")
        return
    
    # Collect all custom fields used by any issue
    all_used_custom_fields = set()
    for issue in all_issues:
        used_fields = extract_custom_field_ids_from_issue(issue)
        all_used_custom_fields.update(used_fields)
    
    print(f"  ✓ Found {len(all_used_custom_fields)} custom fields used by at least one issue")
    print()
    
    # 4. Find all unused custom fields
    print("Step 4: Finding all unused custom fields...")
    unused_fields = find_unused_custom_fields(all_available_custom_fields, all_used_custom_fields)
    
    if not unused_fields:
        print("  Warning: No unused custom fields found")
        return
    
    print(f"  ✓ Found {len(unused_fields)} unused custom fields")
    print()
    
    # 5. Display results
    print("=" * 80)
    print("Results")
    print("=" * 80)
    print(f"Total available custom fields: {len(all_available_custom_fields)}")
    print(f"Custom fields used by issues: {len(all_used_custom_fields)}")
    print(f"Unused custom fields: {len(unused_fields)}")
    print()
    
    # Sort unused fields by field number (descending) for display
    sorted_unused = sorted(
        unused_fields.items(),
        key=lambda x: extract_number_from_custom_field_id(x[0]),
        reverse=True
    )
    
    print("All unused custom fields (sorted by field number, descending):")
    print("-" * 100)
    print(f"{'Field ID':<30} {'Field Name':<40} {'Data Type':<30}")
    print("-" * 100)
    for field_id, field_info in sorted_unused:
        field_name = field_info.get("name", "Unknown")
        field_type = field_info.get("type", "Unknown")
        print(f"{field_id:<30} {field_name:<40} {field_type:<30}")
    print("-" * 100)
    print()
    
    # Also show the two with highest numbers for reference
    if len(sorted_unused) >= 2:
        print("Top 2 unused custom fields (highest numbers) - Recommended for sync metadata:")
        for i, (field_id, field_info) in enumerate(sorted_unused[:2], 1):
            field_number = extract_number_from_custom_field_id(field_id)
            field_name = field_info.get("name", "Unknown")
            field_type = field_info.get("type", "Unknown")
            print(f"  {i}. {field_id} (number: {field_number}) - {field_name} [{field_type}]")
        print()
    
    return unused_fields

if __name__ == "__main__":
    unused_fields = main()
    if unused_fields:
        # Sort by field number (descending) and get top 2
        sorted_unused = sorted(
            unused_fields.items(),
            key=lambda x: extract_number_from_custom_field_id(x[0]),
            reverse=True
        )
        
        if len(sorted_unused) >= 2:
            print("=" * 80)
            print("Next Steps:")
            print("=" * 80)
            print("Top 2 custom field IDs (highest numbers) recommended for sync metadata:")
            field1_id, field1_info = sorted_unused[0]
            field2_id, field2_info = sorted_unused[1]
            print(f"  - {field1_id} ({field1_info.get('name', 'Unknown')}) [{field1_info.get('type', 'Unknown')}] - For remote_issue_id")
            print(f"  - {field2_id} ({field2_info.get('name', 'Unknown')}) [{field2_info.get('type', 'Unknown')}] - For last_sync_time")
            print()
            print("JSON output (for automated processing):")
            print(json.dumps({
                "remote_issue_id_field": field1_id,
                "last_sync_time_field": field2_id
            }, indent=2))


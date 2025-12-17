"""
Jira Issue Synchronization Tool
Sync Issues from Source Jira to Target Jira
"""
import os
import json
import requests
import base64
import re
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Configuration files
CONFIG_FILE = "jira_config.json"
MAPPING_FILE = "jira_field_mapping.json"

# Debug mode settings. When DEBUG_MODE is True:
#     1. Will use "Test" type to query Source Issues, and use "Bug" type to create Target Issue
#     2. Only process source issue key [projectkey]-27979
DEBUG_MODE = True

# Read configuration from jira_config.json
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError(f"Error: Cannot find {CONFIG_FILE}, please ensure the file exists")

try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
        source_config = config.get("source", {})
        target_config = config.get("target", {})
        sync_issue_types = config.get("syncIssueType", [])
except Exception as e:
    raise ValueError(f"Error: Cannot read {CONFIG_FILE}: {e}")

if not source_config:
    raise ValueError(f"Error: Cannot find source configuration in {CONFIG_FILE}")
if not target_config:
    raise ValueError(f"Error: Cannot find target configuration in {CONFIG_FILE}")

# Validate syncIssueType format
if sync_issue_types is not None:
    if not isinstance(sync_issue_types, list):
        raise ValueError(f"Error: syncIssueType format in {CONFIG_FILE} is incorrect, must be a string array")
    for i, item in enumerate(sync_issue_types):
        if not isinstance(item, str):
            raise ValueError(f"Error: syncIssueType format in {CONFIG_FILE} is incorrect, element {i+1} in the array must be a string")

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

class JiraClient:
    """Jira client supporting Basic and Bearer authentication"""
    def __init__(self, config: Dict):
        self.config = config
        self.auth_type = config.get("authType", "Basic")
        self.api_token = config.get("apiToken")
        self.email = config.get("email")
        self.base_url = get_base_url(config)
        self.headers = get_auth_headers(self.auth_type, self.api_token, self.email)

    def test_connection(self):
        """Test connection to Jira API"""
        try:
            url = f"{self.base_url}/myself"
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                user_info = response.json()
                print(f"  ✅ Connection successful - User: {user_info.get('displayName', 'N/A')} ({user_info.get('accountId', 'N/A')})")
                return True
            else:
                self._handle_error(response, "test_connection")
                return False
        except Exception as e:
            print(f"  ❌ Connection failed: {str(e)}")
            return False

    def _handle_error(self, response, operation):
        """Handle HTTP errors and provide detailed diagnostic information"""
        if response.status_code == 410:
            print(f"\n  [Error] HTTP 410 Gone - Resource permanently removed")
            print(f"  Operation: {operation}")
            print(f"  URL: {response.url}")
            print(f"  Possible cause: API endpoint format has changed")
            print(f"  Response content: {response.text[:500]}")
        elif response.status_code == 401:
            print(f"\n  [Error] HTTP 401 Unauthorized - Authentication failed")
            print(f"  Operation: {operation}")
            print(f"  Please check if API Token is correct")
        elif response.status_code == 403:
            print(f"\n  [Error] HTTP 403 Forbidden - Insufficient permissions")
            print(f"  Operation: {operation}")
            print(f"  Please check if API Token has sufficient permissions")
        elif response.status_code == 404:
            print(f"\n  [Error] HTTP 404 Not Found - Resource does not exist")
            print(f"  Operation: {operation}")
            print(f"  URL: {response.url}")

    def search_issues(self, jql: str, max_results: int = 100):
        """Search Issues using the /search/jql API"""
        url = f"{self.base_url}/search/jql"
        all_issues = []
        start_at = 0
        
        while True:
            params = {
                "jql": jql,
                "maxResults": max_results,
                "startAt": start_at,
                "fields": "*all,attachment"  # Ensure attachment field is included
            }
            response = requests.get(url, headers=self.headers, params=params)
            
            if not response.ok:
                self._handle_error(response, f"search_issues (JQL: {jql})")
                response.raise_for_status()
            
            data = response.json()
            issues = data.get('issues', [])
            
            if not issues:
                break
            
            all_issues.extend(issues)
            
            # Check if there are more results
            if len(issues) < max_results:
                break
            
            start_at += max_results
        
        return all_issues

    def create_issue(self, payload):
        """Create Issue"""
        url = f"{self.base_url}/issue"
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code == 201:
            key = response.json()['key']
            print(f"  [Created] New issue key: {key}")
            return key
        else:
            if not response.ok:
                self._handle_error(response, f"create_issue")
            print(f"  [Error Create] {response.status_code}: {response.text}")
            return None

    def update_issue(self, issue_key, fields_dict):
        """Update Issue"""
        url = f"{self.base_url}/issue/{issue_key}"
        payload = {"fields": fields_dict}
        response = requests.put(url, headers=self.headers, json=payload)
        if response.status_code == 204:
            print(f"  [Updated] {issue_key} fields updated.")
        else:
            if not response.ok:
                self._handle_error(response, f"update_issue (key: {issue_key})")
            print(f"  [Error Update] {response.status_code}: {response.text}")

    def get_issue_attachments(self, issue_key):
        """Get all attachments of an Issue"""
        url = f"{self.base_url}/issue/{issue_key}"
        params = {"fields": "attachment"}
        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code == 200:
            issue_data = response.json()
            return issue_data.get('fields', {}).get('attachment', [])
        else:
            self._handle_error(response, f"get_issue_attachments (key: {issue_key})")
            return []

    def download_attachment(self, attachment, local_path):
        """Download attachment to local"""
        content_url = attachment.get('content')
        if not content_url:
            return False
        
        try:
            response = requests.get(content_url, headers=self.headers, stream=True)
            if response.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            else:
                print(f"    Warning: Cannot download attachment (Status {response.status_code})")
                return False
        except Exception as e:
            print(f"    Error: Error occurred while downloading attachment: {str(e)}")
            return False

    def upload_attachment(self, issue_key, file_path):
        """Upload attachment to Issue"""
        url = f"{self.base_url}/issue/{issue_key}/attachments"
        # Upload attachment requires multipart/form-data
        headers = self.headers.copy()
        headers.pop('Content-Type', None)  # Remove Content-Type to let requests set it automatically
        # Jira API requires X-Atlassian-Token header
        headers['X-Atlassian-Token'] = 'no-check'
        
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (os.path.basename(file_path), f, 'application/octet-stream')}
                response = requests.post(url, headers=headers, files=files)
            
            if response.status_code == 200:
                return True
            else:
                self._handle_error(response, f"upload_attachment (key: {issue_key})")
                return False
        except Exception as e:
            print(f"    Error: Error occurred while uploading attachment: {str(e)}")
            return False

class FieldProcessor:
    """Handle field mapping logic"""
    def __init__(self, mapping_config):
        self.mapping_config = mapping_config

    def adf_to_text(self, adf_content):
        """Convert ADF (Atlassian Document Format) to plain text string"""
        if not isinstance(adf_content, dict):
            return None
        
        # Check if it's ADF format (usually has type: "doc" and content field)
        if adf_content.get('type') == 'doc' and 'content' in adf_content:
            text_parts = []
            self._extract_text_from_adf(adf_content.get('content', []), text_parts)
            return '\n'.join(text_parts)
        
        return None
    
    def _extract_text_from_adf(self, content, text_parts):
        """Recursively extract text from ADF content"""
        if not isinstance(content, list):
            return
        
        for item in content:
            if isinstance(item, dict):
                # If it's a text node, extract text
                if item.get('type') == 'text' and 'text' in item:
                    text_parts.append(item['text'])
                # If it's a paragraph or other container, process recursively
                elif 'content' in item:
                    self._extract_text_from_adf(item['content'], text_parts)
                # Handle hard break
                elif item.get('type') == 'hardBreak':
                    text_parts.append('\n')
    
    def text_to_adf(self, text):
        """Convert plain text string to ADF (Atlassian Document Format)"""
        if not isinstance(text, str):
            return None
        
        # If text is empty, return empty ADF document
        if not text.strip():
            return {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": []
                    }
                ]
            }
        
        # Split text by newline, each non-empty line as a paragraph
        lines = [line for line in text.split('\n') if line.strip()]
        
        if not lines:
            return {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": []
                    }
                ]
            }
        
        # Create a paragraph for each non-empty line
        paragraphs = []
        for line in lines:
            paragraphs.append({
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": line
                    }
                ]
            })
        
        return {
            "type": "doc",
            "version": 1,
            "content": paragraphs
        }
    
    def add_prefix_to_adf(self, adf_content, prefix):
        """Add prefix before the first text node in ADF format"""
        if not isinstance(adf_content, dict) or adf_content.get('type') != 'doc':
            return None
        
        # Deep copy ADF structure
        import copy
        new_adf = copy.deepcopy(adf_content)
        
        # Find the first text node in the first paragraph
        content = new_adf.get('content', [])
        for paragraph in content:
            if paragraph.get('type') == 'paragraph':
                para_content = paragraph.get('content', [])
                # Find the first text node
                for i, item in enumerate(para_content):
                    if item.get('type') == 'text':
                        text = item.get('text', '')
                        # Check if prefix already exists
                        if not text.startswith(prefix):
                            # Insert prefix text node before the first text node
                            prefix_node = {
                                "type": "text",
                                "text": f"{prefix} "
                            }
                            para_content.insert(i, prefix_node)
                        return new_adf
        
        # If no text node found, add prefix and text in the first paragraph
        if content and content[0].get('type') == 'paragraph':
            content[0].setdefault('content', []).insert(0, {
                "type": "text",
                "text": f"{prefix} "
            })
        else:
            # Create new paragraph
            new_adf['content'] = [{
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": f"{prefix} "
                    }
                ]
            }]
        
        return new_adf

    def format_field_value(self, field_value, config_item):
        """Format field value based on field type"""
        target_field_id = config_item.get('targetFieldId', '')
        field_data_type = config_item.get('targetFieldDataType', config_item.get('dataType'))
        
        # If already in dict format, return directly
        if isinstance(field_value, dict):
            return field_value
        
        # Format based on field type
        if field_data_type:
            # Option list fields (single or multiple choice)
            if field_data_type in ['option', 'select', 'com.atlassian.jira.plugin.system.customfieldtypes:select']:
                return {"value": field_value}
            # Multi-select option list
            elif field_data_type in ['array', 'multiselect', 'com.atlassian.jira.plugin.system.customfieldtypes:multiselect']:
                if isinstance(field_value, list):
                    return [{"value": v} if isinstance(v, str) else v for v in field_value]
                else:
                    return [{"value": field_value}]
            # Text fields
            elif field_data_type in ['string', 'text', 'textarea']:
                return field_value
            # Number fields
            elif field_data_type in ['number', 'float']:
                return field_value
            # Date fields
            elif field_data_type in ['date', 'datetime']:
                # Jira date fields require YYYY-MM-DD format, if ISO 8601 format, only take date part
                if isinstance(field_value, str):
                    # If ISO 8601 format (contains T), only take date part
                    if 'T' in field_value:
                        return field_value.split('T')[0]
                    # If already in date format, return directly
                    return field_value
                return field_value
        
        # If type not specified, infer from field ID
        if 'customfield' in str(target_field_id):
            # For custom fields, if string, assume option list, use {"value": "..."} format
            if isinstance(field_value, str):
                return {"value": field_value}
        
        return field_value

    def resolve_value(self, input_val, config_item, direction="S2T"):
        """Resolve field value and transform based on strategy"""
        strategy = config_item.get('strategy', 'DIRECT_COPY')

        if strategy == 'STATIC_VALUE':
            static_value = config_item.get('static_value', {})
            return static_value.get('value') if isinstance(static_value, dict) else static_value

        if strategy == 'SYNC_METADATA':
            # SYNC_METADATA strategy is handled in prepare_create_payload and prepare_update_payload
            return None

        if strategy == 'DIRECT_COPY':
            return input_val

        if strategy == 'MAPPED_SYNC':
            # Handle object value extraction (e.g., priority: {name: 'High'})
            raw_val = input_val
            if isinstance(input_val, dict):
                raw_val = input_val.get('name') or input_val.get('value') or input_val

            if direction == "S2T":
                mapping = config_item.get('valueMapping', {})
                mapped_val = mapping.get(raw_val)
                # Return appropriate format based on field type
                if mapped_val:
                    field_type = config_item.get('type')
                    field_id = config_item.get('fieldId', '')
                    
                    # Priority field requires {"name": "..."} format
                    if field_type == 'system' and field_id == 'priority':
                        return {"name": mapped_val}
                    
                    # Custom fields (option list) require {"value": "..."} format
                    if field_type == 'custom' or 'customfield' in str(config_item.get('targetFieldId', '')):
                        return {"value": mapped_val}
                    
                    # Other system fields return string
                    return mapped_val
                return None

            elif direction == "T2S":
                # 1. Check reverseMapping (Explicit)
                reverse_map = config_item.get('reverseMapping', {})
                if raw_val in reverse_map:
                    return {"value": reverse_map[raw_val]}

                # 2. Check valueMapping reverse (Implicit)
                forward_map = config_item.get('valueMapping', {})
                for k, v in forward_map.items():
                    if v == raw_val:
                        return {"value": k}
        
        return None

    def prepare_create_payload(self, source_issue, target_project_key, issue_type, customer_issue_id_field: str):
        """Prepare payload for creating Issue"""
        payload = {
            "fields": {
                "project": {"key": target_project_key},
                "issuetype": {"name": issue_type}
            }
        }

        for item in self.mapping_config:
            sync_direction = item.get('syncDirection', 'S2T')
            if sync_direction != 'S2T' and sync_direction != 'BIDIRECTIONAL':
                continue

            strategy = item.get('strategy', 'DIRECT_COPY')
            
            # Handle SYNC_METADATA strategy
            # Note: These fields are not set during creation, but updated immediately after creation
            # because some issue type creation screens may not include these fields
            if strategy == 'SYNC_METADATA':
                # Skip, will be updated separately after issue creation
                continue

            # Handle STATIC_VALUE strategy
            # Note: Some STATIC_VALUE fields may not be settable during creation (e.g., some issue type creation screens don't include these fields)
            # These fields will be updated separately after creation
            if strategy == 'STATIC_VALUE':
                trigger_on = item.get('triggerOn', item.get('trigger_on', ['CREATE', 'UPDATE']))
                if 'CREATE' in trigger_on:
                    # Temporarily skip, will be updated separately after creation (to avoid field restrictions during creation)
                    # If needed, add logic here to determine which fields can be set during creation
                    continue

            # Handle general fields
            field_type = item.get('type')
            
            if field_type == 'system':
                # System fields use fieldId
                source_field = item.get('fieldId')
                target_field = item.get('fieldId')  # System fields usually have the same name
            else:
                # Custom fields use sourceFieldId and targetFieldId
                source_field = item.get('sourceFieldId')
                target_field = item.get('targetFieldId')
            
            if source_field and target_field:
                # Skip attachment field, as Jira API does not allow setting attachment during creation
                if field_type == 'system' and source_field == 'attachment':
                    continue
                
                src_val = source_issue['fields'].get(source_field)
                if src_val is not None:
                    target_val = self.resolve_value(src_val, item, "S2T")
                    if target_val is not None:
                        # Handle field prefix (read from config, supports all S2T direction fields)
                        prefix = item.get('prefix', '')
                        if prefix:
                            # If value is ADF format (dict), add prefix directly in ADF
                            if isinstance(target_val, dict) and target_val.get('type') == 'doc':
                                # Save original value for fallback
                                original_adf = target_val
                                target_val = self.add_prefix_to_adf(target_val, prefix)
                                if target_val is None:
                                    # If adding failed, use original ADF content directly
                                    target_val = original_adf
                            # Handle string type prefix
                            elif isinstance(target_val, str):
                                # Check if prefix already exists
                                if not target_val.startswith(prefix):
                                    target_val = f'{prefix} {target_val}'
                        payload["fields"][target_field] = target_val

        return payload

    def prepare_update_payload(self, source_issue, target_issue, direction: str, customer_issue_id_field: str, last_sync_time_field: str):
        """Prepare payload for updating Issue"""
        update_fields = {}

        for item in self.mapping_config:
            sync_direction = item.get('syncDirection', 'S2T')
            
            # Check sync direction
            if sync_direction != "BIDIRECTIONAL" and sync_direction != direction:
                continue

            strategy = item.get('strategy', 'DIRECT_COPY')
            
            # Ignore STATIC_VALUE that only triggers on Create
            if strategy == 'STATIC_VALUE':
                trigger_on = item.get('triggerOn', item.get('trigger_on', ['CREATE', 'UPDATE']))
                if 'UPDATE' not in trigger_on:
                    continue
                # Handle STATIC_VALUE update
                static_value = item.get('staticValue', item.get('static_value', {}))
                target_field_id = item.get('targetFieldId')
                if target_field_id:
                    if isinstance(static_value, dict):
                        update_fields[target_field_id] = static_value.get('value')
                    else:
                        update_fields[target_field_id] = static_value
                continue

            # Handle SYNC_METADATA strategy
            if strategy == 'SYNC_METADATA':
                metadata_type = item.get('metadataType')
                target_field_id = item.get('targetFieldId')
                
                if metadata_type == 'last_sync_time' and target_field_id:
                    # Update sync time
                    current_time = datetime.now().isoformat()
                    update_fields[target_field_id] = current_time
                continue

            field_type = item.get('type')
            
            if direction == "S2T":
                if field_type == 'system':
                    # System fields use fieldId
                    source_field = item.get('fieldId')
                    target_field = item.get('fieldId')
                else:
                    # Custom fields use sourceFieldId and targetFieldId
                    source_field = item.get('sourceFieldId')
                    target_field = item.get('targetFieldId')
                
                if source_field and target_field:
                    # Skip attachment field, as Jira API does not allow setting attachment through field update API
                    # attachment should be handled through dedicated attachment API
                    if field_type == 'system' and source_field == 'attachment':
                        continue
                    
                    src_val = source_issue['fields'].get(source_field)
                    if src_val is not None:
                        val = self.resolve_value(src_val, item, "S2T")
                        if val is not None:
                            # Handle field prefix (read from config, supports all S2T direction fields)
                            prefix = item.get('prefix', '')
                            if prefix:
                                # If value is ADF format (dict), add prefix directly in ADF
                                if isinstance(val, dict) and val.get('type') == 'doc':
                                    # Save original value for fallback
                                    original_adf = val
                                    val = self.add_prefix_to_adf(val, prefix)
                                    if val is None:
                                        # If adding failed, use original ADF content directly
                                        val = original_adf
                                # Handle string type prefix
                                elif isinstance(val, str):
                                    # Check if prefix already exists
                                    if not val.startswith(prefix):
                                        val = f'{prefix} {val}'
                            update_fields[target_field] = val

            elif direction == "T2S":
                if field_type == 'system':
                    # System fields use fieldId
                    source_field = item.get('fieldId')
                    target_field = item.get('fieldId')
                else:
                    # Custom fields use sourceFieldId and targetFieldId
                    source_field = item.get('sourceFieldId')
                    target_field = item.get('targetFieldId')
                
                if source_field and target_field:
                    # Skip attachment field, as Jira API does not allow setting attachment through field update API
                    # attachment should be handled through dedicated attachment API
                    if field_type == 'system' and target_field == 'attachment':
                        continue
                    
                    tgt_val = target_issue['fields'].get(target_field)
                    if tgt_val is not None:
                        val = self.resolve_value(tgt_val, item, "T2S")
                        if val is not None:
                            update_fields[source_field] = val

        return update_fields

def get_customer_issue_id_field_info(mappings: List[Dict]) -> Tuple[Optional[str], Optional[str]]:
    """
    Get customer_issue_id field ID and Name from mapping configuration.
    Returns (field_id, field_name). field_name may be None if not provided.
    """
    for item in mappings:
        if item.get('strategy') == 'SYNC_METADATA' and item.get('metadataType') == 'customer_issue_id':
            return item.get('targetFieldId'), item.get('targetFieldName')
    return None, None

def get_last_sync_time_field(mappings: List[Dict]) -> Optional[str]:
    """Get last_sync_time field ID from mapping configuration"""
    for item in mappings:
        if item.get('strategy') == 'SYNC_METADATA' and item.get('metadataType') == 'last_sync_time':
            return item.get('targetFieldId')
    return None

def remove_prefix_from_filename(filename: str) -> str:
    """Remove prefix from filename (format: [PROJECT_KEY])"""
    # Match format: [PROJECT_KEY] filename
    pattern = r'^\[[^\]]+\]\s+(.+)$'
    match = re.match(pattern, filename)
    if match:
        return match.group(1)
    return filename

def get_filename_with_prefix(filename: str, project_key: str) -> str:
    """Add prefix to filename (using project key)"""
    # Format: [PROJECT_KEY] filename
    prefix = f"[{project_key}]"
    # If prefix already exists, remove it first
    clean_filename = remove_prefix_from_filename(filename)
    return f"{prefix} {clean_filename}"

def ensure_local_attachment_dir(target_issue_key: str) -> str:
    """Ensure local attachment directory exists, return directory path"""
    dir_path = target_issue_key
    os.makedirs(dir_path, exist_ok=True)
    return dir_path

def download_attachment_to_local(
    jira_client: JiraClient,
    attachment: Dict,
    local_dir: str,
    project_key: str
) -> Optional[str]:
    """Download attachment to local directory, return local file path"""
    filename = attachment.get('filename', 'unknown')
    prefixed_filename = get_filename_with_prefix(filename, project_key)
    local_path = os.path.join(local_dir, prefixed_filename)
    
    # If file already exists, skip download
    if os.path.exists(local_path):
        return local_path
    
    if jira_client.download_attachment(attachment, local_path):
        return local_path
    return None

def get_local_attachments(local_dir: str) -> List[str]:
    """Get all attachment file names in local directory (prefix removed)"""
    if not os.path.exists(local_dir):
        return []
    
    attachments = []
    for filename in os.listdir(local_dir):
        file_path = os.path.join(local_dir, filename)
        if os.path.isfile(file_path):
            # Name after removing prefix
            clean_name = remove_prefix_from_filename(filename)
            attachments.append(clean_name)
    return attachments

def sync_attachments(
    source_issue: Dict,
    target_issue: Dict,
    direction: str,
    source_jira: JiraClient,
    target_jira: JiraClient,
    source_project_key: str,
    target_project_key: str,
    target_issue_key: str
):
    """Sync attachments - MERGE strategy: Ensure both sides have complete attachment union"""
    print(f"  -> Syncing attachments (MERGE strategy)...")
    
    # Ensure local directory exists
    local_dir = ensure_local_attachment_dir(target_issue_key)
    
    # Get attachment lists from source and target (need to re-fetch to ensure latest attachments are included)
    source_attachments = source_jira.get_issue_attachments(source_issue['key'])
    target_attachments = target_jira.get_issue_attachments(target_issue_key)
    
    # Build attachment map: use filename without prefix as key
    # For quick lookup of whether attachment exists
    source_attachment_map = {}  # {clean_name: attachment}
    target_attachment_map = {}   # {clean_name: attachment}
    
    for attachment in source_attachments:
        filename = attachment.get('filename', '')
        clean_name = remove_prefix_from_filename(filename)
        source_attachment_map[clean_name] = attachment
    
    for attachment in target_attachments:
        filename = attachment.get('filename', '')
        clean_name = remove_prefix_from_filename(filename)
        target_attachment_map[clean_name] = attachment
    
    # Get locally existing attachments (names without prefix)
    local_attachments = get_local_attachments(local_dir)
    
    # Download all attachments to local (if not already exists)
    # First get local file list (names without prefix)
    local_attachments_set = set(local_attachments)
    
    for attachment in source_attachments:
        filename = attachment.get('filename', '')
        clean_name = remove_prefix_from_filename(filename)
        
        # Check if file already exists locally (compare after removing prefix)
        if clean_name not in local_attachments_set:
            print(f"    Downloading Source attachment: {filename}")
            local_path = download_attachment_to_local(
                source_jira, attachment, local_dir,
                source_project_key
            )
            if local_path:
                # After successful download, update local file list
                local_attachments_set.add(clean_name)
        else:
            print(f"    Skipping Source attachment download (already exists locally): {filename}")
    
    for attachment in target_attachments:
        filename = attachment.get('filename', '')
        clean_name = remove_prefix_from_filename(filename)
        
        # Check if file already exists locally (compare after removing prefix)
        if clean_name not in local_attachments_set:
            print(f"    Downloading Target attachment: {filename}")
            local_path = download_attachment_to_local(
                target_jira, attachment, local_dir,
                target_project_key
            )
            if local_path:
                # After successful download, update local file list
                local_attachments_set.add(clean_name)
        else:
            print(f"    Skipping Target attachment download (already exists locally): {filename}")
    
    # MERGE strategy: Ensure both sides have complete attachment union
    # 1. Upload missing attachments from source to target (filename with [SOURCE_PROJECT_KEY] prefix)
    for attachment in source_attachments:
        filename = attachment.get('filename', '')
        clean_name = remove_prefix_from_filename(filename)
        
        # Check if target already has this attachment (compare after removing prefix)
        if clean_name not in target_attachment_map:
            # Before uploading, check again if target issue already has this attachment (may have been added during upload process)
            # Re-fetch target issue attachment list
            current_target_attachments = target_jira.get_issue_attachments(target_issue_key)
            target_has_file = False
            for t_att in current_target_attachments:
                t_filename = t_att.get('filename', '')
                t_clean_name = remove_prefix_from_filename(t_filename)
                if t_clean_name == clean_name:
                    target_has_file = True
                    print(f"    Skipping Source attachment upload to Target (target already exists): {filename} (target has: {t_filename})")
                    break
            
            if target_has_file:
                continue
            
            # Get file from local (with project key prefix)
            local_filename = get_filename_with_prefix(filename, source_project_key)
            local_path = os.path.join(local_dir, local_filename)
            
            if os.path.exists(local_path):
                # Upload to target, filename with [SOURCE_PROJECT_KEY] prefix
                prefixed_filename = get_filename_with_prefix(filename, source_project_key)
                print(f"    Uploading attachment to Target: {prefixed_filename}")
                
                # If local file already has correct prefix filename, use it directly
                # Otherwise create temporary file
                if os.path.basename(local_path) == prefixed_filename:
                    # Filename same, use local file directly
                    upload_path = local_path
                else:
                    # Create temporary file with prefixed filename
                    import shutil
                    import tempfile
                    # Use system temp directory to avoid file locking issues
                    temp_dir = tempfile.gettempdir()
                    temp_path = os.path.join(temp_dir, prefixed_filename)
                    try:
                        shutil.copy2(local_path, temp_path)
                        upload_path = temp_path
                    except PermissionError as e:
                        print(f"    Warning: Cannot copy file (may be used by another process): {str(e)}")
                        # Try to use local file directly
                        upload_path = local_path
                    except Exception as e:
                        print(f"    Error: Error occurred while copying file: {str(e)}")
                        continue
                
                # Upload attachment
                if target_jira.upload_attachment(target_issue_key, upload_path):
                    # If temporary file was used, delete it
                    if upload_path != local_path and os.path.exists(upload_path):
                        try:
                            os.remove(upload_path)
                        except Exception as e:
                            print(f"    Warning: Cannot delete temporary file: {str(e)}")
            else:
                print(f"    Warning: Local file does not exist, cannot upload: {local_path}")
    
    # 2. Upload missing attachments from target to source (filename with [TARGET_PROJECT_KEY] prefix)
    for attachment in target_attachments:
        filename = attachment.get('filename', '')
        clean_name = remove_prefix_from_filename(filename)
        
        # Check if source already has this attachment (compare after removing prefix)
        if clean_name not in source_attachment_map:
            # Before uploading, check again if source issue already has this attachment (may have been added during upload process)
            # Re-fetch source issue attachment list
            current_source_attachments = source_jira.get_issue_attachments(source_issue['key'])
            source_has_file = False
            for s_att in current_source_attachments:
                s_filename = s_att.get('filename', '')
                s_clean_name = remove_prefix_from_filename(s_filename)
                if s_clean_name == clean_name:
                    source_has_file = True
                    print(f"    Skipping Target attachment upload to Source (target already exists): {filename} (target has: {s_filename})")
                    break
            
            if source_has_file:
                continue
            
            # Get file from local (with project key prefix)
            local_filename = get_filename_with_prefix(filename, target_project_key)
            local_path = os.path.join(local_dir, local_filename)
            
            if os.path.exists(local_path):
                # Upload to source, filename with [TARGET_PROJECT_KEY] prefix
                prefixed_filename = get_filename_with_prefix(filename, target_project_key)
                print(f"    Uploading attachment to Source: {prefixed_filename}")
                
                # If local file already has correct prefix filename, use it directly
                # Otherwise create temporary file
                if os.path.basename(local_path) == prefixed_filename:
                    # Filename same, use local file directly
                    upload_path = local_path
                else:
                    # Create temporary file with prefixed filename
                    import shutil
                    import tempfile
                    # Use system temp directory to avoid file locking issues
                    temp_dir = tempfile.gettempdir()
                    temp_path = os.path.join(temp_dir, prefixed_filename)
                    try:
                        shutil.copy2(local_path, temp_path)
                        upload_path = temp_path
                    except PermissionError as e:
                        print(f"    Warning: Cannot copy file (may be used by another process): {str(e)}")
                        # Try to use local file directly
                        upload_path = local_path
                    except Exception as e:
                        print(f"    Error: Error occurred while copying file: {str(e)}")
                        continue
                
                # Upload attachment
                if source_jira.upload_attachment(source_issue['key'], upload_path):
                    # If temporary file was used, delete it
                    if upload_path != local_path and os.path.exists(upload_path):
                        try:
                            os.remove(upload_path)
                        except Exception as e:
                            print(f"    Warning: Cannot delete temporary file: {str(e)}")
            else:
                print(f"    Warning: Local file does not exist, cannot upload: {local_path}")

def run_sync():
    """Execute synchronization process"""
    print("=" * 80)
    print("Jira Issue Synchronization Tool")
    if DEBUG_MODE:
        print("  [DEBUG MODE Enabled]")
        print("    - Source query type: Test")
        print("    - Target create type: Bug")
        print("    - Only process issue key: [projectkey]-27979")
    print("=" * 80)
    print()

    # Read field mapping configuration
    if not os.path.exists(MAPPING_FILE):
        raise FileNotFoundError(f"Error: Cannot find {MAPPING_FILE}")
    
    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        mappings = json.load(f)
    
    processor = FieldProcessor(mappings)
    
    # Get sync metadata field IDs
    customer_issue_id_field, customer_issue_id_field_name = get_customer_issue_id_field_info(mappings)
    last_sync_time_field = get_last_sync_time_field(mappings)
    
    if not customer_issue_id_field:
        print("Warning: Cannot find customer_issue_id field configuration, will not be able to track synced issues")
    
    # Initialize Source and Target Clients
    source_jira = JiraClient(source_config)
    target_jira = JiraClient(target_config)

    # Test connection
    print("[0] Testing connection...")
    print("  Source Jira:")
    source_ok = source_jira.test_connection()
    print("  Target Jira:")
    target_ok = target_jira.test_connection()

    if not source_ok or not target_ok:
        print("\n⚠️  Connection test failed, please check configuration and retry")
        return
    
    print()

    # 1. Get Source Issues
    print("[1] Getting Source Issues...")
    source_project_key = source_config.get("projectKey")
    
    # Build JQL query, including syncIssueType filter
    jql_parts = [f"project = {source_project_key}"]
    
    # Debug mode: use ["Test"] to query source issues
    # Production mode: use syncIssueType configuration
    if DEBUG_MODE:
        print("  [DEBUG MODE] Using Test type to query Source Issues")
        source_issue_types = ["Test"]
        issue_type_filter = " OR ".join([f'issuetype = "{it}"' for it in source_issue_types])
        jql_parts.append(f"({issue_type_filter})")
    elif sync_issue_types:
        issue_type_filter = " OR ".join([f'issuetype = "{it}"' for it in sync_issue_types])
        jql_parts.append(f"({issue_type_filter})")
    
    if DEBUG_MODE:
        jql_parts.append("updated >= -1d")  # Updated in last 1 day
    
    # Build JQL: join conditions with AND, add ORDER BY separately
    source_jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"
    print(f"  JQL: {source_jql}")
    
    source_issues = source_jira.search_issues(source_jql)
    print(f"  Found {len(source_issues)} Source Issues")
    
    # Debug mode: only process specified issue key
    if DEBUG_MODE:
        debug_issue_key = f"{source_project_key}-27979"
        print(f"  [DEBUG MODE] Filtering to only process issue key: {debug_issue_key}")
        filtered_issues = [issue for issue in source_issues if issue.get('key') == debug_issue_key]
        if filtered_issues:
            source_issues = filtered_issues
            print(f"  Found matching Debug Issue: {debug_issue_key}")
        else:
            print(f"  Warning: Issue key {debug_issue_key} not found, will process all found issues")
    
    print()

    # 2. Get Target Issues (based on customer_issue_id field)
    print("[2] Getting Target Issues...")
    target_project_key = target_config.get("projectKey")
    
    if customer_issue_id_field_name:
        target_jql = f'project = {target_project_key} AND "{customer_issue_id_field_name}" is not EMPTY'
    elif customer_issue_id_field:
        target_jql = f"project = {target_project_key} AND {customer_issue_id_field} is not EMPTY"
    else:
        # If no customer_issue_id field, get all issues
        target_jql = f"project = {target_project_key}"
    
    print(f"  JQL: {target_jql}")
    target_issues = target_jira.search_issues(target_jql)
    print(f"  Found {len(target_issues)} Target Issues")
    print()

    # 3. Build Lookup Map (based on customer_issue_id)
    target_map = {}
    for t in target_issues:
        if customer_issue_id_field:
            remote_val = t['fields'].get(customer_issue_id_field)
            # Handle different value formats
            if isinstance(remote_val, dict):
                remote_val = remote_val.get('value') or remote_val.get('name')
            if remote_val:
                target_map[str(remote_val)] = t
        else:
            # If no customer_issue_id field, cannot build mapping
            pass

    # 4. Execute synchronization
    print("[3] Executing synchronization...")
    print()
    
    created_count = 0
    updated_count = 0
    skipped_count = 0
    
    for s_issue in source_issues:
        s_key = s_issue['key']
        print(f"Processing: {s_key}")

        if s_key not in target_map:
            # Create
            print("  -> Creating new Target Issue...")
            # Get issue type
            if DEBUG_MODE:
                # Debug mode: use Bug type to create target issue
                issue_type = "Bug"
                print(f"  [DEBUG MODE] Using Bug type to create Target Issue")
            else:
                # Production mode: get issue type from source issue or use default
                issue_type = s_issue['fields'].get('issuetype', {}).get('name', 'Bug')
            
            payload = processor.prepare_create_payload(
                s_issue, 
                target_project_key, 
                issue_type,
                customer_issue_id_field
            )
            new_key = target_jira.create_issue(payload)
            if new_key:
                created_count += 1
                
                # Immediately update SYNC_METADATA and STATIC_VALUE fields after creation
                post_create_fields = {}
                
                # Update SYNC_METADATA fields (customer_issue_id and last_sync_time)
                if customer_issue_id_field:
                    # Find corresponding config item to get field type
                    customer_issue_id_config = None
                    for item in mappings:
                        if (item.get('strategy') == 'SYNC_METADATA' and 
                            item.get('metadataType') == 'customer_issue_id' and
                            item.get('targetFieldId') == customer_issue_id_field):
                            customer_issue_id_config = item
                            break
                    
                    # Format field value
                    if customer_issue_id_config:
                        formatted_value = processor.format_field_value(s_key, customer_issue_id_config)
                        post_create_fields[customer_issue_id_field] = formatted_value
                    else:
                        post_create_fields[customer_issue_id_field] = s_key
                
                if last_sync_time_field:
                    current_time = datetime.now().isoformat()
                    # Find corresponding config item to get field type
                    last_sync_time_config = None
                    for item in mappings:
                        if (item.get('strategy') == 'SYNC_METADATA' and 
                            item.get('metadataType') == 'last_sync_time' and
                            item.get('targetFieldId') == last_sync_time_field):
                            last_sync_time_config = item
                            break
                    
                    # Format field value
                    if last_sync_time_config:
                        formatted_value = processor.format_field_value(current_time, last_sync_time_config)
                        post_create_fields[last_sync_time_field] = formatted_value
                    else:
                        post_create_fields[last_sync_time_field] = current_time
                
                # Update STATIC_VALUE fields (triggered on CREATE)
                for item in mappings:
                    if item.get('strategy') == 'STATIC_VALUE':
                        trigger_on = item.get('triggerOn', item.get('trigger_on', ['CREATE', 'UPDATE']))
                        if 'CREATE' in trigger_on:
                            static_value = item.get('staticValue', item.get('static_value', {}))
                            target_field_id = item.get('targetFieldId')
                            if target_field_id:
                                # Extract actual value
                                if isinstance(static_value, dict):
                                    actual_value = static_value.get('value', static_value)
                                else:
                                    actual_value = static_value
                                
                                # Use format_field_value to format field value
                                formatted_value = processor.format_field_value(actual_value, item)
                                post_create_fields[target_field_id] = formatted_value
                
                if post_create_fields:
                    print(f"  -> Updating metadata and static value fields...")
                    # Update fields separately, skip fields that cannot be set
                    successful_fields = {}
                    failed_fields = {}
                    
                    for field_id, field_value in post_create_fields.items():
                        try:
                            # Try to update each field separately
                            test_update = {field_id: field_value}
                            url = f"{target_jira.base_url}/issue/{new_key}"
                            payload = {"fields": test_update}
                            response = requests.put(url, headers=target_jira.headers, json=payload)
                            
                            if response.status_code == 204:
                                successful_fields[field_id] = field_value
                            else:
                                # Parse error response
                                error_msg = response.text
                                try:
                                    error_json = response.json()
                                    if 'errors' in error_json:
                                        error_details = error_json['errors'].get(field_id, 'Unknown error')
                                        error_msg = f"{error_details}"
                                    elif 'errorMessages' in error_json:
                                        error_msg = '; '.join(error_json['errorMessages'])
                                except:
                                    pass
                                
                                failed_fields[field_id] = error_msg
                                print(f"    Warning: Cannot set field {field_id}: {response.status_code}")
                                print(f"    Error details: {error_msg}")
                                print(f"    Attempted value: {json.dumps(field_value, ensure_ascii=False)}")
                        except Exception as e:
                            failed_fields[field_id] = str(e)
                            print(f"    Warning: Error occurred while setting field {field_id}: {str(e)}")
                            print(f"    Attempted value: {json.dumps(field_value, ensure_ascii=False)}")
                    
                    # If there are successful fields, batch update
                    if successful_fields:
                        target_jira.update_issue(new_key, successful_fields)
                    
                    # If there are failed fields, log warning
                    if failed_fields:
                        print(f"    Warning: The following fields cannot be set: {list(failed_fields.keys())}")
                        print(f"    These fields may not be on the current issue type's edit screen, or the value format is incorrect")
                        # Display detailed error for each failed field
                        for field_id, error_msg in failed_fields.items():
                            print(f"      - {field_id}: {error_msg[:200]}")
                
                # Sync attachments to newly created issue (using MERGE strategy)
                # Create a target_issue object with only key (sync_attachments function does not use other fields of this parameter)
                new_target_issue = {'key': new_key}
                sync_attachments(
                    s_issue, new_target_issue, "S2T",
                    source_jira, target_jira,
                    source_project_key, target_project_key,
                    new_key
                )
        else:
            # Update
            t_issue = target_map[s_key]
            t_key = t_issue['key']
            print(f"  -> Found matching Target Issue: {t_key}")

            # Simplified update logic: use last_sync_time as baseline
            s_time = s_issue['fields'].get('updated', '')
            t_time = t_issue['fields'].get('updated', '')
            
            # Get last_sync_time
            last_sync_time = None
            if last_sync_time_field:
                last_sync_time = t_issue['fields'].get(last_sync_time_field)
                if isinstance(last_sync_time, dict):
                    last_sync_time = last_sync_time.get('value')
            
            direction = "NONE"
            
            if last_sync_time:
                # If both issues' updated time are earlier than last_sync_time, no need to update fields
                # But attachment MERGE sync still needs to be executed
                if s_time <= last_sync_time and t_time <= last_sync_time:
                    print(f"  -> Skipping field update (no changes since last sync, last_sync_time: {last_sync_time})")
                    # Even if fields have no changes, execute attachment MERGE sync
                    sync_attachments(
                        s_issue, t_issue, "NONE",
                        source_jira, target_jira,
                        source_project_key, target_project_key,
                        t_key
                    )
                    skipped_count += 1
                    continue
                
                # Otherwise, compare two times to determine direction
                if s_time > t_time:
                    direction = "S2T"
                elif t_time > s_time:
                    direction = "T2S"
            else:
                # No last_sync_time (first sync), use original logic
                if s_time > t_time:
                    direction = "S2T"
                elif t_time > s_time:
                    direction = "T2S"

            if direction == "NONE":
                print("  -> Skipping field update (times are same)")
                # Even if times are same, execute attachment MERGE sync
                sync_attachments(
                    s_issue, t_issue, direction,
                    source_jira, target_jira,
                    source_project_key, target_project_key,
                    t_key
                )
                skipped_count += 1
                continue

            # Prepare update fields
            update_fields = processor.prepare_update_payload(
                s_issue,
                t_issue,
                direction,
                customer_issue_id_field,
                last_sync_time_field
            )

            if update_fields:
                print(f"  -> Updating {t_key if direction == 'S2T' else s_key} ({direction})...")
                print("    Update fields:")
                for fid, fval in update_fields.items():
                    try:
                        printable_val = json.dumps(fval, ensure_ascii=False)
                    except Exception:
                        printable_val = str(fval)
                    print(f"      {fid}: {printable_val}")
                # Select corresponding Jira Client based on sync direction
                if direction == "S2T":
                    target_jira.update_issue(t_key, update_fields)
                    updated_count += 1
                elif direction == "T2S":
                    source_jira.update_issue(s_key, update_fields)
                    updated_count += 1
            else:
                print("  -> No fields to update")
            
            # Sync attachments (MERGE strategy: execute attachment sync regardless of whether fields are updated)
            sync_attachments(
                s_issue, t_issue, direction,
                source_jira, target_jira,
                source_project_key, target_project_key,
                t_key
            )
            
            if not update_fields:
                skipped_count += 1

    # 5. Display synchronization results
    print()
    print("=" * 80)
    print("Synchronization Results Summary")
    print("=" * 80)
    print(f"Processed Source Issues: {len(source_issues)}")
    print(f"Created Target Issues: {created_count}")
    print(f"Updated Issues: {updated_count}")
    print(f"Skipped Issues: {skipped_count}")
    print("=" * 80)

if __name__ == "__main__":
    run_sync()

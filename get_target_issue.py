import requests
import json
import os
import base64

# 從 jira_config.json 讀取設定
CONFIG_FILE = "jira_config.json"
MAPPING_FILE = "jira_field_mapping.json"

if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError(f"錯誤：找不到 {CONFIG_FILE}，請確認檔案存在")

try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
        target_config = config.get("target", {})
        sync_issue_types = config.get("syncIssueType", [])
except Exception as e:
    raise ValueError(f"錯誤：無法讀取 {CONFIG_FILE}: {e}")

# 讀取 field mapping 配置，提取 target custom field IDs
target_custom_field_ids = set()
if os.path.exists(MAPPING_FILE):
    try:
        with open(MAPPING_FILE, "r", encoding="utf-8") as f:
            mappings = json.load(f)
            for item in mappings:
                target_field_id = item.get("targetFieldId")
                if target_field_id and target_field_id.startswith("customfield_"):
                    target_custom_field_ids.add(target_field_id)
    except Exception as e:
        print(f"警告：無法讀取 {MAPPING_FILE}: {e}")
        print("將顯示所有 custom field")
else:
    print(f"警告：找不到 {MAPPING_FILE}，將顯示所有 custom field")

if not target_config:
    raise ValueError(f"錯誤：{CONFIG_FILE} 中找不到 target 配置")

# 驗證 syncIssueType 格式：必須是字符串數組
if sync_issue_types is not None:
    if not isinstance(sync_issue_types, list):
        raise ValueError(f"錯誤：{CONFIG_FILE} 的 syncIssueType 格式錯誤，必須是一個字符串數組（array），但得到 {type(sync_issue_types).__name__}")
    
    # 檢查數組中的每個元素是否都是字符串
    for i, item in enumerate(sync_issue_types):
        if not isinstance(item, str):
            raise ValueError(f"錯誤：{CONFIG_FILE} 的 syncIssueType 格式錯誤，數組中的第 {i+1} 個元素必須是字符串，但得到 {type(item).__name__}")

if sync_issue_types:
    print(f"已讀取 syncIssueType 配置: {sync_issue_types}")
else:
    print("未找到 syncIssueType 配置，將取得所有 issue type 的 issue")

# 先讀取 authType 決定需要哪些配置
auth_type = target_config.get("authType", "Basic")

if auth_type not in ["Basic", "Bearer"]:
    raise ValueError(f"錯誤：不支援的 authType: {auth_type}，只支援 Basic 或 Bearer")

# 根據 authType 讀取必要的配置
api_token = target_config.get("apiToken")
project_key = target_config.get("projectKey")

# 檢查共同必要的設定值
if not api_token:
    raise ValueError(f"錯誤：{CONFIG_FILE} 的 target 配置中找不到 apiToken")

if not project_key:
    raise ValueError(f"錯誤：{CONFIG_FILE} 的 target 配置中找不到 projectKey")

# 根據 authType 讀取對應的配置並構建 API URL
if auth_type == "Basic":
    # Basic Auth 需要 domain 和 email
    domain = target_config.get("domain")
    email = target_config.get("email")

    if not domain:
        raise ValueError(f"錯誤：{CONFIG_FILE} 的 target 配置中找不到 domain（Basic Auth 需要）")
    if not email:
        raise ValueError(f"錯誤：{CONFIG_FILE} 的 target 配置中找不到 email（Basic Auth 需要）")

    # 處理 domain 可能已經包含協議的情況
    if domain.startswith("http://") or domain.startswith("https://"):
        base_domain = domain.rstrip("/")
    else:
        base_domain = f"https://{domain}"

    BASE_URL = f"{base_domain}/rest/api/3"
    cloud_id = None  # Basic Auth 不需要 cloudId

elif auth_type == "Bearer":
    # Bearer Auth 需要 cloudId
    cloud_id = target_config.get("cloudId")

    if not cloud_id:
        raise ValueError(f"錯誤：{CONFIG_FILE} 的 target 配置中找不到 cloudId（Bearer Auth 需要）")

    BASE_URL = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"
    domain = None  # Bearer Auth 不需要 domain
    email = None   # Bearer Auth 不需要 email

def get_auth_headers(auth_type, api_token, email=None):
    """根據 authType 生成對應的認證標頭"""
    if auth_type == "Basic":
        if not email:
            raise ValueError("Basic Auth 需要 email 參數")
        # Basic Auth: base64(email:api_token)
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
        raise ValueError(f"不支援的 authType: {auth_type}")

def test_authentication(base_url, auth_type, api_token, email=None):
    """測試認證是否成功"""
    url = f"{base_url}/myself"
    headers = get_auth_headers(auth_type, api_token, email)

    print("正在測試認證...")
    try:
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            user_info = response.json()
            print(f"[成功] 認證成功！")
            print(f"   用戶名稱: {user_info.get('displayName', 'N/A')}")
            print(f"   帳號 ID: {user_info.get('accountId', 'N/A')}")
            print(f"   電子郵件: {user_info.get('emailAddress', 'N/A')}")
            return True
        elif response.status_code == 401:
            print(f"[失敗] 認證失敗 (401 Unauthorized)")
            print(f"   錯誤訊息: {response.text}")
            print(f"   可能原因: API Token 無效或已過期")
            return False
        elif response.status_code == 403:
            print(f"[失敗] 認證失敗 (403 Forbidden)")
            print(f"   錯誤訊息: {response.text}")
            print(f"   可能原因: API Token 權限不足")
            return False
        else:
            print(f"[警告] 認證測試返回狀態碼: {response.status_code}")
            print(f"   回應內容: {response.text}")
            return False
    except Exception as e:
        print(f"[錯誤] 認證測試發生錯誤: {str(e)}")
        return False

def check_project_exists(base_url, project_key, auth_type, api_token, email=None):
    """檢查指定專案是否存在"""
    url = f"{base_url}/project/{project_key}"
    headers = get_auth_headers(auth_type, api_token, email)

    print(f"正在檢查專案 {project_key} 是否存在...")
    try:
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            project_data = response.json()
            print(f"[成功] 專案存在")
            print(f"   專案名稱: {project_data.get('name')}")
            print(f"   專案 Key: {project_data.get('key')}")
            print(f"   專案 ID: {project_data.get('id')}")
            return True
        elif response.status_code == 404:
            print(f"[失敗] 專案不存在 (404 Not Found)")
            print(f"   錯誤訊息: 找不到專案 Key '{project_key}'")
            return False
        elif response.status_code == 403:
            print(f"[失敗] 無權限存取專案 (403 Forbidden)")
            print(f"   錯誤訊息: {response.text}")
            return False
        else:
            print(f"[警告] 檢查專案時返回狀態碼: {response.status_code}")
            print(f"   回應內容: {response.text}")
            return False
    except Exception as e:
        print(f"[錯誤] 檢查專案時發生錯誤: {str(e)}")
        return False

def get_issue_details(base_url, issue_key, auth_type, api_token, email=None):
    """取得單個 Issue 的詳細資訊（包含 description、comments 和 attachments）"""
    url = f"{base_url}/issue/{issue_key}"
    headers = get_auth_headers(auth_type, api_token, email)

    params = {
        "fields": "description,comment,attachment"
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"  警告: 無法取得 {issue_key} 的詳細資訊 (Status {response.status_code})")
            return None
    except Exception as e:
        print(f"  警告: 取得 {issue_key} 詳細資訊時發生錯誤: {str(e)}")
        return None

def get_single_issue_full_details(base_url, issue_key, auth_type, api_token, email=None):
    """取得單個 Issue 的完整詳細資訊（包含所有字段）"""
    url = f"{base_url}/issue/{issue_key}"
    headers = get_auth_headers(auth_type, api_token, email)

    params = {
        "fields": "*all"  # 獲取所有字段
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            print(f"  [錯誤] Issue {issue_key} 不存在 (404 Not Found)")
            return None
        elif response.status_code == 403:
            print(f"  [錯誤] 無權限存取 Issue {issue_key} (403 Forbidden)")
            return None
        else:
            print(f"  [錯誤] 無法取得 {issue_key} 的詳細資訊 (Status {response.status_code})")
            print(f"  回應內容: {response.text}")
            return None
    except Exception as e:
        print(f"  [錯誤] 取得 {issue_key} 詳細資訊時發生錯誤: {str(e)}")
        return None

def get_issue_editmeta(base_url, issue_key, auth_type, api_token, email=None):
    """取得 Issue 的可編輯字段元數據（包含字段類型、是否必填等信息）"""
    url = f"{base_url}/issue/{issue_key}/editmeta"
    headers = get_auth_headers(auth_type, api_token, email)

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            print(f"  [錯誤] Issue {issue_key} 不存在 (404 Not Found)")
            return None
        elif response.status_code == 403:
            print(f"  [錯誤] 無權限存取 Issue {issue_key} (403 Forbidden)")
            return None
        else:
            print(f"  [警告] 無法取得 {issue_key} 的 editmeta (Status {response.status_code})")
            print(f"  回應內容: {response.text}")
            return None
    except Exception as e:
        print(f"  [錯誤] 取得 {issue_key} editmeta 時發生錯誤: {str(e)}")
        return None

def format_field_metadata(editmeta_data):
    """格式化字段元數據，提取字段類型、是否必填等信息"""
    if not editmeta_data or 'fields' not in editmeta_data:
        return {}
    
    fields_metadata = {}
    fields = editmeta_data.get('fields', {})
    
    for field_id, field_info in fields.items():
        field_metadata = {
            'fieldId': field_id,
            'name': field_info.get('name', ''),
            'type': field_info.get('schema', {}).get('type', 'unknown'),
            'system': field_info.get('schema', {}).get('system', ''),
            'custom': field_info.get('schema', {}).get('custom', ''),
            'customId': field_info.get('schema', {}).get('customId', None),
            'required': field_info.get('required', False),
            'hasDefaultValue': field_info.get('hasDefaultValue', False),
            'allowedValues': field_info.get('allowedValues', None),
            'operations': field_info.get('operations', [])
        }
        
        # 如果是自定義字段，添加更多信息
        if field_id.startswith('customfield_'):
            field_metadata['isCustomField'] = True
            # 嘗試獲取字段的具體類型（如 select, text, date 等）
            field_type = field_info.get('schema', {}).get('type', '')
            if field_type == 'option':
                field_metadata['fieldType'] = 'Select List (Single Choice)'
            elif field_type == 'array' and field_info.get('schema', {}).get('items') == 'option':
                field_metadata['fieldType'] = 'Select List (Multiple Choice)'
            elif field_type == 'string':
                field_metadata['fieldType'] = 'Text Field'
            elif field_type == 'date':
                field_metadata['fieldType'] = 'Date'
            elif field_type == 'datetime':
                field_metadata['fieldType'] = 'Date Time'
            elif field_type == 'number':
                field_metadata['fieldType'] = 'Number'
            else:
                field_metadata['fieldType'] = field_type
        else:
            field_metadata['isCustomField'] = False
            field_metadata['fieldType'] = 'System Field'
        
        fields_metadata[field_id] = field_metadata
    
    return fields_metadata

def display_single_issue_info(base_url, issue_key, auth_type, api_token, email=None):
    """顯示單個 Issue 的詳細資訊和可用的字段元數據"""
    print("\n" + "=" * 80)
    print(f"取得 Issue {issue_key} 的詳細資訊")
    print("=" * 80)
    
    # 1. 取得 Issue 完整詳細資訊
    print(f"\n[1] 正在取得 Issue {issue_key} 的完整詳細資訊...")
    issue_data = get_single_issue_full_details(base_url, issue_key, auth_type, api_token, email)
    
    if not issue_data:
        print(f"無法取得 Issue {issue_key} 的詳細資訊")
        return
    
    # 顯示基本資訊
    fields = issue_data.get('fields', {})
    print(f"  ✓ Issue Key: {issue_data.get('key', 'N/A')}")
    print(f"  ✓ Issue ID: {issue_data.get('id', 'N/A')}")
    print(f"  ✓ Summary: {fields.get('summary', 'N/A')}")
    print(f"  ✓ Issue Type: {fields.get('issuetype', {}).get('name', 'N/A')}")
    print(f"  ✓ Status: {fields.get('status', {}).get('name', 'N/A')}")
    print(f"  ✓ Priority: {fields.get('priority', {}).get('name', 'N/A')}")
    print(f"  ✓ Created: {fields.get('created', 'N/A')}")
    print(f"  ✓ Updated: {fields.get('updated', 'N/A')}")
    
    # 2. 取得 Issue 的 editmeta（可編輯字段元數據）
    print(f"\n[2] 正在取得 Issue {issue_key} 的字段元數據...")
    editmeta_data = get_issue_editmeta(base_url, issue_key, auth_type, api_token, email)
    
    if not editmeta_data:
        print(f"無法取得 Issue {issue_key} 的字段元數據")
        # 仍然顯示 issue 的完整數據
        print("\n[Issue 完整數據]")
        print(json.dumps(issue_data, indent=2, ensure_ascii=False))
        return
    
    # 格式化字段元數據
    fields_metadata = format_field_metadata(editmeta_data)
    
    # 3. 顯示字段元數據
    print(f"\n[3] 字段元數據分析")
    print("-" * 80)
    
    # 分離系統字段和自定義字段
    system_fields = {}
    custom_fields = {}
    
    for field_id, metadata in fields_metadata.items():
        if metadata.get('isCustomField', False):
            custom_fields[field_id] = metadata
        else:
            system_fields[field_id] = metadata
    
    print(f"\n系統字段 (共 {len(system_fields)} 個):")
    print("-" * 80)
    for field_id, metadata in sorted(system_fields.items()):
        required_mark = " [必填]" if metadata.get('required', False) else ""
        print(f"  • {field_id}")
        print(f"    名稱: {metadata.get('name', 'N/A')}")
        print(f"    類型: {metadata.get('fieldType', metadata.get('type', 'N/A'))}")
        print(f"    必填: {'是' if metadata.get('required', False) else '否'}{required_mark}")
        if metadata.get('operations'):
            print(f"    可執行操作: {', '.join(metadata.get('operations', []))}")
        print()
    
    print(f"\n自定義字段 (共 {len(custom_fields)} 個):")
    print("-" * 80)
    for field_id, metadata in sorted(custom_fields.items()):
        required_mark = " [必填]" if metadata.get('required', False) else ""
        print(f"  • {field_id}")
        print(f"    名稱: {metadata.get('name', 'N/A')}")
        print(f"    類型: {metadata.get('fieldType', metadata.get('type', 'N/A'))}")
        print(f"    數據類型: {metadata.get('type', 'N/A')}")
        print(f"    必填: {'是' if metadata.get('required', False) else '否'}{required_mark}")
        if metadata.get('customId'):
            print(f"    自定義字段 ID: {metadata.get('customId')}")
        if metadata.get('allowedValues') is not None:
            allowed_count = len(metadata.get('allowedValues', []))
            print(f"    允許的值數量: {allowed_count}")
            if allowed_count > 0 and allowed_count <= 10:
                # 顯示前幾個允許的值
                values = metadata.get('allowedValues', [])[:5]
                value_names = []
                for val in values:
                    if isinstance(val, dict):
                        value_names.append(val.get('value', val.get('name', str(val))))
                    else:
                        value_names.append(str(val))
                print(f"    允許的值範例: {', '.join(value_names)}")
        if metadata.get('operations'):
            print(f"    可執行操作: {', '.join(metadata.get('operations', []))}")
        print()
    
    # 4. 顯示 Issue 的完整數據（包含所有字段值）
    print("\n[4] Issue 完整數據（包含所有字段值）")
    print("-" * 80)
    
    # 分離系統字段值和自定義字段值
    system_field_values = {}
    custom_field_values = {}
    
    for field_name, field_value in fields.items():
        if field_name.startswith('customfield_'):
            custom_field_values[field_name] = field_value
        else:
            system_field_values[field_name] = field_value
    
    formatted_issue = {
        'id': issue_data.get('id'),
        'key': issue_data.get('key'),
        'self': issue_data.get('self'),
        'fields': {
            'systemFields': system_field_values,
            'customFields': custom_field_values
        },
        'fieldMetadata': {
            'systemFields': system_fields,
            'customFields': custom_fields
        }
    }
    
    print(json.dumps(formatted_issue, indent=2, ensure_ascii=False))
    
    # 5. 保存到文件
    target_name = target_config.get("name", "target")
    output_file = f"{target_name.lower()}_{issue_key}_details.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(formatted_issue, f, indent=2, ensure_ascii=False)
    
    print(f"\n[5] 結果已儲存至 {output_file}")
    print("=" * 80)

def get_all_issues(base_url, project_key, auth_type, api_token, email=None, max_results=100):
    """
    取得指定專案的所有 Issue 清單
    使用 Jira Search API (新版本 /rest/api/3/search/jql) 來取得所有 issue
    """
    url = f"{base_url}/search/jql"
    headers = get_auth_headers(auth_type, api_token, email)

    all_issues = []
    start_at = 0
    total = 0

    print(f"正在取得專案 {project_key} 的 Issue...")
    print(f"JQL 過濾條件: 建立時間小於1天，最多 {max_results} 筆")

    while True:
        # 使用 GET 方法，JQL 和參數作為查詢參數
        # 先查詢建立時間小於1天的 issues（最多100筆）
        jql_query = f'project = {project_key} AND created >= -1d ORDER BY created DESC'
        params = {
            "jql": jql_query,
            "maxResults": max_results,
            "startAt": start_at,
            "fields": "*all"  # 獲取所有字段，包括 custom field
        }

        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            print(f"取得 Issue 清單失敗 (Status {response.status_code}): {response.text}")
            break

        data = response.json()

        # 只在第一次請求時打印完整的數據結構
        if start_at == 0:
            print("\n" + "=" * 80)
            print("API 回應數據結構與內容:")
            print("=" * 80)
            print(f"JQL 查詢: {jql_query}")
            print(f"請求 URL: {response.url}")
            print(f"狀態碼: {response.status_code}")
            print("\n完整 JSON 結構:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print("\n數據結構分析:")
            print(f"  - 頂層鍵值: {list(data.keys())}")
            for key in data.keys():
                value = data[key]
                if isinstance(value, list):
                    print(f"  - {key}: 列表，長度 = {len(value)}")
                    if len(value) > 0:
                        print(f"    第一個元素類型: {type(value[0])}")
                        if isinstance(value[0], dict):
                            print(f"    第一個元素的鍵: {list(value[0].keys())}")
                elif isinstance(value, dict):
                    print(f"  - {key}: 字典，鍵 = {list(value.keys())}")
                else:
                    print(f"  - {key}: {type(value).__name__} = {value}")
            print("=" * 80 + "\n")

        # 新版本 API 沒有 total 字段，從 issues 列表獲取
        issues = data.get("issues", [])

        if not issues:
            break

        all_issues.extend(issues)

        # 由於沒有 total 字段，使用當前已取得的數量顯示進度
        # 如果返回的 issues 數量等於 max_results，可能還有更多
        print(f"已取得 {len(all_issues)} 個 Issue... (本批次: {len(issues)} 個)")

        # 限制最多只取得 100 筆
        if len(all_issues) >= max_results:
            break

        # 檢查是否還有更多 issue
        # 如果返回的 issues 數量小於 max_results，說明已經取得所有資料
        if len(issues) < max_results:
            break

        start_at += max_results

    # 根據 syncIssueType 過濾 issue type
    if sync_issue_types:
        print(f"\n正在過濾符合 syncIssueType 條件的 Issue...")
        print(f"過濾前: {len(all_issues)} 個 Issue")
        print(f"允許的 Issue Type: {sync_issue_types}")

        type_filtered_issues = []
        for issue in all_issues:
            fields = issue.get('fields', {})
            issue_type = fields.get('issuetype', {})
            issue_type_name = issue_type.get('name', '') if issue_type else ''

            # 檢查 issue type name 是否在 syncIssueType 列表中
            if issue_type_name in sync_issue_types:
                type_filtered_issues.append(issue)

        print(f"過濾後: {len(type_filtered_issues)} 個 Issue (issue type 符合 syncIssueType 配置)")

        # 使用過濾後的 issues
        all_issues = type_filtered_issues
    total = len(all_issues)

    # 為每個 issue 補充 description、comments 和 attachments 資訊
    if total > 0:
        print(f"\n正在取得 {total} 個 Issue 的詳細資訊（description、comments 和 attachments）...")
        for i, issue in enumerate(all_issues, 1):
            issue_key = issue.get('key')
            print(f"  處理中 ({i}/{total}): {issue_key}...", end='\r')

            details = get_issue_details(base_url, issue_key, auth_type, api_token, email)
            if details and 'fields' in details:
                if 'fields' not in issue:
                    issue['fields'] = {}

                # 補充 description 資訊
                if 'description' in details['fields']:
                    issue['fields']['description'] = details['fields']['description']

                # 補充 comments 資訊
                if 'comment' in details['fields']:
                    issue['fields']['comment'] = details['fields']['comment']

                # 補充 attachments 資訊
                if 'attachment' in details['fields']:
                    issue['fields']['attachment'] = details['fields']['attachment']

        print(f"  完成！已取得所有 Issue 的詳細資訊。{' ' * 50}")

    return all_issues, total

def format_issue_for_console(issue):
    """格式化 Issue 資訊以便在控制台顯示（JSON 格式）"""
    fields = issue.get("fields", {})
    
    # 格式化 issue type
    issue_type_obj = fields.get("issuetype", {})
    formatted_issuetype = None
    if issue_type_obj:
        formatted_issuetype = {
            "name": issue_type_obj.get("name", ""),
            "description": issue_type_obj.get("description", "")
        }
    
    # 格式化 comments
    formatted_comments = []
    comment_obj = fields.get("comment", {})
    if comment_obj and isinstance(comment_obj, dict):
        comments_list = comment_obj.get("comments", [])
        for comment in comments_list:
            formatted_comment = {
                "id": comment.get("id", ""),
                "author": {
                    "accountId": comment.get("author", {}).get("accountId", ""),
                    "emailAddress": comment.get("author", {}).get("emailAddress", ""),
                    "displayName": comment.get("author", {}).get("displayName", "")
                },
                "body": comment.get("body", {}),
                "updateAuthor": {
                    "accountId": comment.get("updateAuthor", {}).get("accountId", ""),
                    "emailAddress": comment.get("updateAuthor", {}).get("emailAddress", ""),
                    "displayName": comment.get("updateAuthor", {}).get("displayName", "")
                },
                "created": comment.get("created", ""),
                "updated": comment.get("updated", "")
            }
            formatted_comments.append(formatted_comment)
    
    # 格式化 reporter
    formatted_reporter = None
    reporter_obj = fields.get("reporter")
    if reporter_obj:
        formatted_reporter = {
            "accountId": reporter_obj.get("accountId", ""),
            "emailAddress": reporter_obj.get("emailAddress", ""),
            "displayName": reporter_obj.get("displayName", "")
        }
    
    # 格式化 assignee
    formatted_assignee = None
    assignee_obj = fields.get("assignee")
    if assignee_obj:
        formatted_assignee = {
            "accountId": assignee_obj.get("accountId", ""),
            "emailAddress": assignee_obj.get("emailAddress", ""),
            "displayName": assignee_obj.get("displayName", "")
        }
    
    # 格式化 priority
    formatted_priority = None
    priority_obj = fields.get("priority")
    if priority_obj:
        formatted_priority = {
            "id": priority_obj.get("id", ""),
            "name": priority_obj.get("name", "")
        }
    
    # 格式化 status
    formatted_status = None
    status_obj = fields.get("status")
    if status_obj:
        formatted_status = {
            "id": status_obj.get("id", ""),
            "name": status_obj.get("name", "")
        }
    
    # 只收集在 field mapping 中配置的 custom field
    custom_fields = {}
    for field_name, field_value in fields.items():
        if field_name.startswith("customfield_") and field_name in target_custom_field_ids:
            custom_fields[field_name] = field_value
    
    # 構建格式化後的 issue
    formatted_issue = {
        "id": issue.get("id", ""),
        "key": issue.get("key", ""),
        "fields": {
            "summary": fields.get("summary", ""),
            "issuetype": formatted_issuetype,
            "attachment": fields.get("attachment", []),
            "created": fields.get("created", ""),
            "description": fields.get("description", {}),
            "comment": {
                "comments": formatted_comments
            },
            "reporter": formatted_reporter,
            "assignee": formatted_assignee,
            "priority": formatted_priority,
            "updated": fields.get("updated", ""),
            "status": formatted_status
        }
    }
    
    # 將 custom fields 添加到 fields 中
    if custom_fields:
        formatted_issue["fields"]["customFields"] = custom_fields
    
    return formatted_issue

def main():
    """主程式"""
    import sys
    
    print("=" * 60)
    print("Jira 專案與 Issue 管理工具 (Target)")
    print("=" * 60)
    print(f"Auth Type: {auth_type}")
    if auth_type == "Basic":
        print(f"Domain: {domain}")
        print(f"Email: {email}")
    elif auth_type == "Bearer":
        print(f"Cloud ID: {cloud_id}")
    print(f"Base URL: {BASE_URL}")
    print(f"Project Key: {project_key}")
    print()

    # 0. 測試認證
    auth_success = test_authentication(BASE_URL, auth_type, api_token, email)
    print()

    if not auth_success:
        print("[警告] 認證失敗，無法繼續執行。請檢查配置是否正確。")
        return

    # 檢查是否提供了 issue key 作為命令行參數
    if len(sys.argv) > 1:
        issue_key = sys.argv[1]
        # 如果提供了 issue key，只獲取該 issue 的詳細資訊
        display_single_issue_info(BASE_URL, issue_key, auth_type, api_token, email)
        return

    # 1. 檢查指定專案是否存在
    project_exists = check_project_exists(BASE_URL, project_key, auth_type, api_token, email)
    print()

    if not project_exists:
        print("[警告] 專案不存在或無權限存取，無法繼續執行。請檢查 projectKey 配置是否正確。")
        return

    # 詢問用戶要執行哪個操作
    print("請選擇操作：")
    print("  1. 取得專案的所有 Issue 清單")
    print("  2. 取得單個 Issue 的詳細資訊和字段元數據")
    print()
    
    try:
        choice = input("請輸入選項 (1 或 2，直接按 Enter 預設為 1): ").strip()
        if not choice:
            choice = "1"
    except (EOFError, KeyboardInterrupt):
        print("\n操作已取消")
        return
    
    if choice == "2":
        # 取得單個 Issue 的詳細資訊
        issue_key = input("請輸入 Issue Key (例如: DM-17): ").strip()
        if not issue_key:
            print("錯誤: 未輸入 Issue Key")
            return
        display_single_issue_info(BASE_URL, issue_key, auth_type, api_token, email)
        return
    
    # 2. 取得指定專案的所有 Issue
    print(f"正在取得專案 {project_key} 的所有 Issue...")
    issues, total = get_all_issues(BASE_URL, project_key, auth_type, api_token, email)

    print()
    print("=" * 60)
    print(f"專案 {project_key} - 共取得 {len(issues)} 個 Issue（總數: {total}）")
    print("=" * 60)
    print()

    # 4. 顯示 Issue 清單（JSON 格式）
    if issues:
        print("Issue 清單：")
        print("=" * 60)
        formatted_issues = []
        for issue in issues:
            formatted_issue = format_issue_for_console(issue)
            formatted_issues.append(formatted_issue)
        
        # 輸出為 JSON 格式
        console_output = {
            "issues": formatted_issues
        }
        print(json.dumps(console_output, indent=2, ensure_ascii=False))
        print("=" * 60)
    else:
        print("沒有找到任何 Issue")

    # 5. 將結果儲存為 JSON 檔案
    target_name = target_config.get("name", "target")
    output_file = f"{target_name.lower()}_{project_key}_issues.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "project_key": project_key,
            "total": total,
            "count": len(issues),
            "issues": issues
        }, f, indent=2, ensure_ascii=False)

    print(f"\n結果已儲存至 {output_file}")

if __name__ == "__main__":
    main()

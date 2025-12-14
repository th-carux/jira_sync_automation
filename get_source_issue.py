import requests
import json
import os
import base64

# 從 jira_config.json 讀取設定
CONFIG_FILE = "jira_config.json"

if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError(f"錯誤：找不到 {CONFIG_FILE}，請確認檔案存在")

try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
        source_config = config.get("source", {})
        sync_issue_types = config.get("syncIssueType", [])
except Exception as e:
    raise ValueError(f"錯誤：無法讀取 {CONFIG_FILE}: {e}")

if not source_config:
    raise ValueError(f"錯誤：{CONFIG_FILE} 中找不到 source 配置")

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
auth_type = source_config.get("authType", "Basic")

if auth_type not in ["Basic", "Bearer"]:
    raise ValueError(f"錯誤：不支援的 authType: {auth_type}，只支援 Basic 或 Bearer")

# 根據 authType 讀取必要的配置
api_token = source_config.get("apiToken")
project_key = source_config.get("projectKey")

# 檢查共同必要的設定值
if not api_token:
    raise ValueError(f"錯誤：{CONFIG_FILE} 的 source 配置中找不到 apiToken")

if not project_key:
    raise ValueError(f"錯誤：{CONFIG_FILE} 的 source 配置中找不到 projectKey")

# 根據 authType 讀取對應的配置並構建 API URL
if auth_type == "Basic":
    # Basic Auth 需要 domain 和 email
    domain = source_config.get("domain")
    email = source_config.get("email")

    if not domain:
        raise ValueError(f"錯誤：{CONFIG_FILE} 的 source 配置中找不到 domain（Basic Auth 需要）")
    if not email:
        raise ValueError(f"錯誤：{CONFIG_FILE} 的 source 配置中找不到 email（Basic Auth 需要）")

    # 處理 domain 可能已經包含協議的情況
    if domain.startswith("http://") or domain.startswith("https://"):
        base_domain = domain.rstrip("/")
    else:
        base_domain = f"https://{domain}"

    BASE_URL = f"{base_domain}/rest/api/3"
    cloud_id = None  # Basic Auth 不需要 cloudId

elif auth_type == "Bearer":
    # Bearer Auth 需要 cloudId
    cloud_id = source_config.get("cloudId")

    if not cloud_id:
        raise ValueError(f"錯誤：{CONFIG_FILE} 的 source 配置中找不到 cloudId（Bearer Auth 需要）")

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

def download_attachment(base_url, attachment, issue_key, auth_type, api_token, email=None):
    """下載單個附件"""
    attachment_id = attachment.get('id')
    filename = attachment.get('filename', 'unknown')
    content_url = attachment.get('content')
    
    if not content_url:
        print(f"    警告: 附件 {filename} 沒有 content URL，跳過下載")
        return False
    
    # 創建以 issue_key 命名的資料夾
    folder_name = issue_key
    try:
        # 如果資料夾不存在則創建，已存在則不報錯
        if not os.path.exists(folder_name):
            os.makedirs(folder_name, exist_ok=True)
            print(f"    已創建資料夾: {folder_name}")
    except Exception as e:
        print(f"    警告: 無法創建資料夾 {folder_name}: {str(e)}")
        return False
    
    # 在檔名前面加上 [issue_key] 前綴
    prefixed_filename = f"[{issue_key}]{filename}"
    file_path = os.path.join(folder_name, prefixed_filename)
    
    # 如果檔案已存在，跳過下載
    if os.path.exists(file_path):
        print(f"    檔案已存在，跳過: {prefixed_filename}")
        return True
    
    try:
        headers = get_auth_headers(auth_type, api_token, email)
        response = requests.get(content_url, headers=headers, stream=True)
        
        if response.status_code == 200:
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            file_size = os.path.getsize(file_path)
            print(f"    已下載: {prefixed_filename} ({file_size} bytes)")
            return True
        else:
            print(f"    警告: 無法下載 {filename} (Status {response.status_code})")
            return False
    except Exception as e:
        print(f"    錯誤: 下載 {filename} 時發生錯誤: {str(e)}")
        return False

def download_issue_attachments(base_url, issue, auth_type, api_token, email=None):
    """下載 Issue 的所有附件"""
    issue_key = issue.get('key', '')
    fields = issue.get('fields', {})
    attachments = fields.get('attachment', [])
    
    if not attachments or len(attachments) == 0:
        return 0
    
    print(f"    正在下載 {len(attachments)} 個附件...")
    downloaded_count = 0
    
    for attachment in attachments:
        if download_attachment(base_url, attachment, issue_key, auth_type, api_token, email):
            downloaded_count += 1
    
    return downloaded_count

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
    print(f"代碼過濾條件: reporter 或 assignee 的 email 必須以 @carux.com 結尾")

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

    # 在代碼中過濾符合 email 條件的 issues
    print(f"\n正在過濾符合 email 條件的 Issue...")
    print(f"過濾前: {len(all_issues)} 個 Issue")

    filtered_issues = []
    for issue in all_issues:
        fields = issue.get('fields', {})
        assignee = fields.get('assignee')
        reporter = fields.get('reporter')

        assignee_email = assignee.get('emailAddress', '') if assignee else ''
        reporter_email = reporter.get('emailAddress', '') if reporter else ''

        # 檢查 assignee 或 reporter 的 email 是否以 @carux.com 結尾
        if assignee_email.endswith('@carux.com') or reporter_email.endswith('@carux.com'):
            filtered_issues.append(issue)

    print(f"過濾後: {len(filtered_issues)} 個 Issue (reporter 或 assignee email 以 @carux.com 結尾)")

    # 使用過濾後的 issues
    all_issues = filtered_issues

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
            print(f"  處理中 ({i}/{total}): {issue_key}...")

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
                    
                    # 下載附件
                    if issue['fields']['attachment']:
                        download_issue_attachments(base_url, issue, auth_type, api_token, email)

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
    
    # 收集所有 custom field（以 customfield_ 開頭的字段）
    custom_fields = {}
    for field_name, field_value in fields.items():
        if field_name.startswith("customfield_"):
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
    print("=" * 60)
    print("Jira 專案與 Issue 管理工具 (Source)")
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

    # 1. 檢查指定專案是否存在
    project_exists = check_project_exists(BASE_URL, project_key, auth_type, api_token, email)
    print()

    if not project_exists:
        print("[警告] 專案不存在或無權限存取，無法繼續執行。請檢查 projectKey 配置是否正確。")
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
    source_name = source_config.get("name", "source")
    output_file = f"{source_name.lower()}_{project_key}_issues.json"
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


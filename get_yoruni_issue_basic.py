import requests
import json
import os
import base64

# 從 jira_config_yoruni.json 讀取設定
CONFIG_FILE = "jira_config_yoruni.json"

if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError(f"錯誤：找不到 {CONFIG_FILE}，請確認檔案存在")

try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
        domain = config.get("domain")
        email = config.get("email")
        api_token = config.get("api_token")
        project_key = config.get("project_key")
except Exception as e:
    raise ValueError(f"錯誤：無法讀取 {CONFIG_FILE}: {e}")

# 檢查必要的設定值
if not domain:
    raise ValueError(f"錯誤：{CONFIG_FILE} 中找不到 domain")

if not email:
    raise ValueError(f"錯誤：{CONFIG_FILE} 中找不到 email（域名格式的 API 需要 email 進行 Basic Auth）")

if not api_token:
    raise ValueError(f"錯誤：{CONFIG_FILE} 中找不到 api_token")

if not project_key:
    raise ValueError(f"錯誤：{CONFIG_FILE} 中找不到 project_key")

# 構建基礎 API URL
# 處理 domain 可能已經包含協議的情況
if domain.startswith("http://") or domain.startswith("https://"):
    # 如果已經包含協議，直接使用
    base_domain = domain.rstrip("/")
else:
    # 如果沒有協議，添加 https://
    base_domain = f"https://{domain}"

BASE_URL = f"{base_domain}/rest/api/3"

def get_auth_headers(email, api_token):
    """生成 Basic Auth 認證標頭"""
    # Basic Auth: base64(email:api_token)
    credentials = f"{email}:{api_token}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    return {
        "Authorization": f"Basic {encoded_credentials}",
        "Accept": "application/json"
    }

def get_all_projects(base_url, email, api_token):
    """取得所有專案清單"""
    url = f"{base_url}/project"
    headers = get_auth_headers(email, api_token)

    print("正在取得所有專案清單...")
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        projects = response.json()
        print(f"\n找到 {len(projects)} 個專案：")
        print("=" * 80)
        print(f"{'專案 Key':<15} {'專案名稱':<40} {'專案 ID':<15} {'專案類型':<15}")
        print("-" * 80)

        for project in projects:
            project_key = project.get('key', 'N/A')
            project_name = project.get('name', 'N/A')
            project_id = project.get('id', 'N/A')
            project_type = project.get('projectTypeKey', 'N/A')
            print(f"{project_key:<15} {project_name:<40} {project_id:<15} {project_type:<15}")

        print("=" * 80)
        return projects
    else:
        print(f"取得專案清單失敗 (Status {response.status_code}): {response.text}")
        return []

def get_project_info(base_url, project_key, email, api_token):
    """取得專案資訊"""
    url = f"{base_url}/project/{project_key}"
    headers = get_auth_headers(email, api_token)

    print(f"正在取得專案 {project_key} 的資訊...")
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        project_data = response.json()
        print(f"專案名稱: {project_data.get('name')}")
        print(f"專案 Key: {project_data.get('key')}")
        print(f"專案 ID: {project_data.get('id')}")
        return project_data
    else:
        print(f"取得專案資訊失敗 (Status {response.status_code}): {response.text}")
        return None

def get_issue_details(base_url, issue_key, email, api_token):
    """取得單個 Issue 的詳細資訊（包含 comments 和 attachments）"""
    url = f"{base_url}/issue/{issue_key}"
    headers = get_auth_headers(email, api_token)

    params = {
        "fields": "comment,attachment"
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

def get_all_issues(base_url, project_key, email, api_token, max_results=100):
    """
    取得指定專案的所有 Issue 清單
    使用 Jira Search API (新版本 /rest/api/3/search/jql) 來取得所有 issue
    """
    url = f"{base_url}/search/jql"
    headers = get_auth_headers(email, api_token)

    all_issues = []
    start_at = 0
    total = 0

    print(f"正在取得專案 {project_key} 的所有 Issue...")

    while True:
        # 使用 GET 方法，JQL 和參數作為查詢參數
        params = {
            "jql": f"project = {project_key}",
            "maxResults": max_results,
            "startAt": start_at,
            "fields": "summary,status,assignee,created,updated,priority,issuetype,comment,attachment"
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

        # 檢查是否還有更多 issue
        # 如果返回的 issues 數量小於 max_results，說明已經取得所有資料
        if len(issues) < max_results:
            break

        start_at += max_results

    # 總數就是實際取得的 issues 數量
    total = len(all_issues)

    # 為每個 issue 補充 comments 和 attachments 資訊
    if total > 0:
        print(f"\n正在取得 {total} 個 Issue 的詳細資訊（comments 和 attachments）...")
        for i, issue in enumerate(all_issues, 1):
            issue_key = issue.get('key')
            print(f"  處理中 ({i}/{total}): {issue_key}...", end='\r')

            details = get_issue_details(base_url, issue_key, email, api_token)
            if details and 'fields' in details:
                # 補充 comments 資訊
                if 'comment' in details['fields']:
                    if 'fields' not in issue:
                        issue['fields'] = {}
                    issue['fields']['comment'] = details['fields']['comment']

                # 補充 attachments 資訊
                if 'attachment' in details['fields']:
                    if 'fields' not in issue:
                        issue['fields'] = {}
                    issue['fields']['attachment'] = details['fields']['attachment']

        print(f"  完成！已取得所有 Issue 的詳細資訊。{' ' * 50}")

    return all_issues, total

def format_issue_info(issue):
    """格式化 Issue 資訊以便顯示"""
    fields = issue.get("fields", {})
    return {
        "key": issue.get("key"),
        "summary": fields.get("summary", "無標題"),
        "status": fields.get("status", {}).get("name", "未知"),
        "assignee": fields.get("assignee", {}).get("displayName", "未指派") if fields.get("assignee") else "未指派",
        "priority": fields.get("priority", {}).get("name", "無") if fields.get("priority") else "無",
        "issue_type": fields.get("issuetype", {}).get("name", "未知"),
        "created": fields.get("created", ""),
        "updated": fields.get("updated", "")
    }

def main():
    """主程式"""
    print("=" * 60)
    print("Jira 專案與 Issue 管理工具")
    print("=" * 60)
    print(f"Domain: {domain}")
    print(f"Base URL: {BASE_URL}")
    print()

    # 0. 先列出所有專案清單
    all_projects = get_all_projects(BASE_URL, email, api_token)
    print()

    # 1. 取得指定專案資訊（可選，用於驗證）
    print(f"正在處理專案: {project_key}")
    project_info = get_project_info(BASE_URL, project_key, email, api_token)
    print()

    # 2. 取得指定專案的所有 Issue
    print(f"正在取得專案 {project_key} 的所有 Issue...")
    issues, total = get_all_issues(BASE_URL, project_key, email, api_token)

    print()
    print("=" * 60)
    print(f"專案 {project_key} - 共取得 {len(issues)} 個 Issue（總數: {total}）")
    print("=" * 60)
    print()

    # 3. 顯示 Issue 清單
    if issues:
        print("Issue 清單：")
        print("-" * 60)
        for issue in issues:
            info = format_issue_info(issue)
            print(f"Key: {info['key']}")
            print(f"  標題: {info['summary']}")
            print(f"  狀態: {info['status']}")
            print(f"  負責人: {info['assignee']}")
            print(f"  優先級: {info['priority']}")
            print(f"  類型: {info['issue_type']}")
            print(f"  建立時間: {info['created']}")
            print(f"  更新時間: {info['updated']}")
            print("-" * 60)
    else:
        print("沒有找到任何 Issue")

    # 4. 將結果儲存為 JSON 檔案（可選）
    output_file = f"yoruni_{project_key}_issues.json"
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


"""
取得 DM 專案的所有 Issue 清單
使用 carux_jira_config.json 檔案中的 cloud_id 與 api_token 進行認證
"""
import requests
import json
import os

# 從 carux_jira_config.json 讀取設定
CONFIG_FILE = "carux_jira_config.json"

if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError(f"錯誤：找不到 {CONFIG_FILE}，請確認檔案存在")

try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
        cloud_id = config.get("cloud_id")
        api_token = config.get("api_token")
except Exception as e:
    raise ValueError(f"錯誤：無法讀取 {CONFIG_FILE}: {e}")

# 檢查必要的設定值
if not cloud_id:
    raise ValueError(f"錯誤：{CONFIG_FILE} 中找不到 cloud_id")

if not api_token:
    raise ValueError(f"錯誤：{CONFIG_FILE} 中找不到 api_token")

# 專案 Key
PROJECT_KEY = "DM"

def get_project_info(cloud_id, project_key, api_token):
    """取得專案資訊"""
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/{project_key}"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json"
    }

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

def get_all_issues(cloud_id, project_key, api_token, max_results=100):
    """
    取得指定專案的所有 Issue 清單
    使用 Jira Search API (新版本 /rest/api/3/search/jql) 來取得所有 issue
    """
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json"
    }

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
            "fields": "summary,status,assignee,created,updated,priority,issuetype"
        }

        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            print(f"取得 Issue 清單失敗 (Status {response.status_code}): {response.text}")
            break

        data = response.json()
        issues = data.get("issues", [])
        total = data.get("total", 0)

        if not issues:
            break

        all_issues.extend(issues)
        print(f"已取得 {len(all_issues)} / {total} 個 Issue...")

        # 檢查是否還有更多 issue
        if len(all_issues) >= total or len(issues) < max_results:
            break

        start_at += max_results

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
    print("取得 DM 專案的所有 Issue 清單")
    print("=" * 60)
    print(f"Cloud ID: {cloud_id}")
    print(f"專案 Key: {PROJECT_KEY}")
    print()

    # 1. 先取得專案資訊（可選，用於驗證）
    project_info = get_project_info(cloud_id, PROJECT_KEY, api_token)
    print()

    # 2. 取得所有 Issue
    issues, total = get_all_issues(cloud_id, PROJECT_KEY, api_token)

    print()
    print("=" * 60)
    print(f"共取得 {len(issues)} 個 Issue（總數: {total}）")
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
    output_file = "dm_issues.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "project_key": PROJECT_KEY,
            "total": total,
            "count": len(issues),
            "issues": issues
        }, f, indent=2, ensure_ascii=False)

    print(f"\n結果已儲存至 {output_file}")

if __name__ == "__main__":
    main()


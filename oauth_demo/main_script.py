import requests
import json
import os

CONFIG_FILE = "jira_config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"找不到 {CONFIG_FILE}，請先執行 auth_setup.py")
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def get_fresh_access_token(config):
    """使用 Refresh Token 換取新的 Access Token"""
    print("正在刷新 Access Token...")
    
    url = "https://auth.atlassian.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "refresh_token": config["refresh_token"]
    }
    
    response = requests.post(url, json=payload)
    
    if response.status_code != 200:
        raise Exception(f"刷新 Token 失敗: {response.text}")
        
    data = response.json()
    new_access_token = data["access_token"]
    new_refresh_token = data["refresh_token"]
    
    # 重要：更新 config 中的 Refresh Token (Atlassian 會給一個新的，舊的會失效)
    config["refresh_token"] = new_refresh_token
    save_config(config)
    print("Token 刷新成功並已更新設定檔。")
    
    return new_access_token

def get_issue_details(issue_key):
    # 1. 讀取設定
    config = load_config()
    
    # 2. 取得有效 Token (建議每次執行都刷新，確保有效性)
    try:
        access_token = get_fresh_access_token(config)
    except Exception as e:
        print(f"錯誤: {e}")
        return

    # 3. 呼叫 Jira API
    cloud_id = config["cloud_id"]
    api_url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{issue_key}"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    print(f"正在查詢 Issue: {issue_key} ...")
    response = requests.get(api_url, headers=headers)
    
    if response.status_code == 200:
        issue_data = response.json()
        # 簡單展示部分資料
        summary = issue_data['fields']['summary']
        status = issue_data['fields']['status']['name']
        assignee = issue_data['fields']['assignee']['displayName'] if issue_data['fields']['assignee'] else "未指派"
        
        print("-" * 30)
        print(f"Issue Key: {issue_key}")
        print(f"主題: {summary}")
        print(f"狀態: {status}")
        print(f"負責人: {assignee}")
        print("-" * 30)
    else:
        print(f"查詢失敗 (Status {response.status_code}): {response.text}")

# ================= 執行區 =================
if __name__ == "__main__":
    # 在這裡填入您想查的 Issue ID
    TARGET_ISSUE = "KAN-5" 
    get_issue_details(TARGET_ISSUE)
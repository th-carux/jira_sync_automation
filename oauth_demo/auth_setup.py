import requests
import webbrowser
import json
from flask import Flask, request

# ================= 設定區 =================
import os
from dotenv import load_dotenv  # 引入讀取套件

# 1. 載入 .env 檔案中的變數
load_dotenv()

# 2. 從環境變數中讀取 (如果讀不到會回傳 None)
CLIENT_ID = os.getenv("ATLASSIAN_CLIENT_ID")
CLIENT_SECRET = os.getenv("ATLASSIAN_CLIENT_SECRET")

# 加入檢查機制，避免設定錯誤
if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError("錯誤：請確認 .env 檔案中已設定 Client ID 與 Secret")

# 必須與 Console 設定完全一致
REDIRECT_URI = "http://localhost:8080/callback" 
# 請求權限：讀取、寫入資料 + 離線存取(取得Refresh Token)
SCOPES = "read:jira-work write:jira-work offline_access"
# =========================================

app = Flask(__name__)

@app.route("/callback")
def callback():
    # 1. 取得授權碼 (Authorization Code)
    code = request.args.get("code")
    if not code:
        return "Error: No code received", 400

    # 2. 用 Code 交換 Access Token 和 Refresh Token
    token_url = "https://auth.atlassian.com/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    
    response = requests.post(token_url, json=payload)
    if response.status_code != 200:
        return f"Error fetching token: {response.text}", 400
    
    tokens = response.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    # 3. 取得 Cloud ID (因為 Token 是通用的，需確認是指向哪個 Jira 站點)
    resource_url = "https://api.atlassian.com/oauth/token/accessible-resources"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    res_response = requests.get(resource_url, headers=headers)
    if res_response.status_code != 200:
        return f"Error fetching resources: {res_response.text}", 400
    
    resources = res_response.json()
    if not resources:
        return "Error: No accessible resources found for this user.", 400

    # 這裡預設抓取第一個站點 (如果您有多個 Jira 站點，可在此加入邏輯篩選)
    cloud_id = resources[0]["id"]
    site_name = resources[0]["name"]
    
    # 4. 將所有資訊存入設定檔 (JSON)
    config_data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "cloud_id": cloud_id,
        "site_name": site_name,
        "refresh_token": refresh_token # 關鍵：我們只存 Refresh Token 即可，Access Token 會過期
    }

    with open("jira_config.json", "w") as f:
        json.dump(config_data, f, indent=4)

    return f"""
    <h1>設定成功！</h1>
    <p>已取得 Cloud ID: {cloud_id} ({site_name})</p>
    <p>設定檔已儲存為 jira_config.json</p>
    <p>您現在可以關閉此視窗並停止 Python 程式。</p>
    """

def main():
    # 組合授權網址
    auth_url = (
        f"https://auth.atlassian.com/authorize?"
        f"audience=api.atlassian.com&"
        f"client_id={CLIENT_ID}&"
        f"scope={SCOPES}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"response_type=code&"
        f"prompt=consent"
    )
    
    print(f"正在開啟瀏覽器進行授權... 請在網頁中點擊同意。")
    webbrowser.open(auth_url)
    
    # 啟動本地 Web Server 等待回調
    app.run(port=8080)

if __name__ == "__main__":
    main()
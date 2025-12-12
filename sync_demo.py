import os
import json
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# ================= Configuration =================
JIRA_DOMAIN = os.getenv("JIRA_DOMAIN")
SA_USER = os.getenv("SERVICE_ACCOUNT_USER")
SA_TOKEN = os.getenv("SERVICE_ACCOUNT_TOKEN")
REMOTE_LINK_FIELD_ID = os.getenv("REMOTE_LINK_FIELD_ID")
SOURCE_PROJECT_KEY = os.getenv("SOURCE_PROJECT_KEY")
TARGET_PROJECT_KEY = os.getenv("TARGET_PROJECT_KEY")
ISSUE_TYPE = os.getenv("ISSUE_TYPE", "Task")  # 預設值為 Task
MAPPING_FILE = "field_mapping.json"

class JiraClient:
    """使用 Service Account (API Token) 的 Jira 客戶端"""
    def __init__(self, domain, user, token):
        self.base_url = f"https://{domain}/rest/api/3"
        self.auth = HTTPBasicAuth(user, token)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def search_issues(self, jql):
        url = f"{self.base_url}/search"
        params = {
            "jql": jql,
            "maxResults": 100,
            "fields": "*all"
        }
        response = requests.get(url, auth=self.auth, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json().get('issues', [])

    def create_issue(self, payload):
        url = f"{self.base_url}/issue"
        response = requests.post(url, auth=self.auth, headers=self.headers, json=payload)
        if response.status_code == 201:
            key = response.json()['key']
            print(f"  [Created] New issue key: {key}")
            return key
        else:
            print(f"  [Error Create] {response.status_code}: {response.text}")
            return None

    def update_issue(self, issue_key, fields_dict):
        url = f"{self.base_url}/issue/{issue_key}"
        payload = {"fields": fields_dict}
        response = requests.put(url, auth=self.auth, headers=self.headers, json=payload)
        if response.status_code == 204:
            print(f"  [Updated] {issue_key} fields updated.")
        else:
            print(f"  [Error Update] {response.status_code}: {response.text}")

class FieldProcessor:
    """處理欄位映射邏輯 (與之前相同)"""
    def __init__(self, mapping_config):
        self.mapping_config = mapping_config

    def resolve_value(self, input_val, config_item, direction="S2T"):
        strategy = config_item.get('strategy', 'DIRECT_COPY')

        if strategy == 'STATIC_VALUE':
            return config_item.get('static_value')

        if strategy == 'DIRECT_COPY':
            return input_val

        if strategy == 'MAPPED_SYNC':
            # 處理物件取值 (例如 priority: {name: 'High'})
            raw_val = input_val
            if isinstance(input_val, dict):
                raw_val = input_val.get('name') or input_val.get('value')

            if direction == "S2T":
                mapping = config_item.get('value_mapping', {})
                mapped_val = mapping.get(raw_val)
                return {"value": mapped_val} if mapped_val else None # 假設是 Select List

            elif direction == "T2S":
                # 1. 查 reverse_mapping (Explicit)
                reverse_map = config_item.get('reverse_mapping', {})
                if raw_val in reverse_map:
                    return {"value": reverse_map[raw_val]}

                # 2. 查 value_mapping 反轉 (Implicit)
                forward_map = config_item.get('value_mapping', {})
                for k, v in forward_map.items():
                    if v == raw_val:
                        return {"value": k}
        return None

    def prepare_create_payload(self, source_issue, target_project_key, issue_type):
        """準備 Create Payload"""
        payload = {
            "fields": {
                "project": {"key": target_project_key},
                "issuetype": {"name": issue_type},
                REMOTE_LINK_FIELD_ID: source_issue['key']
            }
        }

        for item in self.mapping_config:
            # 觸發條件檢查
            if "CREATE" not in item.get('trigger_on', ["CREATE", "UPDATE"]):
                # 如果該欄位設定了 trigger_on 且不包含 CREATE，則跳過
                # 但通常預設是都觸發，除了少數 Update Only 的
                pass

            # 靜態值處理
            if item['strategy'] == 'STATIC_VALUE':
                if "CREATE" in item.get('trigger_on', []):
                    val = self.resolve_value(None, item)
                    if val: payload["fields"][item['target_field']] = val
                continue

            # 一般欄位
            if item['source_field']:
                src_val = source_issue['fields'].get(item['source_field'])
                if src_val:
                    target_val = self.resolve_value(src_val, item, "S2T")
                    if target_val:
                        payload["fields"][item['target_field']] = target_val

        return payload

def run_sync():
    print("=== Start Sync (Service Account Mode) ===")

    # 初始化 Client
    jira = JiraClient(JIRA_DOMAIN, SA_USER, SA_TOKEN)

    with open(MAPPING_FILE, 'r') as f:
        mappings = json.load(f)
    processor = FieldProcessor(mappings)

    # 1. 取得 Source Issues
    print("Fetching Source Issues...")
    source_issues = jira.search_issues(f"project = {SOURCE_PROJECT_KEY} AND updated > -1d")

    # 2. 取得 Target Issues
    print("Fetching Target Issues...")
    target_issues = jira.search_issues(f"project = {TARGET_PROJECT_KEY} AND {REMOTE_LINK_FIELD_ID} is not EMPTY")

    # 3. 建立 Lookup Map
    target_map = {}
    for t in target_issues:
        remote_val = t['fields'].get(REMOTE_LINK_FIELD_ID)
        # 防呆：如果欄位是複雜物件
        if isinstance(remote_val, dict): remote_val = remote_val.get('value')

        if remote_val:
            target_map[remote_val] = t

    # 4. 執行同步
    for s_issue in source_issues:
        s_key = s_issue['key']
        print(f"\nProcessing: {s_key}")

        if s_key not in target_map:
            # Create
            print("  -> Creating new issue in Target...")
            payload = processor.prepare_create_payload(s_issue, TARGET_PROJECT_KEY, ISSUE_TYPE)
            jira.create_issue(payload)
        else:
            # Update
            t_issue = target_map[s_key]
            print(f"  -> Found match: {t_issue['key']}")

            # 時間比對 (Last Updated Wins)
            s_time = s_issue['fields']['updated']
            t_time = t_issue['fields']['updated']

            direction = "NONE"
            if s_time > t_time: direction = "S2T"
            elif t_time > s_time: direction = "T2S"

            if direction == "NONE":
                print("  -> Skipped (Synced)")
                continue

            # 準備更新欄位
            update_fields = {}
            target_key_to_update = None

            for item in mappings:
                # 忽略只在 Create 觸發的欄位
                if item.get('strategy') == 'STATIC_VALUE': continue

                # 忽略方向不符的
                if item['sync_direction'] != "BIDIRECTIONAL" and item['sync_direction'] != direction:
                    continue

                if direction == "S2T":
                    val = processor.resolve_value(s_issue['fields'].get(item['source_field']), item, "S2T")
                    if val: update_fields[item['target_field']] = val
                    target_key_to_update = t_issue['key']

                elif direction == "T2S":
                    val = processor.resolve_value(t_issue['fields'].get(item['target_field']), item, "T2S")
                    if val: update_fields[item['source_field']] = val
                    target_key_to_update = s_issue['key'] # 這裡其實是 source key

            if update_fields:
                print(f"  -> Updating {target_key_to_update} ({direction})...")
                jira.update_issue(target_key_to_update, update_fields)

if __name__ == "__main__":
    run_sync()
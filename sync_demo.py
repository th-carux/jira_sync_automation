import os
import json
import requests
from dotenv import load_dotenv, find_dotenv

# 載入環境變數
env_file = find_dotenv()
if env_file:
    print(f"📄 載入環境變數檔案: {env_file}")
    load_dotenv(env_file, verbose=True)
else:
    print("⚠️  警告: 找不到 .env 檔案")
    print("   請確認專案目錄中是否存在 .env 檔案")
    load_dotenv()  # 仍然嘗試載入，可能在其他位置

# ================= Configuration =================
# Source Jira Site 配置
SOURCE_CLOUD_ID = os.getenv("SOURCE_CLOUD_ID")
SOURCE_API_TOKEN = os.getenv("SOURCE_API_TOKEN")
SOURCE_PROJECT_KEY = os.getenv("SOURCE_PROJECT_KEY")

# Target Jira Site 配置
TARGET_CLOUD_ID = os.getenv("TARGET_CLOUD_ID")
TARGET_API_TOKEN = os.getenv("TARGET_API_TOKEN")
TARGET_PROJECT_KEY = os.getenv("TARGET_PROJECT_KEY")

# 驗證必要的環境變數
def validate_env_vars():
    """驗證必要的環境變數是否已設定"""
    required_vars = {
        "SOURCE_CLOUD_ID": SOURCE_CLOUD_ID,
        "SOURCE_API_TOKEN": SOURCE_API_TOKEN,
        "SOURCE_PROJECT_KEY": SOURCE_PROJECT_KEY,
        "TARGET_CLOUD_ID": TARGET_CLOUD_ID,
        "TARGET_API_TOKEN": TARGET_API_TOKEN,
        "TARGET_PROJECT_KEY": TARGET_PROJECT_KEY,
    }

    missing_vars = []
    for var_name, var_value in required_vars.items():
        if var_value is None or (isinstance(var_value, str) and var_value.strip() == ""):
            missing_vars.append(var_name)

    if missing_vars:
        print("\n❌ 錯誤: 以下環境變數未設定或為空:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\n💡 解決方案:")
        print("   1. 確認專案目錄中存在 .env 檔案")
        print("   2. 檢查 .env 檔案中是否包含以下變數:")
        for var in missing_vars:
            print(f"      {var}=your_value_here")
        print("   3. 確認 .env 檔案格式正確（每行一個 KEY=VALUE）")
        return False

    # 顯示已載入的變數（隱藏敏感值）
    print("\n✅ 環境變數驗證通過:")
    print(f"   SOURCE_CLOUD_ID: {SOURCE_CLOUD_ID[:8]}..." if SOURCE_CLOUD_ID else "   SOURCE_CLOUD_ID: None")
    print(f"   SOURCE_API_TOKEN: {'*' * 20}... (已隱藏)" if SOURCE_API_TOKEN else "   SOURCE_API_TOKEN: None")
    print(f"   SOURCE_PROJECT_KEY: {SOURCE_PROJECT_KEY}" if SOURCE_PROJECT_KEY else "   SOURCE_PROJECT_KEY: None")
    print(f"   TARGET_CLOUD_ID: {TARGET_CLOUD_ID[:8]}..." if TARGET_CLOUD_ID else "   TARGET_CLOUD_ID: None")
    print(f"   TARGET_API_TOKEN: {'*' * 20}... (已隱藏)" if TARGET_API_TOKEN else "   TARGET_API_TOKEN: None")
    print(f"   TARGET_PROJECT_KEY: {TARGET_PROJECT_KEY}" if TARGET_PROJECT_KEY else "   TARGET_PROJECT_KEY: None")
    return True

# 其他配置
# REMOTE_LINK_FIELD_ID = os.getenv("REMOTE_LINK_FIELD_ID")
REMOTE_LINK_FIELD_ID = "customer_ticket_id"
ISSUE_TYPE = os.getenv("ISSUE_TYPE", "Task")  # 預設值為 Task
MAPPING_FILE = "field_mapping.json"

class JiraClient:
    """使用 Cloud ID 和 Bearer Token 的 Jira 客戶端"""
    def __init__(self, cloud_id, api_token):
        self.cloud_id = cloud_id
        self.base_url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def test_connection(self):
        """測試連接到 Jira API"""
        try:
            url = f"{self.base_url}/myself"
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                user_info = response.json()
                print(f"  ✅ 連接成功 - 用戶: {user_info.get('displayName', 'N/A')} ({user_info.get('accountId', 'N/A')})")
                return True
            else:
                self._handle_error(response, "test_connection")
                return False
        except Exception as e:
            print(f"  ❌ 連接失敗: {str(e)}")
            return False

    def _handle_error(self, response, operation):
        """處理 HTTP 錯誤並提供詳細的診斷信息"""
        if response.status_code == 410:
            print(f"\n  [Error] HTTP 410 Gone - 資源已永久移除")
            print(f"  操作: {operation}")
            print(f"  URL: {response.url}")
            print(f"  Cloud ID: {self.cloud_id}")
            print(f"  可能的原因:")
            print(f"    1. Cloud ID 不正確或已過期")
            print(f"    2. API 端點格式已更改")
            print(f"    3. Jira 站點配置已變更")
            print(f"  響應內容: {response.text[:500]}")
        elif response.status_code == 401:
            print(f"\n  [Error] HTTP 401 Unauthorized - 認證失敗")
            print(f"  操作: {operation}")
            print(f"  請檢查 API Token 是否正確")
        elif response.status_code == 403:
            print(f"\n  [Error] HTTP 403 Forbidden - 權限不足")
            print(f"  操作: {operation}")
            print(f"  請檢查 API Token 是否有足夠的權限")
        elif response.status_code == 404:
            print(f"\n  [Error] HTTP 404 Not Found - 資源不存在")
            print(f"  操作: {operation}")
            print(f"  URL: {response.url}")

    def search_issues(self, jql):
        url = f"{self.base_url}/search"
        params = {
            "jql": jql,
            "maxResults": 100,
            "fields": "*all"
        }
        response = requests.get(url, headers=self.headers, params=params)
        if not response.ok:
            self._handle_error(response, f"search_issues (JQL: {jql})")
        response.raise_for_status()
        return response.json().get('issues', [])

    def create_issue(self, payload):
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
        url = f"{self.base_url}/issue/{issue_key}"
        payload = {"fields": fields_dict}
        response = requests.put(url, headers=self.headers, json=payload)
        if response.status_code == 204:
            print(f"  [Updated] {issue_key} fields updated.")
        else:
            if not response.ok:
                self._handle_error(response, f"update_issue (key: {issue_key})")
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

def validate_fields():
    """驗證 Source 和 Target Issues 的欄位是否符合 field_mapping.json 的定義"""
    print("=== Field Validation (Dual Jira Sites Mode) ===")

    # 驗證環境變數
    if not validate_env_vars():
        return None

    # 初始化 Source 和 Target 的 Client
    source_jira = JiraClient(SOURCE_CLOUD_ID, SOURCE_API_TOKEN)
    target_jira = JiraClient(TARGET_CLOUD_ID, TARGET_API_TOKEN)

    # 測試連接
    print("\n[0] Testing Connections...")
    print("  Source Jira:")
    source_ok = source_jira.test_connection()
    print("  Target Jira:")
    target_ok = target_jira.test_connection()

    if not source_ok or not target_ok:
        print("\n⚠️  連接測試失敗，請檢查配置後重試")
        return None

    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        mappings = json.load(f)

    # 1. 取得 Source Issues
    print("\n[1] Fetching Source Issues...")
    source_issues = source_jira.search_issues(f"project = {SOURCE_PROJECT_KEY} AND updated > -1d")
    print(f"   Found {len(source_issues)} source issues")

    # 2. 取得 Target Issues
    print("\n[2] Fetching Target Issues...")
    target_issues = target_jira.search_issues(f"project = {TARGET_PROJECT_KEY} AND {REMOTE_LINK_FIELD_ID} is not EMPTY")
    print(f"   Found {len(target_issues)} target issues")

    # 3. 建立 Lookup Map
    target_map = {}
    for t in target_issues:
        remote_val = t['fields'].get(REMOTE_LINK_FIELD_ID)
        # 防呆：如果欄位是複雜物件
        if isinstance(remote_val, dict):
            remote_val = remote_val.get('value')
        if remote_val:
            target_map[remote_val] = t

    # 4. 驗證每個 Source Issue
    print("\n[3] Validating Source Issues...")
    source_validation_results = []
    for s_issue in source_issues:
        s_key = s_issue['key']
        s_fields = s_issue.get('fields', {})
        missing_fields = []

        for mapping in mappings:
            source_field = mapping.get('source_field')
            if source_field:  # 跳過 STATIC_VALUE 策略（source_field 為 null）
                if source_field not in s_fields:
                    missing_fields.append({
                        'field': source_field,
                        'description': mapping.get('description', 'N/A'),
                        'type': 'missing'
                    })
                elif s_fields[source_field] is None:
                    missing_fields.append({
                        'field': source_field,
                        'description': mapping.get('description', 'N/A'),
                        'type': 'null_value'
                    })

        if missing_fields:
            source_validation_results.append({
                'issue_key': s_key,
                'missing_fields': missing_fields
            })

    # 5. 驗證每個 Target Issue
    print("\n[4] Validating Target Issues...")
    target_validation_results = []
    for t_issue in target_issues:
        t_key = t_issue['key']
        t_fields = t_issue.get('fields', {})
        missing_fields = []

        for mapping in mappings:
            target_field = mapping.get('target_field')
            if target_field:
                if target_field not in t_fields:
                    missing_fields.append({
                        'field': target_field,
                        'description': mapping.get('description', 'N/A'),
                        'type': 'missing'
                    })
                elif t_fields[target_field] is None:
                    missing_fields.append({
                        'field': target_field,
                        'description': mapping.get('description', 'N/A'),
                        'type': 'null_value'
                    })

        if missing_fields:
            target_validation_results.append({
                'issue_key': t_key,
                'missing_fields': missing_fields
            })

    # 6. 驗證配對的 Issues
    print("\n[5] Validating Paired Issues...")
    paired_validation_results = []
    for s_issue in source_issues:
        s_key = s_issue['key']
        s_fields = s_issue.get('fields', {})

        if s_key in target_map:
            t_issue = target_map[s_key]
            t_key = t_issue['key']
            t_fields = t_issue.get('fields', {})

            pair_issues = []
            for mapping in mappings:
                source_field = mapping.get('source_field')
                target_field = mapping.get('target_field')

                # 檢查 source_field
                if source_field:
                    if source_field not in s_fields or s_fields[source_field] is None:
                        pair_issues.append({
                            'mapping_description': mapping.get('description', 'N/A'),
                            'source_field': source_field,
                            'target_field': target_field,
                            'issue': 'source_field missing or null'
                        })

                # 檢查 target_field
                if target_field:
                    if target_field not in t_fields or t_fields[target_field] is None:
                        pair_issues.append({
                            'mapping_description': mapping.get('description', 'N/A'),
                            'source_field': source_field,
                            'target_field': target_field,
                            'issue': 'target_field missing or null'
                        })

            if pair_issues:
                paired_validation_results.append({
                    'source_key': s_key,
                    'target_key': t_key,
                    'issues': pair_issues
                })

    # 7. 輸出驗證結果
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)

    print(f"\n[Source Issues Validation]")
    if source_validation_results:
        print(f"  ⚠️  Found {len(source_validation_results)} source issues with missing fields:")
        for result in source_validation_results:
            print(f"\n  Issue: {result['issue_key']}")
            for missing in result['missing_fields']:
                print(f"    - {missing['field']} ({missing['description']}) - {missing['type']}")
    else:
        print(f"  ✅ All {len(source_issues)} source issues have all required fields")

    print(f"\n[Target Issues Validation]")
    if target_validation_results:
        print(f"  ⚠️  Found {len(target_validation_results)} target issues with missing fields:")
        for result in target_validation_results:
            print(f"\n  Issue: {result['issue_key']}")
            for missing in result['missing_fields']:
                print(f"    - {missing['field']} ({missing['description']}) - {missing['type']}")
    else:
        print(f"  ✅ All {len(target_issues)} target issues have all required fields")

    print(f"\n[Paired Issues Validation]")
    if paired_validation_results:
        print(f"  ⚠️  Found {len(paired_validation_results)} paired issues with field mismatches:")
        for result in paired_validation_results:
            print(f"\n  Pair: {result['source_key']} <-> {result['target_key']}")
            for issue in result['issues']:
                print(f"    - {issue['mapping_description']}")
                print(f"      Source Field: {issue['source_field']}, Target Field: {issue['target_field']}")
                print(f"      Issue: {issue['issue']}")
    else:
        print(f"  ✅ All {len(target_map)} paired issues have matching fields")

    print("\n" + "=" * 80)

    # 返回驗證結果
    return {
        'source_issues_count': len(source_issues),
        'target_issues_count': len(target_issues),
        'paired_issues_count': len(target_map),
        'source_validation_results': source_validation_results,
        'target_validation_results': target_validation_results,
        'paired_validation_results': paired_validation_results
    }

def run_sync():
    print("=== Start Sync (Dual Jira Sites Mode) ===")

    # 驗證環境變數
    if not validate_env_vars():
        return

    # 初始化 Source 和 Target 的 Client
    source_jira = JiraClient(SOURCE_CLOUD_ID, SOURCE_API_TOKEN)
    target_jira = JiraClient(TARGET_CLOUD_ID, TARGET_API_TOKEN)

    # 測試連接
    print("\n[0] Testing Connections...")
    print("  Source Jira:")
    source_ok = source_jira.test_connection()
    print("  Target Jira:")
    target_ok = target_jira.test_connection()

    if not source_ok or not target_ok:
        print("\n⚠️  連接測試失敗，請檢查配置後重試")
        return

    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        mappings = json.load(f)
    processor = FieldProcessor(mappings)

    # 1. 取得 Source Issues
    print("Fetching Source Issues...")
    source_issues = source_jira.search_issues(f"project = {SOURCE_PROJECT_KEY} AND updated > -1d")

    # 2. 取得 Target Issues
    print("Fetching Target Issues...")
    target_issues = target_jira.search_issues(f"project = {TARGET_PROJECT_KEY} AND {REMOTE_LINK_FIELD_ID} is not EMPTY")

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
            target_jira.create_issue(payload)
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
                # 根據同步方向選擇對應的 Jira Client
                if direction == "S2T":
                    target_jira.update_issue(target_key_to_update, update_fields)
                elif direction == "T2S":
                    source_jira.update_issue(target_key_to_update, update_fields)

if __name__ == "__main__":
    validate_fields()
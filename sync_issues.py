"""
Jira Issue 同步程式
從 Source Jira 同步 Issue 到 Target Jira
"""
import os
import json
import requests
import base64
import re
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 配置文件
CONFIG_FILE = "jira_config.json"
MAPPING_FILE = "jira_field_mapping.json"

# Debug 模式設定（可通過環境變數控制）
DEBUG_MODE = True

# 從 jira_config.json 讀取設定
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError(f"錯誤：找不到 {CONFIG_FILE}，請確認檔案存在")

try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
        source_config = config.get("source", {})
        target_config = config.get("target", {})
        sync_issue_types = config.get("syncIssueType", [])
except Exception as e:
    raise ValueError(f"錯誤：無法讀取 {CONFIG_FILE}: {e}")

if not source_config:
    raise ValueError(f"錯誤：{CONFIG_FILE} 中找不到 source 配置")
if not target_config:
    raise ValueError(f"錯誤：{CONFIG_FILE} 中找不到 target 配置")

# 驗證 syncIssueType 格式
if sync_issue_types is not None:
    if not isinstance(sync_issue_types, list):
        raise ValueError(f"錯誤：{CONFIG_FILE} 的 syncIssueType 格式錯誤，必須是一個字符串數組")
    for i, item in enumerate(sync_issue_types):
        if not isinstance(item, str):
            raise ValueError(f"錯誤：{CONFIG_FILE} 的 syncIssueType 格式錯誤，數組中的第 {i+1} 個元素必須是字符串")

def get_auth_headers(auth_type: str, api_token: str, email: str = None) -> Dict:
    """根據 authType 生成對應的認證標頭"""
    if auth_type == "Basic":
        if not email:
            raise ValueError("Basic Auth 需要 email 參數")
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

def get_base_url(config: Dict) -> str:
    """根據配置構建 API URL"""
    auth_type = config.get("authType", "Basic")
    
    if auth_type == "Basic":
        domain = config.get("domain")
        if not domain:
            raise ValueError("Basic Auth 需要 domain")
        if domain.startswith("http://") or domain.startswith("https://"):
            base_domain = domain.rstrip("/")
        else:
            base_domain = f"https://{domain}"
        return f"{base_domain}/rest/api/3"
    elif auth_type == "Bearer":
        cloud_id = config.get("cloudId")
        if not cloud_id:
            raise ValueError("Bearer Auth 需要 cloudId")
        return f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"
    else:
        raise ValueError(f"不支援的 authType: {auth_type}")

class JiraClient:
    """Jira 客戶端，支援 Basic 和 Bearer 認證"""
    def __init__(self, config: Dict):
        self.config = config
        self.auth_type = config.get("authType", "Basic")
        self.api_token = config.get("apiToken")
        self.email = config.get("email")
        self.base_url = get_base_url(config)
        self.headers = get_auth_headers(self.auth_type, self.api_token, self.email)

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
            print(f"  可能的原因: API 端點格式已更改")
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

    def search_issues(self, jql: str, max_results: int = 100):
        """搜尋 Issues，使用新的 /search/jql API"""
        url = f"{self.base_url}/search/jql"
        all_issues = []
        start_at = 0
        
        while True:
            params = {
                "jql": jql,
                "maxResults": max_results,
                "startAt": start_at,
                "fields": "*all,attachment"  # 確保包含 attachment 欄位
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
            
            # 檢查是否還有更多
            if len(issues) < max_results:
                break
            
            start_at += max_results
        
        return all_issues

    def create_issue(self, payload):
        """創建 Issue"""
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
        """更新 Issue"""
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
        """取得 Issue 的所有附件"""
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
        """下載附件到本地"""
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
                print(f"    警告: 無法下載附件 (Status {response.status_code})")
                return False
        except Exception as e:
            print(f"    錯誤: 下載附件時發生錯誤: {str(e)}")
            return False

    def upload_attachment(self, issue_key, file_path):
        """上傳附件到 Issue"""
        url = f"{self.base_url}/issue/{issue_key}/attachments"
        # 上傳附件需要使用 multipart/form-data
        headers = self.headers.copy()
        headers.pop('Content-Type', None)  # 移除 Content-Type，讓 requests 自動設置
        # Jira API 需要 X-Atlassian-Token 頭
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
            print(f"    錯誤: 上傳附件時發生錯誤: {str(e)}")
            return False

class FieldProcessor:
    """處理欄位映射邏輯"""
    def __init__(self, mapping_config):
        self.mapping_config = mapping_config

    def resolve_value(self, input_val, config_item, direction="S2T"):
        """解析欄位值，根據策略進行轉換"""
        strategy = config_item.get('strategy', 'DIRECT_COPY')

        if strategy == 'STATIC_VALUE':
            static_value = config_item.get('static_value', {})
            return static_value.get('value') if isinstance(static_value, dict) else static_value

        if strategy == 'SYNC_METADATA':
            # SYNC_METADATA 策略在 prepare_create_payload 和 prepare_update_payload 中處理
            return None

        if strategy == 'DIRECT_COPY':
            return input_val

        if strategy == 'MAPPED_SYNC':
            # 處理物件取值 (例如 priority: {name: 'High'})
            raw_val = input_val
            if isinstance(input_val, dict):
                raw_val = input_val.get('name') or input_val.get('value') or input_val

            if direction == "S2T":
                mapping = config_item.get('valueMapping', {})
                mapped_val = mapping.get(raw_val)
                # 根據欄位類型返回適當的格式
                if mapped_val:
                    field_type = config_item.get('type')
                    field_id = config_item.get('fieldId', '')
                    
                    # Priority 字段需要 {"name": "..."} 格式
                    if field_type == 'system' and field_id == 'priority':
                        return {"name": mapped_val}
                    
                    # 自定義字段（選項列表）需要 {"value": "..."} 格式
                    if field_type == 'custom' or 'customfield' in str(config_item.get('targetFieldId', '')):
                        return {"value": mapped_val}
                    
                    # 其他 system 字段返回字符串
                    return mapped_val
                return None

            elif direction == "T2S":
                # 1. 查 reverseMapping (Explicit)
                reverse_map = config_item.get('reverseMapping', {})
                if raw_val in reverse_map:
                    return {"value": reverse_map[raw_val]}

                # 2. 查 valueMapping 反轉 (Implicit)
                forward_map = config_item.get('valueMapping', {})
                for k, v in forward_map.items():
                    if v == raw_val:
                        return {"value": k}
        
        return None

    def prepare_create_payload(self, source_issue, target_project_key, issue_type, customer_issue_id_field: str):
        """準備創建 Issue 的 Payload"""
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
            
            # 處理 SYNC_METADATA 策略
            # 注意：這些字段不在創建時設置，而是在創建後立即更新
            # 因為某些 issue type 的創建屏幕可能不包含這些字段
            if strategy == 'SYNC_METADATA':
                # 跳過，將在創建 issue 後單獨更新
                continue

            # 處理 STATIC_VALUE 策略
            # 注意：某些 STATIC_VALUE 字段可能在創建時無法設置（如某些 issue type 的創建屏幕不包含這些字段）
            # 這些字段將在創建後單獨更新
            if strategy == 'STATIC_VALUE':
                trigger_on = item.get('triggerOn', item.get('trigger_on', ['CREATE', 'UPDATE']))
                if 'CREATE' in trigger_on:
                    # 暫時跳過，將在創建後單獨更新（避免創建時字段限制問題）
                    # 如果需要，可以在這裡添加邏輯來決定哪些字段可以在創建時設置
                    continue

            # 處理一般欄位
            field_type = item.get('type')
            
            if field_type == 'system':
                # System 欄位使用 fieldId
                source_field = item.get('fieldId')
                target_field = item.get('fieldId')  # System 欄位通常同名
            else:
                # Custom 欄位使用 sourceFieldId 和 targetFieldId
                source_field = item.get('sourceFieldId')
                target_field = item.get('targetFieldId')
            
            if source_field and target_field:
                # 跳過 attachment 字段，因為 Jira API 不允許在創建時設置 attachment
                if field_type == 'system' and source_field == 'attachment':
                    continue
                
                src_val = source_issue['fields'].get(source_field)
                if src_val is not None:
                    target_val = self.resolve_value(src_val, item, "S2T")
                    if target_val is not None:
                        # 處理 summary 字段的前缀（根據 note）
                        if field_type == 'system' and source_field == 'summary':
                            note = item.get('note', '')
                            if '[MB-EAL]' in note or 'prefix' in note.lower():
                                # 檢查是否已經有前缀
                                if isinstance(target_val, str) and not target_val.startswith('[MB-EAL]'):
                                    target_val = f'[MB-EAL] {target_val}'
                        payload["fields"][target_field] = target_val

        return payload

    def prepare_update_payload(self, source_issue, target_issue, direction: str, customer_issue_id_field: str, last_sync_time_field: str):
        """準備更新 Issue 的 Payload"""
        update_fields = {}

        for item in self.mapping_config:
            sync_direction = item.get('syncDirection', 'S2T')
            
            # 檢查同步方向
            if sync_direction != "BIDIRECTIONAL" and sync_direction != direction:
                continue

            strategy = item.get('strategy', 'DIRECT_COPY')
            
            # 忽略只在 Create 觸發的 STATIC_VALUE
            if strategy == 'STATIC_VALUE':
                trigger_on = item.get('triggerOn', item.get('trigger_on', ['CREATE', 'UPDATE']))
                if 'UPDATE' not in trigger_on:
                    continue
                # 處理 STATIC_VALUE 的更新
                static_value = item.get('staticValue', item.get('static_value', {}))
                target_field_id = item.get('targetFieldId')
                if target_field_id:
                    if isinstance(static_value, dict):
                        update_fields[target_field_id] = static_value.get('value')
                    else:
                        update_fields[target_field_id] = static_value
                continue

            # 處理 SYNC_METADATA 策略
            if strategy == 'SYNC_METADATA':
                metadata_type = item.get('metadataType')
                target_field_id = item.get('targetFieldId')
                
                if metadata_type == 'last_sync_time' and target_field_id:
                    # 更新同步時間
                    current_time = datetime.now().isoformat()
                    update_fields[target_field_id] = current_time
                continue

            field_type = item.get('type')
            
            if direction == "S2T":
                if field_type == 'system':
                    # System 欄位使用 fieldId
                    source_field = item.get('fieldId')
                    target_field = item.get('fieldId')
                else:
                    # Custom 欄位使用 sourceFieldId 和 targetFieldId
                    source_field = item.get('sourceFieldId')
                    target_field = item.get('targetFieldId')
                
                if source_field and target_field:
                    src_val = source_issue['fields'].get(source_field)
                    if src_val is not None:
                        val = self.resolve_value(src_val, item, "S2T")
                        if val is not None:
                            # 處理 summary 字段的前缀（根據 note）
                            if field_type == 'system' and source_field == 'summary':
                                note = item.get('note', '')
                                if '[MB-EAL]' in note or 'prefix' in note.lower():
                                    # 檢查是否已經有前缀
                                    if isinstance(val, str) and not val.startswith('[MB-EAL]'):
                                        val = f'[MB-EAL] {val}'
                            update_fields[target_field] = val

            elif direction == "T2S":
                if field_type == 'system':
                    # System 欄位使用 fieldId
                    source_field = item.get('fieldId')
                    target_field = item.get('fieldId')
                else:
                    # Custom 欄位使用 sourceFieldId 和 targetFieldId
                    source_field = item.get('sourceFieldId')
                    target_field = item.get('targetFieldId')
                
                if source_field and target_field:
                    tgt_val = target_issue['fields'].get(target_field)
                    if tgt_val is not None:
                        val = self.resolve_value(tgt_val, item, "T2S")
                        if val is not None:
                            update_fields[source_field] = val

        return update_fields

def get_customer_issue_id_field(mappings: List[Dict]) -> Optional[str]:
    """從映射配置中取得 customer_issue_id 欄位 ID"""
    for item in mappings:
        if item.get('strategy') == 'SYNC_METADATA' and item.get('metadataType') == 'customer_issue_id':
            return item.get('targetFieldId')
    return None

def get_last_sync_time_field(mappings: List[Dict]) -> Optional[str]:
    """從映射配置中取得 last_sync_time 欄位 ID"""
    for item in mappings:
        if item.get('strategy') == 'SYNC_METADATA' and item.get('metadataType') == 'last_sync_time':
            return item.get('targetFieldId')
    return None

def remove_prefix_from_filename(filename: str) -> str:
    """移除檔案名稱中的 prefix（格式：[PROJECT_KEY]）"""
    # 匹配格式：[PROJECT_KEY] filename
    pattern = r'^\[[^\]]+\]\s+(.+)$'
    match = re.match(pattern, filename)
    if match:
        return match.group(1)
    return filename

def get_filename_with_prefix(filename: str, project_key: str) -> str:
    """為檔案名稱加上 prefix（使用 project key）"""
    # 格式：[PROJECT_KEY] filename
    prefix = f"[{project_key}]"
    # 如果已經有 prefix，先移除
    clean_filename = remove_prefix_from_filename(filename)
    return f"{prefix} {clean_filename}"

def ensure_local_attachment_dir(target_issue_key: str) -> str:
    """確保本地附件目錄存在，返回目錄路徑"""
    dir_path = target_issue_key
    os.makedirs(dir_path, exist_ok=True)
    return dir_path

def download_attachment_to_local(
    jira_client: JiraClient,
    attachment: Dict,
    local_dir: str,
    project_key: str
) -> Optional[str]:
    """下載附件到本地目錄，返回本地檔案路徑"""
    filename = attachment.get('filename', 'unknown')
    prefixed_filename = get_filename_with_prefix(filename, project_key)
    local_path = os.path.join(local_dir, prefixed_filename)
    
    # 如果檔案已存在，跳過下載
    if os.path.exists(local_path):
        return local_path
    
    if jira_client.download_attachment(attachment, local_path):
        return local_path
    return None

def get_local_attachments(local_dir: str) -> List[str]:
    """取得本地目錄中的所有附件檔案名稱（去除 prefix）"""
    if not os.path.exists(local_dir):
        return []
    
    attachments = []
    for filename in os.listdir(local_dir):
        file_path = os.path.join(local_dir, filename)
        if os.path.isfile(file_path):
            # 移除 prefix 後的名稱
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
    """同步附件"""
    print(f"  -> 同步附件...")
    
    # 確保本地目錄存在
    local_dir = ensure_local_attachment_dir(target_issue_key)
    
    # 取得 source 和 target 的附件列表（需要重新獲取以確保包含最新附件）
    source_attachments = source_jira.get_issue_attachments(source_issue['key'])
    target_attachments = target_jira.get_issue_attachments(target_issue_key)
    
    # 取得本地已存在的附件（去除 prefix 後的名稱）
    local_attachments = get_local_attachments(local_dir)
    
    # 下載 source 附件到本地（如果尚未存在）
    for attachment in source_attachments:
        filename = attachment.get('filename', '')
        clean_name = remove_prefix_from_filename(filename)
        
        # 檢查本地是否已有該檔案
        if clean_name not in local_attachments:
            print(f"    下載 Source 附件: {filename}")
            download_attachment_to_local(
                source_jira, attachment, local_dir,
                source_project_key
            )
    
    # 下載 target 附件到本地（如果尚未存在）
    for attachment in target_attachments:
        filename = attachment.get('filename', '')
        clean_name = remove_prefix_from_filename(filename)
        
        # 檢查本地是否已有該檔案
        if clean_name not in local_attachments:
            print(f"    下載 Target 附件: {filename}")
            download_attachment_to_local(
                target_jira, attachment, local_dir,
                target_project_key
            )
    
    # 同步附件到對應的 Jira Issue
    if direction == "S2T":
        # 將 source 的附件上傳到 target
        for attachment in source_attachments:
            filename = attachment.get('filename', '')
            clean_name = remove_prefix_from_filename(filename)
            
            # 檢查 target 是否已有該附件（去除 prefix 後比較）
            target_has_attachment = False
            for t_att in target_attachments:
                t_clean_name = remove_prefix_from_filename(t_att.get('filename', ''))
                if t_clean_name == clean_name:
                    target_has_attachment = True
                    break
            
            if not target_has_attachment:
                # 從本地取得檔案（加上 project key prefix）
                local_filename = get_filename_with_prefix(filename, source_project_key)
                local_path = os.path.join(local_dir, local_filename)
                
                if os.path.exists(local_path):
                    # 上傳到 target，使用原始檔名（不含 prefix）
                    print(f"    上傳附件到 Target: {filename}")
                    # 創建臨時檔案使用原始檔名
                    temp_path = os.path.join(local_dir, filename)
                    import shutil
                    shutil.copy2(local_path, temp_path)
                    target_jira.upload_attachment(target_issue_key, temp_path)
                    os.remove(temp_path)  # 刪除臨時檔案
    
    elif direction == "T2S":
        # 將 target 的附件上傳到 source
        for attachment in target_attachments:
            filename = attachment.get('filename', '')
            clean_name = remove_prefix_from_filename(filename)
            
            # 檢查 source 是否已有該附件（去除 prefix 後比較）
            source_has_attachment = False
            for s_att in source_attachments:
                s_clean_name = remove_prefix_from_filename(s_att.get('filename', ''))
                if s_clean_name == clean_name:
                    source_has_attachment = True
                    break
            
            if not source_has_attachment:
                # 從本地取得檔案（加上 project key prefix）
                local_filename = get_filename_with_prefix(filename, target_project_key)
                local_path = os.path.join(local_dir, local_filename)
                
                if os.path.exists(local_path):
                    # 上傳到 source，使用原始檔名（不含 prefix）
                    print(f"    上傳附件到 Source: {filename}")
                    # 創建臨時檔案使用原始檔名
                    temp_path = os.path.join(local_dir, filename)
                    import shutil
                    shutil.copy2(local_path, temp_path)
                    source_jira.upload_attachment(source_issue['key'], temp_path)
                    os.remove(temp_path)  # 刪除臨時檔案

def run_sync():
    """執行同步流程"""
    print("=" * 80)
    print("Jira Issue 同步程式")
    if DEBUG_MODE:
        print("  [DEBUG MODE 已啟用]")
        print("    - Source 查詢類型: Test")
        print("    - Target 創建類型: Bug")
    print("=" * 80)
    print()

    # 讀取欄位映射配置
    if not os.path.exists(MAPPING_FILE):
        raise FileNotFoundError(f"錯誤：找不到 {MAPPING_FILE}")
    
    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        mappings = json.load(f)
    
    processor = FieldProcessor(mappings)
    
    # 取得同步元數據欄位 ID
    customer_issue_id_field = get_customer_issue_id_field(mappings)
    last_sync_time_field = get_last_sync_time_field(mappings)
    
    if not customer_issue_id_field:
        print("警告：找不到 customer_issue_id 欄位配置，將無法追蹤已同步的 issue")
    
    # 初始化 Source 和 Target 的 Client
    source_jira = JiraClient(source_config)
    target_jira = JiraClient(target_config)

    # 測試連接
    print("[0] 測試連接...")
    print("  Source Jira:")
    source_ok = source_jira.test_connection()
    print("  Target Jira:")
    target_ok = target_jira.test_connection()

    if not source_ok or not target_ok:
        print("\n⚠️  連接測試失敗，請檢查配置後重試")
        return
    
    print()

    # 1. 取得 Source Issues
    print("[1] 取得 Source Issues...")
    source_project_key = source_config.get("projectKey")
    
    # 構建 JQL 查詢，包含 syncIssueType 過濾
    jql_parts = [f"project = {source_project_key}"]
    
    # Debug 模式：使用 ["Test"] 查詢 source issues
    # 正式模式：使用 syncIssueType 配置
    if DEBUG_MODE:
        print("  [DEBUG MODE] 使用 Test 類型查詢 Source Issues")
        source_issue_types = ["Test"]
        issue_type_filter = " OR ".join([f'issuetype = "{it}"' for it in source_issue_types])
        jql_parts.append(f"({issue_type_filter})")
    elif sync_issue_types:
        issue_type_filter = " OR ".join([f'issuetype = "{it}"' for it in sync_issue_types])
        jql_parts.append(f"({issue_type_filter})")
    
    jql_parts.append("updated >= -1d")  # 最近1天更新的
    
    # 構建 JQL：條件部分用 AND 連接，ORDER BY 單獨添加
    source_jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"
    print(f"  JQL: {source_jql}")
    
    source_issues = source_jira.search_issues(source_jql)
    print(f"  找到 {len(source_issues)} 個 Source Issues")
    print()

    # 2. 取得 Target Issues（根據 customer_issue_id 欄位）
    print("[2] 取得 Target Issues...")
    target_project_key = target_config.get("projectKey")
    
    if customer_issue_id_field:
        target_jql = f"project = {target_project_key} AND {customer_issue_id_field} is not EMPTY"
    else:
        # 如果沒有 customer_issue_id 欄位，取得所有 issue
        target_jql = f"project = {target_project_key}"
    
    print(f"  JQL: {target_jql}")
    target_issues = target_jira.search_issues(target_jql)
    print(f"  找到 {len(target_issues)} 個 Target Issues")
    print()

    # 3. 建立 Lookup Map（根據 customer_issue_id）
    target_map = {}
    for t in target_issues:
        if customer_issue_id_field:
            remote_val = t['fields'].get(customer_issue_id_field)
            # 處理不同格式的值
            if isinstance(remote_val, dict):
                remote_val = remote_val.get('value') or remote_val.get('name')
            if remote_val:
                target_map[str(remote_val)] = t
        else:
            # 如果沒有 customer_issue_id 欄位，無法建立映射
            pass

    # 4. 執行同步
    print("[3] 執行同步...")
    print()
    
    created_count = 0
    updated_count = 0
    skipped_count = 0
    
    for s_issue in source_issues:
        s_key = s_issue['key']
        print(f"處理: {s_key}")

        if s_key not in target_map:
            # Create
            print("  -> 創建新的 Target Issue...")
            # 取得 issue type
            if DEBUG_MODE:
                # Debug 模式：使用 Bug 類型創建 target issue
                issue_type = "Bug"
                print(f"  [DEBUG MODE] 使用 Bug 類型創建 Target Issue")
            else:
                # 正式模式：從 source issue 取得 issue type 或使用預設值
                issue_type = s_issue['fields'].get('issuetype', {}).get('name', 'Task')
            
            payload = processor.prepare_create_payload(
                s_issue, 
                target_project_key, 
                issue_type,
                customer_issue_id_field
            )
            new_key = target_jira.create_issue(payload)
            if new_key:
                created_count += 1
                
                # 創建後立即更新 SYNC_METADATA 和 STATIC_VALUE 字段
                post_create_fields = {}
                
                # 更新 SYNC_METADATA 字段（customer_issue_id 和 last_sync_time）
                if customer_issue_id_field:
                    post_create_fields[customer_issue_id_field] = s_key
                if last_sync_time_field:
                    current_time = datetime.now().isoformat()
                    post_create_fields[last_sync_time_field] = current_time
                
                # 更新 STATIC_VALUE 字段（在 CREATE 時觸發的）
                for item in mappings:
                    if item.get('strategy') == 'STATIC_VALUE':
                        trigger_on = item.get('triggerOn', item.get('trigger_on', ['CREATE', 'UPDATE']))
                        if 'CREATE' in trigger_on:
                            static_value = item.get('staticValue', item.get('static_value', {}))
                            target_field_id = item.get('targetFieldId')
                            if target_field_id:
                                # 對於選項列表字段，需要保持 {"value": "..."} 格式
                                if isinstance(static_value, dict):
                                    post_create_fields[target_field_id] = static_value
                                else:
                                    # 如果是字符串，對於自定義字段需要使用 {"value": "..."} 格式
                                    if 'customfield' in str(target_field_id):
                                        post_create_fields[target_field_id] = {"value": static_value}
                                    else:
                                        post_create_fields[target_field_id] = static_value
                
                if post_create_fields:
                    print(f"  -> 更新元數據和靜態值字段...")
                    # 分別更新字段，跳過無法設置的字段
                    successful_fields = {}
                    failed_fields = {}
                    
                    for field_id, field_value in post_create_fields.items():
                        try:
                            # 嘗試單獨更新每個字段
                            test_update = {field_id: field_value}
                            url = f"{target_jira.base_url}/issue/{new_key}"
                            payload = {"fields": test_update}
                            response = requests.put(url, headers=target_jira.headers, json=payload)
                            
                            if response.status_code == 204:
                                successful_fields[field_id] = field_value
                            else:
                                failed_fields[field_id] = response.text
                                print(f"    警告: 無法設置字段 {field_id}: {response.status_code}")
                        except Exception as e:
                            failed_fields[field_id] = str(e)
                            print(f"    警告: 設置字段 {field_id} 時發生錯誤: {str(e)}")
                    
                    # 如果有成功的字段，批量更新
                    if successful_fields:
                        target_jira.update_issue(new_key, successful_fields)
                    
                    # 如果有失敗的字段，記錄警告
                    if failed_fields:
                        print(f"    警告: 以下字段無法設置: {list(failed_fields.keys())}")
                        print(f"    這些字段可能不在當前 issue type 的編輯屏幕上")
                
                # 同步附件到新創建的 issue（只從 source 同步到 target）
                source_attachments = s_issue.get('fields', {}).get('attachment', [])
                if source_attachments:
                    print(f"  -> 同步附件到新創建的 Issue...")
                    local_dir = ensure_local_attachment_dir(new_key)
                    
                    for attachment in source_attachments:
                        filename = attachment.get('filename', '')
                        print(f"    下載 Source 附件: {filename}")
                        local_path = download_attachment_to_local(
                            source_jira, attachment, local_dir,
                            source_project_key
                        )
                        
                        if local_path:
                            # 上傳到 target，使用原始檔名（不含 prefix）
                            print(f"    上傳附件到 Target: {filename}")
                            # 創建臨時檔案使用原始檔名
                            temp_path = os.path.join(local_dir, filename)
                            shutil.copy2(local_path, temp_path)
                            target_jira.upload_attachment(new_key, temp_path)
                            os.remove(temp_path)  # 刪除臨時檔案
        else:
            # Update
            t_issue = target_map[s_key]
            t_key = t_issue['key']
            print(f"  -> 找到匹配的 Target Issue: {t_key}")

            # 簡化的更新邏輯：使用 last_sync_time 作為基準
            s_time = s_issue['fields'].get('updated', '')
            t_time = t_issue['fields'].get('updated', '')
            
            # 取得 last_sync_time
            last_sync_time = None
            if last_sync_time_field:
                last_sync_time = t_issue['fields'].get(last_sync_time_field)
                if isinstance(last_sync_time, dict):
                    last_sync_time = last_sync_time.get('value')
            
            direction = "NONE"
            
            if last_sync_time:
                # 如果兩個 issue 的 updated 時間都早於 last_sync_time，不需要更新
                if s_time <= last_sync_time and t_time <= last_sync_time:
                    print(f"  -> 跳過（上次同步後無變化，last_sync_time: {last_sync_time}）")
                    skipped_count += 1
                    continue
                
                # 否則，比較兩個時間決定方向
                if s_time > t_time:
                    direction = "S2T"
                elif t_time > s_time:
                    direction = "T2S"
            else:
                # 沒有 last_sync_time（首次同步），使用原來的邏輯
                if s_time > t_time:
                    direction = "S2T"
                elif t_time > s_time:
                    direction = "T2S"

            if direction == "NONE":
                print("  -> 跳過（時間相同）")
                skipped_count += 1
                continue

            # 準備更新欄位
            update_fields = processor.prepare_update_payload(
                s_issue,
                t_issue,
                direction,
                customer_issue_id_field,
                last_sync_time_field
            )

            if update_fields:
                print(f"  -> 更新 {t_key if direction == 'S2T' else s_key} ({direction})...")
                # 根據同步方向選擇對應的 Jira Client
                if direction == "S2T":
                    target_jira.update_issue(t_key, update_fields)
                    updated_count += 1
                elif direction == "T2S":
                    source_jira.update_issue(s_key, update_fields)
                    updated_count += 1
                
                # 同步附件
                sync_attachments(
                    s_issue, t_issue, direction,
                    source_jira, target_jira,
                    source_project_key, target_project_key,
                    t_key
                )
            else:
                print("  -> 無需更新的欄位")
                skipped_count += 1

    # 5. 顯示同步結果
    print()
    print("=" * 80)
    print("同步結果總結")
    print("=" * 80)
    print(f"處理的 Source Issues: {len(source_issues)}")
    print(f"創建的 Target Issues: {created_count}")
    print(f"更新的 Issues: {updated_count}")
    print(f"跳過的 Issues: {skipped_count}")
    print("=" * 80)

if __name__ == "__main__":
    run_sync()

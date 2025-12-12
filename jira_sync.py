from datetime import datetime

class JiraSyncEngine:
    def __init__(self, config):
        self.config = config

    def get_value_from_mapping(self, value, mapping_dict, default=None):
        """ 安全的查表函式 """
        return mapping_dict.get(value, default)

    def get_reverse_value(self, target_value, config_item):
        """ 處理反向映射 (T2S) """
        # 1. 先建立反向表 (Value -> Key)
        # 注意：如果有重複 Value (如 Medium)，這裡只會保留最後一個，所以需要 fallback
        forward_map = config_item['value_mapping']
        reverse_map = {v: k for k, v in forward_map.items()}
        
        # 2. 檢查是否有指定的 Default 反向規則 (解決 Medium -> Sev-1 還是 Sev-2 的問題)
        explicit_defaults = config_item.get('reverse_mapping_default', {})
        
        if target_value in explicit_defaults:
            return explicit_defaults[target_value]
        
        return reverse_map.get(target_value)

    def sync_field(self, source_issue, target_issue, field_config):
        """ 單一欄位的同步核心邏輯 """
        direction = field_config['sync_direction']
        s_id = field_config['source_field']
        t_id = field_config['target_field']
        
        # 1. 取得當前值
        s_val = source_issue['fields'].get(s_id, {}).get('value')
        t_val = target_issue['fields'].get(t_id, {}).get('value')
        
        # 2. 決定同步方向 (如果是雙向，比較更新時間)
        final_direction = direction
        if direction == "BIDIRECTIONAL":
            # 字串轉時間物件 (Jira 時間格式通常是 ISO8601)
            s_time = datetime.fromisoformat(source_issue['fields']['updated'].replace('T', ' ').split('.')[0])
            t_time = datetime.fromisoformat(target_issue['fields']['updated'].replace('T', ' ').split('.')[0])
            
            if s_time > t_time:
                final_direction = "S2T"
            elif t_time > s_time:
                final_direction = "T2S"
            else:
                return # 時間一樣，視為已同步，不做事

        # 3. 執行同步
        if final_direction == "S2T":
            # 轉換值
            new_t_val = self.get_value_from_mapping(s_val, field_config['value_mapping'])
            
            # 只有當值真的不同時才更新 (避免無限迴圈)
            if new_t_val and new_t_val != t_val:
                print(f"Update Target ({t_id}): {t_val} -> {new_t_val} (Source won)")
                # self.jira_api.update_issue(target_issue['key'], {t_id: {'value': new_t_val}})

        elif final_direction == "T2S":
            # 反向轉換值
            new_s_val = self.get_reverse_value(t_val, field_config)
            
            if new_s_val and new_s_val != s_val:
                print(f"Update Source ({s_id}): {s_val} -> {new_s_val} (Target won)")
                # self.jira_api.update_issue(source_issue['key'], {s_id: {'value': new_s_val}})

# 使用範例
config_item = {
    "source_field": "customfield_10037",
    "target_field": "customfield_10229",
    "sync_direction": "BIDIRECTIONAL",
    "value_mapping": {"Sev-0": "Low", "Sev-1": "Medium", "Sev-2": "Medium", "Sev-3": "High"},
    "reverse_mapping_default": {"Medium": "Sev-1"}
}

# 模擬資料 (Source 比較新，應該觸發 S2T)
source_data = {"key": "SRC-1", "fields": {"updated": "2023-12-10T10:00:00.000+0800", "customfield_10037": {"value": "Sev-0"}}}
target_data = {"key": "TGT-1", "fields": {"updated": "2023-12-09T10:00:00.000+0800", "customfield_10229": {"value": "High"}}}

engine = JiraSyncEngine(None)
engine.sync_field(source_data, target_data, config_item)
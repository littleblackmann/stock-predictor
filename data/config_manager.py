"""
設定管理模組
統一處理 config.json 的讀取與寫入
"""
import json
import os
from data.data_paths import CONFIG_PATH

DEFAULT_CONFIG = {
    "openai_api_key": "",
    "openai_model": "",
    "auto_retrain_days": 7,
    "default_symbol": "",
    "brave_api_key": "",
    "welcome_shown": False,
}

AVAILABLE_MODELS = [
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
]


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 補上缺少的欄位
                for k, v in DEFAULT_CONFIG.items():
                    data.setdefault(k, v)
                return data
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(data: dict) -> None:
    existing = load_config()
    existing.update(data)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=4)


def is_first_run() -> bool:
    """API Key 未設定視為首次執行"""
    return not load_config().get("openai_api_key", "").strip()



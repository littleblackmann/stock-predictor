"""
設定管理模組
統一處理 config.json 的讀取與寫入

AI 供應商：OpenRouter（https://openrouter.ai）
OpenRouter 提供 OpenAI 相容的 API，因此仍沿用 openai 套件，
只是把 base_url 指向 OpenRouter，即可自由切換各家模型。
"""
import json
import os
from data.data_paths import CONFIG_PATH

# OpenRouter API 端點（OpenAI 相容）
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# OpenRouter 會在排行榜顯示來源，選填
OPENROUTER_APP_URL = "https://github.com/littleblackmann/stock-predictor"
OPENROUTER_APP_NAME = "Taiwan Stock Predictor"

DEFAULT_MODEL = "openai/gpt-5.4-mini"

DEFAULT_CONFIG = {
    "openrouter_api_key": "",
    "openrouter_model": DEFAULT_MODEL,
    "auto_retrain_days": 7,
    "default_symbol": "",
    "brave_api_key": "",
    "welcome_shown": False,
}

# ── 前 10 大熱門模型 ──────────────────────────────────────────────
# (模型 ID, 顯示名稱, 分組, 說明)
# 價格為 OpenRouter 每百萬 token 的輸入/輸出費用（美元），僅供參考
from data.model_catalog import menu_models
AVAILABLE_MODELS = menu_models()

MODEL_IDS = [m[0] for m in AVAILABLE_MODELS]


def _migrate_legacy_keys(data: dict) -> dict:
    """
    舊版使用 OpenAI 直連，設定鍵為 openai_api_key / openai_model。
    改用 OpenRouter 後自動搬移，避免使用者升級後設定不見。

    - 舊 API Key 是 OpenAI 的 sk-... 開頭，在 OpenRouter 不能用，故不沿用。
    - 舊模型名稱（gpt-4o-mini）沒有廠商前綴，補上 "openai/"。
    """
    if "openai_api_key" in data and not data.get("openrouter_api_key"):
        old_key = (data.get("openai_api_key") or "").strip()
        # 只有本來就是 OpenRouter 的 key（sk-or-）才沿用
        if old_key.startswith("sk-or-"):
            data["openrouter_api_key"] = old_key

    if "openai_model" in data and not data.get("openrouter_model"):
        old_model = (data.get("openai_model") or "").strip()
        if old_model:
            candidate = old_model if "/" in old_model else f"openai/{old_model}"
            data["openrouter_model"] = candidate if candidate in MODEL_IDS else DEFAULT_MODEL

    # 清掉舊鍵，避免兩套設定並存造成混淆
    data.pop("openai_api_key", None)
    data.pop("openai_model", None)
    return data


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                data = _migrate_legacy_keys(data)
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
    import tempfile
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CONFIG_PATH), suffix='.tmp')
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=4)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, CONFIG_PATH)


def is_first_run() -> bool:
    """API Key 未設定視為首次執行"""
    return not load_config().get("openrouter_api_key", "").strip()

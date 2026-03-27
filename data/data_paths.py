"""
資料路徑統一管理模組

所有使用者資料存放在 %LOCALAPPDATA%/台股預測分析系統/
程式檔案與使用者資料徹底分離，更新程式時不影響使用者資料。

首次啟動時，如果 AppData 裡沒有資料但 exe 旁邊有（舊版），
會自動遷移過去。
"""
import os
import sys
import shutil
import json
from pathlib import Path

# ─── AppData 根目錄 ────────────────────────────────────────────
APP_NAME = "台股預測分析系統"
_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
DATA_ROOT = os.path.join(_appdata, APP_NAME)

# ─── 程式根目錄（exe 或 .py 所在位置）────────────────────────────
if getattr(sys, "frozen", False):
    # PyInstaller 打包後
    APP_ROOT = os.path.dirname(sys.executable)
else:
    # 開發模式
    APP_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# ─── 使用者資料路徑（全部在 AppData 下）───────────────────────────
CONFIG_PATH       = os.path.join(DATA_ROOT, "config.json")
WATCHLIST_PATH    = os.path.join(DATA_ROOT, "watchlist.json")
RECENT_PATH       = os.path.join(DATA_ROOT, "recent.json")
PREDICTION_LOG    = os.path.join(DATA_ROOT, "prediction_log.csv")
COOLDOWN_PATH     = os.path.join(DATA_ROOT, "auto_retrain_cooldown.json")
STOCK_LIST_CACHE  = os.path.join(DATA_ROOT, "stock_list_cache.json")
HOLIDAY_CACHE     = os.path.join(DATA_ROOT, "tw_holiday_cache.json")
MODEL_DIR         = os.path.join(DATA_ROOT, "models", "saved")
CHIP_CACHE_DIR    = os.path.join(DATA_ROOT, "cache", "chip")
LOG_DIR           = os.path.join(DATA_ROOT, "logs")


def ensure_dirs():
    """確保所有資料夾都存在"""
    for d in [DATA_ROOT, MODEL_DIR, CHIP_CACHE_DIR, LOG_DIR]:
        os.makedirs(d, exist_ok=True)


def migrate_from_old_location():
    """
    首次啟動遷移：把舊版 exe 旁邊的使用者資料搬到 AppData。
    只在 AppData 裡還沒有對應檔案時才搬（不覆蓋）。
    """
    ensure_dirs()

    # 標記檔：遷移過一次就不再檢查
    marker = os.path.join(DATA_ROOT, ".migrated")
    if os.path.exists(marker):
        return

    old_root = APP_ROOT
    migrated_any = False

    # --- 單檔遷移 ---
    file_map = {
        "config.json":              CONFIG_PATH,
        "watchlist.json":           WATCHLIST_PATH,
        "recent.json":              RECENT_PATH,
        "prediction_log.csv":       PREDICTION_LOG,
        "auto_retrain_cooldown.json": COOLDOWN_PATH,
        "stock_list_cache.json":    STOCK_LIST_CACHE,
        "tw_holiday_cache.json":    HOLIDAY_CACHE,
    }
    for old_name, new_path in file_map.items():
        old_path = os.path.join(old_root, old_name)
        if os.path.exists(old_path) and not os.path.exists(new_path):
            shutil.copy2(old_path, new_path)
            migrated_any = True

    # --- 資料夾遷移 ---
    dir_map = {
        os.path.join(old_root, "models", "saved"): MODEL_DIR,
        os.path.join(old_root, "cache", "chip"):   CHIP_CACHE_DIR,
        os.path.join(old_root, "logs"):             LOG_DIR,
    }
    for old_dir, new_dir in dir_map.items():
        if os.path.isdir(old_dir):
            for fname in os.listdir(old_dir):
                src = os.path.join(old_dir, fname)
                dst = os.path.join(new_dir, fname)
                if os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    migrated_any = True

    # 如果 AppData 裡完全沒有 config.json，建一個預設的
    if not os.path.exists(CONFIG_PATH):
        default_config = {
            "openai_api_key": "",
            "openai_model": "gpt-4.1-mini",
            "auto_retrain_days": 7,
            "default_symbol": "0050.TW",
            "brave_api_key": "",
            "welcome_shown": False
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)

    # 寫入遷移標記
    with open(marker, "w") as f:
        f.write("migrated")

"""
台股預測分析系統 — 打包腳本（PyInstaller）

使用方式：
    python build.py

輸出：
    dist/台股預測分析系統/   ← 整個資料夾給對方就能用

重要：
    v1.1.0 起，使用者資料（config、watchlist、模型、快取、日誌）
    全部存放在 %LOCALAPPDATA%/台股預測分析系統/，不再打包進 dist。

    程式首次啟動時會自動建立 AppData 資料夾並初始化預設設定，
    舊版使用者會自動遷移資料到新位置。

    ★ 絕對不要在打包流程中刪除或修改專案原始檔案。
"""
import os
import sys
import json
import subprocess
import shutil
import zipfile
from datetime import datetime

APP_NAME    = "台股預測分析系統"
SPEC_FILE   = "stock_predictor.spec"
DIST_DIR    = os.path.join("dist", APP_NAME)

# 版本號從 version.json 讀取
VERSION_FILE = "version.json"
try:
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        APP_VERSION = json.load(f).get("version", "0.0.0")
except Exception:
    APP_VERSION = "0.0.0"

OUTPUT_ZIP  = f"台股預測分析系統_v{APP_VERSION}.zip"


def check_env():
    """確認 PyInstaller 和必要套件都已安裝"""
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[FAIL] 請先安裝 PyInstaller：pip install pyinstaller")
        return False

    for pkg in ['PySide6', 'tensorflow', 'lightgbm']:
        try:
            __import__(pkg)
            print(f"[OK] {pkg}")
        except ImportError:
            print(f"[FAIL] 缺少套件：{pkg}")
            return False
    return True


def build():
    print("=" * 60)
    print(f"  台股預測分析系統 打包建置")
    print(f"  時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  版本：v{APP_VERSION}")
    print("=" * 60)

    print("\n[0/3] 環境確認...")
    if not check_env():
        return

    # 清理舊的輸出
    if os.path.exists(DIST_DIR):
        print(f"\n  清理舊版本：{DIST_DIR}")
        shutil.rmtree(DIST_DIR)

    print("\n[1/3] PyInstaller 打包中（約需 5～15 分鐘）...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", SPEC_FILE, "--noconfirm"],
        cwd=os.path.dirname(os.path.abspath(__file__))
    )

    if result.returncode != 0:
        print("\n[FAIL] 打包失敗！請查看上方錯誤訊息。")
        return

    print(f"\n[2/3] 壓縮為 {OUTPUT_ZIP}...")
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(DIST_DIR):
            for file in files:
                filepath = os.path.join(root, file)
                arcname  = os.path.relpath(filepath, "dist")
                zf.write(filepath, arcname)

    zip_size = os.path.getsize(OUTPUT_ZIP) / 1024 / 1024
    print(f"\n{'=' * 60}")
    print(f"[OK] 打包完成！")
    print(f"   資料夾：{DIST_DIR}")
    print(f"   壓縮檔：{OUTPUT_ZIP}  ({zip_size:.0f} MB)")
    print(f"\n[NOTE] 給使用者的操作方式：")
    print(f"   1. 解壓縮 ZIP")
    print(f"   2. 進入「{APP_NAME}」資料夾")
    print(f"   3. 點兩下「{APP_NAME}.exe」")
    print(f"   4. 程式會自動在 AppData 建立設定檔")
    print(f"   5. 更新時只需替換程式資料夾，使用者資料不受影響")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    build()

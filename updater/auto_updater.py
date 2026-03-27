"""
自動更新模組
檢查 GitHub Releases → 下載 ZIP → 解壓覆蓋程式檔案 → 重啟

使用者資料在 AppData 中，更新只覆蓋程式目錄，
所有使用者設定、模型、記錄完全不受影響。
"""
import json
import os
import sys
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

from logger.app_logger import get_logger
from data.data_paths import APP_ROOT, DATA_ROOT

logger = get_logger(__name__)

# ── 設定 ──────────────────────────────────────────────────────────
# GitHub 倉庫資訊（使用者需要在 config 設定或寫死）
GITHUB_OWNER = ""     # 例如 "myuser"
GITHUB_REPO  = ""     # 例如 "stock-predictor"

# 本地版本檔
VERSION_FILE = os.path.join(APP_ROOT, "version.json")

# 更新設定檔（存在 AppData，記住上次跳過的版本）
UPDATE_PREFS = os.path.join(DATA_ROOT, "update_prefs.json")


def get_current_version() -> str:
    """讀取本地版本號"""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("version", "0.0.0")
    except Exception:
        return "0.0.0"


def _get_update_config() -> dict:
    """從 config.json 讀取 GitHub 更新設定"""
    try:
        from data.config_manager import load_config
        cfg = load_config()
        return {
            "owner": cfg.get("github_owner", GITHUB_OWNER),
            "repo":  cfg.get("github_repo",  GITHUB_REPO),
        }
    except Exception:
        return {"owner": GITHUB_OWNER, "repo": GITHUB_REPO}


def check_for_update() -> dict | None:
    """
    檢查 GitHub Releases 是否有新版本。

    Returns:
        None: 已是最新版或無法連線
        dict: {"version": "1.1.0", "download_url": "...", "release_notes": "..."}
    """
    cfg = _get_update_config()
    owner, repo = cfg["owner"], cfg["repo"]

    if not owner or not repo:
        logger.debug("未設定 GitHub 倉庫，跳過更新檢查")
        return None

    api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

    try:
        req = Request(api_url, headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "StockPredictor-Updater/1.0",
        })
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, json.JSONDecodeError, OSError) as e:
        logger.warning(f"更新檢查失敗：{e}")
        return None

    remote_version = data.get("tag_name", "").lstrip("v")
    current = get_current_version()

    if not remote_version or not _is_newer(remote_version, current):
        logger.info(f"已是最新版本 v{current}")
        return None

    # 找到 ZIP 下載連結
    download_url = None
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".zip"):
            download_url = asset.get("browser_download_url")
            break

    if not download_url:
        # 沒有 asset 就用 source ZIP
        download_url = data.get("zipball_url")

    if not download_url:
        logger.warning("找不到可下載的更新檔案")
        return None

    # 檢查是否已跳過此版本
    skipped = _load_skipped_version()
    if skipped == remote_version:
        logger.info(f"使用者已跳過 v{remote_version}")
        return None

    logger.info(f"發現新版本：v{current} → v{remote_version}")
    return {
        "version":       remote_version,
        "download_url":  download_url,
        "release_notes": data.get("body", ""),
    }


def download_and_apply(download_url: str, new_version: str,
                       progress_callback=None) -> bool:
    """
    下載 ZIP 並覆蓋程式目錄（使用者資料不受影響）。

    Args:
        download_url: ZIP 下載連結
        new_version: 新版本號
        progress_callback: 進度回呼 (bytes_downloaded, total_bytes)

    Returns:
        True: 更新成功，需要重啟
        False: 更新失敗
    """
    tmp_dir = tempfile.mkdtemp(prefix="stock_update_")
    zip_path = os.path.join(tmp_dir, "update.zip")

    try:
        # ── 下載 ──
        logger.info(f"下載更新：{download_url}")
        req = Request(download_url, headers={
            "User-Agent": "StockPredictor-Updater/1.0",
        })
        with urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(zip_path, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 256)  # 256 KB chunks
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total)

        logger.info(f"下載完成：{downloaded} bytes")

        # ── 解壓 ──
        extract_dir = os.path.join(tmp_dir, "extracted")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # 找到實際的程式根目錄（可能在子資料夾裡）
        contents = os.listdir(extract_dir)
        if len(contents) == 1 and os.path.isdir(os.path.join(extract_dir, contents[0])):
            source_dir = os.path.join(extract_dir, contents[0])
        else:
            source_dir = extract_dir

        # ── 寫更新批次腳本 ──
        # 因為 exe 正在執行，不能直接覆蓋自己
        # 寫一個 bat 腳本：等程式結束 → 覆蓋 → 重新啟動
        bat_path = os.path.join(tmp_dir, "apply_update.bat")
        exe_path = sys.executable if getattr(sys, "frozen", False) else "python"

        with open(bat_path, "w", encoding="utf-8") as bat:
            bat.write(f"""@echo off
chcp 65001 >nul
echo 正在更新台股預測分析系統...
echo 等待程式結束...
timeout /t 2 /nobreak >nul

REM 覆蓋程式檔案（排除使用者資料相關的檔案）
xcopy /E /Y /I "{source_dir}\\*" "{APP_ROOT}\\" >nul 2>&1

REM 更新版本號
echo {{"version": "{new_version}"}} > "{os.path.join(APP_ROOT, "version.json")}"

echo 更新完成！重新啟動...
start "" "{exe_path}"

REM 清理暫存
timeout /t 3 /nobreak >nul
rd /s /q "{tmp_dir}" >nul 2>&1
del "%~f0" >nul 2>&1
""")

        # ── 啟動更新腳本並退出 ──
        logger.info("啟動更新腳本...")
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True

    except Exception as e:
        logger.error(f"更新失敗：{e}")
        # 清理暫存
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
        return False


def skip_version(version: str):
    """記住使用者選擇跳過的版本"""
    try:
        with open(UPDATE_PREFS, "w", encoding="utf-8") as f:
            json.dump({"skipped_version": version}, f)
    except Exception:
        pass


def _load_skipped_version() -> str:
    """讀取使用者跳過的版本"""
    try:
        with open(UPDATE_PREFS, "r", encoding="utf-8") as f:
            return json.load(f).get("skipped_version", "")
    except Exception:
        return ""


def _is_newer(remote: str, local: str) -> bool:
    """比較版本號（支援 1.2.3 格式）"""
    try:
        r_parts = [int(x) for x in remote.split(".")]
        l_parts = [int(x) for x in local.split(".")]
        return r_parts > l_parts
    except (ValueError, AttributeError):
        return remote != local

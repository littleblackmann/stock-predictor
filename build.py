"""
台股預測分析系統 — 打包腳本（PyInstaller）

使用方式：
    python build.py

輸出：
    dist/台股預測分析系統/              ← 整個資料夾給對方就能用
    台股預測分析系統_vX.X.X.zip        ← 完整安裝包（新用戶）
    台股預測分析系統_vX.X.X_patch.zip  ← 差量更新包（已安裝用戶）

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
import hashlib
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

OUTPUT_ZIP   = f"台股預測分析系統_v{APP_VERSION}.zip"
PATCH_ZIP    = f"台股預測分析系統_v{APP_VERSION}_patch.zip"
MANIFEST_SAVE = f"build_manifest_v{APP_VERSION}.json"  # 每個版本獨立 manifest，重複打包不會覆蓋舊版基準線


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


# ── 差量更新工具 ─────────────────────────────────────────────────

def _hash_file(filepath: str) -> str:
    """計算檔案 SHA256"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_manifest(dist_dir: str) -> dict:
    """掃描 dist 資料夾，產生 {相對路徑: sha256} 的 manifest"""
    manifest = {}
    for root, _dirs, files in os.walk(dist_dir):
        for fname in files:
            filepath = os.path.join(root, fname)
            relpath = os.path.relpath(filepath, dist_dir).replace("\\", "/")
            manifest[relpath] = _hash_file(filepath)
    return manifest


def _find_previous_manifest(current_version: str) -> dict:
    """
    找到上一個版本的 manifest 作為 patch 基準線。
    使用版本化檔名（build_manifest_v1.2.8.json），
    重複打包同版本時不會覆蓋舊版的基準。
    """
    import glob

    best_manifest = {}
    best_version = None

    # 搜尋所有版本化 manifest
    for path in glob.glob("build_manifest_v*.json"):
        fname = os.path.basename(path)
        # build_manifest_v1.2.8.json → 1.2.8
        ver = fname.replace("build_manifest_v", "").replace(".json", "")
        if ver == current_version:
            continue  # 跳過當前版本（可能是重複打包）
        try:
            ver_tuple = tuple(int(x) for x in ver.split("."))
        except ValueError:
            continue
        if best_version is None or ver_tuple > best_version:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    best_manifest = json.load(f)
                best_version = ver_tuple
                best_path = path
            except Exception:
                continue

    # Legacy：舊的 build_manifest.json（無版本號）
    if not best_manifest and os.path.exists("build_manifest.json"):
        try:
            with open("build_manifest.json", "r", encoding="utf-8") as f:
                best_manifest = json.load(f)
            print(f"  載入舊版 manifest：build_manifest.json（{len(best_manifest)} 個檔案）")
            return best_manifest
        except Exception:
            pass

    if best_manifest:
        print(f"  載入基準 manifest：{best_path}（v{'.'.join(str(x) for x in best_version)}，{len(best_manifest)} 個檔案）")

    return best_manifest


def create_patch_zip(dist_dir: str, old_manifest: dict, new_manifest: dict) -> str | None:
    """
    比對新舊 manifest，只把有變動的檔案打成 patch zip。
    回傳 patch zip 路徑，若無差異回傳 None。
    """
    changed = []
    for relpath, new_hash in new_manifest.items():
        if relpath not in old_manifest or old_manifest[relpath] != new_hash:
            changed.append(relpath)

    # 強制包含 version.json（更新版本號是最關鍵的，絕不能漏）
    version_key = "_internal/version.json"
    if version_key not in changed and version_key in new_manifest:
        changed.append(version_key)
        print(f"  [PATCH] 強制加入 {version_key}")

    if not changed:
        print("  [PATCH] 與上次打包完全相同，不產生 patch")
        return None

    with zipfile.ZipFile(PATCH_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for relpath in changed:
            filepath = os.path.join(dist_dir, relpath)
            # 保持與 full zip 相同的目錄結構：台股預測分析系統/xxx
            arcname = os.path.join(APP_NAME, relpath)
            zf.write(filepath, arcname)

    patch_size = os.path.getsize(PATCH_ZIP) / 1024 / 1024
    print(f"  [PATCH] 差量更新包：{PATCH_ZIP}  ({patch_size:.1f} MB)")
    print(f"  [PATCH] 變動檔案數：{len(changed)} / {len(new_manifest)}")

    return PATCH_ZIP


# ── 主打包流程 ───────────────────────────────────────────────────

def build():
    print("=" * 60)
    print(f"  台股預測分析系統 打包建置")
    print(f"  時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  版本：v{APP_VERSION}")
    print("=" * 60)

    print("\n[0/4] 環境確認...")
    if not check_env():
        return

    # 清理舊的輸出
    if os.path.exists(DIST_DIR):
        print(f"\n  清理舊版本：{DIST_DIR}")
        shutil.rmtree(DIST_DIR)

    print("\n[1/4] PyInstaller 打包中（約需 5～15 分鐘）...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", SPEC_FILE, "--noconfirm"],
        cwd=os.path.dirname(os.path.abspath(__file__))
    )

    if result.returncode != 0:
        print("\n[FAIL] 打包失敗！請查看上方錯誤訊息。")
        return

    # ── 產生 manifest 並寫入 dist ──
    print("\n[2/4] 產生檔案清單 (manifest)...")
    new_manifest = generate_manifest(DIST_DIR)
    print(f"  共 {len(new_manifest)} 個檔案")

    # 把 manifest 放進 dist（讓使用者端也有一份，未來可用於本地比對）
    manifest_in_dist = os.path.join(DIST_DIR, "manifest.json")
    with open(manifest_in_dist, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, ensure_ascii=False)

    # 更新 manifest 的 hash（因為剛寫入了 manifest.json 本身）
    new_manifest["manifest.json"] = _hash_file(manifest_in_dist)

    # ── 差量更新包 ──
    old_manifest = _find_previous_manifest(APP_VERSION)

    if old_manifest:
        create_patch_zip(DIST_DIR, old_manifest, new_manifest)
    else:
        print("  [PATCH] 找不到前一版 manifest，無法產生差量更新包")

    # 儲存本次 manifest 供下次比對
    with open(MANIFEST_SAVE, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, ensure_ascii=False)

    # ── 完整安裝包 ──
    print(f"\n[3/4] 壓縮完整安裝包 {OUTPUT_ZIP}...")
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
    print(f"   完整包：{OUTPUT_ZIP}  ({zip_size:.0f} MB)")
    if os.path.exists(PATCH_ZIP):
        patch_size = os.path.getsize(PATCH_ZIP) / 1024 / 1024
        print(f"   差量包：{PATCH_ZIP}  ({patch_size:.1f} MB)")
    print(f"\n[NOTE] 上傳 Release 時，full + patch 都上傳：")
    print(f'   gh release create vX.X.X "{OUTPUT_ZIP}" "{PATCH_ZIP}" ...')
    print(f"{'=' * 60}")


if __name__ == "__main__":
    build()

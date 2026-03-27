# -*- mode: python ; coding: utf-8 -*-
"""
台股預測分析系統 — PyInstaller 打包設定
產出：dist/台股預測分析系統/ 資料夾（onedir 模式）
"""
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# ── 專案根目錄 ──────────────────────────────────────────────────
ROOT = os.path.abspath('.')

# ── 需要包含的資料檔案 ──────────────────────────────────────────
# 注意：使用者資料（config, watchlist, models, cache, logs）已移至 AppData，
#       打包只需包含 UI 素材和版本檔。
datas = [
    # UI 樣式
    (os.path.join(ROOT, 'ui', 'styles.qss'),        'ui'),
    # 圖示 / Logo
    (os.path.join(ROOT, 'app_icon.ico'),             '.'),
    (os.path.join(ROOT, 'app_logo.png'),             '.'),
    # 版本號（供自動更新比對用）
    (os.path.join(ROOT, 'version.json'),             '.'),
]

# ── Hidden imports（PyInstaller 無法自動偵測的相依）─────────────
hidden_imports = [
    # PySide6 WebEngine（K 線圖需要）
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebChannel',
    'PySide6.QtPrintSupport',
    # TensorFlow / Keras / LiteRT
    'tensorflow',
    'tensorflow.python',
    'tensorflow.python.keras',
    'keras',
    'litert',
    'litert.python',
    # LightGBM
    'lightgbm',
    # scikit-learn
    'sklearn',
    'sklearn.utils._cython_blas',
    'sklearn.neighbors._partition_nodes',
    # SHAP
    'shap',
    'shap.explainers',
    # Data / Finance
    'yfinance',
    'requests',
    'pandas',
    'numpy',
    'matplotlib',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_agg',
    # Others
    'joblib',
    'scipy',
    'scipy.special._ufuncs_cxx',
    'scipy.linalg.cython_blas',
    'scipy.linalg.cython_lapack',
    'exchange_calendars',
]

# ── VC++ Runtime DLL（目標電腦可能沒裝 VC++ Redistributable）────
VENV = os.path.join(ROOT, 'venv_stock')
_vc_dir = os.path.join(VENV, 'Lib', 'site-packages', 'PySide6')
vc_binaries = [
    (os.path.join(_vc_dir, 'vcruntime140.dll'),   '.'),
    (os.path.join(_vc_dir, 'vcruntime140_1.dll'),  '.'),
]

a = Analysis(
    ['main.py'],
    pathex=[ROOT],
    binaries=vc_binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',        # 不需要
        'IPython',        # 不需要
        'jupyter',
        'notebook',
        'PyQt5',          # 用 PySide6，排除 PyQt5 避免衝突
        'PyQt6',
        # curl_cffi 正常打包，但 main.py 中的 shim 會在 runtime 覆蓋它
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='台股預測分析系統',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX 壓縮可能讓 TF DLL 損壞，關閉
    console=False,      # 不顯示終端機視窗
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'app_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='台股預測分析系統',
)

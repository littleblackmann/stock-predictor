"""
台股預測分析系統
企業級桌面應用程式入口點

技術架構：
  - UI：PySide6 + QSS 深色霓虹主題
  - 圖表：TradingView Lightweight Charts（via QWebEngineView）
  - 資料：yfinance（歷史 2,500 天 OHLCV）+ TWSE API（籌碼面）+ Brave Search（新聞）
  - 特徵：36 維（技術面 + 籌碼面 + 美股隔夜 + 市場行情）
  - 模型：Transformer（3 層 Encoder，300 天窗口）時序萃取 + LightGBM Ensemble 分類
  - AI：OpenAI GPT 新聞情緒分析 + 3 日走勢推估
  - 解析：SHAP 可解釋性分析
  - 並發：QThreadPool 背景執行緒
  - 日誌：QueueHandler 非同步寫入
"""
import sys
import os
from pathlib import Path

# ── 打包環境修正：curl_cffi 在 PyInstaller 中可讀 DB 但無法發 HTTPS 請求 ──
# yfinance 1.2.0 硬依賴 curl_cffi（8 個檔案無 try/except），不能直接封鎖
# 改用 shim：用標準 requests 模擬 curl_cffi.requests 的 API
if getattr(sys, 'frozen', False):
    import types
    import requests as _req

    class _ShimSession(_req.Session):
        def __init__(self, impersonate=None, **kw):
            super().__init__(**kw)
            self.headers.update({
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/131.0.0.0 Safari/537.36'),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
            })
            self.cookies.jar = self.cookies  # curl_cffi 相容

    class _DNSError(_req.exceptions.ConnectionError):
        pass

    # 建立假的 curl_cffi 模組階層
    _m = types.ModuleType('curl_cffi'); _m.__path__ = []
    _mr = types.ModuleType('curl_cffi.requests'); _mr.__path__ = []
    _mr.Session = _ShimSession
    _mr.Response = _req.Response
    _ms = types.ModuleType('curl_cffi.requests.session')
    _ms.Session = _ShimSession
    _me = types.ModuleType('curl_cffi.requests.exceptions')
    _me.HTTPError = _req.exceptions.HTTPError
    _me.RequestException = _req.exceptions.RequestException
    _me.ConnectionError = _req.exceptions.ConnectionError
    _me.Timeout = _req.exceptions.Timeout
    _me.ChunkedEncodingError = _req.exceptions.ChunkedEncodingError
    _me.DNSError = _DNSError
    _mc = types.ModuleType('curl_cffi.requests.cookies')
    _mr.session = _ms; _mr.exceptions = _me; _mr.cookies = _mc
    _m.requests = _mr
    for _k, _v in [('curl_cffi', _m), ('curl_cffi.requests', _mr),
                    ('curl_cffi.requests.session', _ms),
                    ('curl_cffi.requests.exceptions', _me),
                    ('curl_cffi.requests.cookies', _mc)]:
        sys.modules[_k] = _v
    del _m, _mr, _ms, _me, _mc, _k, _v, types

# ── 環境設定：在 import PySide6 前設定 WebEngine 所需的環境變數 ──
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")
os.environ.setdefault("QT_LOGGING_RULES", "qt.webenginecontext.info=false")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal
from PySide6.QtGui import QFont, QIcon


# ── 背景載入執行緒 ────────────────────────────────────────────────

class _LoaderSignals(QObject):
    step = Signal(str)   # 每完成一個步驟，通知 splash 更新文字
    done = Signal()      # 全部載入完畢


class AppLoader(QThread):
    """
    在背景執行緒依序做 heavy import。
    主執行緒的事件迴圈持續運作，spinner 不會停頓。
    """

    def __init__(self):
        super().__init__()
        self.sig = _LoaderSignals()

    def run(self):
        try:
            self.sig.step.emit("載入股票資料庫...")
            from data.tw_stock_list import TW_STOCK_LIST   # noqa: F401
            from data.stock_fetcher import get_stock_dict  # noqa: F401

            self.sig.step.emit("更新台股交易日曆...")
            from data.holiday_checker import get_calendar
            get_calendar().refresh()

            self.sig.step.emit("載入 AI 模型引擎...")
            import workers.prediction_worker               # noqa: F401（觸發 TF/Keras import）

            self.sig.step.emit("初始化圖表模組...")
            from ui.chart_widget import ChartWidget        # noqa: F401

            self.sig.step.emit("初始化預測面板...")
            from ui.prediction_panel import PredictionPanel  # noqa: F401

            self.sig.step.emit("建立主視窗...")
            self.sig.done.emit()
        except Exception:
            import traceback
            from logger.app_logger import get_logger
            get_logger(__name__).critical(
                f"AppLoader 載入失敗:\n{traceback.format_exc()}"
            )
            self.sig.step.emit("載入失敗，請查看 logs 資料夾")
            self.sig.done.emit()  # 必須發射 done，否則主視窗永遠不出現


# ── 主程式 ────────────────────────────────────────────────────────

def main():
    # ── 資料路徑初始化：確保 AppData 資料夾存在，舊版資料自動遷移 ──
    try:
        from data.data_paths import migrate_from_old_location, cleanup_legacy_models
        migrate_from_old_location()
        cleanup_legacy_models()
    except Exception:
        pass  # 遷移/清理失敗不應阻擋啟動，下次再試

    app = QApplication(sys.argv)
    app.setApplicationName("台股預測分析系統")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("StockPredictor")

    # 設定全域字體
    default_font = QFont("Microsoft JhengHei", 10)
    app.setFont(default_font)

    # 設定應用程式圖示（優先用 ICO，備援用 PNG）
    icon_path = Path(__file__).parent / "app_icon.ico"
    if not icon_path.exists():
        icon_path = Path(__file__).parent / "app_logo.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # ── 判斷是否首次啟動 ──
    from data.config_manager import is_first_run
    first_run = is_first_run()

    # ── 顯示 Splash ──
    from ui.splash_screen import SplashScreen
    splash = SplashScreen(is_first_run=first_run)
    splash.show()
    app.processEvents()

    # ── 快速初始化（主執行緒，幾乎不耗時）──
    splash.set_status("初始化日誌系統...")
    from logger.app_logger import setup_logging, get_logger
    setup_logging()
    logger = get_logger(__name__)
    logger.info("應用程式啟動")

    # ── 啟動背景載入執行緒 ──
    loader = AppLoader()
    loader.sig.step.connect(splash.set_status)

    # 用 list 持有 window 引用，防止 GC 回收
    _win: list = []

    def _on_load_done():
        """背景載入完成後，在主執行緒建立視窗（Qt 元件必須在主執行緒）"""
        from ui.main_window import MainWindow
        w = MainWindow()
        _win.append(w)
        splash.set_status("啟動完成！")

        def _launch():
            w.show()
            splash.close()

        QTimer.singleShot(600, _launch)

    loader.sig.done.connect(_on_load_done)
    loader.start()

    # ── 進入事件迴圈（spinner 在此持續運作）──
    exit_code = app.exec()
    logger.info(f"應用程式結束，退出碼：{exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

"""
主視窗
整合所有子元件：控制列、K線圖表、預測面板、狀態列
使用 QThreadPool 排程背景預測任務
"""
import os
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStatusBar,
    QMessageBox, QSizePolicy, QProgressBar, QProgressDialog,
    QScrollArea, QFrame, QGraphicsOpacityEffect,
    QSystemTrayIcon, QMenu, QApplication
)
from PySide6.QtCore import Qt, QThreadPool, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QIcon, QFont, QColor

from ui.chart_widget import ChartWidget
from ui.prediction_panel import PredictionPanel
from ui.watchlist_drawer import WatchlistDrawer
from ui.smart_line_edit import SmartLineEdit
from ui.prediction_log_dialog import PredictionLogDialog
from workers.prediction_worker import PredictionWorker
from logger.app_logger import get_logger
from data.tw_stock_list import TW_STOCK_LIST
from data.stock_fetcher import get_stock_dict, needs_refresh, refresh_cache
from data.prediction_logger import PredictionLogger
from data.config_manager import is_first_run, load_config

logger = get_logger(__name__)

# QSS 樣式路徑
QSS_PATH = os.path.join(os.path.dirname(__file__), "styles.qss")


class MainWindow(QMainWindow):
    """
    應用程式主視窗

    佈局：
    ┌──────────────────────────────────────────┐
    │  [控制列：輸入框 | 預測 | 清除 | 匯出]       │
    ├─────────────────────────┬────────────────┤
    │                         │  預測結果面板   │
    │   TradingView K 線圖    │  (價格/機率/    │
    │   (MA5/MA20/成交量)     │   效能/SHAP)   │
    │                         │               │
    ├─────────────────────────┴────────────────┤
    │  [狀態列：進度條 | 說明文字 | 時間戳記]      │
    └──────────────────────────────────────────┘
    """

    APP_TITLE   = "台股預測分析系統"
    MIN_WIDTH   = 1100
    MIN_HEIGHT  = 700

    def __init__(self):
        super().__init__()
        self._last_result = None
        self._current_symbol = ""
        self._result_cache: dict[str, dict] = {}   # symbol → 該次預測完整結果
        self._pulse_timer: QTimer | None = None
        self._pulse_phase = 0

        # 合併本地快取 + 硬編碼清單作為自動完成資料來源
        self._stock_dict = get_stock_dict(TW_STOCK_LIST)

        self._load_stylesheet()
        self._setup_window()
        self._setup_ui()
        self._setup_tray()
        self._connect_signals()
        logger.info("MainWindow 初始化完成")

        # 若快取過期，啟動後 3 秒在背景更新（不阻塞 UI）
        if needs_refresh():
            QTimer.singleShot(3000, self._refresh_stock_list_bg)

        # 首次使用 → 先顯示引導視窗，再彈出設定
        if not load_config().get("welcome_shown", False):
            QTimer.singleShot(500, self._show_welcome_guide)
        elif is_first_run():
            QTimer.singleShot(500, self._show_first_run_settings)

        # 啟動後 5 秒背景檢查更新（不阻塞 UI）
        QTimer.singleShot(5000, self._check_for_update_bg)

    # ── 初始化方法 ────────────────────────────────────────────────

    def _load_stylesheet(self):
        if os.path.exists(QSS_PATH):
            with open(QSS_PATH, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        else:
            logger.warning(f"找不到 QSS 檔案：{QSS_PATH}")

    def _setup_window(self):
        self.setWindowTitle(self.APP_TITLE)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.resize(1280, 820)
        # 視窗置中
        screen = self.screen().availableGeometry()
        self.move(
            (screen.width()  - self.width())  // 2,
            (screen.height() - self.height()) // 2
        )

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 頂部控制列 ──
        root_layout.addWidget(self._build_control_panel())

        # ── 中央區域（圖表 + 預測面板）──
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.chart_widget = ChartWidget()
        self.chart_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self.chart_widget.setMinimumSize(480, 300)
        content_layout.addWidget(self.chart_widget, stretch=3)

        self.pred_panel = PredictionPanel()

        # 用 QScrollArea 包住，視窗縮小時可垂直捲動，不截斷內容
        pred_scroll = QScrollArea()
        pred_scroll.setWidget(self.pred_panel)
        pred_scroll.setWidgetResizable(True)
        pred_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pred_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        pred_scroll.setMinimumWidth(320)
        pred_scroll.setFrameShape(QFrame.Shape.NoFrame)
        pred_scroll.setObjectName("predictionScrollArea")
        content_layout.addWidget(pred_scroll, stretch=1)

        root_layout.addLayout(content_layout, stretch=1)

        # ── 進度列（圖表下方，明顯可見）──
        root_layout.addWidget(self._build_progress_bar())

        # ── 狀態列 ──
        self._setup_status_bar()

        # ── 自選股抽屜（浮動，不在 layout 裡）──
        # y_offset=58 讓抽屜從控制列底部開始，不蓋住按鈕那排
        self.watchlist_drawer = WatchlistDrawer(self._stock_dict, central, y_offset=58)
        self.watchlist_drawer.symbol_selected.connect(self._on_watchlist_symbol_clicked)

    def _build_control_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("controlPanel")
        panel.setFixedHeight(58)
        panel.setMinimumWidth(820)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)

        layout.addStretch(1)

        # 股票代號智慧輸入框
        self.input_symbol = SmartLineEdit(self._stock_dict)
        self.input_symbol.setPlaceholderText("輸入代號或名稱，例如：0050 / 台積電")
        self.input_symbol.setFixedWidth(240)
        self.input_symbol.setFixedHeight(36)
        layout.addWidget(self.input_symbol)

        # 最近查詢按鈕
        self.btn_recent = QPushButton("🕐")
        self.btn_recent.setObjectName("btnRecent")
        self.btn_recent.setFixedSize(36, 36)
        self.btn_recent.setToolTip("最近查詢的股票")
        layout.addWidget(self.btn_recent)

        # 加入自選股按鈕（小圖示）
        self.btn_watchlist = QPushButton("★")
        self.btn_watchlist.setObjectName("btnWatchlist")
        self.btn_watchlist.setFixedSize(36, 36)
        self.btn_watchlist.setToolTip("將目前股票加入自選股")
        layout.addWidget(self.btn_watchlist)

        # 預測按鈕
        self.btn_predict = QPushButton("▶  預測明天")
        self.btn_predict.setObjectName("btnPredict")
        self.btn_predict.setFixedHeight(36)
        self.btn_predict.setToolTip("下載最新資料並執行 LSTM + LightGBM 模型預測")
        layout.addWidget(self.btn_predict)

        # 預測記錄按鈕
        self.btn_log = QPushButton("📊  記錄")
        self.btn_log.setObjectName("btnLog")
        self.btn_log.setFixedHeight(36)
        self.btn_log.setToolTip("查看歷史預測記錄與準確率報告")
        layout.addWidget(self.btn_log)

        # 設定按鈕
        self.btn_settings = QPushButton("⚙")
        self.btn_settings.setObjectName("btnSettings")
        self.btn_settings.setFixedSize(36, 36)
        self.btn_settings.setToolTip("系統設定（API Key / AI 模型）")
        layout.addWidget(self.btn_settings)

        layout.addStretch(1)

        return panel

    def _build_progress_bar(self) -> QWidget:
        """圖表下方的大型進度列"""
        container = QWidget()
        container.setFixedHeight(36)
        container.setStyleSheet("background-color: #161616; border-top: 1px solid #3A3A3A;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(14, 5, 14, 5)
        layout.setSpacing(10)

        self.big_progress_bar = QProgressBar()
        self.big_progress_bar.setRange(0, 100)
        self.big_progress_bar.setValue(0)
        self.big_progress_bar.setFixedHeight(18)
        self.big_progress_bar.setFormat("")
        self.big_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #3A3A3A;
                border-radius: 9px;
                background: #252525;
                color: transparent;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #004488, stop:0.5 #0099FF, stop:1 #00DDFF);
                border-radius: 8px;
            }
        """)
        layout.addWidget(self.big_progress_bar, stretch=1)

        self.big_progress_label = QLabel("就緒")
        self.big_progress_label.setFixedWidth(320)
        self.big_progress_label.setStyleSheet(
            "color: #5A8ABE; font-size: 13px; font-weight: bold;"
        )
        layout.addWidget(self.big_progress_label)

        return container

    def _setup_status_bar(self):
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        # 小進度條（隱藏，保留供程式碼相容用）
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        # 中央訊息標籤
        self.status_label = QLabel("就緒 — 請輸入台股代號後點擊「預測明天」")
        status_bar.addWidget(self.status_label, stretch=1)

        # 右側時間戳記
        self.label_timestamp = QLabel("")
        self.label_timestamp.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_bar.addPermanentWidget(self.label_timestamp)

        # 啟動時顯示模型訓練狀態
        self._update_model_status()

        # 啟動後 2 秒在背景回填預測記錄
        QTimer.singleShot(2000, self._backfill_in_background)

        # 啟動後 5 秒掃描自選股技術訊號（等網路快取先更新完）
        QTimer.singleShot(5000, self._scan_signals_in_background)

    def _setup_tray(self):
        """初始化系統匣圖示與選單"""
        icon_path = os.path.join(os.path.dirname(__file__), "..", "app_icon.ico")
        if not os.path.exists(icon_path):
            logger.warning("系統匣圖示檔案不存在，跳過")
            self._tray = None
            return

        self._tray = QSystemTrayIcon(QIcon(icon_path), self)
        self._tray.setToolTip("台股預測分析系統")

        tray_menu = QMenu()
        tray_menu.setStyleSheet(
            "QMenu { background: #222222; color: #E0E6F0; border: 1px solid #3A3A3A; }"
            "QMenu::item:selected { background: #333333; }"
        )
        action_show = tray_menu.addAction("顯示主視窗")
        action_show.triggered.connect(self._tray_show_window)
        tray_menu.addSeparator()
        action_quit = tray_menu.addAction("結束程式")
        action_quit.triggered.connect(self.close)
        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _tray_show_window(self):
        self.showNormal()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show_window()

    def _notify(self, title: str, message: str):
        """透過系統匣發送桌面通知"""
        if self._tray and QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)

    def _connect_signals(self):
        self.btn_predict.clicked.connect(self._on_predict_clicked)
        self.btn_log.clicked.connect(self._on_log_clicked)
        self.btn_watchlist.clicked.connect(self._on_watchlist_add_clicked)
        self.btn_recent.clicked.connect(self._on_recent_clicked)
        self.btn_settings.clicked.connect(self._on_settings_clicked)
        self.input_symbol.returnPressed.connect(self._on_predict_clicked)

    # ── 事件處理 ──────────────────────────────────────────────────

    def _on_predict_clicked(self):
        symbol = self.input_symbol.text().strip()
        if not symbol:
            self._show_status("請先輸入股票代號", error=True)
            return

        # ── 台股休市判斷 ──
        from data.holiday_checker import get_calendar
        status = get_calendar().get_tomorrow_status()
        if not status["is_trading"]:
            self._show_market_closed_dialog(status)
            return

        self._start_prediction(symbol, retrain=False)

    def _show_market_closed_dialog(self, status: dict):
        """顯示台股休市提示視窗"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout

        next_d       = status["next_trading"]
        next_weekday = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"][next_d.weekday()]

        dlg = QDialog(self)
        dlg.setWindowTitle("台股休市通知")
        dlg.setFixedWidth(400)
        dlg.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
            }
            QLabel#title {
                color: #FF6B6B;
                font-size: 16px;
                font-weight: bold;
            }
            QLabel#reason {
                color: #cccccc;
                font-size: 13px;
            }
            QLabel#next {
                color: #4FC3F7;
                font-size: 13px;
            }
            QPushButton {
                background-color: #2a2a2a;
                color: #e0e0e0;
                border: 1px solid #444;
                padding: 8px 24px;
                border-radius: 5px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #333333;
                border-color: #666;
            }
        """)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 20)

        lbl_title = QLabel("❌  無法預測明日行情")
        lbl_title.setObjectName("title")
        layout.addWidget(lbl_title)

        lbl_reason = QLabel(status["reason"])
        lbl_reason.setObjectName("reason")
        lbl_reason.setWordWrap(True)
        layout.addWidget(lbl_reason)

        lbl_next = QLabel(f"📅  下一個交易日：{next_d.strftime('%Y/%m/%d')}（{next_weekday}）")
        lbl_next.setObjectName("next")
        layout.addWidget(lbl_next)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("確定")
        btn_ok.setFixedWidth(90)
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        dlg.exec()

    def _on_log_clicked(self):
        dlg = PredictionLogDialog(self)
        dlg.exec()

    def _on_watchlist_add_clicked(self):
        """★ 按鈕：切換抽屜開關；開啟時將目前輸入框代號預填到新增欄"""
        if self.watchlist_drawer._is_open:
            self.watchlist_drawer.close_drawer()
        else:
            symbol = self.input_symbol.text().strip().upper()
            self.watchlist_drawer.open_drawer(prefill=symbol)

    def _on_recent_clicked(self):
        """🕐 按鈕：開啟本次查詢記錄視窗"""
        from ui.recent_dialog import RecentDialog
        dlg = RecentDialog(self._result_cache, self._stock_dict, self)
        dlg.restore_requested.connect(self._on_recent_restore)
        dlg.exec()

    def _on_recent_restore(self, symbol: str):
        """從最近查詢視窗還原指定股票的預測結果"""
        self.input_symbol.setText(symbol)
        self._display_result(self._result_cache[symbol])

    def _on_settings_clicked(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self, first_run=False)
        dlg.exec()

    def _show_welcome_guide(self):
        """首次啟動：先顯示引導視窗，關閉後再彈出設定"""
        from ui.welcome_dialog import WelcomeDialog
        dlg = WelcomeDialog(self)
        dlg.exec()
        # 引導結束後，若 API Key 未設定則接著彈出設定
        if is_first_run():
            self._show_first_run_settings()

    def _show_first_run_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self, first_run=True)
        dlg.exec()

    def _on_watchlist_symbol_clicked(self, symbol: str):
        """點擊抽屜中的自選股卡片：只填入輸入框，不自動預測"""
        self.input_symbol.setText(symbol)
        self._show_status(f"已選取 {symbol}，按「預測明天」開始分析")

    # ── 背景任務管理 ──────────────────────────────────────────────

    def _start_prediction(self, symbol: str, retrain: bool = False):
        """將預測任務丟入執行緒池"""
        self._current_symbol = symbol
        self._set_busy(True)
        self._show_status(f"正在啟動預測任務：{symbol}...")
        self.progress_bar.setValue(0)

        worker = PredictionWorker(symbol=symbol, retrain=retrain)
        worker.signals.progress_updated.connect(self._on_progress)
        worker.signals.prediction_finished.connect(self._on_prediction_finished)
        worker.signals.error_occurred.connect(self._on_error)

        QThreadPool.globalInstance().start(worker)
        logger.info(f"預測任務已派送：{symbol}，retrain={retrain}")

    def _on_progress(self, percent: int, message: str):
        """背景執行緒回報進度"""
        self.progress_bar.setValue(percent)
        self.big_progress_bar.setValue(percent)
        self.big_progress_label.setText(message)
        self.big_progress_label.setStyleSheet(
            "color: #00AAFF; font-size: 13px; font-weight: bold;"
        )
        self._show_status(message)

    def _on_prediction_finished(self, result: dict):
        """預測完成：存 cache、寫記錄、更新最近查詢，最後顯示結果"""
        symbol = result.get("symbol", "")
        self._result_cache[symbol] = result

        # 寫入預測記錄
        try:
            PredictionLogger.append(result)
        except Exception as e:
            logger.warning(f"預測記錄寫入失敗：{e}")

        self._display_result(result)
        self._set_busy(False)
        self.big_progress_bar.setValue(0)
        self.big_progress_label.setText("預測完成 ✓")
        self.big_progress_label.setStyleSheet(
            "color: #00FF88; font-size: 13px; font-weight: bold;"
        )

        # 系統匣通知
        prediction = result.get("prediction", {})
        up_p = prediction.get("up_prob", 0)
        direction = "上漲" if prediction.get("prediction") == 1 else "下跌"
        prob = up_p if prediction.get("prediction") == 1 else prediction.get("down_prob", 0)
        code = symbol.replace(".TW", "").replace(".TWO", "")
        self._notify(f"{code} 預測完成", f"明日預測{direction}（{prob:.1%}）")

        logger.info(f"UI 更新完成：{symbol}")

    def _display_result(self, result: dict):
        """將預測結果渲染到圖表與右側面板（不寫 log / 不更新 cache）"""
        self._fade_in_results()
        self._last_result = result
        symbol     = result.get("symbol", "")
        prediction = result.get("prediction", {})
        chart_data = result.get("chart_data", {})

        # 更新圖表
        if chart_data:
            self.chart_widget.update_chart(chart_data)

        # 在 K 線最新點加上預測箭頭
        candles = chart_data.get("candles", [])
        if candles and prediction.get("prediction") in (0, 1):
            latest_date = candles[-1]["time"]
            self.chart_widget.add_prediction_markers(
                latest_date,
                is_up=(prediction["prediction"] == 1)
            )

        # 更新右側面板
        self.pred_panel.update_prediction(result)

        # 更新狀態列
        up_p   = prediction.get("up_prob",  0)
        down_p = prediction.get("down_prob", 0)
        direction = "🟢 上漲" if prediction.get("prediction") == 1 else "🔴 下跌"
        self._show_status(
            f"[{symbol}] 預測完成 — 明日{direction} "
            f"({up_p:.1%} 上 / {down_p:.1%} 下)"
        )
        self.label_timestamp.setText(
            f"更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def _on_error(self, error_msg: str):
        """背景任務發生錯誤"""
        self._set_busy(False)
        self.progress_bar.setValue(0)
        self._show_status(f"錯誤：{error_msg}", error=True)
        QMessageBox.critical(self, "預測失敗", error_msg)
        logger.error(f"預測任務錯誤：{error_msg}")

    # ── 工具方法 ──────────────────────────────────────────────────

    def _set_busy(self, busy: bool):
        """切換按鈕的可用狀態，含脈衝光暈動畫"""
        self.btn_predict.setEnabled(not busy)
        if busy:
            self.btn_predict.setText("⏳ 預測中...")
            self._start_pulse()
        else:
            self.btn_predict.setText("▶  預測明天")
            self._stop_pulse()
            self.progress_bar.setValue(0)

    def _start_pulse(self):
        """啟動預測按鈕脈衝光暈動畫"""
        self._pulse_phase = 0
        if self._pulse_timer is None:
            self._pulse_timer = QTimer(self)
            self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_timer.start(50)

    def _stop_pulse(self):
        """停止脈衝動畫，恢復按鈕原始樣式"""
        if self._pulse_timer:
            self._pulse_timer.stop()
        # 清除 inline style，讓 QSS 接管
        self.btn_predict.setStyleSheet("")

    def _pulse_tick(self):
        """每 50ms 更新一次按鈕光暈"""
        import math
        self._pulse_phase += 0.12
        # 0.3 ~ 1.0 之間的呼吸效果
        glow = 0.65 + 0.35 * math.sin(self._pulse_phase)
        r, g, b = int(0 * glow), int(204 * glow), int(102 * glow)
        border_alpha = int(255 * glow)
        self.btn_predict.setStyleSheet(
            f"QPushButton#btnPredict {{"
            f"  background-color: rgb({r},{g},{b});"
            f"  color: #FFFFFF; border: 2px solid rgba(0,255,136,{border_alpha});"
            f"  border-radius: 8px; padding: 9px 22px;"
            f"  font-size: 14px; font-weight: bold; min-width: 110px;"
            f"}}"
        )

    def _fade_in_results(self):
        """預測結果面板漸入動畫"""
        effect = self.pred_panel.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self.pred_panel)
            self.pred_panel.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(500)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        # 保持參照避免被 GC
        self._fade_anim = anim

    def _show_status(self, message: str, error: bool = False):
        color = "#FF6666" if error else "#7A9ABE"
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _refresh_stock_list_bg(self):
        """背景更新股票清單快取（不阻塞 UI，下次啟動生效）"""
        from PySide6.QtCore import QRunnable, QObject, Signal

        class _W(QRunnable):
            def __init__(self):
                super().__init__()
                self.setAutoDelete(True)
            def run(self):
                refresh_cache()

        QThreadPool.globalInstance().start(_W())
        logger.info("股票清單背景更新已啟動")

    def _check_auto_retrain(self):
        """backfill 後檢查是否有股票準確率低於門檻，有則靜默重訓"""
        candidates = PredictionLogger.check_auto_retrain_candidates()
        if not candidates:
            return

        logger.info(f"自動重訓候選：{candidates}")
        self._show_status(f"🔄 準確率下降，自動重訓中：{', '.join(c.replace('.TW','').replace('.TWO','') for c in candidates)}...")

        from workers.auto_retrain_worker import AutoRetrainWorker
        worker = AutoRetrainWorker(candidates)
        worker.signals.symbol_done.connect(self._on_auto_retrain_symbol_done)
        worker.signals.all_done.connect(self._on_auto_retrain_all_done)
        QThreadPool.globalInstance().start(worker)

    def _on_auto_retrain_symbol_done(self, symbol: str, success: bool):
        if success:
            PredictionLogger.mark_retrained(symbol)
            code = symbol.replace(".TW", "").replace(".TWO", "")
            self._show_status(f"✅ {code} 模型已自動更新")

    def _on_auto_retrain_all_done(self, success: int, total: int):
        if success > 0:
            self._show_status(f"✅ 自動重訓完成：{success}/{total} 支股票模型已更新")
        else:
            self._show_status("⚠ 自動重訓失敗，請查看 log")

    def _scan_signals_in_background(self):
        """啟動後掃描自選股的技術訊號（MACD 金叉/死叉、RSI 超買/超賣）"""
        symbols = self.watchlist_drawer.symbols
        if not symbols:
            return
        from workers.signal_scan_worker import SignalScanWorker
        worker = SignalScanWorker(symbols)
        worker.signals.finished.connect(self.watchlist_drawer.update_signals)
        QThreadPool.globalInstance().start(worker)
        logger.info(f"技術訊號掃描已啟動：{symbols}")

    def _backfill_in_background(self):
        """啟動後在背景執行緒回填歷史預測記錄的 actual 欄位"""
        from PySide6.QtCore import QRunnable, QObject, Signal

        class _Signals(QObject):
            done = Signal(int, int, int)   # filled, correct, total

        class _Worker(QRunnable):
            def __init__(self):
                super().__init__()
                self.signals = _Signals()
                self.setAutoDelete(True)
            def run(self):
                filled = PredictionLogger.backfill_actuals()
                stats  = PredictionLogger.get_stats()
                self.signals.done.emit(filled, stats["correct"], stats["total"])

        def _on_done(filled: int, correct: int, total: int):
            if filled > 0:
                acc = f"{correct/total:.0%}" if total > 0 else "—"
                msg = f"回填完成：{filled} 筆 ｜ 歷史準確率 {acc}（{correct}/{total} 筆）"
                logger.info(msg)
                self._show_status(msg)
            # 回填後延遲 1 秒再檢查是否需要自動重訓
            QTimer.singleShot(1000, self._check_auto_retrain)

        worker = _Worker()
        worker.signals.done.connect(_on_done)
        QThreadPool.globalInstance().start(worker)

    def _update_model_status(self):
        """啟動時在狀態列顯示模型新鮮度"""
        from models.lgbm_classifier import LGBMClassifier
        symbol = self.input_symbol.text().strip()
        if not symbol:
            self.label_timestamp.setText("")
            return
        needs, reason = LGBMClassifier.needs_retrain(symbol)
        if needs:
            self.label_timestamp.setText(f"⚠️ {reason}")
            self.label_timestamp.setStyleSheet("color: #FFAA44; font-size: 11px;")
        else:
            self.label_timestamp.setText(f"✅ {reason}")
            self.label_timestamp.setStyleSheet("color: #00AA55; font-size: 11px;")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        central = self.centralWidget()
        if central and hasattr(self, "watchlist_drawer"):
            self.watchlist_drawer.update_size(central.width(), central.height())

    # ── 自動更新 ─────────────────────────────────────────────────

    def _check_for_update_bg(self):
        """背景檢查是否有新版本"""
        try:
            from updater.auto_updater import check_for_update
            update_info = check_for_update()
            if update_info:
                self._show_update_dialog(update_info)
        except Exception as e:
            logger.debug(f"更新檢查跳過：{e}")

    def _show_update_dialog(self, update_info: dict):
        """顯示更新提示對話框"""
        version = update_info["version"]
        notes = update_info.get("release_notes", "")

        # 截斷過長的 release notes
        if len(notes) > 500:
            notes = notes[:500] + "..."

        msg = QMessageBox(self)
        msg.setWindowTitle("發現新版本")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(f"有新版本可用：v{version}")
        msg.setInformativeText(
            f"{notes}\n\n"
            "更新只會替換程式檔案，\n"
            "您的設定、自選股、模型、預測記錄都會保留。"
        )

        btn_update = msg.addButton("立即更新", QMessageBox.ButtonRole.AcceptRole)
        btn_skip   = msg.addButton("跳過此版本", QMessageBox.ButtonRole.RejectRole)
        btn_later  = msg.addButton("稍後提醒", QMessageBox.ButtonRole.DestructiveRole)

        msg.exec()
        clicked = msg.clickedButton()

        if clicked == btn_update:
            self._do_update(update_info)
        elif clicked == btn_skip:
            from updater.auto_updater import skip_version
            skip_version(version)
            self.statusBar().showMessage(f"已跳過 v{version}，下個版本會再通知", 5000)

    def _do_update(self, update_info: dict):
        """執行更新"""
        from updater.auto_updater import download_and_apply

        version = update_info["version"]

        # 建立明顯的進度對話框
        progress = QProgressDialog(
            f"正在下載更新 v{version}...", None, 0, 100, self
        )
        progress.setWindowTitle("台股預測分析系統 — 更新中")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumWidth(420)
        progress.setMinimumHeight(120)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setCancelButton(None)
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()

        def on_progress(downloaded, total):
            if total > 0:
                pct = int(downloaded / total * 100)
                mb_done  = downloaded / 1024 / 1024
                mb_total = total / 1024 / 1024
                progress.setLabelText(
                    f"正在下載更新 v{version}...\n"
                    f"{mb_done:.1f} MB / {mb_total:.1f} MB  ({pct}%)"
                )
                progress.setValue(pct)
                QApplication.processEvents()

        success = download_and_apply(
            update_info["download_url"],
            update_info["version"],
            progress_callback=on_progress,
        )

        progress.close()

        if success:
            QMessageBox.information(
                self, "更新完成",
                "更新已下載完成，程式將自動重新啟動。\n"
                "您的所有資料都已安全保留。"
            )
            # 強制終止程式，讓更新腳本接手重啟
            import os as _os
            _os._exit(0)
        else:
            QMessageBox.warning(
                self, "更新失敗",
                "下載或安裝更新時發生錯誤。\n"
                "請稍後再試，或手動下載新版本。"
            )
            self.statusBar().showMessage("更新失敗", 5000)

    def closeEvent(self, event):
        """視窗關閉時等待執行緒池完成"""
        QThreadPool.globalInstance().waitForDone(3000)
        from logger.app_logger import shutdown_logging
        shutdown_logging()
        event.accept()

"""
預測進度對話框
顯示預測流程中的每個步驟、進度百分比與已經過時間
"""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QWidget,
)


# 步驟定義：(百分比門檻, 圖示, 說明)
_STEPS = [
    (0,   "📡", "連線下載股價資料"),
    (10,  "🏦", "抓取籌碼資料（三大法人 + 融資融券）"),
    (45,  "🌏", "下載美股隔夜資料"),
    (50,  "🔧", "計算技術指標 + 籌碼 + 美股特徵"),
    (55,  "🧠", "Transformer 時序模型"),
    (72,  "🌲", "LightGBM 分類模型"),
    (85,  "📰", "搜尋新聞 + AI 情緒分析"),
    (92,  "📊", "推論明日走勢 + SHAP 解釋"),
    (96,  "🔮", "AI 推估未來 3 日走勢"),
]


class PredictionProgressDialog(QDialog):
    """預測進度對話框 — 置中顯示、深色主題、不可關閉"""

    def __init__(self, symbol: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("預測分析中")
        self.setFixedSize(480, 210)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setModal(True)

        self._elapsed = 0
        self._symbol = symbol.replace(".TW", "").replace(".TWO", "")

        self._build_ui()

        # 每秒更新計時器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _build_ui(self):
        self.setStyleSheet("""
            QDialog {
                background: #1E1E1E;
                border: 1px solid #3A3A3A;
                border-radius: 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(12)

        # 標題列：股票代號
        title = QLabel(f"正在分析  {self._symbol}")
        title.setFont(QFont("Microsoft JhengHei", 15, QFont.Weight.Bold))
        title.setStyleSheet("color: #E0E6F0;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 步驟說明（圖示 + 文字）
        self._step_label = QLabel("📡  連線下載股價資料")
        self._step_label.setFont(QFont("Microsoft JhengHei", 12))
        self._step_label.setStyleSheet("color: #80C8FF;")
        self._step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._step_label)

        # 進度條
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(22)
        self._bar.setFormat("")
        self._bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #3A3A3A;
                border-radius: 11px;
                background: #252525;
                color: transparent;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #004488, stop:0.5 #0099FF, stop:1 #00DDFF);
                border-radius: 10px;
            }
        """)
        layout.addWidget(self._bar)

        # 底部：百分比 + 經過時間
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)

        self._pct_label = QLabel("0%")
        self._pct_label.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
        self._pct_label.setStyleSheet("color: #00AAFF;")
        bottom.addWidget(self._pct_label)

        bottom.addStretch()

        self._time_label = QLabel("已經過 0 秒")
        self._time_label.setFont(QFont("Microsoft JhengHei", 10))
        self._time_label.setStyleSheet("color: #6A7A8A;")
        bottom.addWidget(self._time_label)

        layout.addLayout(bottom)

    # ── Public API ──────────────────────────────────────────────────

    def update_progress(self, percent: int, message: str):
        """從外部（signal）更新進度"""
        self._bar.setValue(percent)
        self._pct_label.setText(f"{percent}%")

        # 根據百分比自動匹配步驟圖示
        step_text = message
        for threshold, icon, desc in reversed(_STEPS):
            if percent >= threshold:
                step_text = f"{icon}  {message}"
                break

        self._step_label.setText(step_text)

    def finish(self):
        """預測完成，關閉對話框"""
        self._timer.stop()
        self.accept()

    def abort(self, error_msg: str = ""):
        """預測失敗，關閉對話框"""
        self._timer.stop()
        self.reject()

    # ── Private ─────────────────────────────────────────────────────

    def _tick(self):
        self._elapsed += 1
        m, s = divmod(self._elapsed, 60)
        if m > 0:
            self._time_label.setText(f"已經過 {m} 分 {s} 秒")
        else:
            self._time_label.setText(f"已經過 {s} 秒")

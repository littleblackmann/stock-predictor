"""
首次啟動引導視窗
- 歡迎語 + 功能簡介
- 模型成長說明
- 投資風險警語
- 「不再顯示」勾選框
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QFrame, QWidget, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from data.config_manager import load_config, save_config


class WelcomeDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("歡迎使用台股預測分析系統")
        self.setMinimumWidth(520)
        self.setMinimumHeight(500)
        self.setMaximumWidth(600)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 頂部 Banner ──
        banner = QWidget()
        banner.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #0A1628, stop:1 #1A2A4A);"
        )
        banner_layout = QVBoxLayout(banner)
        banner_layout.setContentsMargins(32, 28, 32, 24)
        banner_layout.setSpacing(8)

        title = QLabel("歡迎使用台股預測分析系統")
        title.setFont(QFont("Microsoft JhengHei", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #FFFFFF;")
        banner_layout.addWidget(title)

        subtitle = QLabel("Transformer + LightGBM 雙模型智慧預測平台")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #7A9ABE; font-size: 13px;")
        banner_layout.addWidget(subtitle)

        layout.addWidget(banner)

        # ── 內容區（可捲動）──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: #1E1E1E; }")

        content = QWidget()
        content.setStyleSheet("background: #1E1E1E;")
        clayout = QVBoxLayout(content)
        clayout.setContentsMargins(28, 20, 28, 16)
        clayout.setSpacing(16)

        # ── 快速上手 ──
        clayout.addWidget(self._make_section("快速上手"))
        clayout.addWidget(self._make_step_card([
            ("1️⃣", "輸入股票代號", "在頂部輸入框輸入台股代號（如 2330）或名稱（如 台積電）"),
            ("2️⃣", "點擊預測", "按下「預測明天」按鈕，系統將下載最新數據並執行模型分析"),
            ("3️⃣", "查看結果", "右側面板顯示漲跌預測、信心度、技術指標與 AI 分析"),
        ]))

        clayout.addWidget(self._make_hline())

        # ── 模型準確度 ──
        clayout.addWidget(self._make_section("關於預測準確度"))
        clayout.addWidget(self._make_info_card(
            "📈  模型會隨時間成長",
            "本系統採用累積式訓練，每次預測都會學習最新市場資料。\n"
            "建議持續使用 3～6 個月，預測準確度將逐步提升。\n"
            "初期準確率較低屬正常現象，請耐心使用。",
            "#1A2A3A", "#2A4A6A"
        ))

        clayout.addWidget(self._make_hline())

        # ── 投資風險警語 ──
        clayout.addWidget(self._make_section("投資風險提醒"))
        clayout.addWidget(self._make_info_card(
            "⚠  重要聲明",
            "• 本系統預測結果僅供參考，不構成任何投資建議\n"
            "• 投資理財有賺有賠，過去績效不代表未來表現\n"
            "• 模型預測並非百分之百準確，請搭配個人判斷\n"
            "• 請勿依據單一工具的預測做出全部投資決策\n"
            "• 使用者應自行承擔所有投資決策之風險與責任",
            "#2A1A1A", "#6A2A2A"
        ))

        clayout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        # ── 底部（勾選框 + 按鈕）──
        footer = QWidget()
        footer.setStyleSheet("background: #1A1A1A; border-top: 1px solid #333333;")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(28, 14, 28, 14)
        footer_layout.setSpacing(12)

        self.chk_no_show = QCheckBox("我已閱讀並了解，下次不再顯示")
        self.chk_no_show.setChecked(True)
        self.chk_no_show.setStyleSheet(
            "QCheckBox { color: #8A8A8A; font-size: 12px; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
            "QCheckBox::indicator:unchecked { "
            "  border: 1px solid #555; border-radius: 3px; background: #2A2A2A; }"
            "QCheckBox::indicator:checked { "
            "  border: 1px solid #00AA55; border-radius: 3px; "
            "  background: #00AA55; }"
        )
        footer_layout.addWidget(self.chk_no_show)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_ok = QPushButton("我知道了，開始使用")
        btn_ok.setFixedSize(180, 38)
        btn_ok.clicked.connect(self._on_confirm)
        btn_ok.setStyleSheet(
            "QPushButton { "
            "  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "  stop:0 #00CC66, stop:1 #008844); "
            "  color: #FFFFFF; border: none; border-radius: 8px; "
            "  font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { "
            "  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "  stop:0 #00DD77, stop:1 #009955); }"
        )
        btn_row.addWidget(btn_ok)
        btn_row.addStretch()

        footer_layout.addLayout(btn_row)
        layout.addWidget(footer)

    def _on_confirm(self):
        if self.chk_no_show.isChecked():
            save_config({"welcome_shown": True})
        self.accept()

    # ── 工具方法 ─────────────────────────────────────────────────

    def _make_section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Microsoft JhengHei", 13, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #E0E6F0;")
        return lbl

    def _make_hline(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #2A2A2A;")
        return line

    def _make_info_card(self, title: str, body: str,
                        bg_color: str, border_color: str) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background-color: {bg_color}; "
            f"border: 1px solid {border_color}; "
            f"border-radius: 8px;"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(6)

        lbl_title = QLabel(title)
        lbl_title.setFont(QFont("Microsoft JhengHei", 12, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #E0E6F0; border: none; background: transparent;")
        card_layout.addWidget(lbl_title)

        lbl_body = QLabel(body)
        lbl_body.setWordWrap(True)
        lbl_body.setStyleSheet("color: #B0C0D0; font-size: 12px; border: none; background: transparent;")
        card_layout.addWidget(lbl_body)

        return card

    def _make_step_card(self, steps: list[tuple[str, str, str]]) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            "background-color: #1A2A1A; "
            "border: 1px solid #2A4A2A; "
            "border-radius: 8px;"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        for icon, title, desc in steps:
            row = QHBoxLayout()
            row.setSpacing(10)

            lbl_icon = QLabel(icon)
            lbl_icon.setFixedWidth(28)
            lbl_icon.setStyleSheet("font-size: 16px; border: none; background: transparent;")
            lbl_icon.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.addWidget(lbl_icon)

            text_layout = QVBoxLayout()
            text_layout.setSpacing(2)

            lbl_title = QLabel(title)
            lbl_title.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
            lbl_title.setStyleSheet("color: #C0E0C0; border: none; background: transparent;")
            text_layout.addWidget(lbl_title)

            lbl_desc = QLabel(desc)
            lbl_desc.setWordWrap(True)
            lbl_desc.setStyleSheet("color: #90B090; font-size: 11px; border: none; background: transparent;")
            text_layout.addWidget(lbl_desc)

            row.addLayout(text_layout, stretch=1)
            card_layout.addLayout(row)

        return card

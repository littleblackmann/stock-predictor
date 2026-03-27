"""
設定視窗（分頁版）
- Tab 1：API 設定（OpenAI / Brave Search / 模型選擇）
- Tab 2：使用說明（模型成長、功能介紹、注意事項）
- 首次啟動時自動彈出（API Key 為空）
- 可透過控制列 ⚙ 按鈕隨時開啟
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QFrame,
    QWidget, QTabWidget, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from data.config_manager import load_config, save_config, AVAILABLE_MODELS


class SettingsDialog(QDialog):

    def __init__(self, parent=None, first_run: bool = False):
        super().__init__(parent)
        self._first_run = first_run
        self.setWindowTitle("⚙  系統設定")
        self.setMinimumWidth(520)
        self.setMinimumHeight(480)
        self.setModal(True)
        self._setup_ui()
        self._load_current()

    # ── UI 建構 ───────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 首次啟動標題 ──
        if self._first_run:
            title = QLabel("歡迎使用台股預測分析系統")
            title.setFont(QFont("Microsoft JhengHei", 14, QFont.Weight.Bold))
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("color: #E0E6F0; padding-bottom: 4px;")
            layout.addWidget(title)

            subtitle = QLabel("請完成以下設定以啟用完整功能")
            subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            subtitle.setStyleSheet("color: #7A9ABE; font-size: 12px;")
            layout.addWidget(subtitle)

        # ── 分頁 ──
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3A3A3A;
                border-radius: 6px;
                background: #1E1E1E;
            }
            QTabBar::tab {
                background: #2A2A2A;
                color: #8A8A8A;
                padding: 8px 24px;
                border: 1px solid #3A3A3A;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background: #1E1E1E;
                color: #E0E6F0;
                font-weight: bold;
                border-bottom: 2px solid #00CC66;
            }
            QTabBar::tab:hover:!selected {
                background: #333333;
                color: #C0C0C0;
            }
        """)

        self.tabs.addTab(self._build_api_tab(), "API 設定")
        self.tabs.addTab(self._build_guide_tab(), "使用說明")
        layout.addWidget(self.tabs, stretch=1)

        # ── 按鈕列 ──
        layout.addWidget(self._make_hline())

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        if not self._first_run:
            btn_cancel = QPushButton("取消")
            btn_cancel.setFixedSize(80, 34)
            btn_cancel.clicked.connect(self.reject)
            btn_cancel.setStyleSheet(
                "background: #2A2A2A; color: #8A8A8A; "
                "border: 1px solid #3A3A3A; border-radius: 6px;"
            )
            btn_row.addWidget(btn_cancel)

        self.btn_save = QPushButton("儲存設定" if not self._first_run else "開始使用")
        self.btn_save.setFixedSize(100, 34)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #00CC66, stop:1 #008844); "
            "color: #FFFFFF; border: none; border-radius: 6px; font-weight: bold;"
        )
        btn_row.addWidget(self.btn_save)

        if self._first_run:
            btn_skip = QPushButton("略過，稍後再設定")
            btn_skip.setFixedHeight(34)
            btn_skip.clicked.connect(self.reject)
            btn_skip.setStyleSheet(
                "background: transparent; color: #5A5A5A; "
                "border: none; font-size: 11px;"
            )
            btn_row.addWidget(btn_skip)

        layout.addLayout(btn_row)

    # ── Tab 1: API 設定 ───────────────────────────────────────────

    def _build_api_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        # 警語框
        warning = QLabel(
            "⚠  API Key 為選填。\n"
            "不填入仍可使用技術面預測（LSTM + LightGBM），\n"
            "但將停用「AI 新聞情緒分析」與「未來 3 日走勢」功能。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "color: #DDAA44; font-size: 12px; padding: 10px 14px; "
            "background-color: #2A2200; border: 1px solid #554400; "
            "border-radius: 6px;"
        )
        layout.addWidget(warning)

        # OpenAI API Key
        layout.addWidget(self._make_label("OpenAI API Key"))

        key_row = QHBoxLayout()
        self.input_key = QLineEdit()
        self.input_key.setPlaceholderText("sk-proj-...")
        self.input_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_key.setFixedHeight(36)
        key_row.addWidget(self.input_key)

        self.btn_toggle_key = QPushButton("👁")
        self.btn_toggle_key.setFixedSize(36, 36)
        self.btn_toggle_key.setCheckable(True)
        self.btn_toggle_key.setToolTip("顯示 / 隱藏 Key")
        self.btn_toggle_key.clicked.connect(self._toggle_key_visibility)
        self.btn_toggle_key.setStyleSheet(
            "QPushButton { background: #2A2A2A; border: 1px solid #3A3A3A; "
            "border-radius: 6px; font-size: 15px; }"
            "QPushButton:checked { background: #3A3A3A; }"
        )
        key_row.addWidget(self.btn_toggle_key)
        layout.addLayout(key_row)

        # Brave Search API Key
        layout.addWidget(self._make_hline())
        layout.addWidget(self._make_label("Brave Search API Key（選填）"))

        brave_hint = QLabel("啟用後可取得更深入的新聞與產業分析，提升預測準確度")
        brave_hint.setStyleSheet("color: #5A7A9A; font-size: 11px;")
        layout.addWidget(brave_hint)

        brave_row = QHBoxLayout()
        self.input_brave_key = QLineEdit()
        self.input_brave_key.setPlaceholderText("BSA...")
        self.input_brave_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_brave_key.setFixedHeight(36)
        brave_row.addWidget(self.input_brave_key)

        self.btn_toggle_brave = QPushButton("\U0001f441")
        self.btn_toggle_brave.setFixedSize(36, 36)
        self.btn_toggle_brave.setCheckable(True)
        self.btn_toggle_brave.setToolTip("顯示 / 隱藏 Key")
        self.btn_toggle_brave.clicked.connect(self._toggle_brave_visibility)
        self.btn_toggle_brave.setStyleSheet(
            "QPushButton { background: #2A2A2A; border: 1px solid #3A3A3A; "
            "border-radius: 6px; font-size: 15px; }"
            "QPushButton:checked { background: #3A3A3A; }"
        )
        brave_row.addWidget(self.btn_toggle_brave)
        layout.addLayout(brave_row)

        # 模型選擇
        layout.addWidget(self._make_label("AI 模型"))

        self.combo_model = QComboBox()
        self.combo_model.setFixedHeight(36)

        # GPT-5.4 系列
        self.combo_model.addItem("── GPT-5.4 系列（最新旗艦）──")
        self.combo_model.model().item(0).setEnabled(False)
        for m in ["gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"]:
            self.combo_model.addItem(f"  {m}", m)

        self.combo_model.insertSeparator(self.combo_model.count())

        sep_idx = self.combo_model.count()
        self.combo_model.addItem("── GPT-4o 系列 ──")
        self.combo_model.model().item(sep_idx).setEnabled(False)
        for m in ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]:
            self.combo_model.addItem(f"  {m}", m)

        layout.addWidget(self.combo_model)

        hint = QLabel("建議：日常使用選 gpt-5.4-mini（速度快、費用低）")
        hint.setStyleSheet("color: #5A7A9A; font-size: 11px;")
        layout.addWidget(hint)

        layout.addStretch()
        return tab

    # ── Tab 2: 使用說明 ───────────────────────────────────────────

    def _build_guide_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # ── 功能簡介 ──
        layout.addWidget(self._make_section_title("功能簡介"))
        layout.addWidget(self._make_guide_text(
            "本系統結合 LSTM 深度學習與 LightGBM 機器學習模型，\n"
            "透過技術面指標、籌碼面數據、美股隔夜訊號等 84 維特徵，\n"
            "對台股個股進行明日漲跌預測。\n\n"
            "若設定 OpenAI API Key，可額外啟用：\n"
            "• AI 新聞情緒分析（搭配 Brave Search 效果更佳）\n"
            "• 未來 3 日走勢預測"
        ))

        layout.addWidget(self._make_hline())

        # ── 模型成長說明 ──
        layout.addWidget(self._make_section_title("模型準確度"))
        layout.addWidget(self._make_guide_card(
            "📈  模型會隨使用時間成長",
            "系統採用累積式訓練機制，每次預測都會自動學習最新市場數據。\n"
            "建議持續使用 3～6 個月，讓模型累積足夠的歷史資料，\n"
            "預測準確度會逐步提升。初期準確率較低屬正常現象。",
            "#1A2A3A", "#2A4A6A"
        ))

        layout.addWidget(self._make_guide_card(
            "🔄  自動重訓機制",
            "系統會在每次啟動時自動回填歷史預測結果，\n"
            "並在準確率低於門檻時自動觸發模型重訓，\n"
            "無需手動操作。",
            "#1A2A3A", "#2A4A6A"
        ))

        layout.addWidget(self._make_hline())

        # ── 投資風險警語 ──
        layout.addWidget(self._make_section_title("投資風險提醒"))
        layout.addWidget(self._make_guide_card(
            "⚠  重要聲明",
            "• 本系統預測結果僅供參考，不構成任何投資建議\n"
            "• 投資理財有賺有賠，過去績效不代表未來表現\n"
            "• 模型預測不代表完全正確，請搭配自身判斷使用\n"
            "• 請勿將全部資金依據單一工具的預測進行操作\n"
            "• 使用者應自行承擔所有投資決策之風險與責任",
            "#2A1A1A", "#6A2A2A"
        ))

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return tab

    # ── 資料 ─────────────────────────────────────────────────────

    def _load_current(self):
        config = load_config()
        self.input_key.setText(config.get("openai_api_key", ""))
        self.input_brave_key.setText(config.get("brave_api_key", ""))
        current_model = config.get("openai_model", "")
        for i in range(self.combo_model.count()):
            if self.combo_model.itemData(i) == current_model:
                self.combo_model.setCurrentIndex(i)
                break

    def _on_save(self):
        key = self.input_key.text().strip()
        brave_key = self.input_brave_key.text().strip()
        model = self.combo_model.currentData()
        if model is None:
            model = ""
        save_config({
            "openai_api_key": key,
            "openai_model": model,
            "brave_api_key": brave_key,
        })
        self.accept()

    def _toggle_key_visibility(self, checked: bool):
        self.input_key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def _toggle_brave_visibility(self, checked: bool):
        self.input_brave_key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    # ── 工具 ─────────────────────────────────────────────────────

    def _make_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #C0C0C0; font-size: 13px; font-weight: bold;")
        return lbl

    def _make_hline(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #2A2A2A;")
        return line

    def _make_section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Microsoft JhengHei", 13, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #E0E6F0;")
        return lbl

    def _make_guide_text(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #A0B0C0; font-size: 12px; line-height: 1.6;")
        return lbl

    def _make_guide_card(self, title: str, body: str,
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
        lbl_title.setStyleSheet(f"color: #E0E6F0; border: none; background: transparent;")
        card_layout.addWidget(lbl_title)

        lbl_body = QLabel(body)
        lbl_body.setWordWrap(True)
        lbl_body.setStyleSheet(f"color: #B0C0D0; font-size: 12px; border: none; background: transparent;")
        card_layout.addWidget(lbl_body)

        return card

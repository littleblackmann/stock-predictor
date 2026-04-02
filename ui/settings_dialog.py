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
        self.tabs.addTab(self._build_about_tab(), "關於 / 更新")
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
            "不填入仍可使用技術面預測（Transformer + LightGBM），\n"
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
        self.combo_model.setStyleSheet(
            "QComboBox { font-size: 13px; background: #2A2A2A; color: #E0E6F0; "
            "border: 1px solid #3A3A3A; border-radius: 6px; padding: 4px 8px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { font-size: 13px; background: #2A2A2A; "
            "color: #E0E6F0; selection-background-color: #3A5A3A; }"
        )

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
            "本系統結合 Transformer 深度學習與 LightGBM 機器學習模型，\n"
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

    # ── Tab 3: 關於 / 更新 ─────────────────────────────────────────

    def _build_about_tab(self) -> QWidget:
        from updater.auto_updater import get_current_version

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

        # ── 版本資訊 ──
        version = get_current_version()
        layout.addWidget(self._make_section_title("台股預測分析系統"))

        ver_label = QLabel(f"目前版本：v{version}")
        ver_label.setFont(QFont("Microsoft JhengHei", 16, QFont.Weight.Bold))
        ver_label.setStyleSheet("color: #00CC66;")
        layout.addWidget(ver_label)

        # ── 檢查更新按鈕 ──
        self.btn_check_update = QPushButton("檢查更新")
        self.btn_check_update.setFixedSize(120, 36)
        self.btn_check_update.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #0088CC, stop:1 #006699); "
            "color: #FFFFFF; border: none; border-radius: 6px; "
            "font-weight: bold; font-size: 13px;"
        )
        self.btn_check_update.clicked.connect(self._on_check_update)
        layout.addWidget(self.btn_check_update)

        self.update_status_label = QLabel("")
        self.update_status_label.setStyleSheet("color: #7A9ABE; font-size: 12px;")
        layout.addWidget(self.update_status_label)

        layout.addWidget(self._make_hline())

        # ── 更新日誌 ──
        layout.addWidget(self._make_section_title("更新日誌"))

        changelogs = [
            {
                "version": "v1.4.3",
                "date": "2026-04-03",
                "changes": [
                    "修復預測記錄無法回填實際結果的問題（BOM 編碼汙染）",
                    "回填失敗不再靜默，改為記錄警告日誌方便排查",
                ],
            },
            {
                "version": "v1.4.2",
                "date": "2026-04-01",
                "changes": [
                    "修復預測記錄漲跌%顯示 0.00% 或 nan% 的問題",
                    "已回填的錯誤記錄會自動重新計算",
                ],
            },
            {
                "version": "v1.4.1",
                "date": "2026-03-30",
                "changes": [
                    "修復 K 線圖日期缺少當天資料的問題",
                    "修復偶發啟動閃退問題（檔案鎖定保護 + 背景載入容錯）",
                ],
            },
            {
                "version": "v1.4.0",
                "date": "2026-03-30",
                "changes": [
                    "【重大升級】核心模型從 LSTM 升級為 Transformer（業界主流架構）",
                    "分析窗口從 60 天大幅擴展至 300 天，可捕捉季節性與長期規律",
                    "歷史資料量從 4 年擴充至 7 年（2,500 天），訓練樣本更充足",
                    "Transformer 輸入從 17 維擴充至 28~41 維（含完整技術面 + 籌碼 + 行情）",
                    "新增時間衰減權重，近期資料影響力更大，適應市場結構變化",
                    "預估持續使用 2~3 個月後，準確率可達 65%~70% 參考水準",
                    "首次啟動自動清理舊模型，無需手動操作",
                ],
            },
            {
                "version": "v1.3.2",
                "date": "2026-03-30",
                "changes": [
                    "新增預測進度對話框（顯示步驟、百分比、經過時間）",
                    "籌碼抓取加入逐日進度回報，不再看似當機",
                    "修復 Win10 預測記錄表格白色背景問題",
                ],
            },
            {
                "version": "v1.3.1",
                "date": "2026-03-29",
                "changes": [
                    "修復自動更新後版本號未更新的問題（不再無限跳更新通知）",
                    "修復差量更新包可能遺漏關鍵檔案的問題",
                    "強化版本帶偵測機制，Win10/Win11 皆可穩定更新",
                ],
            },
            {
                "version": "v1.3.0",
                "date": "2026-03-29",
                "changes": [
                    "新增 6 個籌碼面二階特徵（外資加速度、投信連續買超、籌碼共振等）",
                    "新增市場行情狀態辨識（多頭/空頭/盤整 + 趨勢強度 + 波動率）",
                    "預測特徵從 27 維擴充至 36 維，提升準確度天花板",
                    "盤整行情自動降級信心度，避免過度自信",
                    "修復 TWSE API 格式變更導致籌碼資料無法抓取",
                    "新增 TWSE 限流偵測與自動重試機制",
                ],
            },
            {
                "version": "v1.2.8",
                "date": "2026-03-28",
                "changes": [
                    "修正 Win10 SSL 連線問題導致無法偵測/下載更新",
                    "差量更新失敗時自動改用完整更新",
                    "修正自選股標題列顏色不一致",
                ],
            },
        ]

        # 只顯示最新一筆
        for entry in changelogs[:1]:
            ver_title = QLabel(f"{entry['version']}  ({entry['date']})")
            ver_title.setFont(QFont("Microsoft JhengHei", 12, QFont.Weight.Bold))
            ver_title.setStyleSheet("color: #E0E6F0;")
            layout.addWidget(ver_title)

            changes_text = "\n".join(f"  •  {c}" for c in entry["changes"])
            changes_label = QLabel(changes_text)
            changes_label.setWordWrap(True)
            changes_label.setStyleSheet(
                "color: #A0B0C0; font-size: 12px; "
                "padding: 6px 10px 12px 10px;"
            )
            layout.addWidget(changes_label)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return tab

    def _on_check_update(self):
        """手動檢查更新 — 發現新版本時直接觸發更新"""
        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText("檢查中...")
        self.update_status_label.setText("")

        try:
            from updater.auto_updater import check_for_update
            result = check_for_update()
            if result:
                self.update_status_label.setText(
                    f"發現新版本 v{result['version']}！"
                )
                self.update_status_label.setStyleSheet(
                    "color: #00CC66; font-size: 12px; font-weight: bold;"
                )
                # 關閉設定視窗，讓主視窗執行更新
                self.close()
                main_win = self.parent()
                if main_win and hasattr(main_win, '_do_update'):
                    main_win._do_update(result)
                return
            else:
                self.update_status_label.setText("已是最新版本！")
                self.update_status_label.setStyleSheet(
                    "color: #7A9ABE; font-size: 12px;"
                )
        except Exception as e:
            self.update_status_label.setText(f"檢查失敗：{e}")
            self.update_status_label.setStyleSheet(
                "color: #FF6666; font-size: 12px;"
            )

        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText("檢查更新")

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

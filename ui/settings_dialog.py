"""
設定視窗（分頁版）
- Tab 1：API 設定（OpenRouter / Brave Search / 模型選擇）
- Tab 2：使用說明（模型成長、功能介紹、注意事項）
- 首次啟動時自動彈出（API Key 為空）
- 可透過控制列 ⚙ 按鈕隨時開啟
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QFrame,
    QWidget, QTabWidget, QScrollArea
)
from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QFont

from data.config_manager import (
    load_config, save_config, AVAILABLE_MODELS, DEFAULT_MODEL,
)


class _CatalogSignals(QObject):
    done = Signal(object, str)


class _CatalogWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = _CatalogSignals()

    def run(self):
        from data.model_catalog import refresh_catalog
        try:
            self.signals.done.emit(refresh_catalog(), "")
        except Exception:
            self.signals.done.emit(None, "連線失敗，保留原清單與選擇，請稍後重試")


class SettingsDialog(QDialog):

    def __init__(self, parent=None, first_run: bool = False):
        super().__init__(parent)
        self._first_run = first_run
        self.setWindowTitle("⚙  系統設定")
        self.setMinimumWidth(520)
        self.setMinimumHeight(480)
        self.resize(680, 740)
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

        api_scroll = QScrollArea()
        api_scroll.setWidgetResizable(True)
        api_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        api_scroll.setFrameShape(QFrame.Shape.NoFrame)
        api_scroll.setWidget(self._build_api_tab())
        self.tabs.addTab(api_scroll, "API 設定")
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
            "不填入仍可使用 1、3、5 交易日量化預測，\n"
            "填入後可另外使用 AI 新聞分析；模型費用由 OpenRouter 收取。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "color: #DDAA44; font-size: 12px; padding: 10px 14px; "
            "background-color: #2A2200; border: 1px solid #554400; "
            "border-radius: 6px;"
        )
        layout.addWidget(warning)

        # OpenRouter API Key
        layout.addWidget(self._make_label("OpenRouter API Key"))

        key_hint = QLabel(
            "至 https://openrouter.ai/keys 申請，一把 Key 即可使用下方所有模型"
        )
        key_hint.setStyleSheet("color: #5A7A9A; font-size: 11px;")
        layout.addWidget(key_hint)

        key_row = QHBoxLayout()
        self.input_key = QLineEdit()
        self.input_key.setPlaceholderText("sk-or-v1-...")
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

        brave_hint = QLabel("啟用後可取得新聞摘要與產業資訊，並不保證提高預測準確率")
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

        self._model_desc = {}
        self._populate_models(AVAILABLE_MODELS)
        self.combo_model.setMaxVisibleItems(18)
        layout.addWidget(self.combo_model)

        # 選到哪個模型就顯示該模型的說明與參考費用
        self.label_model_hint = QLabel("")
        self.label_model_hint.setWordWrap(True)
        self.label_model_hint.setStyleSheet("color: #5A7A9A; font-size: 11px;")
        layout.addWidget(self.label_model_hint)
        model_tools = QHBoxLayout()
        self.model_search = QLineEdit()
        self.model_search.setFixedHeight(36)
        self.model_search.setPlaceholderText("搜尋模型名稱或廠商")
        self.model_search.textChanged.connect(self._filter_models)
        model_tools.addWidget(self.model_search)
        self.btn_refresh_models = QPushButton("更新模型清單")
        self.btn_refresh_models.clicked.connect(self._refresh_models)
        model_tools.addWidget(self.btn_refresh_models)
        layout.addLayout(model_tools)
        from data.model_catalog import load_catalog
        self.catalog_status = QLabel("清單更新：" + load_catalog().get('updated_at','')[:10] + " · 不會自動切換模型")
        self.catalog_status.setWordWrap(True)
        layout.addWidget(self.catalog_status)

        # 標籤建好後才接訊號，避免初始化期間觸發時抓不到 label
        self.combo_model.currentIndexChanged.connect(self._on_model_changed)
        self._on_model_changed()

        layout.addStretch()
        return tab

    def _populate_models(self, entries, selected=None):
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        self._model_desc = {m[0]:m[3] for m in entries}
        for model_id, display, group, desc in entries:
            prefix = "★ " if group == "精選模型" else ""
            self.combo_model.addItem(prefix + display, model_id)
            self.combo_model.setItemData(self.combo_model.count()-1, desc, Qt.ItemDataRole.ToolTipRole)
        if selected and self.combo_model.findData(selected) < 0:
            self.combo_model.addItem("目前設定（未列於目錄）：" + selected, selected)
            self._model_desc[selected] = "原設定已保留；服務是否可用需由供應商確認"
        if selected:
            self.combo_model.setCurrentIndex(self.combo_model.findData(selected))
        self.combo_model.blockSignals(False)

    def _filter_models(self, text):
        for i in range(self.combo_model.count()):
            haystack = (self.combo_model.itemText(i) + ' ' + str(self.combo_model.itemData(i))).lower()
            self.combo_model.view().setRowHidden(i, text.lower() not in haystack)

    def _refresh_models(self):
        self.btn_refresh_models.setEnabled(False)
        self.catalog_status.setText("正在讀取 OpenRouter 公開目錄…")
        self._refresh_job = _CatalogWorker()
        self._refresh_job.signals.done.connect(self._catalog_ready)
        QThreadPool.globalInstance().start(self._refresh_job)

    def _catalog_ready(self, catalog, error):
        self.btn_refresh_models.setEnabled(True)
        if error:
            self.catalog_status.setText(error)
            return
        from data.model_catalog import menu_models
        self._populate_models(menu_models(catalog), self.combo_model.currentData())
        self.model_search.clear()
        self._on_model_changed()
        self.catalog_status.setText("清單更新：" + catalog['updated_at'][:10] + " · 原模型選擇已保留")

    def _on_model_changed(self, *_):
        """更新模型說明文字"""
        model_id = self.combo_model.currentData()
        desc = self._model_desc.get(model_id, "")
        if model_id:
            self.label_model_hint.setText(f"{model_id}　—　{desc}")
        else:
            self.label_model_hint.setText("請選擇一個模型")

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
            "本系統使用獨立的短線 LightGBM 模型與機率校準，\n"
            "透過技術面與美股歷史訊號，採用完整收盤資料，\n"
            "分別分析未來 1、3、5 個交易日相對基準日的漲跌。\n\n"
            "若設定 OpenRouter API Key，可額外啟用：\n"
            "• AI 新聞情緒分析（搭配 Brave Search 效果更佳）\n"
            "• 新聞作為補充說明，不直接修改模型機率"
        ))

        layout.addWidget(self._make_hline())

        # ── 模型成長說明 ──
        layout.addWidget(self._make_section_title("模型準確度"))
        layout.addWidget(self._make_guide_card(
            "📈  以實際驗證判斷模型表現",
            "系統按時間順序訓練、校準與驗證，每段測試只使用過去資料。\n"
            "畫面同時顯示模型與歷史多數方向基準的成績，\n"
            "使用越久不代表一定越準；方向不明時不強行給出漲跌結論。",
            "#1A2A3A", "#2A4A6A"
        ))

        layout.addWidget(self._make_guide_card(
            "🔄  自動重訓機制",
            "系統會在每次啟動時自動回填歷史預測結果，\n"
            "新交易日或行情修訂時會更新模型；同資料再次查詢使用快取，\n"
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
            {"version": "v1.7.1", "date": "2026-10-04", "changes": [
                "手動檢查可更新已跳過的版本；關閉提示只會稍後提醒。",
                "無法取得版本資訊時顯示檢查失敗，不再誤報已是最新版。",
            ]},
            {"version":"v1.7.0", "date":"2026-10-04", "changes":[
                "1、3、5 個交易日獨立預測，完整收盤資料與時間分段驗證",
                "清楚顯示資料日期、回測基準、方向不明與新版實際紀錄",
                "更新 OpenRouter 模型、費用、搜尋與線上更新清單",
                "保留 API Key、自選股與舊紀錄，舊紀錄自動備份",
            ]},
            {
                "version": "v1.6.2",
                "date": "2026-07-24",
                "changes": [
                    "新增「連漲/連跌天數」與「金叉距離變化」兩項技術特徵（經 7 年歷史回測驗證）",
                    "自選股訊號掃描新增「連跌 N 天」提示（連跌 3 天以上顯示）",
                    "首次更新後每支股票會自動重新訓練一次（約 5-8 分鐘），之後恢復正常速度",
                ],
            },
            {
                "version": "v1.6.1",
                "date": "2026-07-23",
                "changes": [
                    "預測大幅提速：例行重訓從約 8 分鐘縮短到 1 分鐘內",
                    "Transformer 時序模型改為 45 天重訓週期（長期型態不需每週重練）",
                    "每週例行重訓只更新 LightGBM（秒級增量訓練）",
                    "手動重訓與準確率驅動的自動重訓不受影響，仍完整重練",
                ],
            },
            {
                "version": "v1.6.0",
                "date": "2026-07-23",
                "changes": [
                    "AI 供應商改為 OpenRouter，一把 Key 即可使用 GPT / Claude / Gemini / Grok 等各家模型",
                    "設定視窗新增 10 大熱門模型選單（依廠商分組，顯示參考費用）",
                    "⚠ 需重新申請 OpenRouter API Key（https://openrouter.ai/keys），舊的 OpenAI Key 無法使用",
                    "修復無新聞時的情緒分析：token 上限過低導致推理型模型回傳空值",
                ],
            },
            {
                "version": "v1.5.5",
                "date": "2026-04-20",
                "changes": [
                    "修復 v1.5.4 預測記錄欄位錯位問題（3日走勢顯示機率值、實際欄位顯示走勢文字）",
                    "預測記錄視窗新增「原始機率」欄位（v1.5.4 漏加 UI）",
                    "啟動時自動修復舊版 CSV schema，錯位記錄自動對齊",
                ],
            },
            {
                "version": "v1.5.4",
                "date": "2026-04-18",
                "changes": [
                    "降低 GPT 新聞情緒權重（15% → 8%），避免情緒主導模型決策",
                    "LightGBM 訓練啟用類別平衡（is_unbalance），減輕上漲偏見",
                    "預測記錄新增「原始模型機率」欄位，可比較純模型 vs 加情緒效果",
                    "修復美股隔夜資料偶發 NaN（啟用 repair 模式）",
                ],
            },
            {
                "version": "v1.5.3",
                "date": "2026-04-10",
                "changes": [
                    "修復多筆記錄刪除無效的問題",
                ],
            },
            {
                "version": "v1.5.2",
                "date": "2026-04-10",
                "changes": [
                    "修復即時行情顯示 nan",
                    "修復 K 線圖缺少當日 K 棒",
                ],
            },
            {
                "version": "v1.5.1",
                "date": "2026-04-10",
                "changes": [
                    "修復預測記錄寫入遺失問題（強制落盤 + 防止背景執行緒覆蓋）",
                    "修復 yfinance 回傳 NaN 導致無法回填實際結果（啟用 repair 模式）",
                    "無法取得收盤價時顯示「⏳ 資料延遲」，下次啟動自動重試",
                    "新增完整寫入/回填日誌，方便追蹤問題",
                ],
            },
            {
                "version": "v1.5.0",
                "date": "2026-04-03",
                "changes": [
                    "新增成交量異常偵測（Z-score、爆量突破、量價背離、量能趨勢）",
                    "新增分市場狀態訓練（多頭/空頭/盤整各訓練專門模型，預測時混合）",
                    "預測特徵擴充 4 維，提升量能面辨識能力",
                    "SHAP 特徵解釋新增中文量能標籤",
                ],
            },
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
            result = check_for_update(manual=True)
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
        self.input_key.setText(config.get("openrouter_api_key", ""))
        self.input_brave_key.setText(config.get("brave_api_key", ""))
        current_model = config.get("openrouter_model", "") or DEFAULT_MODEL
        from data.model_catalog import menu_models
        self._populate_models(menu_models(), current_model)
        self._on_model_changed()

    def _on_save(self):
        key = self.input_key.text().strip()
        brave_key = self.input_brave_key.text().strip()
        model = self.combo_model.currentData()
        if not model:
            model = DEFAULT_MODEL
        save_config({
            "openrouter_api_key": key,
            "openrouter_model": model,
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

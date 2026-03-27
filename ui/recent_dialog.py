"""
本次查詢記錄視窗
顯示本次 session 內預測過的股票，可一鍵還原至主畫面
關閉程式後自動清除（資料存在記憶體，不寫檔）
"""
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor


class RecentDialog(QDialog):

    restore_requested = Signal(str)   # 發射 symbol

    def __init__(self, result_cache: dict, stock_dict: dict, parent=None):
        super().__init__(parent)
        self._cache = result_cache
        self._stock_dict = stock_dict
        self.setWindowTitle("🕐  本次查詢記錄")
        self.setMinimumWidth(820)
        self.setMinimumHeight(400)
        self.setModal(True)
        self._setup_ui()
        self._fill_table()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        # ── 表格 ──
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "", "股票", "方向", "上漲機率", "收盤價", "AI 情緒"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 100)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1A1A1A;
                alternate-background-color: #202020;
                color: #E0E6F0;
                border: 1px solid #3A3A3A;
                border-radius: 6px;
                gridline-color: #2A2A2A;
                font-size: 13px;
            }
            QHeaderView::section {
                background-color: #252525;
                color: #8A8A8A;
                border: none;
                border-bottom: 1px solid #3A3A3A;
                padding: 6px;
                font-size: 12px;
                font-weight: bold;
            }
            QTableWidget::item { padding: 4px 8px; }
            QTableWidget::item:hover { background-color: #252525; }
            QTableWidget::item:selected { background-color: transparent; color: inherit; }
            QTableWidget::item:focus { background-color: transparent; border: none; }
        """)
        layout.addWidget(self.table)

        # ── 警語 ──
        warning = QLabel("⚠  關閉程式時，本次查詢記錄將自動清除")
        warning.setStyleSheet(
            "color: #886600; font-size: 11px; padding: 6px 10px; "
            "background-color: #1A1500; border: 1px solid #443300; "
            "border-radius: 4px;"
        )
        layout.addWidget(warning)

        # ── 關閉按鈕 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton("關閉")
        btn_close.setFixedSize(80, 32)
        btn_close.clicked.connect(self.reject)
        btn_close.setStyleSheet(
            "background: #2A2A2A; color: #8A8A8A; "
            "border: 1px solid #3A3A3A; border-radius: 6px;"
        )
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _fill_table(self):
        if not self._cache:
            self.table.setRowCount(1)
            empty = QTableWidgetItem("尚無查詢記錄")
            empty.setForeground(QColor("#4A4A4A"))
            empty.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setSpan(0, 0, 1, 6)
            self.table.setItem(0, 0, empty)
            self.table.setRowHeight(0, 48)
            return

        # cache 是 {symbol: result}，最新預測的排最上面
        entries = list(self._cache.items())
        entries.reverse()
        self.table.setRowCount(len(entries))

        for row, (symbol, result) in enumerate(entries):
            self.table.setRowHeight(row, 42)
            pred       = result.get("prediction", {})
            price_info = result.get("price_info", {})
            sentiment  = result.get("sentiment", {})

            # ── 還原按鈕 ──
            btn = QPushButton("↩ 還原")
            btn.setFixedHeight(28)
            btn.setStyleSheet(
                "background: #2A2A2A; color: #00AACC; "
                "border: 1px solid #3A3A3A; border-radius: 4px; "
                "font-size: 12px; font-weight: bold;"
            )
            btn.clicked.connect(lambda _, s=symbol: self._on_restore(s))
            self.table.setCellWidget(row, 0, btn)

            # ── 股票代號 + 中文名稱 ──
            code = symbol.replace(".TW", "").replace(".TWO", "")
            name = self._stock_dict.get(symbol, "")
            display = f"{code}\n{name}" if name and name != symbol else code
            sym_item = QTableWidgetItem(display)
            sym_item.setForeground(QColor("#00CCFF"))
            sym_item.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
            sym_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, sym_item)
            if name and name != symbol:
                self.table.setRowHeight(row, 52)

            # ── 方向 ──
            is_up = pred.get("prediction") == 1
            dir_text = "🔴 上漲" if is_up else "🟢 下跌"
            dir_color = "#FF3355" if is_up else "#00CC66"
            dir_item = QTableWidgetItem(dir_text)
            dir_item.setForeground(QColor(dir_color))
            dir_item.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            dir_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, dir_item)

            # ── 上漲機率 ──
            up_prob = pred.get("up_prob", 0)
            prob_item = QTableWidgetItem(f"{up_prob:.1%}")
            prob_item.setForeground(QColor("#E0E6F0"))
            prob_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, prob_item)

            # ── 收盤價 ──
            price = price_info.get("price", "--")
            change_pct = price_info.get("change_pct", 0)
            price_color = "#FF3355" if change_pct >= 0 else "#00CC66"
            price_item = QTableWidgetItem(str(price))
            price_item.setForeground(QColor(price_color))
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, price_item)

            # ── AI 情緒 ──
            if sentiment.get("available"):
                score = sentiment.get("score", 0)
                if score >= 0.3:
                    sent_text = f"😊 樂觀  {score:+.2f}"
                    sent_color = "#FF3355"
                elif score <= -0.3:
                    sent_text = f"😞 悲觀  {score:+.2f}"
                    sent_color = "#00CC66"
                else:
                    sent_text = f"😐 中性  {score:+.2f}"
                    sent_color = "#FFCC44"
            else:
                sent_text = "—"
                sent_color = "#4A4A4A"
            sent_item = QTableWidgetItem(sent_text)
            sent_item.setForeground(QColor(sent_color))
            sent_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, sent_item)

    def _on_restore(self, symbol: str):
        self.restore_requested.emit(symbol)
        self.accept()

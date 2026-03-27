"""
預測記錄對話框
顯示歷史預測記錄、準確率統計，並可手動觸發回填
"""
import os
from datetime import date

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, QThreadPool, QRunnable, QObject, Signal
from PySide6.QtGui import QColor, QFont

from data.prediction_logger import PredictionLogger


# ── 背景回填 Worker ────────────────────────────────────────────────

class _BackfillSignals(QObject):
    finished = Signal(int)   # 回填筆數


class _BackfillWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = _BackfillSignals()
        self.setAutoDelete(True)

    def run(self):
        count = PredictionLogger.backfill_actuals()
        self.signals.finished.emit(count)


# ── Dialog ────────────────────────────────────────────────────────

class PredictionLogDialog(QDialog):
    """
    預測記錄彈出視窗

    ┌─────────────────────────────────────────────┐
    │  📊 預測記錄          [🔄 更新] [↓ 匯出] [✕]│
    ├─────────────────────────────────────────────┤
    │  日期 | 股票 | 預測 | 上漲機率 | 實際 | 漲跌%│
    │  ...                                        │
    ├─────────────────────────────────────────────┤
    │  整體準確率 65.0%（20筆）                    │
    │  0050.TW 70%  2330.TW 60% ...              │
    └─────────────────────────────────────────────┘
    """

    COLUMNS = [
        ("預測日期",  "prediction_date", 100),
        ("股票",      "symbol",          90),
        ("預測",      "predicted",       60),
        ("上漲機率",  "up_prob",         80),
        ("3日走勢",   "gpt_3day",        200),
        ("實際",      "actual",          60),
        ("漲跌%",     "actual_return",   70),
        ("正確",      "correct",         55),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 預測記錄")
        self.resize(900, 560)
        self.setMinimumSize(700, 400)
        self._setup_ui()
        self._load_table()

    # ── 建立 UI ───────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(8)

        # 頂部按鈕列
        top = QHBoxLayout()
        self.lbl_status = QLabel("💡 實際 / 漲跌% / 正確：預測目標日過後由「更新實際結果」自動回填")
        self.lbl_status.setStyleSheet("color: #4A6A8A; font-size: 11px;")
        top.addWidget(self.lbl_status, stretch=1)

        self.btn_delete = QPushButton("🗑  刪除選取")
        self.btn_delete.setFixedHeight(32)
        self.btn_delete.setEnabled(False)
        self.btn_delete.setToolTip("刪除所選的記錄列（可多選）")
        self.btn_delete.clicked.connect(self._on_delete)
        top.addWidget(self.btn_delete)

        self.btn_backfill = QPushButton("🔄  更新實際結果")
        self.btn_backfill.setFixedHeight(32)
        self.btn_backfill.clicked.connect(self._on_backfill)
        top.addWidget(self.btn_backfill)

        btn_trend = QPushButton("📈  趨勢圖")
        btn_trend.setFixedHeight(32)
        btn_trend.setToolTip("查看每週預測準確率趨勢圖")
        btn_trend.clicked.connect(self._on_trend)
        top.addWidget(btn_trend)

        btn_export = QPushButton("↓  匯出 CSV")
        btn_export.setFixedHeight(32)
        btn_export.clicked.connect(self._on_export)
        top.addWidget(btn_export)

        root.addLayout(top)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in self.COLUMNS])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        hdr = self.table.horizontalHeader()
        for col_idx, (_, _, width) in enumerate(self.COLUMNS):
            self.table.setColumnWidth(col_idx, width)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)   # 3日走勢欄自動延伸
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self.table, stretch=1)

        # 統計列
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1E3A5F;")
        root.addWidget(sep)

        self.lbl_stats = QLabel("讀取中...")
        self.lbl_stats.setStyleSheet("color: #7A9ABE; font-size: 12px; padding: 2px 0;")
        self.lbl_stats.setWordWrap(True)
        root.addWidget(self.lbl_stats)

    # ── 載入資料 ──────────────────────────────────────────────────

    def _load_table(self):
        rows = PredictionLogger.load_all()
        rows_rev = list(reversed(rows))   # 最新在最上面

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows_rev))

        GREEN  = QColor("#00CC66")   # 下跌色（台灣：下跌=綠）
        RED    = QColor("#FF3355")   # 上漲色（台灣：上漲=紅）
        GRAY   = QColor("#5A7A9A")
        total  = len(rows)   # 原始 CSV 總筆數

        for row_idx, (orig_idx, row) in enumerate(
            zip(reversed(range(total)), rows_rev)
        ):
            values = [
                row.get("prediction_date", ""),
                row.get("symbol", ""),
                row.get("predicted", ""),
                f"{float(row['up_prob']):.1%}" if row.get("up_prob") else "",
                row.get("gpt_3day", ""),
                row.get("actual", ""),
                f"{float(row['actual_return']):.2f}%" if row.get("actual_return") else "—",
                {"True": "✓", "False": "✗", "": "—"}.get(row.get("correct", ""), "—"),
            ]

            for col_idx, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col_idx == 0:
                    item.setData(Qt.ItemDataRole.UserRole, orig_idx)

                # 上色
                field = self.COLUMNS[col_idx][1]
                if field == "predicted":
                    # 台灣慣例：上漲=紅、下跌=綠
                    item.setForeground(RED if val == "up" else GREEN)
                elif field == "actual":
                    if val == "up":
                        item.setForeground(RED)
                    elif val == "down":
                        item.setForeground(GREEN)
                    else:
                        item.setForeground(GRAY)
                elif field == "actual_return" and row.get("actual_return"):
                    try:
                        v = float(row["actual_return"])
                        item.setForeground(RED if v > 0 else GREEN)
                    except ValueError:
                        pass
                elif field == "correct":
                    # ✓/✗ 是對錯，不是漲跌，保持綠=正確、紅=錯誤
                    if val == "✓":
                        item.setForeground(GREEN)
                    elif val == "✗":
                        item.setForeground(RED)
                    else:
                        item.setForeground(GRAY)

                self.table.setItem(row_idx, col_idx, item)

        self.table.setSortingEnabled(True)
        self._update_stats()

    def _update_stats(self):
        stats = PredictionLogger.get_stats()
        if stats["total"] == 0:
            self.lbl_stats.setText("尚無已評估的預測記錄")
            return

        parts = [f"整體準確率：{stats['accuracy']:.1%}（{stats['correct']}/{stats['total']} 筆）"]
        sym_parts = []
        for sym, sv in sorted(stats["by_symbol"].items()):
            sym_parts.append(f"{sym} {sv['accuracy']:.0%}（{sv['correct']}/{sv['total']}）")
        if sym_parts:
            parts.append("  |  ".join(sym_parts))
        self.lbl_stats.setText("    ".join(parts))

    # ── 事件處理 ──────────────────────────────────────────────────

    def _on_selection_changed(self):
        self.btn_delete.setEnabled(bool(self.table.selectedItems()))

    def _on_delete(self):
        selected_rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not selected_rows:
            return

        # 取得每列的原始 CSV index（存在 col 0 的 UserRole）
        orig_indices = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item is not None:
                orig_indices.append(item.data(Qt.ItemDataRole.UserRole))

        count = len(orig_indices)
        reply = QMessageBox.question(
            self, "確認刪除",
            f"確定要刪除選取的 {count} 筆記錄嗎？\n此操作無法復原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        PredictionLogger.delete_rows(orig_indices)
        self.lbl_status.setText(f"已刪除 {count} 筆記錄")
        self._load_table()

    def _on_backfill(self):
        self.btn_backfill.setEnabled(False)
        self.lbl_status.setText("⏳ 正在更新實際結果...")

        worker = _BackfillWorker()
        worker.signals.finished.connect(self._on_backfill_done)
        QThreadPool.globalInstance().start(worker)

    def _on_backfill_done(self, count: int):
        self.btn_backfill.setEnabled(True)
        if count > 0:
            self.lbl_status.setText(f"✅ 已更新 {count} 筆實際結果")
            self._load_table()
        else:
            self.lbl_status.setText("✅ 已是最新，所有可回填記錄均已更新")

    def _on_trend(self):
        from ui.accuracy_trend_dialog import AccuracyTrendDialog
        dlg = AccuracyTrendDialog(self)
        dlg.exec()

    def _on_export(self):
        from data.prediction_logger import LOG_PATH
        if not os.path.exists(LOG_PATH):
            self.lbl_status.setText("尚無記錄可匯出")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "匯出預測記錄",
            f"prediction_log_{date.today().isoformat()}.csv",
            "CSV (*.csv)"
        )
        if dest:
            import shutil
            shutil.copy(LOG_PATH, dest)
            self.lbl_status.setText(f"已匯出：{dest}")

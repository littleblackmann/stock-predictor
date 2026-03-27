"""
自選股列
橫向 chips 列，支援新增/刪除/點擊觸發預測
資料儲存於 watchlist.json
"""
import json
import os

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, Signal

from data.data_paths import WATCHLIST_PATH


class WatchlistBar(QWidget):
    """
    自選股列

    ┌──────────────────────────────────────────────────────┐
    │ ★ 自選股  [0050.TW ✕] [2330.TW ✕] [00878.TW ✕] …  │
    └──────────────────────────────────────────────────────┘

    Signals:
        symbol_clicked(str): 使用者點擊某個自選股 chip
    """

    symbol_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._symbols: list[str] = []
        self._setup_ui()
        self._load()

    # ── 初始化 ────────────────────────────────────────────

    def _setup_ui(self):
        self.setFixedHeight(44)
        self.setObjectName("watchlistBar")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 0, 14, 0)
        outer.setSpacing(10)

        lbl = QLabel("★ 自選股")
        lbl.setObjectName("watchlistTitle")
        lbl.setFixedWidth(60)
        outer.addWidget(lbl)

        # 可橫向捲動的 chips 區域
        self._scroll = QScrollArea()
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFixedHeight(40)
        self._scroll.setObjectName("watchlistScroll")
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._chips_widget = QWidget()
        self._chips_widget.setObjectName("chipsContainer")
        self._chips_layout = QHBoxLayout(self._chips_widget)
        self._chips_layout.setContentsMargins(2, 4, 2, 4)
        self._chips_layout.setSpacing(6)
        self._chips_layout.addStretch()

        self._scroll.setWidget(self._chips_widget)
        outer.addWidget(self._scroll, stretch=1)

    # ── 資料讀寫 ──────────────────────────────────────────

    def _load(self):
        path = os.path.normpath(WATCHLIST_PATH)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._symbols = json.load(f).get("symbols", [])
            except Exception:
                self._symbols = []
        self._rebuild_chips()

    def _save(self):
        path = os.path.normpath(WATCHLIST_PATH)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"symbols": self._symbols}, f, ensure_ascii=False, indent=2)

    # ── 公開 API ──────────────────────────────────────────

    def add_symbol(self, symbol: str):
        """加入自選股（重複忽略）"""
        symbol = symbol.strip().upper()
        if symbol and symbol not in self._symbols:
            self._symbols.append(symbol)
            self._save()
            self._rebuild_chips()

    def remove_symbol(self, symbol: str):
        """刪除自選股"""
        if symbol in self._symbols:
            self._symbols.remove(symbol)
            self._save()
            self._rebuild_chips()

    def get_symbols(self) -> list[str]:
        return list(self._symbols)

    # ── 內部：重建 chips ──────────────────────────────────

    def _rebuild_chips(self):
        # 清空所有 widget
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for symbol in self._symbols:
            self._chips_layout.addWidget(self._make_chip(symbol))

        self._chips_layout.addStretch()

    def _make_chip(self, symbol: str) -> QWidget:
        chip = QWidget()
        chip.setObjectName("watchlistChip")
        chip.setFixedHeight(30)

        layout = QHBoxLayout(chip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        btn_sym = QPushButton(symbol)
        btn_sym.setObjectName("chipSymbol")
        btn_sym.setFixedHeight(28)
        btn_sym.clicked.connect(lambda _checked, s=symbol: self.symbol_clicked.emit(s))
        layout.addWidget(btn_sym)

        btn_del = QPushButton("✕")
        btn_del.setObjectName("chipDelete")
        btn_del.setFixedSize(22, 28)
        btn_del.setToolTip(f"從自選股移除 {symbol}")
        btn_del.clicked.connect(lambda _checked, s=symbol: self.remove_symbol(s))
        layout.addWidget(btn_del)

        return chip

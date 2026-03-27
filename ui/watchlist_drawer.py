"""
自選股側邊抽屜
點擊左上角按鈕從左側滑入，卡片式清單顯示自選股
點卡片 → 填入主輸入框（不自動預測）
底部可新增股票
"""
import json
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect
from PySide6.QtGui import QPainter, QColor

from ui.smart_line_edit import SmartLineEdit

from data.data_paths import WATCHLIST_PATH


# ── 半透明遮罩 ─────────────────────────────────────────────────────

class _Backdrop(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hide()

    def mousePressEvent(self, event):
        self.clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))


# ── 主抽屜 ────────────────────────────────────────────────────────

class WatchlistDrawer(QWidget):
    """
    自選股側邊抽屜

    開啟：從左側滑入，遮罩出現在右側
    關閉：滑回左側消失，點遮罩或 ✕ 均可關閉
    行為：點卡片 → 發射 symbol_selected，自動關閉
    """

    symbol_selected = Signal(str)

    DRAWER_WIDTH  = 280
    ANIM_MS       = 220

    def __init__(self, stock_dict: dict, parent=None, y_offset: int = 0):
        super().__init__(parent)
        self._stock_dict = stock_dict
        self._symbols: list[str] = []
        self._signals: dict[str, list[str]] = {}
        self._is_open = False
        self._anim    = None
        self._y_off   = y_offset   # 抽屜起始 Y（控制列高度，避免蓋住按鈕）

        # 遮罩是 parent 的直接子元件（和 drawer 同層）
        self._backdrop = _Backdrop(parent)
        self._backdrop.clicked.connect(self.close_drawer)

        self._load()
        self._setup_ui()
        self.hide()

    # ── 初始化 UI ────────────────────────────────────────────────

    def _setup_ui(self):
        self.setObjectName("watchlistDrawer")
        self.setFixedWidth(self.DRAWER_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_scroll_area(), stretch=1)
        root.addWidget(self._build_add_section())

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("drawerHeader")
        header.setFixedHeight(52)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 12, 0)

        title = QLabel("★  自選股")
        title.setObjectName("drawerTitle")
        layout.addWidget(title, stretch=1)

        btn_close = QPushButton("✕")
        btn_close.setObjectName("drawerClose")
        btn_close.setFixedSize(30, 30)
        btn_close.clicked.connect(self.close_drawer)
        layout.addWidget(btn_close)

        return header

    def _build_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("drawerScroll")

        self._cards_widget = QWidget()
        self._cards_widget.setObjectName("drawerCardsContainer")
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(10, 10, 10, 10)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_widget)
        return scroll

    def _build_add_section(self) -> QWidget:
        container = QWidget()
        container.setObjectName("drawerAddSection")
        container.setFixedHeight(58)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._add_input = SmartLineEdit(self._stock_dict)
        self._add_input.setPlaceholderText("輸入代號或名稱新增...")
        self._add_input.setFixedHeight(34)
        layout.addWidget(self._add_input, stretch=1)

        btn_add = QPushButton("＋")
        btn_add.setObjectName("drawerAddBtn")
        btn_add.setFixedSize(34, 34)
        btn_add.clicked.connect(self._on_add)
        layout.addWidget(btn_add)

        self._add_input.returnPressed.connect(self._on_add)
        return container

    # ── 卡片 ─────────────────────────────────────────────────────

    def _build_cards(self):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._symbols:
            empty = QLabel("尚無自選股\n\n在下方輸入代號新增")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                "color: #2A4A6A; font-size: 12px; padding: 30px 0;"
            )
            self._cards_layout.addWidget(empty)
        else:
            for symbol in self._symbols:
                self._cards_layout.addWidget(self._make_card(symbol))

        self._cards_layout.addStretch()

    def _make_card(self, symbol: str) -> QFrame:
        name = self._stock_dict.get(symbol, symbol)
        code = symbol.replace(".TW", "").replace(".TWO", "")

        sigs = self._signals.get(symbol, [])
        card_h = 72 if len(sigs) >= 2 else 60

        card = QFrame()
        card.setObjectName("drawerCard")
        card.setFixedHeight(card_h)
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 6, 10, 6)
        layout.setSpacing(0)

        # 左側：代碼 + 名稱
        info = QVBoxLayout()
        info.setSpacing(3)

        lbl_code = QLabel(code)
        lbl_code.setObjectName("cardCode")

        lbl_name = QLabel(name)
        lbl_name.setObjectName("cardName")

        info.addWidget(lbl_code)
        info.addWidget(lbl_name)
        layout.addLayout(info, stretch=1)

        # 訊號標籤（若有）
        if sigs:
            sig_col = QVBoxLayout()
            sig_col.setSpacing(2)
            sig_col.setContentsMargins(0, 0, 0, 0)
            for sig_text in sigs[:2]:   # 最多顯示 2 個
                lbl_sig = QLabel(sig_text)
                lbl_sig.setObjectName("signalBadge")
                sig_col.addWidget(lbl_sig)
            layout.addLayout(sig_col)

        # 刪除按鈕
        btn_del = QPushButton("✕")
        btn_del.setObjectName("cardDelete")
        btn_del.setFixedSize(22, 22)
        btn_del.setCursor(Qt.CursorShape.ArrowCursor)
        btn_del.clicked.connect(lambda _, s=symbol: self._on_delete(s))
        layout.addWidget(btn_del)

        # 點卡片主體 → 選擇（刪除按鈕自己消費 event，不會觸發這裡）
        card.mousePressEvent = lambda _e, s=symbol: self._on_card_clicked(s)

        return card

    # ── 資料操作 ─────────────────────────────────────────────────

    def _load(self):
        if os.path.exists(WATCHLIST_PATH):
            try:
                with open(WATCHLIST_PATH, encoding="utf-8") as f:
                    self._symbols = json.load(f).get("symbols", [])
            except Exception:
                self._symbols = []

    def _save(self):
        with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
            json.dump({"symbols": self._symbols}, f, ensure_ascii=False, indent=2)

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    def update_signals(self, signals: dict[str, list[str]]):
        """背景掃描完成後更新訊號，若抽屜開啟中則重繪卡片"""
        self._signals = signals
        if self._is_open:
            self._build_cards()

    def add_symbol(self, symbol: str):
        symbol = symbol.strip().upper()
        if symbol and symbol not in self._symbols:
            self._symbols.append(symbol)
            self._save()
            if self._is_open:
                self._build_cards()

    def _on_add(self):
        symbol = self._add_input.text().strip().upper()
        if symbol:
            self.add_symbol(symbol)
            self._add_input.clear()

    def _on_delete(self, symbol: str):
        if symbol in self._symbols:
            self._symbols.remove(symbol)
            self._save()
            self._build_cards()

    def _on_card_clicked(self, symbol: str):
        self.symbol_selected.emit(symbol)
        self.close_drawer()

    # ── 開關動畫 ─────────────────────────────────────────────────

    def open_drawer(self, prefill: str = ""):
        """開啟抽屜，可選擇預填新增輸入框"""
        # 若有舊動畫正在執行（例如關閉動畫未跑完）先停止並切斷 callback
        # 避免關閉動畫的 finished → hide() 在開啟後觸發，造成抽屜跑到視窗外
        if self._anim is not None:
            self._anim.stop()
            try:
                self._anim.finished.disconnect()
            except RuntimeError:
                pass
            self._anim = None
        self._is_open = False   # 重置，讓後面的開啟邏輯正常執行

        parent = self.parent()
        ph = parent.height() if parent else 700
        pw = parent.width()  if parent else 1100
        w  = self.DRAWER_WIDTH
        y  = self._y_off
        h  = ph - y   # 抽屜高度：從控制列底部到視窗底部

        # 遮罩：從控制列底部開始，蓋住抽屜右側區域
        self._backdrop.setGeometry(w, y, pw - w, h)
        self._backdrop.show()
        self._backdrop.raise_()

        self.setGeometry(-w, y, w, h)
        self.show()
        self.raise_()
        self._build_cards()

        self._is_open = True

        anim = QPropertyAnimation(self, b"geometry")
        anim.setDuration(self.ANIM_MS)
        anim.setStartValue(QRect(-w, y, w, h))
        anim.setEndValue(QRect(0, y, w, h))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # prefill 在動畫完成後才設定：
        # 動畫進行中 drawer 在 x=-280 ~ 0，此時 mapToGlobal 座標會算錯
        # 等 drawer 完全滑到 x=0 再設文字，popup 位置才正確
        if prefill:
            anim.finished.connect(lambda: self._add_input.setText(prefill))

        self._anim = anim
        anim.start()

    def close_drawer(self):
        if not self._is_open:
            return
        self._is_open = False
        self._backdrop.hide()
        self._add_input.clear()

        w  = self.DRAWER_WIDTH
        y  = self._y_off
        ph = self.parent().height() if self.parent() else 700
        h  = ph - y

        anim = QPropertyAnimation(self, b"geometry")
        anim.setDuration(self.ANIM_MS)
        anim.setStartValue(QRect(0, y, w, h))
        anim.setEndValue(QRect(-w, y, w, h))
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        # 只有在真的沒有被重新開啟的情況下才 hide
        anim.finished.connect(lambda: self.hide() if not self._is_open else None)
        self._anim = anim
        anim.start()

    def update_size(self, pw: int, ph: int):
        """視窗 resize 時更新幾何"""
        w = self.DRAWER_WIDTH
        y = self._y_off
        h = ph - y
        self._backdrop.setGeometry(w, y, pw - w, h)
        if self._is_open:
            self.setGeometry(0, y, w, h)

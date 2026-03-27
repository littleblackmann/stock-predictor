"""
SmartLineEdit
帶有股票代碼自動完成下拉選單的輸入框
輸入字元時自動彈出，支援代碼與中文名稱搜尋
"""
from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QApplication
from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QFont


class SmartLineEdit(QLineEdit):
    """
    股票代碼智慧輸入框

    行為：
    - 輸入 1 個字元起即觸發搜尋，同時比對代碼與中文名稱
    - ↑↓ 方向鍵瀏覽，Enter 確認，Esc 關閉，點擊選擇
    - Popup 跟隨主視窗移動（eventFilter 監聽頂層視窗 Move/Resize）
    - Popup 位置驗證：若算出的螢幕座標在主視窗範圍外則不顯示
    """

    def __init__(self, stock_dict: dict[str, str], parent=None):
        super().__init__(parent)
        self._stock_dict = stock_dict
        self._popup = self._build_popup()
        self._tracked_window = None   # 目前監聽 Move/Resize 的頂層視窗
        self.textChanged.connect(self._on_text_changed)

    # ── 建立 popup ────────────────────────────────

    def _build_popup(self) -> QListWidget:
        popup = QListWidget()
        popup.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        popup.setObjectName("stockDropdown")
        popup.setMouseTracking(True)
        popup.itemClicked.connect(self._select_item)
        popup.setFont(QFont("Microsoft JhengHei", 12))
        return popup

    # ── 頂層視窗事件監聽（主視窗移動/縮放時隱藏 popup）─────

    def showEvent(self, event):
        super().showEvent(event)
        self._attach_window_filter()

    def _attach_window_filter(self):
        """在頂層視窗安裝事件過濾器，以便在主視窗移動時隱藏 popup"""
        top = self.window()
        if top and top is not self._tracked_window:
            if self._tracked_window:
                self._tracked_window.removeEventFilter(self)
            self._tracked_window = top
            top.installEventFilter(self)

    def eventFilter(self, obj, event):
        """主視窗 Move 或 Resize 時，立即隱藏 popup，避免位置殘留"""
        if obj is self._tracked_window and event.type() in (
            QEvent.Type.Move,
            QEvent.Type.Resize,
        ):
            self._popup.hide()
        return super().eventFilter(obj, event)

    # ── 文字變化 ──────────────────────────────────

    def _on_text_changed(self, text: str):
        text = text.strip()

        # Widget 尚未可見時不顯示 popup
        # （例如 drawer 在動畫前就設了 prefill 文字）
        if not text or not self.isVisible():
            self._popup.hide()
            return

        query = text.upper()
        matches = [
            (sym, name)
            for sym, name in self._stock_dict.items()
            if query in sym.upper() or query in name
        ][:14]

        if not matches:
            self._popup.hide()
            return

        self._popup.clear()
        for sym, name in matches:
            item = QListWidgetItem(f"  {sym}    {name}")
            item.setData(Qt.ItemDataRole.UserRole, sym)
            self._popup.addItem(item)

        self._reposition_popup(len(matches))

    def _reposition_popup(self, item_count: int):
        row_h   = max(self._popup.sizeHintForRow(0), 30)
        total_h = min(item_count * row_h + 6, 360)
        popup_w = max(self.width() + 60, 300)

        bottom_left = self.mapToGlobal(self.rect().bottomLeft())
        top_left    = self.mapToGlobal(self.rect().topLeft())

        # ── 位置驗證：計算出的座標必須在頂層視窗範圍內 ──────
        # 若 drawer 還在動畫中（x=-280），global 座標會跑到視窗左側外
        # 這時直接隱藏 popup，不顯示在錯誤位置
        top_window = self.window()
        if top_window:
            win_geo = top_window.frameGeometry()
            if (bottom_left.x() < win_geo.left() - 10 or
                    bottom_left.x() > win_geo.right()):
                self._popup.hide()
                return

        # ── 螢幕底部邊界：超出時改向上彈出 ─────────────────
        screen = QApplication.screenAt(bottom_left)
        if screen is None:
            screen = QApplication.primaryScreen()
        screen_bottom = screen.availableGeometry().bottom()

        if bottom_left.y() + total_h > screen_bottom:
            pos = top_left
            pos.setY(top_left.y() - total_h)
        else:
            pos = bottom_left

        self._popup.move(pos)
        self._popup.setFixedWidth(popup_w)
        self._popup.setFixedHeight(total_h)
        self._popup.show()

    # ── 選擇項目 ──────────────────────────────────

    def _select_item(self, item: QListWidgetItem):
        sym = item.data(Qt.ItemDataRole.UserRole)
        self.blockSignals(True)
        self.setText(sym)
        self.blockSignals(False)
        self._popup.hide()
        self.setFocus()

    # ── 鍵盤事件 ──────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        if self._popup.isVisible():
            if key == Qt.Key.Key_Down:
                self._popup.setCurrentRow(
                    min(self._popup.currentRow() + 1, self._popup.count() - 1)
                )
                return
            elif key == Qt.Key.Key_Up:
                self._popup.setCurrentRow(
                    max(self._popup.currentRow() - 1, 0)
                )
                return
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self._popup.currentItem()
                if item:
                    self._select_item(item)
                    return
            elif key == Qt.Key.Key_Escape:
                self._popup.hide()
                return
        super().keyPressEvent(event)

    # ── 焦點 / 隱藏事件 ───────────────────────────

    def focusOutEvent(self, event):
        QTimer.singleShot(200, self._popup.hide)
        super().focusOutEvent(event)

    def hideEvent(self, event):
        self._popup.hide()
        super().hideEvent(event)

    def moveEvent(self, event):
        if self._popup.isVisible():
            self._reposition_popup(self._popup.count())
        super().moveEvent(event)

"""
啟動畫面（Splash Screen）
顯示於主視窗載入完成之前，呈現旋轉動畫與目前初始化進度
"""
from pathlib import Path
from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient, QBrush, QPixmap


class SplashScreen(QWidget):
    """
    自訂啟動畫面
    - 漸層旋轉 spinner（頭亮尾暗，iOS 風格）
    - 底部進度條（隨載入步驟推進）
    - 即時更新狀態文字
    - 首次啟動時顯示警語
    """

    WIDTH        = 500
    HEIGHT       = 400
    TOTAL_STEPS  = 8   # 對應 main.py 中 set_status() 的呼叫次數

    # 主題色
    BG_COLOR      = QColor("#141414")
    BORDER_COLOR  = QColor("#2a2a2a")
    ACCENT_COLOR  = QColor("#00d4ff")
    TRACK_COLOR   = QColor("#252525")
    TITLE_COLOR   = QColor("#ffffff")
    SUB_COLOR     = QColor("#666666")
    STATUS_COLOR  = QColor("#888888")
    WARNING_COLOR = QColor("#f39c12")
    BAR_BG_COLOR  = QColor("#1e1e1e")

    def __init__(self, is_first_run: bool = False):
        super().__init__()
        self._angle        = 0
        self._status       = "初始化中..."
        self._step         = 0
        self._is_first_run = is_first_run

        # 載入 logo（放在 spinner 上方，自動去除白色背景）
        logo_path = Path(__file__).parent.parent / "app_logo.png"
        self._logo_pixmap = self._load_logo(logo_path)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.SplashScreen
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self._center_on_screen()

        # 旋轉動畫計時器（50fps）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(20)

    # ── 靜態工具 ──────────────────────────────────────────────────

    @staticmethod
    def _load_logo(path: Path) -> QPixmap:
        """載入 logo（已是 RGBA 透明背景 PNG，直接縮放即可）"""
        if not path.exists():
            return QPixmap()

        pxm = QPixmap(str(path))
        if pxm.isNull():
            return QPixmap()

        return pxm.scaled(
            120, 120,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    # ── 公開 API ──────────────────────────────────────────────────

    def set_status(self, text: str) -> None:
        """更新狀態文字並推進進度條一格"""
        self._step   = min(self._step + 1, self.TOTAL_STEPS)
        self._status = text
        self.update()
        QApplication.processEvents()

    # ── 私有方法 ──────────────────────────────────────────────────

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width()  - self.WIDTH)  // 2,
            (screen.height() - self.HEIGHT) // 2,
        )

    def _tick(self) -> None:
        self._angle = (self._angle + 6) % 360
        self.update()

    # ── 繪製 ─────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.WIDTH, self.HEIGHT

        # ── 背景 ──
        painter.fillRect(self.rect(), self.BG_COLOR)

        # ── 外框 ──
        pen = QPen(self.BORDER_COLOR)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        cx = w // 2

        # ── Logo（上方，已在 __init__ 縮好並去背）──
        logo_top = 22
        if not self._logo_pixmap.isNull():
            lx = cx - self._logo_pixmap.width()  // 2
            ly = logo_top
            painter.drawPixmap(lx, ly, self._logo_pixmap)

        # ── Spinner（logo 下方）──
        logo_h = self._logo_pixmap.height() if not self._logo_pixmap.isNull() else 80
        cy   = logo_top + logo_h + 20 + 36   # logo底 + 間距 + 半徑
        r    = 36
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)

        # 底圓（軌道）
        pen = QPen(self.TRACK_COLOR)
        pen.setWidth(5)
        painter.setPen(pen)
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # 漸層弧線（iOS 風格：頭亮尾暗）
        self._draw_gradient_arc(painter, rect)

        # ── 標題 ──
        painter.setPen(self.TITLE_COLOR)
        font = QFont("Microsoft JhengHei", 17, QFont.Weight.Bold)
        painter.setFont(font)
        title_y = cy + r + 16
        painter.drawText(
            0, title_y, w, 30,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "小黑股票預測系統"
        )

        # ── 副標題 ──
        painter.setPen(self.SUB_COLOR)
        font = QFont("Microsoft JhengHei", 9)
        painter.setFont(font)
        painter.drawText(
            0, title_y + 28, w, 20,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "台股 AI 預測分析"
        )

        # ── 狀態文字 ──
        painter.setPen(self.STATUS_COLOR)
        font = QFont("Microsoft JhengHei", 8)
        painter.setFont(font)
        painter.drawText(
            0, title_y + 50, w, 18,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self._status
        )

        # ── 首次啟動警語 ──
        if self._is_first_run:
            painter.setPen(self.WARNING_COLOR)
            font = QFont("Microsoft JhengHei", 8)
            painter.setFont(font)
            painter.drawText(
                0, title_y + 70, w, 18,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                "⚠  首次啟動需要較長時間，請耐心等候"
            )

        # ── 底部進度條 ──
        self._draw_progress_bar(painter, w, h)

    def _draw_gradient_arc(self, painter: QPainter, rect: QRectF) -> None:
        """
        繪製漸層旋轉弧線
        頭部：#00d4ff 全亮，尾部：透明
        分成 NUM_SEG 段，從尾到頭逐漸增加不透明度
        """
        NUM_SEG   = 28          # 分段數（越多越順滑）
        ARC_SPAN  = 260         # 弧線總角度
        seg_span  = ARC_SPAN / NUM_SEG

        # 弧線頭部角度（Qt 座標：0=3點鐘，正值=逆時針）
        # 頭在 -self._angle，尾在 -self._angle - ARC_SPAN
        head_angle = -self._angle

        for i in range(NUM_SEG):
            # i=0 為尾端（透明），i=NUM_SEG-1 為頭端（全亮）
            alpha   = int(255 * (i + 1) / NUM_SEG)
            r_v, g_v, b_v = 0, 212, 255
            color   = QColor(r_v, g_v, b_v, alpha)

            pen = QPen(color)
            pen.setWidth(5)
            # 只對最後一段（頭部）加圓頭，其餘用平頭避免接縫
            pen.setCapStyle(
                Qt.PenCapStyle.RoundCap if i == NUM_SEG - 1
                else Qt.PenCapStyle.FlatCap
            )
            painter.setPen(pen)

            # 這一段的起始角度（從尾往頭方向計算）
            seg_start = head_angle - ARC_SPAN + i * seg_span
            painter.drawArc(rect, int(seg_start * 16), int(seg_span * 16))

    def _draw_progress_bar(self, painter: QPainter, w: int, h: int) -> None:
        """
        繪製底部進度條
        - 背景：深灰細線
        - 進度：#00d4ff 漸層，隨步驟推進
        """
        bar_h      = 3
        bar_y      = h - bar_h
        bar_margin = 0   # 貼齊左右邊框

        # 進度計算（0.0 ~ 1.0）
        progress = self._step / self.TOTAL_STEPS

        # 背景條
        painter.fillRect(bar_margin, bar_y, w - bar_margin * 2, bar_h, self.BAR_BG_COLOR)

        # 進度條（漸層）
        fill_w = int((w - bar_margin * 2) * progress)
        if fill_w > 0:
            grad = QLinearGradient(
                QPointF(bar_margin, 0),
                QPointF(bar_margin + fill_w, 0)
            )
            grad.setColorAt(0.0, QColor("#0077aa"))   # 左：深藍
            grad.setColorAt(1.0, QColor("#00d4ff"))   # 右：亮藍（頭部最亮）
            painter.fillRect(bar_margin, bar_y, fill_w, bar_h, QBrush(grad))

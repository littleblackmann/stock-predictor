"""
右側預測結果面板
顯示預測機率、信心度進度條、指標說明、SHAP 解析（條形圖）
"""
import re

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QProgressBar, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QPainter, QColor, QBrush, QPen
from logger.app_logger import get_logger

logger = get_logger(__name__)


class ShapBarWidget(QWidget):
    """SHAP 特徵重要性水平條形圖"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, float]] = []  # [(label, value), ...]
        self.setMinimumHeight(30)

    def set_data(self, items: list[tuple[str, float]]):
        self._items = items
        # 每項 28px 高 + 8px padding
        self.setFixedHeight(max(30, len(items) * 28 + 8))
        self.update()

    def paintEvent(self, event):
        if not self._items:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        max_abs = max(abs(v) for _, v in self._items) if self._items else 1
        if max_abs == 0:
            max_abs = 1

        bar_h = 16
        row_h = 28
        label_w = int(w * 0.42)
        bar_area_w = w - label_w - 50  # 50 for value text
        y = 4

        for label, value in self._items:
            # Label text
            painter.setPen(QColor("#A0B0C0"))
            painter.setFont(QFont("Microsoft JhengHei", 9))
            painter.drawText(4, y, label_w - 8, row_h, Qt.AlignmentFlag.AlignVCenter, label)

            # Bar
            bar_x = label_w
            bar_ratio = abs(value) / max_abs
            bar_w = max(3, int(bar_area_w * bar_ratio))

            if value > 0:
                color = QColor("#FF335580")
                border = QColor("#FF3355")
            else:
                color = QColor("#00CC6680")
                border = QColor("#00CC66")

            painter.setBrush(QBrush(color))
            painter.setPen(QPen(border, 1))
            painter.drawRoundedRect(bar_x, y + (row_h - bar_h) // 2, bar_w, bar_h, 3, 3)

            # Value text
            painter.setPen(border)
            painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            txt = f"{value:+.3f}"
            painter.drawText(
                bar_x + bar_w + 6, y, 44, row_h,
                Qt.AlignmentFlag.AlignVCenter, txt
            )

            y += row_h

        painter.end()


class ConfidenceBar(QWidget):
    """信心等級視覺化進度條"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(42)
        self._level = ""
        self._note = ""
        self._value = 0.0  # 0~1

    def set_confidence(self, level: str, note: str, conviction: float):
        self._level = level
        self._note = note
        # conviction: 距離 50% 的幅度，映射到 0~1 範圍
        self._value = min(1.0, max(0.0, conviction / 15.0))
        self.update()

    def paintEvent(self, event):
        if not self._level:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Color by level
        colors = {
            "high":   (QColor("#00CC66"), QColor("#003322"), "✅"),
            "medium": (QColor("#FFCC44"), QColor("#332200"), "🔶"),
            "low":    (QColor("#FFAA44"), QColor("#332200"), "⚠️"),
        }
        fg_color, bg_color, emoji = colors.get(self._level, (QColor("#7A9ABE"), QColor("#1A2A3A"), ""))

        # Background bar
        bar_y = 4
        bar_h = 14
        painter.setBrush(QBrush(QColor("#252525")))
        painter.setPen(QPen(QColor("#3A3A3A"), 1))
        painter.drawRoundedRect(0, bar_y, w, bar_h, 7, 7)

        # Filled portion
        fill_w = max(4, int(w * self._value))
        painter.setBrush(QBrush(fg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, bar_y, fill_w, bar_h, 7, 7)

        # Text below
        painter.setPen(fg_color)
        painter.setFont(QFont("Microsoft JhengHei", 10, QFont.Weight.Bold))
        painter.drawText(0, bar_y + bar_h + 2, w, h - bar_h - 6,
                         Qt.AlignmentFlag.AlignCenter, f"{emoji} {self._note}")

        painter.end()


class PredictionPanel(QWidget):
    """
    右側預測結果面板，包含：
    - 大型漲跌預測文字
    - 上漲/下跌雙進度條
    - 信心等級進度條
    - 模型效能指標
    - SHAP 特徵條形圖
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("predictionPanel")
        self.setMinimumWidth(320)
        self._setup_ui()
        self.reset()
        logger.info("PredictionPanel 初始化完成")

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 10)
        main_layout.setSpacing(10)

        # ── 股票代號 + 最新價格 ──
        self.label_symbol = self._make_section_title("📊 即時行情")
        main_layout.addWidget(self.label_symbol)

        self.label_price = QLabel("--")
        self.label_price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_price.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        self.label_price.setStyleSheet("color: #E0E6F0; padding: 4px 0;")
        main_layout.addWidget(self.label_price)

        self.label_change = QLabel("--")
        self.label_change.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_change.setStyleSheet("color: #7A9ABE; font-size: 16px;")
        main_layout.addWidget(self.label_change)

        main_layout.addWidget(self._make_hline())

        # ── 明日預測主標題 ──
        main_layout.addWidget(self._make_section_title("🤖 明日預測"))

        self.label_prediction = QLabel("等待預測...")
        self.label_prediction.setObjectName("labelPrediction")
        self.label_prediction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_prediction.setWordWrap(True)
        main_layout.addWidget(self.label_prediction)

        # ── 上漲進度條 ──
        up_row = QHBoxLayout()
        lbl_up = QLabel("🔴 上漲")
        lbl_up.setStyleSheet("color: #FF3355; font-size: 14px; min-width: 55px;")
        self.bar_up = QProgressBar()
        self.bar_up.setRange(0, 100)
        self.bar_up.setValue(0)
        self.bar_up.setFormat("%p%")
        self.bar_up.setStyleSheet("""
            QProgressBar { border: 1px solid #3A3A3A; border-radius: 5px;
                           background: #252525; color: #E0E6F0; font-size: 11px; height: 18px; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #551122, stop:1 #FF3355); border-radius: 4px; }
        """)
        up_row.addWidget(lbl_up)
        up_row.addWidget(self.bar_up)
        main_layout.addLayout(up_row)

        # ── 下跌進度條 ──
        down_row = QHBoxLayout()
        lbl_down = QLabel("🟢 下跌")
        lbl_down.setStyleSheet("color: #00CC66; font-size: 14px; min-width: 55px;")
        self.bar_down = QProgressBar()
        self.bar_down.setRange(0, 100)
        self.bar_down.setValue(0)
        self.bar_down.setFormat("%p%")
        self.bar_down.setStyleSheet("""
            QProgressBar { border: 1px solid #3A3A3A; border-radius: 5px;
                           background: #252525; color: #E0E6F0; font-size: 11px; height: 18px; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #003322, stop:1 #00CC66); border-radius: 4px; }
        """)
        down_row.addWidget(lbl_down)
        down_row.addWidget(self.bar_down)
        main_layout.addLayout(down_row)

        # ── 信心等級進度條 ──
        self.confidence_bar = ConfidenceBar()
        self.confidence_bar.setVisible(False)
        main_layout.addWidget(self.confidence_bar)

        main_layout.addWidget(self._make_hline())

        # ── 模型效能 ──
        main_layout.addWidget(self._make_section_title("📈 模型效能（回測）"))

        self.label_metrics = QLabel("尚未訓練")
        self.label_metrics.setObjectName("labelMetrics")
        self.label_metrics.setWordWrap(True)
        self.label_metrics.setAlignment(Qt.AlignmentFlag.AlignTop)
        main_layout.addWidget(self.label_metrics)

        main_layout.addWidget(self._make_hline())

        # ── SHAP 特徵解析（條形圖 + 文字備份）──
        main_layout.addWidget(self._make_section_title("🔍 主要驅動因子"))

        self.shap_bar = ShapBarWidget()
        main_layout.addWidget(self.shap_bar)

        self.label_explain = QLabel("--")
        self.label_explain.setObjectName("labelExplain")
        self.label_explain.setWordWrap(True)
        self.label_explain.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.label_explain.setContentsMargins(4, 4, 4, 4)
        self.label_explain.setVisible(False)  # 預設隱藏文字版
        main_layout.addWidget(self.label_explain)

        main_layout.addWidget(self._make_hline())

        # ── 3日走勢卡片 ──
        main_layout.addWidget(self._make_section_title("📅 未來 3 日走勢（AI 推估）"))

        self.forecast_cards = []
        for i in range(3):
            card = self._make_forecast_card()
            main_layout.addWidget(card["widget"])
            self.forecast_cards.append(card)

        main_layout.addWidget(self._make_hline())

        # ── GPT 新聞情緒 ──
        main_layout.addWidget(self._make_section_title("📰 AI 新聞情緒"))

        self.label_sentiment = QLabel("--")
        self.label_sentiment.setObjectName("labelExplain")
        self.label_sentiment.setWordWrap(True)
        self.label_sentiment.setAlignment(Qt.AlignmentFlag.AlignTop)
        main_layout.addWidget(self.label_sentiment)

        main_layout.addStretch()

    # ── 公開方法 ────────────────────────────────────────────────────

    def update_prediction(self, result: dict):
        """
        接收預測結果並更新所有 UI 元件

        Args:
            result: prediction_worker 發射的結果字典
        """
        prediction  = result.get("prediction", {})
        eval_m      = result.get("eval_metrics", {})
        explanations = result.get("explanations", [])
        price_info  = result.get("price_info", {})
        symbol      = result.get("symbol", "")

        up_prob   = prediction.get("up_prob",   0.5)
        down_prob = prediction.get("down_prob", 0.5)
        pred_dir  = prediction.get("prediction", -1)

        # ── 更新行情 ──
        if price_info:
            price = price_info.get("price", "--")
            change = price_info.get("change", 0)
            change_pct = price_info.get("change_pct", 0)
            self.label_price.setText(f"{symbol}\n{price}")
            color = "#FF3355" if change >= 0 else "#00CC66"
            sign  = "+" if change >= 0 else ""
            self.label_change.setText(f"{sign}{change} ({sign}{change_pct}%)")
            self.label_change.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")

        # ── 更新預測主標題 ──
        if pred_dir == 1:
            text  = f"🔴 明日預測\n上漲 {up_prob:.1%}"
            color = "#FF3355"
        elif pred_dir == 0:
            text  = f"🟢 明日預測\n下跌 {down_prob:.1%}"
            color = "#00CC66"
        else:
            text  = "⚠️ 預測不確定"
            color = "#FFAA44"

        self.label_prediction.setText(text)
        self.label_prediction.setStyleSheet(
            f"color: {color}; font-size: 20px; font-weight: bold; padding: 8px 0;"
        )

        # ── 信心等級（動態進度條）──
        confidence = prediction.get("confidence_level", "")
        confidence_note = prediction.get("confidence_note", "")
        conviction = abs(up_prob - 0.5) * 100  # 距離 50% 的百分點
        if confidence:
            self.confidence_bar.set_confidence(confidence, confidence_note, conviction)
            self.confidence_bar.setVisible(True)
        else:
            self.confidence_bar.setVisible(False)

        # ── 動畫更新進度條 ──
        self._animate_bar(self.bar_up,   int(up_prob   * 100))
        self._animate_bar(self.bar_down, int(down_prob * 100))

        # ── 更新模型效能 ──
        if eval_m:
            acc  = eval_m.get("accuracy",   0)
            f1   = eval_m.get("f1_score",   0)
            n    = eval_m.get("test_samples", 0)
            cm   = eval_m.get("confusion_matrix", [])
            cm_text = ""
            if cm and len(cm) == 2:
                tn, fp = cm[0][0], cm[0][1]
                fn, tp = cm[1][0], cm[1][1]
                cm_text = f"\nTP:{tp}  FP:{fp}\nFN:{fn}  TN:{tn}"

            self.label_metrics.setText(
                f"準確率：{acc:.1%}\n"
                f"F1 Score：{f1:.4f}\n"
                f"測試樣本：{n} 筆"
                f"{cm_text}"
            )
        else:
            self.label_metrics.setText("（模型已載入，效能數據不適用）")

        # ── 更新 3 日走勢卡片 ──
        forecast_3d = result.get("forecast_3d", [])
        if forecast_3d:
            self._update_forecast_cards(forecast_3d)

        # ── 更新 SHAP 解析（條形圖）──
        if explanations:
            parsed = self._parse_shap_items(explanations)
            if parsed:
                self.shap_bar.set_data(parsed)
                self.shap_bar.setVisible(True)
                self.label_explain.setVisible(False)
            else:
                self.label_explain.setText("\n".join(explanations))
                self.label_explain.setVisible(True)
                self.shap_bar.setVisible(False)
        else:
            self.label_explain.setText("SHAP 解析不可用\n（需安裝 shap 套件）")
            self.label_explain.setVisible(True)
            self.shap_bar.setVisible(False)

        # ── 更新 GPT 情緒 ──
        sentiment = result.get("sentiment", {})
        if sentiment.get("available"):
            score  = sentiment.get("score", 0.0)
            reason = sentiment.get("reason", "")
            count  = sentiment.get("news_count", 0)
            raw_up = prediction.get("raw_up_prob", up_prob)

            if score >= 0.3:
                emoji, color = "🔴", "#FF3355"
                label = "樂觀"
            elif score <= -0.3:
                emoji, color = "🟢", "#00CC66"
                label = "悲觀"
            else:
                emoji, color = "🟡", "#FFCC44"
                label = "中性"

            # 顯示融合前後的機率變化
            diff = up_prob - raw_up
            diff_text = f"（{diff:+.1%}）" if prediction.get("gpt_adjusted") else ""

            self.label_sentiment.setText(
                f"{emoji} 情緒：{label}（{score:+.2f}）\n"
                f"分析 {count} 則新聞\n"
                f"ML 原始：{raw_up:.1%} → 融合後：{up_prob:.1%} {diff_text}\n"
                f"{reason}"
            )
            self.label_sentiment.setStyleSheet(
                f"color: {color}; font-size: 15px; padding: 10px; "
                f"background-color: #202020; border-radius: 6px; "
                f"border: 1px solid #3A3A3A;"
            )
        else:
            self.label_sentiment.setText("AI 分析未啟用\n請按右上角 ⚙ 設定 API Key")

    def update_price_only(self, price_info: dict, symbol: str):
        """僅更新行情欄位（不觸及預測結果）"""
        if not price_info:
            return
        price = price_info.get("price", "--")
        change = price_info.get("change", 0)
        change_pct = price_info.get("change_pct", 0)
        self.label_price.setText(f"{symbol}\n{price}")
        color = "#FF3355" if change >= 0 else "#00CC66"
        sign  = "+" if change >= 0 else ""
        self.label_change.setText(f"{sign}{change} ({sign}{change_pct}%)")
        self.label_change.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")

    def reset(self):
        """重置面板至初始狀態"""
        self.label_symbol.setText("📊 即時行情")
        self.label_price.setText("--")
        self.label_change.setText("輸入代號後點擊預測")
        self.label_change.setStyleSheet("color: #3A5A7A; font-size: 12px;")
        self.label_prediction.setText("等待預測...")
        self.label_prediction.setStyleSheet(
            "color: #3A5A7A; font-size: 18px; font-weight: bold; padding: 8px 0;"
        )
        self.bar_up.setValue(0)
        self.bar_down.setValue(0)
        self.label_metrics.setText("尚未訓練")
        self.label_explain.setText("--")
        self.shap_bar.set_data([])

    # ── 私有方法 ────────────────────────────────────────────────────

    def _animate_bar(self, bar: QProgressBar, target: int):
        """使用屬性動畫讓進度條平滑更新"""
        anim = QPropertyAnimation(bar, b"value", self)
        anim.setDuration(600)
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()

    def _parse_shap_items(self, explanations: list[str]) -> list[tuple[str, float]]:
        """從 SHAP 說明文字解析出 (名稱, 值) 列表"""
        items = []
        # 格式：• RSI 強弱指數：看多 (+0.123)
        pattern = re.compile(r"•\s*(.+?)：\S+\s*\(([+\-]?\d+\.\d+)\)")
        for line in explanations:
            m = pattern.match(line)
            if m:
                items.append((m.group(1).strip(), float(m.group(2))))
        return items

    def _make_forecast_card(self) -> dict:
        """建立單日走勢卡片（上行：日期+趨勢+信心，下行：原因）"""
        widget = QWidget()
        widget.setStyleSheet(
            "background-color: #202020; border-radius: 8px; "
            "border: 1px solid #3A3A3A; margin: 2px 0;"
        )
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(4)

        # 上行：日期 + 趨勢 + 信心
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        lbl_day = QLabel("--")
        lbl_day.setFixedWidth(44)
        lbl_day.setStyleSheet(
            "color: #7A9ABE; font-size: 14px; font-weight: bold; "
            "border: none; background: transparent;"
        )

        lbl_trend = QLabel("--")
        lbl_trend.setStyleSheet(
            "font-size: 15px; font-weight: bold; "
            "border: none; background: transparent;"
        )

        lbl_conf = QLabel("--")
        lbl_conf.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_conf.setStyleSheet(
            "color: #5A7A9A; font-size: 13px; "
            "border: none; background: transparent;"
        )

        top_row.addWidget(lbl_day)
        top_row.addWidget(lbl_trend)
        top_row.addStretch()
        top_row.addWidget(lbl_conf)

        # 下行：原因
        lbl_reason = QLabel("--")
        lbl_reason.setWordWrap(True)
        lbl_reason.setStyleSheet(
            "color: #6A8EAE; font-size: 13px; "
            "border: none; background: transparent;"
        )

        outer.addLayout(top_row)
        outer.addWidget(lbl_reason)

        return {
            "widget":     widget,
            "lbl_day":    lbl_day,
            "lbl_trend":  lbl_trend,
            "lbl_conf":   lbl_conf,
            "lbl_reason": lbl_reason,
        }

    def _update_forecast_cards(self, forecast: list):
        """更新 3 日走勢卡片內容"""
        color_map = {
            "green":  ("#FF3355", "🔴"),   # 偏多 → 台灣紅
            "red":    ("#00CC66", "🟢"),   # 偏空 → 台灣綠
            "yellow": ("#FFCC44", "🟡"),
        }
        conf_color = {"高": "#FF3355", "中": "#FFCC44", "低": "#7A9ABE"}

        for i, (card, data) in enumerate(zip(self.forecast_cards, forecast)):
            color, emoji = color_map.get(data.get("color", "yellow"), ("#FFCC44", "🟡"))
            conf  = data.get("confidence", "低")
            trend = data.get("trend", "盤整")

            card["lbl_day"].setText(data.get("day", f"+{i+1}天"))
            card["lbl_trend"].setText(f"{emoji} {trend}")
            card["lbl_trend"].setStyleSheet(
                f"color: {color}; font-size: 14px; font-weight: bold; border: none; background: transparent;"
            )
            card["lbl_conf"].setText(f"信心：{conf}")
            card["lbl_conf"].setStyleSheet(
                f"color: {conf_color.get(conf, '#FFCC44')}; font-size: 12px; border: none; background: transparent;"
            )
            card["lbl_reason"].setText(data.get("reason", ""))

    def _make_section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        label.setStyleSheet(
            "color: #4A8ACA; font-size: 11px; font-weight: bold; "
            "letter-spacing: 1px; padding-bottom: 3px; "
            "border-bottom: 1px solid #3A3A3A;"
        )
        return label

    def _make_hline(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #3A3A3A;")
        return line

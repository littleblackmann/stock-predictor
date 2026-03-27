"""
準確率趨勢圖對話框
以週為單位統計預測準確率，顯示模型隨時間的學習成效
"""
from datetime import date, timedelta
from collections import defaultdict

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt

from data.prediction_logger import PredictionLogger


class AccuracyTrendDialog(QDialog):
    """
    顯示歷史預測準確率趨勢折線圖（matplotlib）

    X 軸：週次（最近 N 週）
    Y 軸：該週正確率（%）
    另外顯示累積總準確率基準線
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📈 準確率趨勢")
        self.resize(720, 460)
        self.setMinimumSize(500, 360)
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(8)

        # 嵌入 matplotlib 圖表
        try:
            canvas = self._build_canvas()
            root.addWidget(canvas, stretch=1)
        except Exception as e:
            lbl = QLabel(f"⚠ 無法建立圖表：{e}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #FF6666; font-size: 13px;")
            root.addWidget(lbl, stretch=1)

        # 底部提示
        hint = QLabel("資料不足 5 筆時該週不顯示 · 灰色虛線為整體準確率基準")
        hint.setStyleSheet("color: #4A6A8A; font-size: 11px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(hint)

        # 關閉按鈕
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton("關閉")
        btn_close.setFixedWidth(90)
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _build_canvas(self):
        import matplotlib
        matplotlib.use("QtAgg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

        # 全局設定中文字型，避免方塊亂碼
        plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "SimHei", "Arial"]
        plt.rcParams["axes.unicode_minus"] = False

        weeks, acc_list, overall = self._compute_weekly()

        fig, ax = plt.subplots(figsize=(8, 4.2))
        fig.patch.set_facecolor("#0B1426")
        ax.set_facecolor("#0D1B2E")

        if weeks:
            # 折線圖
            colors = ["#00FF88" if a >= 0.5 else "#FF3366" for a in acc_list]
            ax.plot(weeks, [a * 100 for a in acc_list],
                    color="#00CCFF", linewidth=2, marker="o",
                    markersize=7, zorder=3, label="週準確率")

            # 各點上色（綠>=50%, 紅<50%）
            for x, y, c in zip(weeks, acc_list, colors):
                ax.scatter(x, y * 100, color=c, s=60, zorder=4)

            # 整體基準線
            if overall is not None:
                ax.axhline(overall * 100, color="#888888", linewidth=1.2,
                           linestyle="--", label=f"整體 {overall:.1%}")

            ax.set_ylim(0, 105)
            ax.set_ylabel("準確率 (%)", color="#A0B8D0", fontsize=11)
            ax.set_xlabel("週次", color="#A0B8D0", fontsize=11)
            ax.tick_params(colors="#A0B8D0", labelsize=9)
            ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
            ax.spines[:].set_color("#1E3A5F")
            ax.grid(axis="y", color="#1E3A5F", linewidth=0.7, linestyle="--")

            # X 軸標籤旋轉
            if len(weeks) > 6:
                plt.setp(ax.get_xticklabels(), rotation=35, ha="right")

            ax.legend(facecolor="#0D1B2E", edgecolor="#1E3A5F",
                      labelcolor="#A0B8D0", fontsize=10)
        else:
            ax.text(0.5, 0.5, "尚無足夠記錄\n請累積更多預測資料",
                    transform=ax.transAxes,
                    ha="center", va="center",
                    color="#4A6A8A", fontsize=14)

        ax.set_title("每週預測準確率趨勢", color="#00CCFF",
                     fontsize=13, pad=12)

        fig.tight_layout(pad=1.5)
        canvas = FigureCanvasQTAgg(fig)
        return canvas

    @staticmethod
    def _compute_weekly() -> tuple[list, list, float | None]:
        """
        依週分組統計準確率
        回傳 (week_labels, accuracies, overall_accuracy)
        """
        rows = PredictionLogger.load_all()
        evaluated = [r for r in rows if r.get("correct") in ("True", "False")]
        if not evaluated:
            return [], [], None

        # 依週分組
        by_week: dict[str, list[bool]] = defaultdict(list)
        for r in evaluated:
            try:
                d = date.fromisoformat(r["prediction_date"])
                # ISO 週格式 YYYY-W##
                week_key = d.strftime("%Y-W%W")
                by_week[week_key].append(r["correct"] == "True")
            except ValueError:
                continue

        if not by_week:
            return [], [], None

        # 排序並過濾（每週至少 1 筆才顯示，但圖上用點大小表示樣本量）
        sorted_weeks = sorted(by_week.keys())
        weeks    = []
        acc_list = []
        for w in sorted_weeks:
            vals = by_week[w]
            weeks.append(w.replace("-W", "\nW"))
            acc_list.append(sum(vals) / len(vals))

        overall = sum(1 for r in evaluated if r["correct"] == "True") / len(evaluated)
        return weeks, acc_list, overall

    @staticmethod
    def _cjk_font():
        """嘗試取得中文字體，失敗回傳 None"""
        try:
            from matplotlib.font_manager import FontProperties
            return FontProperties(family="Microsoft JhengHei")
        except Exception:
            return None

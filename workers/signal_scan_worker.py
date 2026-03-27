"""
自選股技術訊號掃描器
啟動時在背景執行，偵測 MACD 黃金/死亡交叉與 RSI 超買/超賣
只回報最近 1~2 個交易日剛出現的訊號
"""
import numpy as np
from PySide6.QtCore import QRunnable, QObject, Signal

from data.yfinance_adapter import YFinanceAdapter
from logger.app_logger import get_logger

logger = get_logger(__name__)


class _ScanSignals(QObject):
    finished = Signal(dict)   # {symbol: [signal_str, ...]}


class SignalScanWorker(QRunnable):
    """
    對給定的股票清單批次計算技術指標訊號

    訊號種類：
    - 🟡 金叉：MACD Histogram 昨負今正（黃金交叉）
    - 🔴 死叉：MACD Histogram 昨正今負（死亡交叉）
    - 📈 超賣：RSI < 30（逢低可能反彈）
    - 📉 超買：RSI > 70（高檔可能回調）
    """

    def __init__(self, symbols: list[str]):
        super().__init__()
        self.symbols = symbols
        self.signals = _ScanSignals()
        self.setAutoDelete(True)

    def run(self):
        result: dict[str, list[str]] = {}
        adapter = YFinanceAdapter()

        for symbol in self.symbols:
            try:
                df = adapter.fetch_history(symbol=symbol, period_days=90)
                if df is None or len(df) < 35:
                    continue

                close = df["Close"].values.astype(float)
                sigs  = []

                # ── MACD ─────────────────────────────────────────
                ema12      = self._ema(close, 12)
                ema26      = self._ema(close, 26)
                macd_line  = ema12 - ema26
                signal_line = self._ema(macd_line, 9)
                hist       = macd_line - signal_line

                if len(hist) >= 2:
                    if hist[-2] < 0 and hist[-1] > 0:
                        sigs.append("🟡 金叉")
                    elif hist[-2] > 0 and hist[-1] < 0:
                        sigs.append("🔴 死叉")

                # ── RSI ──────────────────────────────────────────
                rsi = self._rsi(close, 14)
                if rsi is not None:
                    if rsi < 30:
                        sigs.append(f"📈 超賣({rsi:.0f})")
                    elif rsi > 70:
                        sigs.append(f"📉 超買({rsi:.0f})")

                if sigs:
                    result[symbol] = sigs
                    logger.info(f"訊號掃描 {symbol}：{sigs}")

            except Exception as e:
                logger.warning(f"掃描 {symbol} 失敗：{e}")
                continue

        logger.info(f"訊號掃描完成，{len(result)} 支股票有訊號")
        self.signals.finished.emit(result)

    # ── 指標計算 ─────────────────────────────────────────────────

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> np.ndarray:
        alpha = 2.0 / (period + 1)
        ema = np.empty_like(data)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema

    @staticmethod
    def _rsi(data: np.ndarray, period: int = 14) -> float | None:
        if len(data) < period + 1:
            return None
        deltas   = np.diff(data)
        gains    = np.where(deltas > 0, deltas, 0.0)
        losses   = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

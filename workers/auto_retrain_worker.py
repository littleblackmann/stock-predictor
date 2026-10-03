"""
自動重訓工作器
根據 PredictionLogger.check_auto_retrain_candidates() 回傳的清單，
在背景靜默重訓指定股票的 Transformer + LightGBM 模型，不顯示進度條、不影響 UI。
完成後透過 Signal 通知主視窗更新狀態列。
"""
import traceback

import numpy as np
from PySide6.QtCore import QRunnable, QObject, Signal

from data.yfinance_adapter import YFinanceAdapter
from data.chip_fetcher import ChipFetcher
from features.feature_engineer import FeatureEngineer
from models.lgbm_classifier import LGBMClassifier
from logger.app_logger import get_logger

logger = get_logger(__name__)


class AutoRetrainSignals(QObject):
    symbol_done = Signal(str, bool)   # symbol, success
    all_done    = Signal(int, int)    # success_count, total_count


class AutoRetrainWorker(QRunnable):
    """
    對多支股票依序執行背景重訓。
    每支完成後發射 symbol_done；全部完成後發射 all_done。
    """

    def __init__(self, symbols: list[str]):
        super().__init__()
        self.symbols = symbols
        self.signals = AutoRetrainSignals()
        self.setAutoDelete(True)

    def run(self):
        success = 0

        for symbol in self.symbols:
            try:
                logger.info(f"[AutoRetrain] 開始重訓：{symbol}")

                from workers.prediction_worker import run_prediction
                run_prediction(symbol, force=True, include_news=False)

                success += 1
                logger.info(f"[AutoRetrain] 完成：{symbol}")
                self.signals.symbol_done.emit(symbol, True)

            except Exception as e:
                logger.error(
                    f"[AutoRetrain] 失敗：{symbol} — {e}\n{traceback.format_exc()}"
                )
                self.signals.symbol_done.emit(symbol, False)

        self.signals.all_done.emit(success, len(self.symbols))

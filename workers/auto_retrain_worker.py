"""
自動重訓工作器
根據 PredictionLogger.check_auto_retrain_candidates() 回傳的清單，
在背景靜默重訓指定股票的 LSTM + LightGBM 模型，不顯示進度條、不影響 UI。
完成後透過 Signal 通知主視窗更新狀態列。
"""
import traceback

import numpy as np
from PySide6.QtCore import QRunnable, QObject, Signal

from data.yfinance_adapter import YFinanceAdapter
from data.chip_fetcher import ChipFetcher
from features.feature_engineer import FeatureEngineer
from models.lstm_extractor import LSTMExtractor, SEQUENCE_LEN, LSTM_UNITS
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

                # 1. 下載資料
                adapter = YFinanceAdapter()
                df_raw  = adapter.fetch_history(symbol=symbol, period_days=1500)

                # 2. 籌碼資料
                try:
                    chip_start = df_raw.index[0].date()
                    chip_end   = df_raw.index[-1].date()
                    chip_df = ChipFetcher().fetch(symbol=symbol,
                                                  start=chip_start,
                                                  end=chip_end)
                except Exception as e:
                    logger.warning(f"[AutoRetrain] 籌碼資料失敗 {symbol}: {e}")
                    chip_df = None

                # 3. 特徵工程
                engineer        = FeatureEngineer()
                df_features     = engineer.build_features(df_raw, chip_df=chip_df)
                feature_cols    = engineer.get_feature_cols()
                lstm_input_cols = engineer.get_lstm_input_cols()

                # 3. 重訓 LSTM
                lstm = LSTMExtractor(symbol=symbol)
                lstm.train(df=df_features, input_cols=lstm_input_cols)

                # 4. 批次萃取 LSTM 特徵（供 LightGBM 使用）
                feature_data = df_features[lstm_input_cols].values
                scaled_data  = lstm.scaler.transform(feature_data)
                n_windows    = len(scaled_data) - SEQUENCE_LEN + 1
                windows      = np.stack([
                    scaled_data[i: i + SEQUENCE_LEN]
                    for i in range(n_windows)
                ])
                all_lstm_features = lstm.feature_extractor.predict(
                    windows, batch_size=256, verbose=0
                )

                # 5. 重訓 LightGBM
                lgbm = LGBMClassifier(symbol=symbol)
                lgbm.train(
                    df=df_features,
                    feature_cols=feature_cols,
                    lstm_features=all_lstm_features,
                )

                success += 1
                logger.info(f"[AutoRetrain] 完成：{symbol}")
                self.signals.symbol_done.emit(symbol, True)

            except Exception as e:
                logger.error(
                    f"[AutoRetrain] 失敗：{symbol} — {e}\n{traceback.format_exc()}"
                )
                self.signals.symbol_done.emit(symbol, False)

        self.signals.all_done.emit(success, len(self.symbols))

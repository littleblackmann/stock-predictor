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
from models.transformer_extractor import TransformerExtractor, SEQUENCE_LEN, OUTPUT_DIM
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

                # 1. 下載資料（2500 天，供 Transformer 300 天窗口使用）
                adapter = YFinanceAdapter()
                df_raw  = adapter.fetch_history(symbol=symbol, period_days=2500)

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
                seq_input_cols  = engineer.get_transformer_input_cols()

                # 4. 重訓 Transformer
                seq_extractor = TransformerExtractor(symbol=symbol)
                seq_extractor.train(df=df_features, input_cols=seq_input_cols)

                # 5. 批次萃取 Transformer 特徵（供 LightGBM 使用）
                feature_data = df_features[seq_input_cols].values
                scaled_data  = seq_extractor.scaler.transform(feature_data)
                n_windows    = len(scaled_data) - SEQUENCE_LEN + 1
                BATCH_EXTRACT = 64
                all_seq_features_list = []
                for start in range(0, n_windows, BATCH_EXTRACT):
                    end = min(start + BATCH_EXTRACT, n_windows)
                    batch_windows = np.stack([
                        scaled_data[i: i + SEQUENCE_LEN]
                        for i in range(start, end)
                    ])
                    batch_feats = seq_extractor.feature_extractor.predict(
                        batch_windows, batch_size=BATCH_EXTRACT, verbose=0
                    )
                    all_seq_features_list.append(batch_feats)
                all_seq_features = np.concatenate(all_seq_features_list, axis=0)

                # 6. 重訓 LightGBM
                lgbm = LGBMClassifier(symbol=symbol)
                lgbm.train(
                    df=df_features,
                    feature_cols=feature_cols,
                    seq_features=all_seq_features,
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

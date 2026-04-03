"""
背景預測任務工作器
繼承 QRunnable，在獨立執行緒中執行耗時的資料下載與模型推論
透過 Qt Signals 安全地將結果回傳給主介面
"""
import numpy as np
import traceback
from PySide6.QtCore import QRunnable, QObject, Signal, Slot

from data.yfinance_adapter import YFinanceAdapter
from data.news_sentiment import NewsSentimentAnalyzer
from data.chip_fetcher import ChipFetcher
from features.feature_engineer import FeatureEngineer
from models.transformer_extractor import TransformerExtractor
from models.lgbm_classifier import LGBMClassifier
from logger.app_logger import get_logger

logger = get_logger(__name__)


class WorkerSignals(QObject):
    """
    定義背景執行緒可發射的所有訊號
    注意：訊號必須定義在繼承 QObject 的類別中
    """
    # 進度更新：(百分比 0-100, 說明文字)
    progress_updated = Signal(int, str)

    # 預測完成：傳回包含所有結果的字典
    prediction_finished = Signal(dict)

    # 發生錯誤：傳回錯誤訊息
    error_occurred = Signal(str)


class PredictionWorker(QRunnable):
    """
    完整的預測流程背景工作器

    流程：
    1. 下載歷史資料 (yfinance, 2500 天)
    2. 抓取籌碼資料 + 美股隔夜資料
    3. 計算技術指標 (FeatureEngineer)
    4. 訓練或載入 Transformer 模型（300 天窗口）
    5. 訓練或載入 LightGBM 模型
    6. 新聞情緒分析 + 推論，輸出預測機率
    7. 透過訊號回傳結果給主執行緒
    """

    def __init__(self, symbol: str, retrain: bool = False):
        """
        Args:
            symbol: 股票代號（如 0050 或 0050.TW）
            retrain: True = 強制重新訓練模型（忽略已存檔的模型）
        """
        super().__init__()
        self.symbol  = symbol
        self.retrain = retrain
        self.signals = WorkerSignals()
        self._aborted = False
        self.setAutoDelete(True)  # 執行完畢後自動釋放資源

    def _emit_progress(self, pct: int, msg: str):
        """安全發射進度訊號，signal 已被回收時靜默跳過"""
        if self._aborted:
            return
        try:
            self.signals.progress_updated.emit(pct, msg)
        except RuntimeError:
            self._aborted = True
            logger.warning("Signal source 已被回收，停止進度更新")

    @Slot()
    def run(self):
        """背景執行緒的主要執行邏輯"""

        # ── 自動判斷是否需要重訓 ──────────────────────────────────
        if not self.retrain:
            should_retrain, reason = LGBMClassifier.needs_retrain(self.symbol)
            if should_retrain:
                logger.info(f"自動觸發重訓：{reason}")
                self.retrain = True
                self._emit_progress(2, f"🔄 自動重訓：{reason}")

        logger.info(f"預測任務開始：symbol={self.symbol}, retrain={self.retrain}")

        try:
            # ── 步驟 1：下載資料 ──────────────────────────────────
            self._emit_progress(5, f"正在連線下載 {self.symbol} 歷史資料...")

            adapter = YFinanceAdapter()
            df_raw = adapter.fetch_history(
                symbol=self.symbol,
                period_days=2500,  # ~7 年，Transformer 需要更多資料學習長期規律
                progress_callback=lambda p, msg: self._emit_progress(p, msg)
            )

            self._emit_progress(10, "資料下載完成，抓取籌碼資料...")

            # ── 步驟 2：抓取籌碼面資料（三大法人 + 融資融券）──────
            try:
                from datetime import date, timedelta
                chip_start = df_raw.index[0].date()
                chip_end   = df_raw.index[-1].date()

                def _chip_progress(cur, total):
                    if total > 0:
                        pct = 10 + int((cur / total) * 35)  # 10% → 45%
                        self._emit_progress(pct, f"抓取籌碼資料... ({cur+1}/{total})")

                chip_df = ChipFetcher().fetch(
                    self.symbol, chip_start, chip_end,
                    progress_callback=_chip_progress,
                )
            except Exception as e:
                logger.warning(f"籌碼資料抓取失敗，降級為純技術面：{e}")
                chip_df = None

            self._emit_progress(46, "下載美股隔夜資料（S&P500 / 費半 / VIX）...")

            # ── 步驟 2.5：下載美股隔夜資料 ─────────────────────
            us_data = self._download_us_market_data(2500)

            self._emit_progress(50, "計算技術指標 + 籌碼 + 美股 + 週線特徵...")

            # ── 步驟 3：特徵工程 ─────────────────────────────────
            engineer = FeatureEngineer()
            df_features = engineer.build_features(df_raw, chip_df=chip_df, us_data=us_data)

            feature_cols      = engineer.get_feature_cols()
            seq_input_cols    = engineer.get_transformer_input_cols()

            self._emit_progress(53, "技術指標計算完成")

            # ── 步驟 3：Transformer 訓練 / 載入 ─────────────────
            from models.transformer_extractor import SEQUENCE_LEN, OUTPUT_DIM
            seq_extractor = TransformerExtractor(symbol=self.symbol)
            seq_loaded = False

            if not self.retrain:
                seq_loaded = seq_extractor.load()
                # 特徵數防護：舊模型特徵維度不符時強制重訓
                if seq_loaded:
                    expected_n = len(seq_input_cols)
                    scaler_n = getattr(seq_extractor.scaler, "n_features_in_", None)
                    if scaler_n is not None and scaler_n != expected_n:
                        logger.info(f"Transformer 特徵數不符（模型={scaler_n}，當前={expected_n}），強制重訓")
                        seq_loaded = False

            if not seq_loaded:
                self._emit_progress(55, "開始訓練 Transformer 時序模型（首次訓練需要幾分鐘）...")
                seq_extractor.train(
                    df=df_features,
                    input_cols=seq_input_cols,
                    progress_callback=lambda p, msg: self._emit_progress(p, msg)
                )
            else:
                self._emit_progress(68, "Transformer 模型載入成功")

            # ── 步驟 4：萃取全部時間步的 Transformer 特徵 ───────
            self._emit_progress(70, "萃取 Transformer 時間特徵向量...")

            # 對所有訓練資料萃取 Transformer 特徵（用於訓練 LGBM）
            all_seq_features = self._extract_all_seq_features(
                seq_extractor, df_features, seq_input_cols
            )

            # ── 步驟 5：LightGBM 訓練 / 載入 ────────────────────
            lgbm_clf = LGBMClassifier(symbol=self.symbol)
            lgbm_loaded = False

            if not self.retrain:
                # 傳入當前特徵數，維度不符時自動強制重訓
                expected_feats = OUTPUT_DIM + len(feature_cols)
                lgbm_loaded = lgbm_clf.load(expected_n_features=expected_feats)

                # Transformer 剛訓練完 → LightGBM 必須重訓（舊模型特徵語義不同）
                if lgbm_loaded and not seq_loaded:
                    logger.info("Transformer 剛完成訓練，LightGBM 必須搭配重訓（特徵語義不同）")
                    lgbm_loaded = False

            if not lgbm_loaded:
                eval_metrics = lgbm_clf.train(
                    df=df_features,
                    feature_cols=feature_cols,
                    seq_features=all_seq_features,
                    progress_callback=lambda p, msg: self._emit_progress(p, msg)
                )
            else:
                eval_metrics = lgbm_clf.eval_metrics
                self._emit_progress(83, "LightGBM 模型載入成功")

            # ── 步驟 6：新聞搜尋 + 情緒分析 ──────────────────────
            self._emit_progress(85, "正在搜尋新聞並分析情緒（AI）...")
            sentiment_analyzer = NewsSentimentAnalyzer()
            sentiment = sentiment_analyzer.analyze(self.symbol)

            # ── 步驟 7：預測明天 ──────────────────────────────────
            self._emit_progress(92, "正在推論明日走勢...")

            latest_seq_feat = seq_extractor.extract_features(df_features, seq_input_cols)
            latest_tech_feat = df_features[feature_cols].iloc[-1].values.reshape(1, -1)

            # 取出最新一筆的市場狀態特徵（供行情專用模型混合 + 信心篩選）
            latest_regime = float(df_features["market_regime"].iloc[-1])

            prediction = lgbm_clf.predict(latest_seq_feat, latest_tech_feat,
                                          current_regime=int(latest_regime))

            # ── 信心篩選機制 ─────────────────────────────────────────
            # 根據 Ensemble 模型的一致性（std）和距離 50% 的幅度判斷信心
            # 並考慮市場行情狀態：盤整盤本來就難預測，自動降級信心
            ensemble_std = prediction.get("ensemble_std", 0)
            distance_from_50 = abs(prediction["up_prob"] - 0.5)
            if "volatility_regime" in df_features.columns:
                latest_vol_regime = float(df_features["volatility_regime"].iloc[-1])
            else:
                latest_vol_regime = 0.5

            if distance_from_50 < 0.03 or ensemble_std > 0.05:
                confidence_level = "low"
                confidence_note = "模型信心不足，建議觀望"
            elif distance_from_50 < 0.08 or ensemble_std > 0.03:
                confidence_level = "medium"
                confidence_note = "模型信心中等"
            else:
                confidence_level = "high"
                confidence_note = "模型高度一致"

            # 盤整盤降級：行情不明時即使模型有方向，信心也不該太高
            if latest_regime == 0 and confidence_level == "high":
                confidence_level = "medium"
                confidence_note = "趨勢不明（盤整），信心自動降級"
            elif latest_regime == 0 and confidence_level == "medium":
                confidence_note += "（盤整行情，預測難度較高）"

            # 高波動環境額外提示
            if latest_vol_regime > 0.8:
                confidence_note += "（波動偏高，注意風險）"

            prediction["confidence_level"] = confidence_level
            prediction["confidence_note"]  = confidence_note
            prediction["market_regime"]    = int(latest_regime)

            regime_label = {1: "多頭", -1: "空頭", 0: "盤整"}.get(int(latest_regime), "未知")
            logger.info(f"信心篩選：{confidence_level}（距50%={distance_from_50:.1%}，"
                        f"模型分散度={ensemble_std:.4f}，行情={regime_label}，"
                        f"波動率={latest_vol_regime:.0%}）")

            # ── GPT 情緒加權融合 ──────────────────────────────────
            # 基礎權重 15%，Brave 深度分析時根據影響程度 / 時間範圍動態調整
            base_weight = 0.15
            if sentiment.get("source") == "brave" and sentiment.get("impact"):
                impact_mult    = {"low": 0.7, "medium": 1.0, "high": 1.3}
                timeframe_mult = {"short": 1.2, "medium": 1.0, "long": 0.6}
                base_weight = (0.15
                               * impact_mult.get(sentiment["impact"], 1.0)
                               * timeframe_mult.get(sentiment["timeframe"], 1.0))
                base_weight = min(base_weight, 0.15)  # 上限 15%（避免情緒過度主導）
            SENTIMENT_WEIGHT = base_weight
            raw_up_prob = prediction["up_prob"]

            if sentiment.get("available"):
                raw_sentiment = sentiment.get("score", 0.0)  # -1.0 ~ +1.0
                # 壓縮極端情緒分數：用 tanh 緩衝，避免媒體聳動標題過度影響
                # ±0.3→±0.24  ±0.5→±0.35  ±0.7→±0.42  ±1.0→±0.50
                sentiment_score = 0.5 * np.tanh(1.0 * raw_sentiment)
                # 將情緒分數轉換為機率調整量
                sentiment_adjustment = sentiment_score * SENTIMENT_WEIGHT
                adjusted_up_prob = raw_up_prob + sentiment_adjustment
                # 限制在合理範圍內
                adjusted_up_prob = float(np.clip(adjusted_up_prob, 0.05, 0.95))
                adjusted_down_prob = 1.0 - adjusted_up_prob

                prediction["raw_up_prob"]   = round(raw_up_prob, 4)
                prediction["up_prob"]       = round(adjusted_up_prob, 4)
                prediction["down_prob"]     = round(adjusted_down_prob, 4)
                prediction["prediction"]    = 1 if adjusted_up_prob > 0.5 else 0
                prediction["gpt_adjusted"]  = True

                logger.info(
                    f"GPT 情緒融合：原始={raw_up_prob:.1%} → "
                    f"調整後={adjusted_up_prob:.1%}（原始情緒={raw_sentiment:+.2f} → 壓縮後={sentiment_score:+.2f}）"
                )
            else:
                prediction["raw_up_prob"]  = raw_up_prob
                prediction["gpt_adjusted"] = False

            # SHAP 解析
            explanations = lgbm_clf.get_shap_explanation(
                latest_seq_feat, latest_tech_feat, feature_cols
            )

            # ── 步驟 8：整理圖表資料 ──────────────────────────────
            self._emit_progress(95, "整理圖表資料...")
            chart_data = engineer.get_chart_data(df_raw, df_features)

            # ── 步驟 9：3日走勢預測 ───────────────────────────────
            self._emit_progress(96, "AI 推估未來 3 日走勢...")
            tech_context = df_features[engineer.get_feature_cols()].iloc[-1].to_dict()
            forecast_3d  = sentiment_analyzer.forecast_3days(
                symbol=self.symbol,
                tech_context=tech_context,
                ml_result=prediction,
                sentiment=sentiment,
            )
            # ── 完成：打包結果字典 ────────────────────────────────
            latest_price_info = adapter.get_latest_price(self.symbol)

            result = {
                "symbol":        self.symbol,
                "prediction":    prediction,
                "eval_metrics":  eval_metrics if eval_metrics else {},
                "explanations":  explanations,
                "sentiment":     sentiment,
                "forecast_3d":   forecast_3d,
                "chart_data":    chart_data,
                "price_info":    latest_price_info,
                "data_rows":     len(df_raw),
            }

            self._emit_progress(100, "預測完成！")
            try:
                self.signals.prediction_finished.emit(result)
            except RuntimeError:
                logger.warning("Signal source 已被回收，預測結果無法回傳 UI")
            logger.info(f"預測任務完成：{self.symbol} → 上漲機率 {prediction['up_prob']:.1%}")

        except Exception as e:
            error_msg = f"預測失敗：{str(e)}"
            logger.error(error_msg + "\n" + traceback.format_exc())
            try:
                self.signals.error_occurred.emit(error_msg)
            except RuntimeError:
                pass

    def _extract_all_seq_features(self, seq_extractor, df_features, input_cols) -> np.ndarray:
        """
        對整個資料集批次萃取 Transformer 特徵
        用於建構 LightGBM 的訓練特徵矩陣
        """
        from models.transformer_extractor import SEQUENCE_LEN, OUTPUT_DIM

        if not seq_extractor.is_trained:
            n = len(df_features)
            return np.zeros((n, OUTPUT_DIM))

        feature_data = df_features[input_cols].values
        scaled_data  = seq_extractor.scaler.transform(feature_data)

        # 建構所有滑動窗口 → shape: (n_windows, SEQUENCE_LEN, n_features)
        n_windows = len(scaled_data) - SEQUENCE_LEN + 1

        if n_windows <= 0:
            logger.warning(f"資料不足以建構 {SEQUENCE_LEN} 天窗口，回傳空特徵")
            return np.zeros((len(df_features), OUTPUT_DIM))

        # Transformer 窗口較大（300），分批建構避免記憶體爆掉
        BATCH_EXTRACT = 64
        all_features_list = []

        for batch_start in range(0, n_windows, BATCH_EXTRACT):
            batch_end = min(batch_start + BATCH_EXTRACT, n_windows)
            windows = np.stack([
                scaled_data[i: i + SEQUENCE_LEN]
                for i in range(batch_start, batch_end)
            ])
            batch_features = seq_extractor.feature_extractor.predict(
                windows, batch_size=BATCH_EXTRACT, verbose=0
            )
            all_features_list.append(batch_features)

        all_features = np.concatenate(all_features_list, axis=0)
        return all_features  # shape: (n_windows, OUTPUT_DIM)

    def _download_us_market_data(self, period_days: int) -> dict | None:
        """
        下載美股隔夜訊號所需的市場資料：S&P 500、費半指數、VIX

        Returns:
            {"^GSPC": DataFrame, "^SOX": DataFrame, "^VIX": DataFrame} 或 None
        """
        import yfinance as yf

        us_symbols = {
            "^GSPC": "S&P 500",
            "^SOX":  "費半指數",
            "^VIX":  "VIX 恐慌指數",
        }
        us_data = {}
        for sym, name in us_symbols.items():
            try:
                ticker = yf.Ticker(sym)
                df = ticker.history(period=f"{period_days}d")
                if df is not None and not df.empty:
                    us_data[sym] = df
                    logger.info(f"[美股] {name} 下載成功，{len(df)} 筆")
                else:
                    logger.warning(f"[美股] {name} 無資料")
            except Exception as e:
                logger.warning(f"[美股] {name} 下載失敗：{e}")

        return us_data if us_data else None

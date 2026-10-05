"""
背景預測任務工作器
繼承 QRunnable，在獨立執行緒中執行耗時的資料下載與模型推論
透過 Qt Signals 安全地將結果回傳給主介面
"""
from __future__ import annotations
from resource_budget import background_resources
import traceback
from PySide6.QtCore import QRunnable, QObject, Signal, Slot

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
            retrain: True = 強制重新訓練（Transformer + LightGBM 都從頭練）。
                     False 時各自依週期判斷：LightGBM 7 天、Transformer 45 天。
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

        try:
            with background_resources():
                result = run_prediction(self.symbol, self.retrain, self._emit_progress)
            self.signals.prediction_finished.emit(result)
        except Exception as e:
            logger.error("預測失敗：%s", e, exc_info=True)
            try:
                self.signals.error_occurred.emit(f"預測失敗：{e}")
            except RuntimeError:
                pass

    def _extract_all_seq_features(self, seq_extractor, df_features, input_cols) -> np.ndarray:
        """
        對整個資料集批次萃取 Transformer 特徵
        用於建構 LightGBM 的訓練特徵矩陣
        """
        import numpy as np
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
        from data.yfinance_adapter import YFinanceAdapter

        us_symbols = {
            "^GSPC": "S&P 500",
            "^SOX":  "費半指數",
            "^VIX":  "VIX 恐慌指數",
        }
        us_data = {}
        for sym, name in us_symbols.items():
            try:
                ticker = yf.Ticker(sym)
                df = ticker.history(period=f"{period_days}d", auto_adjust=True, repair=True)
                if df is not None and not df.empty:
                    df = df.dropna(subset=["Close"])
                    us_data[sym] = df
                    logger.info(f"[美股] {name} 下載成功，{len(df)} 筆")
                else:
                    logger.warning(f"[美股] {name} 無資料")
            except Exception as e:
                logger.warning(f"[美股] {name} 主來源失敗，使用行情備援")
                try:
                    us_data[sym] = YFinanceAdapter.fetch_chart(sym, period_days)
                except Exception:
                    logger.warning(f"[美股] {name} 備援也無資料")

        return us_data if us_data else None


def run_prediction(symbol, force=False, progress=None, include_news=True):
    from data.yfinance_adapter import YFinanceAdapter
    from features.feature_engineer import FeatureEngineer
    from data.market_time import completed_history, taipei_now, target_session
    from data.holiday_checker import get_calendar
    from data.data_paths import MODEL_DIR
    from models.short_term import cached_forecast

    emit = progress or (lambda *args: None)
    calendar = get_calendar()
    calendar.refresh()
    adapter = YFinanceAdapter()
    symbol = adapter.normalize_symbol(symbol)
    emit(5, "下載歷史行情，確認完整交易日...")
    raw = completed_history(adapter.fetch_history(symbol, period_days=2500))
    if raw.empty:
        raise ValueError("尚無已完成交易日資料，請稍後再試")
    data_date = raw.index[-1].date()
    calendar = get_calendar()
    now = taipei_now()
    next_date = target_session(data_date, 1, calendar)
    # A model based on stale history must not masquerade as a forecast for today.
    if next_date < now.date() or (next_date == now.date() and now.hour >= 15):
        raise ValueError(f"行情只更新到 {data_date}，請等資料來源更新後重試")
    emit(20, "下載美股資料...")
    us_data = PredictionWorker._download_us_market_data(None, 2500)
    engineer = FeatureEngineer()
    # Historical chip coverage is only 90 calendar days; it cannot be trained
    # honestly against seven years of prices with earlier missing values = zero.
    features = engineer.build_features(raw, us_data=us_data, include_latest=True)
    if features.empty or features.index[-1] != raw.index[-1]:
        raise ValueError("最新交易日指標資料不完整，暫不產生過期預測")
    emit(50, "驗證 1、3、5 個交易日模型...")
    horizons = cached_forecast(features, engineer.get_feature_cols(), raw['Close'],
                               symbol, MODEL_DIR, force, emit)
    cards = []
    for item in horizons:
        target = target_session(data_date, item['horizon'], calendar)
        item['target_date'] = target.isoformat()
        direction = {1: '偏多', 0: '偏空', -1: '方向不明'}[item['prediction']]
        cards.append({'day': f"{item['horizon']} 交易日 · {target:%m/%d}",
                      'trend': f"{direction} · 上漲 {item['up_prob']:.0%}",
                      'color': {1:'green',0:'red',-1:'yellow'}[item['prediction']],
                      'confidence': '待驗證' if item['prediction'] == -1 else '參考',
                      'reason': f"回測 {item['eval_metrics']['accuracy']:.0%} / 基準 {item['eval_metrics']['baseline_accuracy']:.0%}"})
    sentiment = {'available': False, 'reason': '新聞分析未啟用'}
    if include_news:
        emit(88, "整理新聞分析...")
        from data.news_sentiment import NewsSentimentAnalyzer
        sentiment = NewsSentimentAnalyzer().analyze(symbol)
    latest = float(raw.Close.iloc[-1]); previous = float(raw.Close.iloc[-2])
    result = {'symbol': symbol, 'prediction': horizons[0], 'horizons': horizons,
              'eval_metrics': horizons[0]['eval_metrics'], 'forecast_3d': cards,
              'data_date': data_date.isoformat(), 'created_at': now.isoformat(),
              'target_date': horizons[0]['target_date'],
              'explanations': ['各期限使用獨立歷史驗證；新聞不直接調整模型機率。',
                               '籌碼歷史僅涵蓋近期，暫不納入長期模型。'],
              'sentiment': sentiment, 'chart_data': engineer.get_chart_data(raw, features),
              'price_info': {'price': round(latest,2), 'change': round(latest-previous,2),
                             'change_pct': round((latest/previous-1)*100,2), 'date': data_date.isoformat()},
              'data_rows': len(raw)}
    emit(100, "分析完成")
    return result

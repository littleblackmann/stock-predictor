"""
特徵工程模組
計算技術指標，建構供 LSTM + LightGBM 使用的特徵矩陣

特徵維度：
- 技術面基礎：13 維
- 美股隔夜訊號：4 維（S&P500 報酬、費半報酬、VIX 水位、VIX 變化）
- 多時間框架：2 維（週線趨勢、週 RSI）
- 市場狀態辨識：1 維（多頭 / 空頭 / 盤整）
- 籌碼面（選用）：7 維
"""
import pandas as pd
import numpy as np
from logger.app_logger import get_logger

logger = get_logger(__name__)

# 籌碼特徵欄位名稱（對應 ChipFetcher 輸出）
CHIP_COLS_INST   = ["fi_net", "it_net", "dealer_net", "institutional_net"]
CHIP_COLS_MARGIN = ["margin_balance", "short_balance", "margin_change", "short_change"]
CHIP_COLS_ALL    = CHIP_COLS_INST + CHIP_COLS_MARGIN

# 衍生籌碼特徵（由上面計算得來）
CHIP_DERIVED = [
    "fi_net_pct",           # 外資淨買超 / 成交量
    "it_net_pct",           # 投信淨買超 / 成交量
    "institutional_net_pct",# 三大法人合計 / 成交量
    "fi_consecutive",       # 外資連續買超天數（負值=連續賣超）
    "margin_change_pct",    # 融資增減 / 融資餘額
    "short_change_pct",     # 融券增減 / 融券餘額
    "short_margin_ratio",   # 融券 / 融資（軋空風險指標）
]

# 美股隔夜訊號特徵
US_OVERNIGHT_FEATURES = [
    "sp500_return",   # S&P 500 隔夜對數報酬率
    "sox_return",     # 費半指數隔夜對數報酬率
    "vix_level",      # VIX 恐慌指數水位（÷100 標準化）
    "vix_change",     # VIX 日變化率
]

# 多時間框架特徵
MULTIFRAME_FEATURES = [
    "weekly_ma_trend",  # 週線收盤 vs 週 MA5（1=在上, -1=在下）
    "weekly_rsi",       # 週線 RSI（0~1 標準化）
]

# 市場狀態辨識特徵
REGIME_FEATURES = [
    "market_regime",  # 1=多頭（Close>MA20>MA60）, -1=空頭, 0=盤整
]


class FeatureEngineer:
    """
    從 OHLCV 資料計算多維度技術面特徵：
    - 趨勢指標：MA5, MA20, EMA12, EMA26
    - 動能指標：RSI(14), MACD, MACD Signal, MACD Histogram
    - 波動指標：Bollinger Bands (bandwidth, %b), ATR(14)
    - 量能指標：成交量變化率, 量比
    - 報酬序列：對數收益率 Log Returns
    - 籌碼指標（選用）：三大法人淨買超、融資融券（需傳入 chip_df）
    """

    def __init__(self):
        self._has_chip = False   # 本次是否有籌碼資料
        self._has_us   = False   # 本次是否有美股隔夜資料
        logger.info("FeatureEngineer 初始化完成")

    def build_features(self, df: pd.DataFrame,
                       chip_df: pd.DataFrame | None = None,
                       us_data: dict | None = None) -> pd.DataFrame:
        """
        輸入 OHLCV DataFrame，輸出包含所有特徵的完整 DataFrame

        Args:
            df:      含 Open, High, Low, Close, Volume 的 DataFrame
            chip_df: ChipFetcher.fetch() 回傳的籌碼 DataFrame（選用）
                     有籌碼資料時加入三大法人 + 融資融券衍生特徵
            us_data: 美股隔夜資料字典（選用）
                     {"^GSPC": DataFrame, "^SOX": DataFrame, "^VIX": DataFrame}

        Returns:
            加入所有技術指標欄位後的 DataFrame（已移除 NaN）
        """
        logger.info(f"開始計算技術指標，輸入資料：{len(df)} 筆")
        df = df.copy()

        # --- 對數收益率 ---
        df["log_return"] = np.log(df["Close"] / df["Close"].shift(1))

        # --- 移動平均線 ---
        df["ma5"]  = df["Close"].rolling(window=5).mean()
        df["ma20"] = df["Close"].rolling(window=20).mean()
        df["ma5_cross_ma20"] = (df["ma5"] - df["ma20"]) / df["Close"]  # 金死叉強度

        # --- EMA（MACD 使用）---
        df["ema12"] = df["Close"].ewm(span=12, adjust=False).mean()
        df["ema26"] = df["Close"].ewm(span=26, adjust=False).mean()

        # --- MACD ---
        df["macd"]        = df["ema12"] - df["ema26"]
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"]   = df["macd"] - df["macd_signal"]

        # --- RSI(14) ---
        df["rsi"] = self._calc_rsi(df["Close"], period=14)

        # --- 布林通道 ---
        bb_mid = df["Close"].rolling(window=20).mean()
        bb_std = df["Close"].rolling(window=20).std()
        df["bb_upper"]     = bb_mid + 2 * bb_std
        df["bb_lower"]     = bb_mid - 2 * bb_std
        df["bb_bandwidth"] = (df["bb_upper"] - df["bb_lower"]) / bb_mid          # 通道寬度
        df["bb_pct_b"]     = (df["Close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])  # %b 位置

        # --- ATR(14) ---
        df["atr"] = self._calc_atr(df, period=14)
        df["atr_ratio"] = df["atr"] / df["Close"]  # 標準化 ATR

        # --- 成交量特徵 ---
        df["vol_ma5"]      = df["Volume"].rolling(window=5).mean()
        df["vol_ratio"]    = df["Volume"] / df["vol_ma5"]              # 量比（今量/5日均量）
        df["vol_change"]   = df["Volume"].pct_change()                 # 成交量變化率

        # --- 價格位置特徵 ---
        df["high_low_ratio"] = (df["High"] - df["Low"]) / df["Close"]  # 當日振幅
        df["close_position"] = (df["Close"] - df["Low"]) / (df["High"] - df["Low"])  # 收盤在高低點間的位置

        # --- 目標標籤：明天是否上漲 ---
        # 1 = 明天收盤 > 今天收盤（上漲），0 = 下跌或平盤
        df["label"] = (df["Close"].shift(-1) > df["Close"]).astype(int)

        # --- 美股隔夜訊號 ---
        df = self._build_us_overnight(df, us_data)

        # --- 多時間框架特徵 ---
        df = self._build_multiframe(df)

        # --- 市場狀態辨識 ---
        df = self._build_market_regime(df)

        # --- 籌碼面特徵（選用）---
        self._has_chip = False
        if chip_df is not None and not chip_df.empty:
            df = self._merge_chip_features(df, chip_df)

        # 移除因計算產生的 inf（除以零）與 NaN（頭部），以及最後一列（無明日標籤）
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.dropna(inplace=True)
        df = df.iloc[:-1]  # 最後一天沒有明日標籤，移除

        extras = []
        if self._has_us:
            extras.append("美股隔夜")
        extras.append("多時間框架+市場狀態")
        if self._has_chip:
            extras.append(f"籌碼{len(CHIP_DERIVED)}維")
        else:
            extras.append("純技術面")
        note = "（" + " + ".join(extras) + "）"
        logger.info(f"特徵工程完成，共 {len(df)} 筆有效資料，"
                    f"{len(self.get_feature_cols())} 個特徵 {note}")
        return df

    def _merge_chip_features(self, df: pd.DataFrame, chip_df: pd.DataFrame) -> pd.DataFrame:
        """
        將籌碼 DataFrame 對齊合併進技術面 DataFrame，並計算衍生特徵。
        缺值以 0 填補（某些交易日 TWSE 可能無資料）。
        """
        try:
            # 對齊索引（以 OHLCV 日期為主，左合併）
            chip_df = chip_df.copy()
            chip_df.index = pd.to_datetime(chip_df.index).normalize()
            df.index = pd.to_datetime(df.index).normalize()

            for col in CHIP_COLS_ALL:
                if col in chip_df.columns:
                    df[col] = chip_df[col].reindex(df.index).fillna(0)
                else:
                    df[col] = 0

            vol = df["Volume"].replace(0, 1)  # 防止除以 0

            # 外資/投信淨買超佔成交量比（標準化，消除股本差異）
            df["fi_net_pct"]            = df["fi_net"] * 1000 / vol
            df["it_net_pct"]            = df["it_net"] * 1000 / vol
            df["institutional_net_pct"] = df["institutional_net"] * 1000 / vol

            # 外資連續買超天數（連續正值累加，負值清零；賣超則累加負值）
            df["fi_consecutive"] = self._calc_consecutive(df["fi_net"])

            # 融資增減率（增加 = 散戶加碼，減少 = 散戶出場）
            df["margin_change_pct"] = df["margin_change"] / df["margin_balance"].replace(0, 1)
            df["short_change_pct"]  = df["short_change"]  / df["short_balance"].replace(0, 1)

            # 融券/融資比（越高代表空頭部位越重，容易軋空反彈）
            df["short_margin_ratio"] = df["short_balance"] / df["margin_balance"].replace(0, 1)

            self._has_chip = True
            logger.info("籌碼特徵合併完成")
        except Exception as e:
            logger.warning(f"籌碼特徵合併失敗，降級為純技術面：{e}")
            # 確保衍生欄位不殘留
            for col in CHIP_DERIVED:
                if col in df.columns:
                    df.drop(columns=[col], inplace=True)

        return df

    @staticmethod
    def _calc_consecutive(series: pd.Series) -> pd.Series:
        """
        計算連續正值或負值的累計天數。
        例如 [1, 2, 3, -1, -2, 4] → [1, 2, 3, -1, -2, 1]
        """
        result = [0] * len(series)
        for i, val in enumerate(series):
            if i == 0:
                result[i] = 1 if val > 0 else (-1 if val < 0 else 0)
            else:
                if val > 0:
                    result[i] = max(result[i - 1], 0) + 1
                elif val < 0:
                    result[i] = min(result[i - 1], 0) - 1
                else:
                    result[i] = 0
        return pd.Series(result, index=series.index)

    # ─── 美股隔夜訊號 ──────────────────────────────────────────────

    def _build_us_overnight(self, df: pd.DataFrame, us_data: dict | None) -> pd.DataFrame:
        """
        將美股隔夜資料對齊至台股交易日。

        原理：美股 D 日收盤（台灣時間 D+1 凌晨 5 點）
              → 影響台股 D+1 日開盤（9 點）
              → 所以 US date 向前推 1 個營業日對齊

        若無資料則填入預設值（0 / 0.2），min_gain_to_split 會自動忽略。
        """
        self._has_us = False
        if not us_data:
            for col in US_OVERNIGHT_FEATURES:
                df[col] = 0 if col != "vix_level" else 0.2
            return df

        try:
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()

            # S&P 500 / 費半：計算隔夜對數報酬率
            for sym, col_name in [("^GSPC", "sp500_return"), ("^SOX", "sox_return")]:
                if sym in us_data and us_data[sym] is not None and not us_data[sym].empty:
                    us_df = us_data[sym].copy()
                    us_df.index = pd.to_datetime(us_df.index).tz_localize(None).normalize()
                    us_ret = np.log(us_df["Close"] / us_df["Close"].shift(1))
                    # 日期向前推 1 個營業日 → 對齊台股隔日
                    us_ret.index = us_ret.index + pd.offsets.BDay(1)
                    df[col_name] = us_ret.reindex(df.index, method="ffill").fillna(0)
                else:
                    df[col_name] = 0

            # VIX：恐慌指數水位 + 變化率
            if "^VIX" in us_data and us_data["^VIX"] is not None and not us_data["^VIX"].empty:
                vix_df = us_data["^VIX"].copy()
                vix_df.index = pd.to_datetime(vix_df.index).tz_localize(None).normalize()
                vix_close = vix_df["Close"].copy()
                vix_close.index = vix_close.index + pd.offsets.BDay(1)
                vix_aligned = vix_close.reindex(df.index, method="ffill")
                df["vix_level"]  = (vix_aligned / 100).fillna(0.2)   # 標準化到 0~1 區間
                df["vix_change"] = vix_aligned.pct_change().fillna(0)
            else:
                df["vix_level"]  = 0.2
                df["vix_change"] = 0

            self._has_us = True
            logger.info("美股隔夜訊號特徵計算完成")
        except Exception as e:
            logger.warning(f"美股隔夜訊號計算失敗，使用預設值：{e}")
            for col in US_OVERNIGHT_FEATURES:
                if col not in df.columns:
                    df[col] = 0 if col != "vix_level" else 0.2
        return df

    # ─── 多時間框架特徵 ──────────────────────────────────────────

    def _build_multiframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        將日線 resample 成週線，計算週線趨勢與 RSI，再映射回日線。

        週線 MA5 趨勢：週收盤 > 週 MA5 → 1（多頭排列），否則 -1
        週線 RSI：標準化至 0~1
        """
        try:
            df.index = pd.to_datetime(df.index)

            # 週線 resample（以週五收盤為準）
            weekly = df[["Close"]].resample("W-FRI").last().dropna()

            if len(weekly) < 6:
                # 資料太少無法計算週線指標
                df["weekly_ma_trend"] = 0
                df["weekly_rsi"]      = 0.5
                return df

            # 週線 MA5 趨勢
            w_ma5 = weekly["Close"].rolling(5).mean()
            weekly["weekly_ma_trend"] = np.where(weekly["Close"] > w_ma5, 1, -1)

            # 週線 RSI（標準化 0~1）
            weekly["weekly_rsi"] = self._calc_rsi(weekly["Close"], period=14) / 100

            # 映射回日線（forward fill：同一週內每天使用該週的值）
            for col in MULTIFRAME_FEATURES:
                df[col] = weekly[col].reindex(df.index, method="ffill")

            # 填補前幾週 NaN（週線需要 5 週熱身）
            df["weekly_ma_trend"] = df["weekly_ma_trend"].fillna(0)
            df["weekly_rsi"]      = df["weekly_rsi"].fillna(0.5)

            logger.info("多時間框架特徵計算完成")
        except Exception as e:
            logger.warning(f"多時間框架特徵計算失敗：{e}")
            df["weekly_ma_trend"] = 0
            df["weekly_rsi"]      = 0.5
        return df

    # ─── 市場狀態辨識 ────────────────────────────────────────────

    def _build_market_regime(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        根據均線排列判斷市場狀態：

        多頭（1）：Close > MA20 且 MA20 > MA60 → 趨勢向上
        空頭（-1）：Close < MA20 且 MA20 < MA60 → 趨勢向下
        盤整（0）：均線糾結，方向不明
        """
        try:
            ma20 = df["Close"].rolling(20).mean()
            ma60 = df["Close"].rolling(60).mean()

            conditions = [
                (df["Close"] > ma20) & (ma20 > ma60),   # 多頭
                (df["Close"] < ma20) & (ma20 < ma60),   # 空頭
            ]
            choices = [1, -1]
            df["market_regime"] = np.select(conditions, choices, default=0)

            # 統計市場狀態分布
            regime_counts = df["market_regime"].value_counts()
            bull  = regime_counts.get(1, 0)
            bear  = regime_counts.get(-1, 0)
            side  = regime_counts.get(0, 0)
            logger.info(f"市場狀態辨識完成（多頭:{bull} 空頭:{bear} 盤整:{side}）")
        except Exception as e:
            logger.warning(f"市場狀態辨識失敗：{e}")
            df["market_regime"] = 0
        return df

    def get_feature_cols(self) -> list:
        """
        回傳所有用於 LightGBM 訓練的特徵欄位名稱。
        包含：基礎技術面 + 美股隔夜 + 多時間框架 + 市場狀態 + 籌碼（選用）
        """
        base = [
            # 基礎技術面（13 維）
            "log_return",
            "ma5_cross_ma20",
            "macd", "macd_signal", "macd_hist",
            "rsi",
            "bb_bandwidth", "bb_pct_b",
            "atr_ratio",
            "vol_ratio", "vol_change",
            "high_low_ratio", "close_position",
        ]
        # 美股隔夜訊號（4 維，永遠包含）
        base += US_OVERNIGHT_FEATURES
        # 多時間框架（2 維，永遠包含）
        base += MULTIFRAME_FEATURES
        # 市場狀態（1 維，永遠包含）
        base += REGIME_FEATURES
        # 籌碼面（7 維，選用）
        if self._has_chip:
            base += CHIP_DERIVED
        return base

    def get_lstm_input_cols(self) -> list:
        """
        LSTM 時間序列輸入欄位（OHLCV + 技術特徵 + 美股隔夜訊號）。
        籌碼/週線/市場狀態特徵不放進 LSTM，只給 LightGBM 使用。
        美股隔夜的 sp500_return / sox_return 是日頻時序，適合 LSTM 學習。
        """
        return [
            "Open", "High", "Low", "Close", "Volume",
            "log_return",
            "ma5", "ma20",
            "macd", "macd_hist",
            "rsi",
            "bb_bandwidth", "bb_pct_b",
            "atr_ratio",
            "vol_ratio",
            # 美股隔夜訊號（2 維）
            "sp500_return", "sox_return",
        ]

    # ─── 私有計算方法 ───────────────────────────────────────────────

    def _calc_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Wilder 平滑法計算 RSI"""
        delta = prices.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.finfo(float).eps)
        return 100 - (100 / (1 + rs))

    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """計算平均真實區間 ATR"""
        high = df["High"]
        low  = df["Low"]
        prev_close = df["Close"].shift(1)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs()
        ], axis=1).max(axis=1)

        return tr.ewm(alpha=1/period, adjust=False).mean()

    def prepare_latest_features(self, df: pd.DataFrame) -> pd.Series:
        """
        取出最新一筆特徵（用於預測明天）
        需傳入已經過 build_features 的 DataFrame
        """
        feature_cols = self.get_feature_cols()
        return df[feature_cols].iloc[-1]

    def get_chart_data(self, df_raw: pd.DataFrame, df_features: pd.DataFrame) -> dict:
        """
        整理圖表所需的資料（K線 + 均線 + RSI + MACD）

        Returns:
            dict 格式可直接序列化為 JSON 傳給前端圖表
        """
        candles = []
        for idx, row in df_raw.iterrows():
            candles.append({
                "time": idx.strftime("%Y-%m-%d"),
                "open":  round(float(row["Open"]),  2),
                "high":  round(float(row["High"]),  2),
                "low":   round(float(row["Low"]),   2),
                "close": round(float(row["Close"]), 2),
            })

        volumes = []
        for idx, row in df_raw.iterrows():
            volumes.append({
                "time":  idx.strftime("%Y-%m-%d"),
                "value": int(row["Volume"]),
                "color": "#00FF88" if row["Close"] >= row["Open"] else "#FF3366",
            })

        ma5_data, ma20_data = [], []
        if "ma5" in df_features.columns:
            for idx, row in df_features.iterrows():
                if not pd.isna(row["ma5"]):
                    ma5_data.append({"time": idx.strftime("%Y-%m-%d"), "value": round(float(row["ma5"]), 2)})
                if not pd.isna(row["ma20"]):
                    ma20_data.append({"time": idx.strftime("%Y-%m-%d"), "value": round(float(row["ma20"]), 2)})

        return {
            "candles": candles,
            "volumes": volumes,
            "ma5":     ma5_data,
            "ma20":    ma20_data,
        }

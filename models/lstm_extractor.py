"""
LSTM 時間序列特徵萃取器
將過去 60 個交易日的序列壓縮為一個固定維度的「深度時間特徵向量」
供 LightGBM 分類器使用
"""
import os
import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler
import joblib
from logger.app_logger import get_logger

# 檢查 TensorFlow 是否可用
try:
    import tensorflow as tf
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

logger = get_logger(__name__)

# 模型存放路徑
from data.data_paths import MODEL_DIR


def _symbol_to_filename(symbol: str) -> str:
    """將股票代號轉換為安全的檔名（例如 0050.TW → 0050_TW）"""
    return symbol.replace(".", "_").replace("/", "_")

# LSTM 超參數
SEQUENCE_LEN   = 60    # 回望 60 個交易日
LSTM_UNITS     = 64    # 隱藏層維度（即輸出特徵向量維度）
EPOCHS         = 30
BATCH_SIZE     = 32


class LSTMExtractor:
    """
    LSTM 特徵萃取器

    架構：
        Input (60, n_features)
          → LSTM(128, return_sequences=True)
          → Dropout(0.2)
          → LSTM(64)           ← 最後隱藏狀態作為特徵向量
          → Dense(1, sigmoid)  ← 輔助訓練用，不作為最終預測
    """

    def __init__(self, symbol: str = "default"):
        self.symbol = symbol
        _name = _symbol_to_filename(symbol)
        self._model_path  = os.path.join(MODEL_DIR, f"lstm_{_name}.keras")
        self._scaler_path = os.path.join(MODEL_DIR, f"lstm_{_name}_scaler.pkl")

        self.model = None
        self.feature_extractor = None   # 只輸出 LSTM 隱藏狀態的子模型
        self.scaler = RobustScaler()
        self.is_trained = False
        self._n_features = None
        logger.info(f"LSTMExtractor 初始化完成（symbol={symbol}）")

    def _build_model(self, n_features: int):
        """建立 Keras LSTM 模型"""
        try:
            if not TF_AVAILABLE:
                logger.warning("TensorFlow 未安裝，LSTM 功能停用")
                return
            from tensorflow import keras

            inputs = keras.Input(shape=(SEQUENCE_LEN, n_features))
            x = keras.layers.LSTM(128, return_sequences=True)(inputs)
            x = keras.layers.Dropout(0.2)(x)
            lstm_out = keras.layers.LSTM(LSTM_UNITS, name="lstm_features")(x)
            x = keras.layers.Dropout(0.2)(lstm_out)
            output = keras.layers.Dense(1, activation="sigmoid")(x)

            self.model = keras.Model(inputs=inputs, outputs=output)
            self.model.compile(
                optimizer=keras.optimizers.Adam(learning_rate=0.001),
                loss="binary_crossentropy",
                metrics=["accuracy"]
            )

            # 只輸出 LSTM 隱藏狀態的子模型
            self.feature_extractor = keras.Model(
                inputs=inputs,
                outputs=self.model.get_layer("lstm_features").output
            )
            self._n_features = n_features
            logger.info(f"LSTM 模型建立成功，輸入維度：(60, {n_features})")

        except ImportError:
            logger.warning("TensorFlow 未安裝，LSTM 特徵萃取將略過")
            self.model = None

    def train(
        self,
        df: pd.DataFrame,
        input_cols: list,
        label_col: str = "label",
        progress_callback=None
    ) -> bool:
        """
        訓練 LSTM 模型

        Args:
            df: 已完成特徵工程的 DataFrame
            input_cols: 作為 LSTM 輸入的欄位列表
            label_col: 目標標籤欄位名稱
            progress_callback: 進度回呼

        Returns:
            True = 訓練成功
        """
        if not TF_AVAILABLE:
            logger.warning("跳過 LSTM 訓練（TensorFlow 未安裝），僅使用 LightGBM")
            return False

        if progress_callback:
            progress_callback(40, "正在準備 LSTM 訓練資料...")

        # 正規化特徵
        feature_data = df[input_cols].values
        scaled_data = self.scaler.fit_transform(feature_data)

        # 建立時間序列窗口
        X, y = self._create_sequences(scaled_data, df[label_col].values)

        if len(X) < 100:
            logger.warning(f"訓練資料不足（{len(X)} 筆），建議使用更多歷史資料")
            return False

        # 80/20 分割（不隨機，保持時間順序）
        split = int(len(X) * 0.8)
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        self._build_model(n_features=X.shape[2])

        if progress_callback:
            progress_callback(50, f"LSTM 開始訓練（{EPOCHS} 個 Epoch）...")

        import tensorflow as tf
        from tensorflow import keras

        callbacks = [
            keras.callbacks.EarlyStopping(patience=5, restore_best_weights=True),
            keras.callbacks.ReduceLROnPlateau(factor=0.5, patience=3),
        ]

        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=EPOCHS,
            batch_size=BATCH_SIZE,
            callbacks=callbacks,
            verbose=0
        )

        val_acc = max(history.history.get("val_accuracy", [0]))
        logger.info(f"LSTM 訓練完成，最佳驗證準確率：{val_acc:.4f}")

        self.is_trained = True
        self._save()

        if progress_callback:
            progress_callback(65, f"LSTM 訓練完成（驗證準確率 {val_acc:.1%}）")

        return True

    def extract_features(self, df: pd.DataFrame, input_cols: list) -> np.ndarray:
        """
        從最新資料中萃取 LSTM 時間特徵向量

        Returns:
            shape (1, LSTM_UNITS) 的特徵向量
        """
        if self.feature_extractor is None or not self.is_trained:
            logger.warning("LSTM 尚未訓練，回傳空向量")
            return np.zeros((1, LSTM_UNITS))

        feature_data = df[input_cols].values[-SEQUENCE_LEN:]

        if len(feature_data) < SEQUENCE_LEN:
            logger.warning(f"資料不足 {SEQUENCE_LEN} 筆，無法萃取 LSTM 特徵")
            return np.zeros((1, LSTM_UNITS))

        scaled = self.scaler.transform(feature_data)
        X = scaled.reshape(1, SEQUENCE_LEN, -1)
        features = self.feature_extractor.predict(X, verbose=0)
        return features  # shape: (1, LSTM_UNITS)

    def load(self) -> bool:
        """載入已儲存的模型"""
        if not os.path.exists(self._model_path):
            return False
        try:
            from tensorflow import keras
            self.model = keras.models.load_model(self._model_path)
            self.scaler = joblib.load(self._scaler_path)
            self.feature_extractor = keras.Model(
                inputs=self.model.input,
                outputs=self.model.get_layer("lstm_features").output
            )
            self.is_trained = True
            logger.info(f"LSTM 模型載入成功（{self.symbol}）")
            return True
        except Exception as e:
            logger.error(f"LSTM 模型載入失敗：{e}")
            return False

    def _save(self):
        """儲存模型與 Scaler"""
        os.makedirs(MODEL_DIR, exist_ok=True)
        self.model.save(self._model_path)
        joblib.dump(self.scaler, self._scaler_path)
        logger.info(f"LSTM 模型已儲存（{self.symbol}）")

    def _create_sequences(
        self,
        data: np.ndarray,
        labels: np.ndarray
    ):
        """將平坦的時間序列轉換為 3D 滑動窗口張量"""
        X, y = [], []
        for i in range(SEQUENCE_LEN, len(data)):
            X.append(data[i - SEQUENCE_LEN:i])
            y.append(labels[i])
        return np.array(X), np.array(y)

"""
Transformer 時間序列特徵萃取器
將過去 300 個交易日的序列壓縮為一個固定維度的「深度時間特徵向量」
供 LightGBM 分類器使用

相較 LSTM（60 天窗口），Transformer 可有效回望 300 天，
利用 Self-Attention 捕捉長距離依賴（季節性、財報週期、歷史相似型態）。

接口設計與 LSTMExtractor 完全一致，可無縫替換。
"""
import os
import math
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


# ── Transformer 超參數 ──────────────────────────────────────────────
SEQUENCE_LEN   = 300   # 回望 300 個交易日（約 14 個月）
D_MODEL        = 64    # 模型維度（也是輸出特徵向量維度）
N_HEADS        = 4     # Multi-Head Attention 頭數
N_LAYERS       = 3     # Transformer Encoder 層數
D_FF           = 128   # Feed-Forward 隱藏層維度
DROPOUT_RATE   = 0.15  # Dropout 比率
EPOCHS         = 40    # 訓練 Epoch 數
BATCH_SIZE     = 32    # 批次大小
OUTPUT_DIM     = 64    # 輸出特徵向量維度（與 LSTM 的 LSTM_UNITS 對應）


# ── 自訂 Keras 層 ──────────────────────────────────────────────────

def _build_positional_encoding(max_len: int, d_model: int) -> np.ndarray:
    """
    正弦餘弦位置編碼（Sinusoidal Positional Encoding）

    讓模型知道每一天在序列中的位置，
    使其能區分「第 1 天」和「第 300 天」的時間關係。
    """
    pe = np.zeros((max_len, d_model))
    position = np.arange(0, max_len)[:, np.newaxis]
    div_term = np.exp(np.arange(0, d_model, 2) * -(math.log(10000.0) / d_model))

    pe[:, 0::2] = np.sin(position * div_term)
    pe[:, 1::2] = np.cos(position * div_term)
    return pe.astype(np.float32)


def _build_time_decay_weights(n_samples: int, df_index: pd.DatetimeIndex = None) -> np.ndarray:
    """
    時間衰減權重：越近的資料權重越高

    權重分配：
      - 最近 2 年 → 1.0
      - 2~4 年前  → 0.7
      - 4~6 年前  → 0.4
      - 6+ 年前   → 0.2
    """
    if df_index is not None and len(df_index) == n_samples:
        latest_date = df_index.max()
        days_ago = (latest_date - df_index).days
        weights = np.ones(n_samples, dtype=np.float32)
        weights[days_ago > 365 * 2] = 0.7   # 2~4 年前
        weights[days_ago > 365 * 4] = 0.4   # 4~6 年前
        weights[days_ago > 365 * 6] = 0.2   # 6+ 年前
    else:
        # 沒有日期索引時，用線性衰減作為後備
        weights = np.linspace(0.4, 1.0, n_samples).astype(np.float32)
    return weights


class TransformerExtractor:
    """
    Transformer 特徵萃取器

    架構：
        Input (300, n_features)
          → Linear Projection → (300, d_model=64)
          → + Positional Encoding
          → TransformerEncoder × 3 (MultiHeadAttention + FFN)
          → Global Average Pooling
          → Dense(64)  ← 特徵向量（feature_extractor 的輸出）
          → Dense(1, sigmoid)  ← 輔助訓練用，不作為最終預測

    對外接口與 LSTMExtractor 完全一致：
        - train(df, input_cols, label_col, progress_callback) → bool
        - extract_features(df, input_cols) → np.ndarray (1, OUTPUT_DIM)
        - load() → bool
        - _save()
    """

    def __init__(self, symbol: str = "default"):
        self.symbol = symbol
        _name = _symbol_to_filename(symbol)
        self._model_path  = os.path.join(MODEL_DIR, f"transformer_{_name}.keras")
        self._scaler_path = os.path.join(MODEL_DIR, f"transformer_{_name}_scaler.pkl")

        self.model = None
        self.feature_extractor = None   # 只輸出特徵向量的子模型
        self.scaler = RobustScaler()
        self.is_trained = False
        self._n_features = None
        logger.info(f"TransformerExtractor 初始化完成（symbol={symbol}）")

    def _build_model(self, n_features: int):
        """建立 Keras Transformer 模型"""
        try:
            if not TF_AVAILABLE:
                logger.warning("TensorFlow 未安裝，Transformer 功能停用")
                return
            from tensorflow import keras

            # ── 輸入層 ──
            inputs = keras.Input(shape=(SEQUENCE_LEN, n_features), name="input")

            # ── 線性投影：將原始特徵維度映射到 d_model ──
            x = keras.layers.Dense(D_MODEL, name="input_projection")(inputs)

            # ── 位置編碼（加法） ──
            # 使用 Lambda 層讓 positional encoding 成為計算圖的一部分
            pe_matrix = _build_positional_encoding(SEQUENCE_LEN, D_MODEL)
            pe_const = tf.constant(pe_matrix[np.newaxis, :, :])  # (1, seq_len, d_model)
            x = keras.layers.Add(name="pos_encoding")([x, pe_const])

            # ── Dropout（正規化） ──
            x = keras.layers.Dropout(DROPOUT_RATE)(x)

            # ── Transformer Encoder × N_LAYERS ──
            for i in range(N_LAYERS):
                x = self._encoder_block(x, f"encoder_{i}")

            # ── Global Average Pooling：(batch, seq_len, d_model) → (batch, d_model) ──
            pooled = keras.layers.GlobalAveragePooling1D(name="global_pool")(x)

            # ── 特徵向量層 ──
            feature_vec = keras.layers.Dense(
                OUTPUT_DIM, activation="relu", name="feature_vector"
            )(pooled)

            # ── 分類頭（輔助訓練用） ──
            drop = keras.layers.Dropout(DROPOUT_RATE)(feature_vec)
            output = keras.layers.Dense(1, activation="sigmoid", name="output")(drop)

            # ── 組裝模型 ──
            self.model = keras.Model(inputs=inputs, outputs=output)

            self.model.compile(
                optimizer=keras.optimizers.Adam(learning_rate=5e-4),
                loss="binary_crossentropy",
                metrics=["accuracy"]
            )

            # ── 特徵萃取子模型（只到 feature_vector 層） ──
            self.feature_extractor = keras.Model(
                inputs=inputs,
                outputs=self.model.get_layer("feature_vector").output
            )
            self._n_features = n_features

            total_params = self.model.count_params()
            logger.info(
                f"Transformer 模型建立成功，"
                f"輸入維度：({SEQUENCE_LEN}, {n_features})，"
                f"總參數：{total_params:,}"
            )

        except ImportError:
            logger.warning("TensorFlow 未安裝，Transformer 特徵萃取將略過")
            self.model = None

    def _encoder_block(self, x, name_prefix: str):
        """
        單一 Transformer Encoder Block

        結構：
            x → LayerNorm → MultiHeadAttention → Dropout → + Residual
              → LayerNorm → FFN → Dropout → + Residual

        使用 Pre-LN（LayerNorm 在 Attention/FFN 之前），
        訓練穩定性比 Post-LN 更好。
        """
        from tensorflow import keras

        # ── Multi-Head Self-Attention ──
        attn_input = keras.layers.LayerNormalization(
            name=f"{name_prefix}_ln1"
        )(x)
        attn_output = keras.layers.MultiHeadAttention(
            num_heads=N_HEADS,
            key_dim=D_MODEL // N_HEADS,
            dropout=DROPOUT_RATE,
            name=f"{name_prefix}_mha"
        )(attn_input, attn_input)
        attn_output = keras.layers.Dropout(DROPOUT_RATE)(attn_output)
        x = keras.layers.Add(name=f"{name_prefix}_add1")([x, attn_output])

        # ── Position-wise Feed-Forward Network ──
        ffn_input = keras.layers.LayerNormalization(
            name=f"{name_prefix}_ln2"
        )(x)
        ffn = keras.layers.Dense(D_FF, activation="gelu", name=f"{name_prefix}_ffn1")(ffn_input)
        ffn = keras.layers.Dropout(DROPOUT_RATE)(ffn)
        ffn = keras.layers.Dense(D_MODEL, name=f"{name_prefix}_ffn2")(ffn)
        ffn = keras.layers.Dropout(DROPOUT_RATE)(ffn)
        x = keras.layers.Add(name=f"{name_prefix}_add2")([x, ffn])

        return x

    def train(
        self,
        df: pd.DataFrame,
        input_cols: list,
        label_col: str = "label",
        progress_callback=None
    ) -> bool:
        """
        訓練 Transformer 模型

        Args:
            df: 已完成特徵工程的 DataFrame
            input_cols: 作為 Transformer 輸入的欄位列表
            label_col: 目標標籤欄位名稱
            progress_callback: 進度回呼

        Returns:
            True = 訓練成功
        """
        if not TF_AVAILABLE:
            logger.warning("跳過 Transformer 訓練（TensorFlow 未安裝），僅使用 LightGBM")
            return False

        if progress_callback:
            progress_callback(40, "正在準備 Transformer 訓練資料...")

        # ── 正規化特徵 ──
        feature_data = df[input_cols].values
        scaled_data = self.scaler.fit_transform(feature_data)

        # ── 建立時間序列窗口 ──
        X, y = self._create_sequences(scaled_data, df[label_col].values)

        if len(X) < 100:
            logger.warning(f"訓練資料不足（{len(X)} 筆），建議使用更多歷史資料")
            return False

        # ── 計算時間衰減權重 ──
        # 序列起始位置對應的日期索引（每個窗口以最後一天的日期為代表）
        seq_end_indices = df.index[SEQUENCE_LEN:][:len(y)]
        sample_weights = _build_time_decay_weights(len(y), seq_end_indices)

        # ── 80/20 分割（保持時間順序，不隨機打亂） ──
        split = int(len(X) * 0.8)
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]
        w_train, w_val = sample_weights[:split], sample_weights[split:]

        # ── 建立模型 ──
        self._build_model(n_features=X.shape[2])

        if self.model is None:
            return False

        if progress_callback:
            progress_callback(45, f"Transformer 開始訓練（{EPOCHS} 個 Epoch，{len(X_train)} 筆資料）...")

        from tensorflow import keras

        # ── 回調函數 ──
        # 注意：不使用 ReduceLROnPlateau，EarlyStopping 已足夠
        callbacks = [
            keras.callbacks.EarlyStopping(
                patience=8,
                restore_best_weights=True,
                monitor="val_loss",
                verbose=0
            ),
        ]

        # ── 自訂進度回呼 ──
        class ProgressCallback(keras.callbacks.Callback):
            def __init__(self, total_epochs, emit_fn):
                super().__init__()
                self.total_epochs = total_epochs
                self.emit_fn = emit_fn

            def on_epoch_end(self, epoch, logs=None):
                if self.emit_fn and epoch % 5 == 0:
                    # 進度範圍：45% → 63%（留空間給後續步驟）
                    pct = 45 + int((epoch / self.total_epochs) * 18)
                    val_acc = logs.get("val_accuracy", 0)
                    self.emit_fn(
                        pct,
                        f"Transformer 訓練中（Epoch {epoch+1}/{self.total_epochs}，"
                        f"驗證準確率 {val_acc:.1%}）..."
                    )

        if progress_callback:
            callbacks.append(ProgressCallback(EPOCHS, progress_callback))

        # ── 訓練 ──
        history = self.model.fit(
            X_train, y_train,
            sample_weight=w_train,
            validation_data=(X_val, y_val, w_val),
            epochs=EPOCHS,
            batch_size=BATCH_SIZE,
            callbacks=callbacks,
            verbose=0
        )

        val_acc = max(history.history.get("val_accuracy", [0]))
        val_loss = min(history.history.get("val_loss", [999]))
        actual_epochs = len(history.history.get("loss", []))
        logger.info(
            f"Transformer 訓練完成，"
            f"共 {actual_epochs} Epochs，"
            f"最佳驗證準確率：{val_acc:.4f}，"
            f"最佳驗證損失：{val_loss:.4f}"
        )

        self.is_trained = True
        self._save()

        if progress_callback:
            progress_callback(65, f"Transformer 訓練完成（驗證準確率 {val_acc:.1%}）")

        return True

    def extract_features(self, df: pd.DataFrame, input_cols: list) -> np.ndarray:
        """
        從最新資料中萃取 Transformer 時間特徵向量

        Returns:
            shape (1, OUTPUT_DIM) 的特徵向量
        """
        if self.feature_extractor is None or not self.is_trained:
            logger.warning("Transformer 尚未訓練，回傳空向量")
            return np.zeros((1, OUTPUT_DIM))

        feature_data = df[input_cols].values[-SEQUENCE_LEN:]

        if len(feature_data) < SEQUENCE_LEN:
            # 資料不足時用零填充（左側填零，右側放實際資料）
            pad_len = SEQUENCE_LEN - len(feature_data)
            feature_data = np.vstack([
                np.zeros((pad_len, feature_data.shape[1])),
                feature_data
            ])
            logger.warning(
                f"資料不足 {SEQUENCE_LEN} 筆（實際 {len(feature_data) - pad_len} 筆），"
                f"已左側零填充"
            )

        scaled = self.scaler.transform(feature_data)
        X = scaled.reshape(1, SEQUENCE_LEN, -1)
        features = self.feature_extractor.predict(X, verbose=0)
        return features  # shape: (1, OUTPUT_DIM)

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
                outputs=self.model.get_layer("feature_vector").output
            )
            self.is_trained = True
            logger.info(f"Transformer 模型載入成功（{self.symbol}）")
            return True
        except Exception as e:
            logger.error(f"Transformer 模型載入失敗：{e}")
            return False

    def _save(self):
        """儲存模型與 Scaler"""
        os.makedirs(MODEL_DIR, exist_ok=True)
        self.model.save(self._model_path)
        joblib.dump(self.scaler, self._scaler_path)
        logger.info(f"Transformer 模型已儲存（{self.symbol}）")

    def _create_sequences(
        self,
        data: np.ndarray,
        labels: np.ndarray
    ):
        """
        將平坦的時間序列轉換為 3D 滑動窗口張量

        Returns:
            X: shape (n_windows, SEQUENCE_LEN, n_features)
            y: shape (n_windows,)
        """
        X, y = [], []
        for i in range(SEQUENCE_LEN, len(data)):
            X.append(data[i - SEQUENCE_LEN:i])
            y.append(labels[i])
        return np.array(X), np.array(y)

"""
LightGBM 分類器（自我進化版）
融合 LSTM 時間特徵向量 + 橫截面技術/籌碼特徵，進行明日漲跌二元分類

自我進化機制：
- Ensemble 投票：TimeSeriesSplit 訓練 3 個模型，平均預測
- 增量式訓練：retrain 時以上一代模型為基礎繼續訓練
- 特徵自動篩選：min_gain_to_split 自動忽略雜訊特徵
"""
import os
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from datetime import datetime
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix
from sklearn.preprocessing import RobustScaler
import joblib
from logger.app_logger import get_logger

logger = get_logger(__name__)

from data.data_paths import MODEL_DIR

# 自動重訓門檻（天數）
AUTO_RETRAIN_DAYS = 7

# Ensemble 模型數量
ENSEMBLE_SIZE = 3


def _symbol_to_filename(symbol: str) -> str:
    """將股票代號轉換為安全的檔名（例如 0050.TW → 0050_TW）"""
    return symbol.replace(".", "_").replace("/", "_")


class LGBMClassifier:
    """
    LightGBM 漲跌分類器（Ensemble 版）

    輸入特徵 = LSTM 時間特徵向量（64維）+ 今日技術面特徵（13維）
    輸出 = 上漲機率 [0.0, 1.0]（3 個模型平均）
    """

    LGBM_PARAMS = {
        "objective":       "binary",
        "metric":          "binary_logloss",
        "boosting_type":   "gbdt",
        "n_estimators":    500,
        "learning_rate":   0.05,
        "num_leaves":      31,
        "max_depth":       -1,
        "min_child_samples": 20,
        "min_gain_to_split": 0.01,   # 自動忽略增益不足的特徵分裂
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq":    5,
        "lambda_l1":       0.1,
        "lambda_l2":       0.1,
        "random_state":    42,
        "n_jobs":          -1,
        "verbose":         -1,
    }

    def __init__(self, symbol: str = "default"):
        self.symbol = symbol
        _name = _symbol_to_filename(symbol)

        # Ensemble 路徑：每個 fold 一組 (model, scaler)
        self._ensemble_model_paths = [
            os.path.join(MODEL_DIR, f"lgbm_{_name}_e{i}.pkl")
            for i in range(ENSEMBLE_SIZE)
        ]
        self._ensemble_scaler_paths = [
            os.path.join(MODEL_DIR, f"lgbm_{_name}_e{i}_scaler.pkl")
            for i in range(ENSEMBLE_SIZE)
        ]
        # 舊版單一模型路徑（向下相容載入用）
        self._legacy_model_path  = os.path.join(MODEL_DIR, f"lgbm_{_name}.pkl")
        self._legacy_scaler_path = os.path.join(MODEL_DIR, f"lgbm_{_name}_scaler.pkl")
        self._ts_path = os.path.join(MODEL_DIR, f"lgbm_{_name}_timestamp.json")

        # Ensemble 狀態
        self.models = []     # list of (model, scaler) tuples
        self.model = None    # 向下相容：指向最後一個 fold 的 model（SHAP 用）
        self.scaler = None   # 向下相容：指向最後一個 fold 的 scaler（SHAP 用）
        self.is_trained = False
        self.feature_importances = {}
        self.eval_metrics = {}
        logger.info(f"LGBMClassifier 初始化完成（symbol={symbol}）")

    def train(
        self,
        df: pd.DataFrame,
        feature_cols: list,
        lstm_features: np.ndarray,   # shape: (n_samples, 64)
        label_col: str = "label",
        progress_callback=None
    ) -> dict:
        """
        Ensemble 訓練：用 TimeSeriesSplit 產生 3 個 fold，每個 fold 訓練一個模型。
        若有上一代模型，以 init_model 進行增量式訓練。
        """
        if progress_callback:
            progress_callback(68, "正在合併 LSTM 特徵與技術特徵...")

        # 取出技術面特徵
        tech_features = df[feature_cols].values

        # 對齊長度（LSTM 需要 60 個 timestep 才能開始，所以行數較少）
        n = min(len(tech_features), len(lstm_features))
        tech_features  = tech_features[-n:]
        lstm_feat_trim = lstm_features[-n:]
        labels = df[label_col].values[-n:]

        # 合併特徵
        X = np.concatenate([lstm_feat_trim, tech_features], axis=1)
        y = labels

        # ── 載入上一代模型作為增量學習基礎 ──
        prev_models = self._load_previous_ensemble()

        # ── TimeSeriesSplit Ensemble 訓練 ──
        tscv = TimeSeriesSplit(n_splits=ENSEMBLE_SIZE)
        self.models = []
        fold_metrics = []

        for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]

            scaler = RobustScaler()
            X_train_s = scaler.fit_transform(X_train)
            X_test_s  = scaler.transform(X_test)

            if progress_callback:
                progress_callback(
                    70 + fold_idx * 4,
                    f"Ensemble 訓練中（Fold {fold_idx + 1}/{ENSEMBLE_SIZE}，"
                    f"訓練集 {len(X_train)} 筆）..."
                )

            # 增量學習：若有上一代對應 fold 的模型，用作 init_model
            # 注意：特徵數不符時必須跳過（例如新增美股隔夜特徵後 77→84）
            init_model = None
            if fold_idx < len(prev_models):
                prev_model = prev_models[fold_idx][0]
                prev_n = getattr(prev_model, "n_features_in_", None)
                if prev_n is not None and prev_n != X.shape[1]:
                    if fold_idx == 0:
                        logger.info(f"增量學習跳過：舊模型特徵數 {prev_n} ≠ 當前 {X.shape[1]}，改為全新訓練")
                    prev_models = []  # 清空，後續 fold 也不再嘗試
                else:
                    init_model = prev_model

            model = lgb.LGBMClassifier(**self.LGBM_PARAMS)
            model.fit(
                X_train_s, y_train,
                eval_set=[(X_test_s, y_test)],
                callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
                init_model=init_model,
            )

            # 評估
            y_pred = model.predict(X_test)
            acc = accuracy_score(y_test, y_pred)
            f1  = f1_score(y_test, y_pred, zero_division=0)

            fold_metrics.append({"accuracy": acc, "f1": f1, "test_samples": len(y_test)})
            self.models.append((model, scaler))

            logger.info(f"Ensemble Fold {fold_idx + 1}/{ENSEMBLE_SIZE} | "
                        f"準確率：{acc:.4f} | F1：{f1:.4f}")

        # ── 彙整 Ensemble 指標 ──
        avg_acc = np.mean([m["accuracy"] for m in fold_metrics])
        avg_f1  = np.mean([m["f1"] for m in fold_metrics])

        # 最後一個 fold 通常最具代表性（最大訓練集）
        last_model, last_scaler = self.models[-1]
        self.model  = last_model
        self.scaler = last_scaler

        # 用最後一個 fold 計算 confusion matrix
        last_test_idx = list(tscv.split(X))[-1][1]
        X_last_test_s = last_scaler.transform(X[last_test_idx])
        y_last_pred   = last_model.predict(X_last_test_s)
        cm = confusion_matrix(y[last_test_idx], y_last_pred)

        self.eval_metrics = {
            "accuracy":         round(avg_acc, 4),
            "f1_score":         round(avg_f1, 4),
            "confusion_matrix": cm.tolist(),
            "test_samples":     sum(m["test_samples"] for m in fold_metrics),
            "ensemble_size":    ENSEMBLE_SIZE,
            "fold_details":     [
                {"fold": i + 1, "accuracy": round(m["accuracy"], 4), "f1": round(m["f1"], 4)}
                for i, m in enumerate(fold_metrics)
            ],
            "incremental":      len(prev_models) > 0,
        }

        # 特徵重要性（用最後一個 fold，最具代表性）
        if hasattr(last_model, "feature_importances_"):
            importances = last_model.feature_importances_
            lstm_names = [f"lstm_{i}" for i in range(lstm_feat_trim.shape[1])]
            all_names  = lstm_names + feature_cols
            self.feature_importances = dict(zip(all_names, importances.tolist()))

        logger.info(f"Ensemble 訓練完成 | 平均準確率：{avg_acc:.4f} | 平均 F1：{avg_f1:.4f}"
                    + (" | 增量學習" if len(prev_models) > 0 else " | 全新訓練"))
        self.is_trained = True
        self._save()

        if progress_callback:
            progress_callback(85, f"Ensemble 訓練完成！平均準確率 {avg_acc:.1%}，F1 {avg_f1:.4f}")

        return self.eval_metrics

    def predict(self, lstm_feature: np.ndarray, tech_feature: np.ndarray) -> dict:
        """
        Ensemble 預測：所有模型各自預測，取平均機率。
        """
        if not self.is_trained or not self.models:
            logger.error("模型尚未訓練，無法預測")
            return {"up_prob": 0.5, "down_prob": 0.5, "prediction": -1}

        X = np.concatenate([lstm_feature, tech_feature], axis=1)

        all_probs = []
        for model, scaler in self.models:
            X_scaled = scaler.transform(X)
            prob = model.predict_proba(X_scaled)[0]
            all_probs.append(prob[1])  # 上漲機率

        avg_up_prob   = float(np.mean(all_probs))
        avg_down_prob = 1.0 - avg_up_prob
        std_prob      = float(np.std(all_probs))

        result = {
            "up_prob":      round(avg_up_prob, 4),
            "down_prob":    round(avg_down_prob, 4),
            "prediction":   1 if avg_up_prob > 0.5 else 0,
            "model_probs":  [round(p, 4) for p in all_probs],
            "ensemble_std": round(std_prob, 4),
        }

        detail = " | ".join([f"M{i+1}={p:.1%}" for i, p in enumerate(all_probs)])
        logger.info(f"預測結果：上漲 {avg_up_prob:.1%} / 下跌 {avg_down_prob:.1%}（{detail}）"
                    f"  分散度={std_prob:.4f}")
        return result

    def get_shap_explanation(self, lstm_feature: np.ndarray, tech_feature: np.ndarray, feature_cols: list) -> list:
        """
        使用 SHAP 計算特徵貢獻度（使用最後一個 fold 的模型）
        返回前 5 大影響因子的說明文字列表
        """
        try:
            import shap
            X = np.concatenate([lstm_feature, tech_feature], axis=1)
            X_scaled = self.scaler.transform(X)

            lstm_names = [f"lstm_{i}" for i in range(lstm_feature.shape[1])]
            all_names  = lstm_names + feature_cols

            explainer   = shap.TreeExplainer(self.model)
            shap_values = explainer.shap_values(X_scaled)

            if isinstance(shap_values, list):
                shap_vals = shap_values[1][0]
            else:
                shap_vals = shap_values[0]

            # 取前 5 大絕對貢獻的技術面特徵（跳過 LSTM 潛藏特徵）
            tech_start = lstm_feature.shape[1]
            tech_shap  = shap_vals[tech_start:]
            top_idx    = np.argsort(np.abs(tech_shap))[::-1][:5]

            explanations = []
            for idx in top_idx:
                name  = feature_cols[idx]
                value = tech_shap[idx]
                direction = "看多" if value > 0 else "看空"
                explanations.append(f"• {self._feature_label(name)}：{direction} ({value:+.3f})")

            return explanations

        except ImportError:
            return ["（安裝 shap 套件以啟用特徵解析）"]
        except Exception as e:
            logger.warning(f"SHAP 計算失敗：{e}")
            return []

    def _feature_label(self, name: str) -> str:
        """將英文特徵名稱轉換為中文說明"""
        labels = {
            "log_return":       "今日對數報酬",
            "ma5_cross_ma20":   "均線金死叉強度",
            "macd":             "MACD 值",
            "macd_signal":      "MACD 訊號線",
            "macd_hist":        "MACD 柱狀圖",
            "rsi":              "RSI 強弱指數",
            "bb_bandwidth":     "布林通道寬度",
            "bb_pct_b":         "布林 %b 位置",
            "atr_ratio":        "ATR 波動率",
            "vol_ratio":        "量比（今量/均量）",
            "vol_change":       "成交量變化率",
            "high_low_ratio":   "當日振幅",
            "close_position":   "收盤強弱位置",
            # 美股隔夜訊號
            "sp500_return":     "美股 S&P500 隔夜漲跌",
            "sox_return":       "費半指數隔夜漲跌",
            "vix_level":        "VIX 恐慌指數水位",
            "vix_change":       "VIX 變化率",
            # 多時間框架
            "weekly_ma_trend":  "週線均線趨勢",
            "weekly_rsi":       "週線 RSI 強弱",
            # 市場狀態
            "market_regime":         "市場狀態（多/空/盤）",
            "regime_strength":       "趨勢強度",
            "regime_duration":       "行情持續天數",
            "volatility_regime":     "波動率狀態",
            # 二階籌碼特徵
            "fi_accel":              "外資買超加速度",
            "it_consecutive":        "投信連續買超天數",
            "chip_sync":             "籌碼共振（外資+投信）",
            "margin_price_diverge":  "融資股價背離",
            "fi_net_ma5":            "外資淨買超5日均值",
            "it_net_ma5":            "投信淨買超5日均值",
        }
        return labels.get(name, name)

    def load(self, expected_n_features: int | None = None) -> bool:
        """
        載入已儲存的 Ensemble 模型。
        優先載入 Ensemble 格式，找不到則嘗試載入舊版單一模型。
        若傳入 expected_n_features 且與儲存時不符，回傳 False 強制重訓。
        """
        # 嘗試載入 Ensemble 格式
        loaded = self._load_ensemble(expected_n_features)
        if loaded:
            return True

        # Fallback：嘗試載入舊版單一模型
        return self._load_legacy(expected_n_features)

    def _load_ensemble(self, expected_n_features: int | None = None) -> bool:
        """載入 Ensemble 格式的模型"""
        # 檢查至少第一個 fold 是否存在
        if not os.path.exists(self._ensemble_model_paths[0]):
            return False

        try:
            models = []
            for i in range(ENSEMBLE_SIZE):
                m_path = self._ensemble_model_paths[i]
                s_path = self._ensemble_scaler_paths[i]
                if not os.path.exists(m_path) or not os.path.exists(s_path):
                    break
                model  = joblib.load(m_path)
                scaler = joblib.load(s_path)

                # 特徵數防護
                if expected_n_features is not None:
                    saved_n = getattr(model, "n_features_in_", None)
                    if saved_n is not None and saved_n != expected_n_features:
                        logger.warning(
                            f"Ensemble 特徵數不符（模型={saved_n}，當前={expected_n_features}），"
                            f"強制重訓（{self.symbol}）"
                        )
                        return False

                models.append((model, scaler))

            if not models:
                return False

            self.models = models
            self.model  = models[-1][0]
            self.scaler = models[-1][1]
            self.is_trained = True

            # 載入 eval_metrics
            self._load_eval_metrics()

            logger.info(f"Ensemble 模型載入成功（{self.symbol}，{len(models)} 個模型）")
            return True
        except Exception as e:
            logger.error(f"Ensemble 模型載入失敗：{e}")
            return False

    def _load_legacy(self, expected_n_features: int | None = None) -> bool:
        """載入舊版單一模型（向下相容）"""
        if not os.path.exists(self._legacy_model_path):
            return False
        try:
            model  = joblib.load(self._legacy_model_path)
            scaler = joblib.load(self._legacy_scaler_path)

            # 特徵數防護
            if expected_n_features is not None:
                saved_n = getattr(model, "n_features_in_", None)
                if saved_n is not None and saved_n != expected_n_features:
                    logger.warning(
                        f"LightGBM 特徵數不符（模型={saved_n}，當前={expected_n_features}），"
                        f"強制重訓（{self.symbol}）"
                    )
                    return False

            # 包裝成單一模型的 Ensemble
            self.models = [(model, scaler)]
            self.model  = model
            self.scaler = scaler
            self.is_trained = True

            logger.info(f"舊版 LightGBM 模型載入成功（{self.symbol}，相容模式）")
            return True
        except Exception as e:
            logger.error(f"LightGBM 模型載入失敗：{e}")
            return False

    def _load_previous_ensemble(self) -> list:
        """
        載入上一代的 Ensemble 模型，用於增量學習的 init_model。
        不影響當前實例狀態。
        """
        prev_models = []
        for i in range(ENSEMBLE_SIZE):
            m_path = self._ensemble_model_paths[i]
            if os.path.exists(m_path):
                try:
                    model = joblib.load(m_path)
                    prev_models.append((model, None))
                except Exception:
                    break
            else:
                # 嘗試舊版單一模型作為 init（所有 fold 共用）
                if i == 0 and os.path.exists(self._legacy_model_path):
                    try:
                        model = joblib.load(self._legacy_model_path)
                        prev_models.append((model, None))
                    except Exception:
                        pass
                break
        return prev_models

    def _save(self):
        """儲存 Ensemble 模型"""
        os.makedirs(MODEL_DIR, exist_ok=True)

        for i, (model, scaler) in enumerate(self.models):
            joblib.dump(model,  self._ensemble_model_paths[i])
            joblib.dump(scaler, self._ensemble_scaler_paths[i])

        # 同時存一份到舊版路徑（向下相容）
        if self.models:
            joblib.dump(self.models[-1][0], self._legacy_model_path)
            joblib.dump(self.models[-1][1], self._legacy_scaler_path)

        # 儲存 timestamp + eval_metrics
        ts_data = {
            "trained_at": datetime.now().isoformat(),
            "ensemble_size": len(self.models),
            "eval_metrics": self.eval_metrics,
        }
        with open(self._ts_path, "w") as f:
            json.dump(ts_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Ensemble 模型已儲存（{self.symbol}，{len(self.models)} 個模型）")

    def _load_eval_metrics(self):
        """從 timestamp JSON 載入 eval_metrics"""
        if os.path.exists(self._ts_path):
            try:
                with open(self._ts_path, "r") as f:
                    data = json.load(f)
                self.eval_metrics = data.get("eval_metrics", {})
            except Exception:
                pass

    @staticmethod
    def needs_retrain(symbol: str = "default") -> tuple[bool, str]:
        """
        檢查指定股票的模型是否需要重新訓練

        Returns:
            (需要重訓: bool, 原因說明: str)
        """
        _name      = _symbol_to_filename(symbol)
        # 檢查 Ensemble 或舊版模型是否存在
        ensemble_path = os.path.join(MODEL_DIR, f"lgbm_{_name}_e0.pkl")
        legacy_path   = os.path.join(MODEL_DIR, f"lgbm_{_name}.pkl")
        ts_path       = os.path.join(MODEL_DIR, f"lgbm_{_name}_timestamp.json")

        if not os.path.exists(ensemble_path) and not os.path.exists(legacy_path):
            return True, "尚無已訓練模型"

        if not os.path.exists(ts_path):
            return True, "找不到訓練時間記錄"

        try:
            with open(ts_path, "r") as f:
                data = json.load(f)
            trained_at = datetime.fromisoformat(data["trained_at"])
            days_ago = (datetime.now() - trained_at).days
            if days_ago >= AUTO_RETRAIN_DAYS:
                return True, f"模型已 {days_ago} 天未更新（門檻 {AUTO_RETRAIN_DAYS} 天）"
            return False, f"[{symbol}] 模型上次訓練於 {days_ago} 天前"
        except Exception as e:
            return True, f"時間戳記讀取失敗：{e}"

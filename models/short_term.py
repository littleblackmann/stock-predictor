"""Causal 1/3/5-session forecasts with purged walk-forward evaluation.

The production path deliberately does not reuse legacy Transformer embeddings:
those were trained before the outer folds and cannot give out-of-time scores.
Every fold fits its own model and probability calibrator using past rows only.
"""
import hashlib
import json
import os
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss
from sklearn.model_selection import TimeSeriesSplit

ENGINE_VERSION = "short-term-1"
HORIZONS = (1, 3, 5)
MIN_ROWS = 420


def make_target(close, horizon):
    future = close.shift(-horizon)
    return (future > close).astype(float).where(future.notna())


def temporal_partitions(n, horizon):
    """Outer test never participates in training, calibration or early stopping."""
    for train, test in TimeSeriesSplit(n_splits=3, gap=horizon).split(np.arange(n)):
        cut = max(50, int(len(train) * .75))
        fit = train[:cut - horizon]
        calibration = train[cut:]
        yield fit, calibration, test


def _logits(p):
    p = np.clip(p, 1e-5, 1 - 1e-5)
    return np.log(p / (1 - p)).reshape(-1, 1)


def _fit(X, y, fit, calibration):
    # Constant columns are removed per fold, not using future data.
    active = np.flatnonzero(np.nanstd(X[fit], axis=0) > 1e-10)
    prior = float((y[fit].sum() + 1) / (len(fit) + 2))
    if len(active) == 0 or len(np.unique(y[fit])) < 2:
        return {"model": None, "active": active, "prior": prior, "calibrator": None}
    model = lgb.LGBMClassifier(
        n_estimators=100, learning_rate=.035, num_leaves=7, max_depth=3,
        min_child_samples=25, reg_lambda=3, reg_alpha=.2,
        is_unbalance=False, n_jobs=2, random_state=42, verbosity=-1,
    )
    model.fit(X[fit][:, active], y[fit])
    calibrator = None
    if len(calibration) >= 30 and len(np.unique(y[calibration])) == 2:
        p = model.predict_proba(X[calibration][:, active])[:, 1]
        calibrator = LogisticRegression(C=.1, random_state=42)
        calibrator.fit(_logits(p), y[calibration])
    return {"model": model, "active": active, "prior": prior, "calibrator": calibrator}


def _predict(bundle, X):
    if bundle["model"] is None:
        return np.full(len(X), bundle["prior"])
    p = bundle["model"].predict_proba(X[:, bundle["active"]])[:, 1]
    if bundle["calibrator"] is not None:
        p = bundle["calibrator"].predict_proba(_logits(p))[:, 1]
    return p


def forecast_frame(features, feature_cols, raw_close, progress=None):
    results = []
    # Known price outcomes come from the original session index, not a compressed
    # frame where missing indicator rows would change the meaning of "3 days".
    for number, horizon in enumerate(HORIZONS):
        target = make_target(raw_close, horizon).reindex(features.index)
        known = target.notna()
        train_frame = features.loc[known]
        if len(train_frame) < MIN_ROWS:
            raise ValueError(f"需至少 {MIN_ROWS} 筆有效歷史資料，目前只有 {len(train_frame)} 筆")
        X = train_frame[feature_cols].to_numpy(dtype=float)
        y = target.loc[known].to_numpy(dtype=int)
        actual, probabilities, baseline, folds = [], [], [], []
        for fit, calibration, test in temporal_partitions(len(X), horizon):
            bundle = _fit(X, y, fit, calibration)
            p = _predict(bundle, X[test])
            # Baseline knows only the prefix of labels available at this fold.
            known_prefix = np.concatenate([fit, calibration])
            base_p = float(y[known_prefix].mean())
            actual.extend(y[test].tolist())
            probabilities.extend(p.tolist())
            baseline.extend([base_p] * len(test))
            folds.append({
                "fit_end": str(train_frame.index[fit[-1]].date()),
                "calibration_start": str(train_frame.index[calibration[0]].date()),
                "calibration_end": str(train_frame.index[calibration[-1]].date()),
                "test_start": str(train_frame.index[test[0]].date()),
                "test_end": str(train_frame.index[test[-1]].date()),
                "accuracy": float(accuracy_score(y[test], p > .5)),
                "samples": len(test),
            })
        actual = np.asarray(actual)
        probabilities = np.asarray(probabilities)
        baseline = np.asarray(baseline)
        accuracy = float(accuracy_score(actual, probabilities > .5))
        base_accuracy = float(accuracy_score(actual, baseline > .5))
        brier = float(brier_score_loss(actual, probabilities))
        base_brier = float(brier_score_loss(actual, baseline))
        # Final production fit uses a recent held-out calibration block; the
        # historical score above is never recomputed on this refitted model.
        cut = int(len(X) * .8)
        final = _fit(X, y, np.arange(cut - horizon), np.arange(cut, len(X)))
        up = float(_predict(final, features[feature_cols].iloc[[-1]].to_numpy(dtype=float))[0])
        has_edge = accuracy > base_accuracy and brier < base_brier
        note = "歷史回測尚未優於基準，請保守參考" if not has_edge else "歷史回測優於基準，仍需持續驗證"
        direction = 1 if up > .5 else 0
        if abs(up - .5) < .05 or not has_edge:
            direction = -1
        metrics = {"accuracy": accuracy, "baseline_accuracy": base_accuracy,
                   "brier": brier, "baseline_brier": base_brier,
                   "test_samples": len(actual), "fold_details": folds,
                   "method": "purged_walk_forward", "horizon": horizon}
        results.append({"horizon": horizon, "up_prob": round(up, 4),
                        "down_prob": round(1-up, 4), "raw_up_prob": round(up, 4),
                        "prediction": direction, "confidence_level": "medium" if direction != -1 else "low",
                        "confidence_note": note, "eval_metrics": metrics,
                        "model_version": ENGINE_VERSION, "gpt_adjusted": False})
        if progress:
            progress(55 + (number + 1) * 10, f"{horizon} 個交易日模型與歷史驗證完成")
    return results


def cached_forecast(features, cols, close, symbol, model_dir, force=False, progress=None):
    # Content fingerprint catches revised prices and feature availability as well
    # as new sessions. A separate namespace leaves all legacy models intact.
    digest = hashlib.sha256(pd.util.hash_pandas_object(features[cols], index=True).values.tobytes())
    digest.update(pd.util.hash_pandas_object(close, index=True).values.tobytes())
    digest.update(json.dumps([ENGINE_VERSION, cols]).encode())
    key = digest.hexdigest()
    safe = ''.join(c for c in symbol if c.isalnum() or c in '._-')
    path = Path(model_dir) / f"short_term_{safe}.json"
    if not force and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached["fingerprint"] == key:
                return cached["results"]
        except (OSError, ValueError, KeyError):
            pass
    results = forecast_frame(features, cols, close, progress)
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"fingerprint": key, "results": results}, f, ensure_ascii=False)
    os.replace(tmp, path)
    return results

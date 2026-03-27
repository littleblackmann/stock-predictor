"""
預測記錄管理器
- 每次預測後自動 append 一筆記錄
- 啟動時 / 預測時自動回填 actual 結果（透過 yfinance）
- 提供準確率統計
"""
import csv
import json
import os
from collections import defaultdict
from datetime import date, timedelta

import yfinance as yf

from data.data_paths import PREDICTION_LOG as LOG_PATH, COOLDOWN_PATH

FIELDS = [
    "prediction_date",   # 執行預測當天 YYYY-MM-DD
    "symbol",            # 股票代碼
    "predicted",         # up / down
    "up_prob",           # 上漲機率 float
    "down_prob",         # 下跌機率 float
    "gpt_3day",          # GPT 3日走勢摘要（截斷）
    "actual",            # up / down（回填）
    "actual_return",     # 實際漲跌% float（回填）
    "correct",           # True / False（回填）
]


class PredictionLogger:

    # ── 寫入 ──────────────────────────────────────────────────────

    @staticmethod
    def append(result: dict) -> None:
        """預測完成後寫入一筆空 actual 的記錄"""
        pred     = result.get("prediction", {})
        forecast = result.get("forecast_3d", "") or ""

        # 3日走勢轉成可讀文字
        gpt_short = PredictionLogger._format_forecast(forecast)

        row = {
            "prediction_date": date.today().isoformat(),
            "symbol":          result.get("symbol", ""),
            "predicted":       "up" if pred.get("prediction") == 1 else "down",
            "up_prob":         f"{pred.get('up_prob', 0):.4f}",
            "down_prob":       f"{pred.get('down_prob', 0):.4f}",
            "gpt_3day":        gpt_short,
            "actual":          "",
            "actual_return":   "",
            "correct":         "",
        }

        file_exists = os.path.exists(LOG_PATH)
        with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

    # ── 讀取 ──────────────────────────────────────────────────────

    @staticmethod
    def load_all() -> list[dict]:
        if not os.path.exists(LOG_PATH):
            return []
        with open(LOG_PATH, "r", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    # ── 回填 actual ───────────────────────────────────────────────

    @staticmethod
    def backfill_actuals() -> int:
        """
        回填所有 actual 為空的記錄（用 yfinance 取收盤價）
        回傳成功回填的筆數
        """
        # 順手修復舊格式的 gpt_3day
        PredictionLogger.migrate_gpt_3day()

        rows = PredictionLogger.load_all()
        if not rows:
            return 0

        pending = [(i, r) for i, r in enumerate(rows) if not r.get("actual")]
        if not pending:
            return 0

        # 依 symbol 分組，減少 yfinance 請求次數
        by_symbol: dict[str, list] = defaultdict(list)
        for i, row in pending:
            by_symbol[row["symbol"]].append((i, row))

        filled = 0
        today  = date.today()

        for symbol, items in by_symbol.items():
            try:
                dates = [date.fromisoformat(r["prediction_date"]) for _, r in items]
                fetch_start = min(dates) - timedelta(days=3)

                ticker = yf.Ticker(symbol)
                hist   = ticker.history(
                    start=fetch_start.isoformat(),
                    end=(today + timedelta(days=1)).isoformat()
                )
                if hist.empty:
                    continue

                hist.index = hist.index.tz_localize(None)
                price_map: dict[date, float] = {
                    idx.date(): float(close)
                    for idx, close in zip(hist.index, hist["Close"])
                }

                for i, row in items:
                    pred_date = date.fromisoformat(row["prediction_date"])
                    target_date = pred_date + timedelta(days=1)

                    # 目標日期還沒過 → 跳過（明天還沒開盤）
                    if target_date > today:
                        continue

                    # pred_close: 預測當天的收盤價（往後找最近交易日）
                    # target_close: 隔天的收盤價（往後找最近交易日）
                    pred_close   = PredictionLogger._near_price(price_map, pred_date, "after")
                    target_close = PredictionLogger._near_price(price_map, target_date, "after")

                    if pred_close is None or target_close is None:
                        continue

                    ret    = (target_close - pred_close) / pred_close * 100
                    actual = "up" if ret > 0 else "down"

                    rows[i]["actual"]        = actual
                    rows[i]["actual_return"] = f"{ret:.2f}"
                    rows[i]["correct"]       = str(actual == row["predicted"])
                    filled += 1

            except Exception:
                continue

        if filled > 0:
            PredictionLogger._save_all(rows)

        return filled

    @staticmethod
    def migrate_gpt_3day() -> int:
        """修復舊格式的 gpt_3day 欄位（Python list repr → 可讀文字）"""
        rows = PredictionLogger.load_all()
        fixed = 0
        for row in rows:
            raw = row.get("gpt_3day", "")
            if raw.startswith("[{") or raw.startswith("[{'"):
                try:
                    import ast as _ast
                    data = _ast.literal_eval(raw)
                    row["gpt_3day"] = PredictionLogger._format_forecast(data)
                    fixed += 1
                except Exception:
                    pass
        if fixed > 0:
            PredictionLogger._save_all(rows)
        return fixed

    @staticmethod
    def _format_forecast(forecast_3d) -> str:
        """將 3日走勢 list[dict] 格式化為可讀字串，例如：明日:盤整(中) / 後天:偏多(高) / +3天:偏空(低)"""
        if not forecast_3d:
            return ""
        if not isinstance(forecast_3d, list):
            return str(forecast_3d)[:100]
        parts = []
        for item in forecast_3d:
            if not isinstance(item, dict):
                continue
            day   = item.get("day", "")
            trend = item.get("trend", "")
            conf  = item.get("confidence", "")
            parts.append(f"{day}:{trend}({conf})")
        return " / ".join(parts)

    @staticmethod
    def _near_price(price_map: dict, target: date, direction: str) -> float | None:
        """找最近的交易日收盤價（最多找 7 天）"""
        for delta in range(0, 8):
            d = target + timedelta(days=delta if direction == "after" else -delta)
            if d in price_map:
                return price_map[d]
        return None

    @staticmethod
    def _save_all(rows: list[dict]) -> None:
        with open(LOG_PATH, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    # ── 統計 ──────────────────────────────────────────────────────

    @staticmethod
    def delete_rows(row_indices: list[int]) -> None:
        """
        刪除指定的記錄列（傳入 CSV 原始順序的 index）
        """
        rows = PredictionLogger.load_all()
        to_delete = set(row_indices)
        rows = [r for i, r in enumerate(rows) if i not in to_delete]
        PredictionLogger._save_all(rows)

    @staticmethod
    def get_stats() -> dict:
        """
        回傳準確率統計字典
        {
          "total": int,
          "correct": int,
          "accuracy": float,
          "by_symbol": { symbol: {"total":n, "correct":n, "accuracy":f} }
        }
        """
        rows      = PredictionLogger.load_all()
        evaluated = [r for r in rows if r.get("correct") in ("True", "False")]

        if not evaluated:
            return {"total": 0, "correct": 0, "accuracy": 0.0, "by_symbol": {}}

        correct_count = sum(1 for r in evaluated if r["correct"] == "True")

        by_sym: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
        for r in evaluated:
            s = r["symbol"]
            by_sym[s]["total"] += 1
            if r["correct"] == "True":
                by_sym[s]["correct"] += 1

        return {
            "total":     len(evaluated),
            "correct":   correct_count,
            "accuracy":  correct_count / len(evaluated),
            "by_symbol": {
                s: {**v, "accuracy": v["correct"] / v["total"]}
                for s, v in by_sym.items()
            },
        }

    # ── 自動重訓判斷 ───────────────────────────────────────────────

    @staticmethod
    def check_auto_retrain_candidates(
        accuracy_threshold: float = 0.55,
        min_records: int = 20,
        cooldown_days: int = 3,
    ) -> list[str]:
        """
        回傳需要自動重訓的股票清單。
        條件：最近 min_records 筆準確率 < accuracy_threshold，
              且距上次自動重訓超過 cooldown_days 天。
        """
        rows = PredictionLogger.load_all()
        evaluated = [r for r in rows if r.get("correct") in ("True", "False")]
        if not evaluated:
            return []

        cooldown_log = PredictionLogger._load_cooldown_log()
        today = date.today()

        by_symbol: dict[str, list] = defaultdict(list)
        for r in evaluated:
            by_symbol[r["symbol"]].append(r)

        candidates = []
        for symbol, records in by_symbol.items():
            recent = records[-min_records:]
            if len(recent) < min_records:
                continue

            # 冷卻期檢查
            last_str = cooldown_log.get(symbol)
            if last_str:
                if (today - date.fromisoformat(last_str)).days < cooldown_days:
                    continue

            accuracy = sum(1 for r in recent if r["correct"] == "True") / len(recent)
            if accuracy < accuracy_threshold:
                candidates.append(symbol)

        return candidates

    @staticmethod
    def mark_retrained(symbol: str) -> None:
        """記錄某股票的自動重訓日期，供冷卻期計算使用"""
        log = PredictionLogger._load_cooldown_log()
        log[symbol] = date.today().isoformat()
        with open(COOLDOWN_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)

    @staticmethod
    def _load_cooldown_log() -> dict:
        if not os.path.exists(COOLDOWN_PATH):
            return {}
        try:
            with open(COOLDOWN_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

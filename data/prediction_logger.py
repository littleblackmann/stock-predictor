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

import logging

import yfinance as yf

from data.data_paths import PREDICTION_LOG as LOG_PATH, COOLDOWN_PATH

logger = logging.getLogger(__name__)

FIELDS = [
    "prediction_date",   # 執行預測當天 YYYY-MM-DD
    "symbol",            # 股票代碼
    "predicted",         # up / down
    "up_prob",           # 上漲機率 float（含 GPT 情緒調整）
    "down_prob",         # 下跌機率 float
    "raw_up_prob",       # 原始模型機率（未加 GPT 情緒），用於 A/B 分析
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
        # 先 migrate 舊 header（避免新 10 欄資料寫進舊 9 欄 CSV 造成欄位錯位）
        PredictionLogger.migrate_header_if_needed()

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
            "raw_up_prob":     f"{pred.get('raw_up_prob', pred.get('up_prob', 0)):.4f}",
            "gpt_3day":        gpt_short,
            "actual":          "",
            "actual_return":   "",
            "correct":         "",
        }

        logger.info("寫入預測記錄：%s %s → %s (path=%s)",
                     row["prediction_date"], row["symbol"], row["predicted"], LOG_PATH)

        file_exists = os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 0
        with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
            # 注意：不用 utf-8-sig，因為 append 模式會在每次寫入前插入 BOM，
            # 導致第 2 筆以後的 prediction_date 被 BOM 汙染，backfill 會靜默失敗
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
            f.flush()
            os.fsync(f.fileno())

        # 寫入後驗證
        new_size = os.path.getsize(LOG_PATH)
        logger.info("預測記錄寫入完成：%s（檔案大小 %d bytes）", row["symbol"], new_size)

    # ── 讀取 ──────────────────────────────────────────────────────

    @staticmethod
    def load_all() -> list[dict]:
        # 先 migrate 舊 header，讓後續 DictReader 能正確解析
        PredictionLogger.migrate_header_if_needed()

        if not os.path.exists(LOG_PATH):
            return []
        with open(LOG_PATH, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        # 清除舊版 BOM append 汙染：prediction_date 前可能殘留 \ufeff
        for r in rows:
            pd = r.get("prediction_date", "")
            if pd.startswith("\ufeff"):
                r["prediction_date"] = pd.lstrip("\ufeff")
        return rows

    # ── Schema 升級 ────────────────────────────────────────────────

    @staticmethod
    def migrate_header_if_needed() -> int:
        """
        v1.5.4 新增 raw_up_prob 欄位時，舊 CSV header 只有 9 欄。
        append 模式不會重寫 header，導致新記錄按 10 欄寫入但 DictReader 依舊 header 解析，
        結果 raw_up_prob→gpt_3day、gpt_3day→actual 全部錯位一格。

        此函式偵測並修復：
          - 舊 9 欄記錄：補空 raw_up_prob
          - 錯位 10 欄記錄：依新 FIELDS 順序重新對齊

        回傳修復筆數（已是新 header 時為 0）。
        """
        if not os.path.exists(LOG_PATH) or os.path.getsize(LOG_PATH) == 0:
            return 0

        # 快速檢查第一行 header，避免每次都讀整個檔
        with open(LOG_PATH, "r", encoding="utf-8-sig", newline="") as f:
            first_line = f.readline()
        if "raw_up_prob" in first_line:
            return 0

        # 舊 header → 讀入全部 raw rows 重建
        with open(LOG_PATH, "r", encoding="utf-8-sig", newline="") as f:
            raw_rows = list(csv.reader(f))
        if not raw_rows:
            return 0

        fixed_rows: list[dict] = []
        migrated_old = 0
        migrated_misaligned = 0
        skipped = 0

        for data_row in raw_rows[1:]:
            if not data_row:
                continue

            if len(data_row) == 9:
                # 舊版 9 欄：prediction_date, symbol, predicted, up_prob, down_prob,
                #            gpt_3day, actual, actual_return, correct
                new_row = {
                    "prediction_date": data_row[0],
                    "symbol":          data_row[1],
                    "predicted":       data_row[2],
                    "up_prob":         data_row[3],
                    "down_prob":       data_row[4],
                    "raw_up_prob":     "",   # 舊記錄沒有這個值
                    "gpt_3day":        data_row[5],
                    "actual":          data_row[6],
                    "actual_return":   data_row[7],
                    "correct":         data_row[8],
                }
                migrated_old += 1
            elif len(data_row) == 10:
                # 新版 10 欄錯位記錄：按 FIELDS 順序對齊
                new_row = dict(zip(FIELDS, data_row))
                migrated_misaligned += 1
            else:
                logger.warning("migrate 跳過欄位數異常記錄（%d 欄）：%s", len(data_row), data_row)
                skipped += 1
                continue

            fixed_rows.append(new_row)

        # 重寫 CSV（10 欄新 header）
        with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(fixed_rows)
            f.flush()
            os.fsync(f.fileno())

        logger.info(
            "CSV header migrate 完成：舊 9 欄記錄 %d 筆、錯位 10 欄記錄 %d 筆、跳過 %d 筆 → 新 10 欄 schema",
            migrated_old, migrated_misaligned, skipped
        )
        return migrated_old + migrated_misaligned

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

        pending = [
            (i, r) for i, r in enumerate(rows)
            if not r.get("actual")
            or r.get("actual_return") in ("", "0.00", "nan", "資料延遲")
        ]
        logger.info("backfill: 共 %d 筆記錄，%d 筆待回填", len(rows), len(pending))
        if not pending:
            return 0

        # 依 symbol 分組，減少 yfinance 請求次數
        by_symbol: dict[str, list] = defaultdict(list)
        for i, row in pending:
            by_symbol[row["symbol"]].append((i, row))

        filled = 0
        deferred = 0
        today  = date.today()

        for symbol, items in by_symbol.items():
            try:
                dates = [date.fromisoformat(r["prediction_date"]) for _, r in items]
                fetch_start = min(dates) - timedelta(days=3)

                ticker = yf.Ticker(symbol)
                hist   = ticker.history(
                    start=fetch_start.isoformat(),
                    end=(today + timedelta(days=1)).isoformat(),
                    repair=True,
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

                    # pred_close: 預測當天（或之前最近交易日）的收盤價作為基準
                    # target_close: 隔天（或之後最近交易日）的收盤價
                    pred_close   = PredictionLogger._near_price(price_map, pred_date, "before")
                    target_close = PredictionLogger._near_price(price_map, target_date, "after")

                    if pred_close is None or target_close is None:
                        # repair 也救不回來 → 標記為「資料延遲」，下次啟動會重試
                        if not rows[i].get("actual"):
                            rows[i]["actual_return"] = "資料延遲"
                            deferred += 1
                        logger.debug("backfill %s %s: 找不到價格 pred=%s target=%s",
                                     symbol, row["prediction_date"], pred_close, target_close)
                        continue

                    ret    = (target_close - pred_close) / pred_close * 100
                    actual = "up" if ret > 0 else "down"

                    rows[i]["actual"]        = actual
                    rows[i]["actual_return"] = f"{ret:.2f}"
                    rows[i]["correct"]       = str(actual == row["predicted"])
                    filled += 1

            except Exception as e:
                logger.warning("backfill %s 失敗: %s", symbol, e)
                continue

        logger.info("backfill: 完成，成功回填 %d 筆，資料延遲 %d 筆", filled, deferred)
        if filled > 0 or deferred > 0:
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
        """找最近的交易日收盤價（最多找 7 天，跳過 NaN）"""
        import math
        for delta in range(0, 8):
            d = target + timedelta(days=delta if direction == "after" else -delta)
            if d in price_map:
                val = price_map[d]
                if val is not None and not math.isnan(val):
                    return val
        return None

    @staticmethod
    def _save_all(rows: list[dict], merge_protect: bool = True) -> None:
        # merge_protect=True：寫入前重新讀取 CSV，合併期間可能被 append() 新增的記錄，
        # 避免 backfill 背景執行緒覆蓋掉新追加的預測。
        # merge_protect=False：直接寫入（用於刪除操作，否則被刪的記錄會被合併回來）。
        if merge_protect:
            on_disk = PredictionLogger.load_all()
            known_keys = {
                (r.get("prediction_date", ""), r.get("symbol", ""))
                for r in rows
            }
            for disk_row in on_disk:
                key = (disk_row.get("prediction_date", ""), disk_row.get("symbol", ""))
                if key not in known_keys:
                    rows.append(disk_row)
                    logger.info("_save_all 合併漏失記錄：%s %s", *key)

        with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())

    # ── 統計 ──────────────────────────────────────────────────────

    @staticmethod
    def delete_rows(row_indices: list[int]) -> None:
        """
        刪除指定的記錄列（傳入 CSV 原始順序的 index）
        """
        rows = PredictionLogger.load_all()
        to_delete = set(row_indices)
        rows = [r for i, r in enumerate(rows) if i not in to_delete]
        PredictionLogger._save_all(rows, merge_protect=False)

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

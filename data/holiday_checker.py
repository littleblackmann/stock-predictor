"""
台股交易日曆檢查器

資料來源（雙層機制）：
  主要：台灣證券交易所官方 API（每次啟動背景更新）
  備援：exchange_calendars 套件（離線使用）

功能：
  - 判斷明天是否為台股交易日
  - 識別週末、國定假日
  - 找出下一個交易日
  - 本機 JSON 快取（7 天有效期）
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常數設定 ──────────────────────────────────────────────────────
from data.data_paths import HOLIDAY_CACHE as _HOLIDAY_CACHE_STR
CACHE_PATH = Path(_HOLIDAY_CACHE_STR)
TWSE_URL   = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
CACHE_MAX_AGE_DAYS = 7

WEEKDAY_NAMES = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


class TradingCalendar:
    """
    台股交易日曆：結合 TWSE 官方 API + exchange_calendars 備援

    使用方式：
        cal = TradingCalendar()
        cal.refresh()                  # App 啟動時呼叫一次（背景更新）
        status = cal.get_tomorrow_status()
    """

    def __init__(self):
        self._holiday_set:   set[str]       = set()   # "YYYY-MM-DD"
        self._holiday_names: dict[str, str] = {}      # "YYYY-MM-DD" → "節日名稱"
        self._load_cache()

    # ── 快取管理 ───────────────────────────────────────────────────

    def _load_cache(self):
        if not CACHE_PATH.exists():
            return
        try:
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            self._holiday_set   = set(data.get("holidays", []))
            self._holiday_names = data.get("holiday_names", {})
            logger.info(f"假日快取載入成功，共 {len(self._holiday_set)} 筆")
        except Exception as e:
            logger.warning(f"假日快取載入失敗：{e}")

    def _save_cache(self, holidays: set, names: dict):
        try:
            data = {
                "updated":       date.today().isoformat(),
                "holidays":      sorted(list(holidays)),
                "holiday_names": names,
            }
            CACHE_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info(f"假日快取已更新，共 {len(holidays)} 筆")
        except Exception as e:
            logger.warning(f"假日快取儲存失敗：{e}")

    def _is_cache_fresh(self) -> bool:
        if not CACHE_PATH.exists():
            return False
        try:
            data    = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            updated = date.fromisoformat(data.get("updated", "2000-01-01"))
            return (date.today() - updated).days < CACHE_MAX_AGE_DAYS
        except Exception:
            return False

    # ── TWSE 資料抓取 ──────────────────────────────────────────────

    def _fetch_twse_holidays(self, year: int) -> dict[str, str]:
        """從 TWSE API 抓取指定年份的休市日，回傳 {日期: 節日名稱}"""
        try:
            import requests
            resp = requests.get(
                TWSE_URL,
                params={"response": "json", "queryYear": str(year)},
                timeout=8,
            )
            resp.raise_for_status()
            raw = resp.json()

            if str(raw.get("stat", "")).upper() != "OK":
                logger.warning(f"TWSE API 回傳非 OK 狀態（{year}）：{raw.get('stat')}")
                return {}

            names: dict[str, str] = {}
            for row in raw.get("data", []):
                if len(row) < 2:
                    continue
                date_str = row[0].strip()
                try:
                    if "-" in date_str:
                        # 新格式：row[0] = "2026-01-01"，row[1] = 節日名稱
                        full = date_str
                        name = row[1].strip()
                    else:
                        # 舊格式：row[0] = "01/01"，row[2] = 節日名稱
                        full = f"{year}-{date_str.replace('/', '-')}"
                        name = row[2].strip() if len(row) > 2 else row[1].strip()

                    # 略過交易日標記（「最後交易日」「開始交易日」等，非休市日）
                    if "交易日" in name:
                        continue

                    date.fromisoformat(full)   # 驗證格式
                    names[full] = name
                except ValueError:
                    pass

            logger.info(f"TWSE 假日資料抓取成功（{year}），共 {len(names)} 筆")
            return names

        except Exception as e:
            logger.warning(f"TWSE 假日資料抓取失敗（{year}）：{e}")
            return {}

    def _fallback_refresh(self):
        """備援：從 exchange_calendars 取得台股非交易日（週末以外的假日）"""
        try:
            import exchange_calendars as xcals
            import pandas as pd

            today = date.today()
            start = pd.Timestamp(today.year, 1, 1)
            end   = pd.Timestamp(today.year + 1, 12, 31)
            cal   = xcals.get_calendar("XTAI")

            # 工作日（Mon-Fri）中，不在 sessions 裡的就是假日
            business_days = pd.date_range(start, end, freq="B")
            sessions      = set(cal.sessions_in_range(start, end))
            non_trading   = [d for d in business_days if d not in sessions]

            names = {d.strftime("%Y-%m-%d"): "國定假日" for d in non_trading}
            self._holiday_set   = set(names.keys())
            self._holiday_names = names
            self._save_cache(self._holiday_set, names)
            logger.info(f"備援假日資料載入成功（exchange_calendars），共 {len(names)} 筆")

        except ImportError:
            logger.warning("exchange_calendars 未安裝，備援跳過")
        except Exception as e:
            logger.warning(f"備援假日資料載入失敗：{e}")

    # ── 公開方法 ───────────────────────────────────────────────────

    def refresh(self):
        """
        更新假日資料（App 啟動時呼叫一次即可）。
        快取仍在有效期內則跳過網路請求。
        """
        if self._is_cache_fresh():
            logger.info("假日快取仍在有效期內，跳過更新")
            return

        today = date.today()
        all_names: dict[str, str] = {}
        all_names.update(self._fetch_twse_holidays(today.year))
        all_names.update(self._fetch_twse_holidays(today.year + 1))

        if all_names:
            self._holiday_set   = set(all_names.keys())
            self._holiday_names = all_names
            self._save_cache(self._holiday_set, all_names)
        else:
            logger.warning("TWSE 主要來源失敗，切換備援（exchange_calendars）")
            self._fallback_refresh()

    def is_weekend(self, d: date) -> bool:
        return d.weekday() >= 5

    def is_holiday(self, d: date) -> bool:
        return d.isoformat() in self._holiday_set

    def is_trading_day(self, d: date) -> bool:
        return not self.is_weekend(d) and not self.is_holiday(d)

    def get_holiday_name(self, d: date) -> str:
        return self._holiday_names.get(d.isoformat(), "國定假日")

    def next_trading_day_after(self, d: date) -> date:
        """找出 d 之後（不含 d）的第一個交易日"""
        candidate = d + timedelta(days=1)
        for _ in range(30):
            if self.is_trading_day(candidate):
                return candidate
            candidate += timedelta(days=1)
        return candidate

    def get_tomorrow_status(self) -> dict:
        """
        回傳明天的台股交易狀態。

        回傳格式：
        {
            "is_trading":   bool,    # 明天是否為交易日
            "tomorrow":     date,    # 明天日期
            "weekday_name": str,     # 明天是週幾
            "reason":       str,     # 休市原因（若休市）
            "next_trading": date,    # 下一個交易日（若休市時才有意義）
        }
        """
        today         = date.today()
        tomorrow      = today + timedelta(days=1)
        weekday_name  = WEEKDAY_NAMES[tomorrow.weekday()]

        if self.is_weekend(tomorrow):
            return {
                "is_trading":   False,
                "tomorrow":     tomorrow,
                "weekday_name": weekday_name,
                "reason":       f"明天（{tomorrow.strftime('%m/%d')} {weekday_name}）為週末，台股休市",
                "next_trading": self.next_trading_day_after(tomorrow),
            }

        if self.is_holiday(tomorrow):
            holiday_name = self.get_holiday_name(tomorrow)
            return {
                "is_trading":   False,
                "tomorrow":     tomorrow,
                "weekday_name": weekday_name,
                "reason":       f"明天（{tomorrow.strftime('%m/%d')} {weekday_name}）是「{holiday_name}」，台股休市",
                "next_trading": self.next_trading_day_after(tomorrow),
            }

        return {
            "is_trading":   True,
            "tomorrow":     tomorrow,
            "weekday_name": weekday_name,
            "reason":       "",
            "next_trading": tomorrow,
        }


# ── 全局單例 ───────────────────────────────────────────────────────
_calendar: Optional[TradingCalendar] = None


def get_calendar() -> TradingCalendar:
    global _calendar
    if _calendar is None:
        _calendar = TradingCalendar()
    return _calendar

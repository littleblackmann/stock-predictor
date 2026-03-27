"""
籌碼面資料抓取器
來源：TWSE（台灣證券交易所）公開 API
- 三大法人買賣超（外資、投信、自營商）
- 融資融券餘額

所有資料以每月為單位抓取，並快取於 cache/chip/ 資料夾，
7 天內不重複請求，避免對 TWSE 造成過多請求。
"""
import os
import json
import time
import requests
import pandas as pd
from datetime import date, timedelta
from logger.app_logger import get_logger

logger = get_logger(__name__)

from data.data_paths import CHIP_CACHE_DIR as CACHE_DIR
CACHE_TTL_DAYS = 7   # 快取有效期（天）
REQUEST_DELAY  = 0.15  # 每次 API 請求間隔（秒），避免被 TWSE 限流


def _stock_no(symbol: str) -> str:
    """2330.TW / 2330.TWO → 2330"""
    return symbol.split(".")[0].strip()


def _parse_num(s) -> int:
    """把 '1,234' / '-1,234' / '' 解析成 int，失敗回傳 0"""
    try:
        return int(str(s).replace(",", "").replace("+", ""))
    except Exception:
        return 0


def _roc_to_date(roc_str: str) -> date | None:
    """
    民國年格式轉西元 date
    '113/01/02'  → date(2024, 1, 2)
    '113年01月02日' 也支援
    """
    try:
        s = roc_str.replace("年", "/").replace("月", "/").replace("日", "")
        parts = s.split("/")
        year  = int(parts[0]) + 1911
        month = int(parts[1])
        day   = int(parts[2])
        return date(year, month, day)
    except Exception:
        return None


class ChipFetcher:
    """
    台股籌碼面資料抓取器（TWSE 公開 API）

    用法：
        fetcher = ChipFetcher()
        chip_df = fetcher.fetch(symbol="2330.TW",
                                start=date(2023,1,1), end=date.today())
        # chip_df columns: fi_net, it_net, dealer_net, institutional_net,
        #                  margin_balance, short_balance, margin_change, short_change
    """

    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)

    # ── 公開 API ──────────────────────────────────────────────────

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """
        抓取指定股票從 start 到 end 的籌碼資料。
        回傳 DataFrame，index 為 date，欄位為各籌碼指標。
        任一來源失敗時降級使用空 DataFrame（不中斷預測流程）。
        """
        no = _stock_no(symbol)
        logger.info(f"[ChipFetcher] 抓取 {no} 籌碼資料 {start}~{end}")

        inst_df   = self._fetch_institutional(no, start, end)
        margin_df = self._fetch_margin(no, start, end)

        frames = [df for df in [inst_df, margin_df] if not df.empty]
        if not frames:
            logger.warning(f"[ChipFetcher] {no} 無可用籌碼資料，將以技術面特徵為主")
            return pd.DataFrame()

        result = frames[0]
        for df in frames[1:]:
            result = result.join(df, how="outer")

        result.sort_index(inplace=True)
        return result

    # ── 三大法人 ──────────────────────────────────────────────────

    def _fetch_institutional(self, no: str, start: date, end: date) -> pd.DataFrame:
        rows = []
        consecutive_fails = 0
        for month_start in self._month_range(start, end):
            data = self._cached("inst", no, month_start,
                                lambda: self._api_institutional(no, month_start))
            if data:
                rows.extend(data)
                consecutive_fails = 0
            else:
                consecutive_fails += 1
                if consecutive_fails >= 3:
                    logger.info(f"[ChipFetcher] {no} 三大法人連續 {consecutive_fails} 個月無資料，跳過剩餘月份")
                    break
            time.sleep(REQUEST_DELAY)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).set_index("date").sort_index()
        df.index = pd.to_datetime(df.index)
        df = df[(df.index.date >= start) & (df.index.date <= end)]
        return df[["fi_net", "it_net", "dealer_net", "institutional_net"]]

    def _api_institutional(self, no: str, month_start: date) -> list:
        """
        TWSE TWT38U：個股三大法人月報
        https://www.twse.com.tw/rwd/zh/fund/TWT38U
        """
        url = "https://www.twse.com.tw/rwd/zh/fund/TWT38U"
        params = {
            "response": "json",
            "date":     month_start.strftime("%Y%m01"),
            "stockNo":  no,
        }
        try:
            resp = requests.get(url, params=params, timeout=12)
            resp.raise_for_status()
            j = resp.json()
            if str(j.get("stat", "")).upper() != "OK" or not j.get("data"):
                return []

            rows = []
            for item in j["data"]:
                d = _roc_to_date(str(item[0]))
                if d is None:
                    continue
                fi_net     = _parse_num(item[3])   # 外資淨買超（千股）
                it_net     = _parse_num(item[6])   # 投信淨買超
                dealer_net = _parse_num(item[9])   # 自營商淨買超（自行+避險）
                rows.append({
                    "date":             d.isoformat(),
                    "fi_net":           fi_net,
                    "it_net":           it_net,
                    "dealer_net":       dealer_net,
                    "institutional_net": fi_net + it_net + dealer_net,
                })
            return rows

        except Exception as e:
            logger.warning(f"[ChipFetcher] 三大法人 API 失敗 ({no} {month_start}): {e}")
            return []

    # ── 融資融券 ──────────────────────────────────────────────────

    def _fetch_margin(self, no: str, start: date, end: date) -> pd.DataFrame:
        rows = []
        consecutive_fails = 0
        for month_start in self._month_range(start, end):
            data = self._cached("margin", no, month_start,
                                lambda: self._api_margin(no, month_start))
            if data:
                rows.extend(data)
                consecutive_fails = 0
            else:
                consecutive_fails += 1
                if consecutive_fails >= 3:
                    logger.info(f"[ChipFetcher] {no} 融資融券連續 {consecutive_fails} 個月無資料，跳過剩餘月份")
                    break
            time.sleep(REQUEST_DELAY)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).set_index("date").sort_index()
        df.index = pd.to_datetime(df.index)
        df = df[(df.index.date >= start) & (df.index.date <= end)]
        return df[["margin_balance", "short_balance", "margin_change", "short_change"]]

    def _api_margin(self, no: str, month_start: date) -> list:
        """
        TWSE TWT93U：個股融資融券月報
        https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U
        """
        url = "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U"
        params = {
            "response": "json",
            "date":     month_start.strftime("%Y%m01"),
            "selectType": "ALL",
            "stockNo":  no,
        }
        try:
            resp = requests.get(url, params=params, timeout=12)
            resp.raise_for_status()
            j = resp.json()
            if str(j.get("stat", "")).upper() != "OK" or not j.get("data"):
                return []

            rows = []
            for item in j["data"]:
                d = _roc_to_date(str(item[0]))
                if d is None:
                    continue
                # 融資欄位（index 依 TWSE 格式）
                # [日期, 融資買進, 融資賣出, 融資現金償還, 融資今日餘額, 融資限額,
                #  融券買進, 融券賣出, 融券今日餘額, 融券限額, ...]
                margin_balance = _parse_num(item[4])   # 融資今日餘額（千股）
                margin_change  = _parse_num(item[1]) - _parse_num(item[2])  # 融資買進 - 賣出
                short_balance  = _parse_num(item[8])   # 融券今日餘額（千股）
                short_change   = _parse_num(item[7]) - _parse_num(item[6])  # 融券賣出 - 買進
                rows.append({
                    "date":           d.isoformat(),
                    "margin_balance": margin_balance,
                    "margin_change":  margin_change,
                    "short_balance":  short_balance,
                    "short_change":   short_change,
                })
            return rows

        except Exception as e:
            logger.warning(f"[ChipFetcher] 融資融券 API 失敗 ({no} {month_start}): {e}")
            return []

    # ── 快取 ──────────────────────────────────────────────────────

    def _cache_path(self, kind: str, no: str, month_start: date) -> str:
        fname = f"{kind}_{no}_{month_start.strftime('%Y%m')}.json"
        return os.path.join(CACHE_DIR, fname)

    def _cached(self, kind: str, no: str, month_start: date, fetch_fn) -> list:
        """讀快取，若不存在或過期則呼叫 fetch_fn 重新抓取"""
        path = self._cache_path(kind, no, month_start)
        today = date.today()

        # 未來月份（包含當月）不快取，資料可能還不完整
        is_current_or_future = (month_start.year, month_start.month) >= (today.year, today.month)

        if not is_current_or_future and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                saved_on = date.fromisoformat(meta["saved_on"])
                if (today - saved_on).days < CACHE_TTL_DAYS:
                    return meta["data"]
            except Exception:
                pass

        data = fetch_fn()

        if not is_current_or_future:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"saved_on": today.isoformat(), "data": data}, f)
            except Exception:
                pass

        return data

    # ── 輔助 ──────────────────────────────────────────────────────

    @staticmethod
    def _month_range(start: date, end: date) -> list[date]:
        """回傳從 start 到 end 之間每個月的第一天"""
        months = []
        cur = date(start.year, start.month, 1)
        end_m = date(end.year, end.month, 1)
        while cur <= end_m:
            months.append(cur)
            if cur.month == 12:
                cur = date(cur.year + 1, 1, 1)
            else:
                cur = date(cur.year, cur.month + 1, 1)
        return months

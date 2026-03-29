"""
籌碼面資料抓取器
來源：TWSE（台灣證券交易所）公開 API
- 三大法人買賣超（T86 日報：外資、投信、自營商）
- 融資融券餘額（TWT93U 日報）

資料以每日為單位抓取（TWSE API 回傳某日全部個股），
快取於 cache/chip/ 資料夾，避免重複請求。
只抓取最近 90 個日曆天的資料（籌碼面重近不重遠）。

策略：從最近日期往回抓（最近的籌碼資訊最有價值），
遇到限流立即停止，下次執行會從快取繼續。
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
CACHE_TTL_DAYS = 7    # 當日/近日快取有效期（天）
REQUEST_DELAY  = 3.0   # 每次 API 請求間隔（秒），TWSE 對高頻限制很嚴
CHIP_LOOKBACK  = 90    # 只抓最近 N 個日曆天的籌碼資料
RATE_LIMIT_WAIT = 15   # 偵測到限流時等待秒數
MAX_CONSECUTIVE_FAILS = 3  # 連續失敗幾次視為限流


def _stock_no(symbol: str) -> str:
    """2330.TW / 2330.TWO → 2330"""
    return symbol.split(".")[0].strip()


def _parse_num(s) -> int:
    """把 '1,234' / '-1,234' / '' 解析成 int，失敗回傳 0"""
    try:
        return int(str(s).replace(",", "").replace("+", "").strip())
    except Exception:
        return 0


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
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.twse.com.tw/",
        })
        self._session_ready = False

    def _ensure_session(self):
        """訪問 TWSE 首頁取得 session cookie（只做一次）"""
        if self._session_ready:
            return
        try:
            self._session.get("https://www.twse.com.tw/", timeout=10)
            time.sleep(1)
        except Exception:
            pass
        self._session_ready = True

    # ── 公開 API ──────────────────────────────────────────────────

    def fetch(self, symbol: str, start: date, end: date,
              progress_callback=None) -> pd.DataFrame:
        """
        抓取指定股票的籌碼資料。
        自動限制只抓最近 CHIP_LOOKBACK 天（籌碼面重近不重遠）。
        從最近日期往回抓（最新的籌碼最有價值）。

        Args:
            progress_callback: 可選，(current_index, total_count) 回報進度
        回傳 DataFrame，index 為 date，欄位為各籌碼指標。
        """
        no = _stock_no(symbol)

        # 限制日期範圍：只抓最近 N 天
        effective_start = max(start, end - timedelta(days=CHIP_LOOKBACK))
        logger.info(f"[ChipFetcher] 抓取 {no} 籌碼資料 {effective_start}~{end}")

        # 產生候選日期（週一~週五），反轉為從最近往回抓
        candidate_dates = list(reversed(self._weekday_range(effective_start, end)))

        # 先檢查有多少日期已有快取（快取不需要打 API）
        uncached_count = sum(
            1 for d in candidate_dates
            if not self._has_cache(d, "t86") and not self._has_cache(d, "margin")
        )
        if uncached_count > 0:
            logger.info(f"[ChipFetcher] {len(candidate_dates)} 個候選日期，"
                        f"{uncached_count} 個需要從 API 抓取")
            self._ensure_session()

        inst_rows = []
        margin_rows = []
        api_fail_streak = 0
        rate_limited = False

        total_dates = len(candidate_dates)
        for idx, d in enumerate(candidate_dates):
            if progress_callback:
                progress_callback(idx, total_dates)

            if rate_limited:
                # 被限流但仍然可以讀快取
                inst_data = self._read_cache(
                    os.path.join(CACHE_DIR, f"t86_{d.isoformat()}.json"), d)
                if inst_data is not None and no in inst_data:
                    inst_rows.append(inst_data[no])
                margin_data = self._read_cache(
                    os.path.join(CACHE_DIR, f"margin_{d.isoformat()}.json"), d)
                if margin_data is not None and no in margin_data:
                    margin_rows.append(margin_data[no])
                continue

            # 三大法人
            inst_data, inst_from_api = self._get_daily_institutional(d)
            if inst_data is None and inst_from_api:
                # API 真的失敗（不是快取命中也不是假日空快取）
                api_fail_streak += 1
                if api_fail_streak >= MAX_CONSECUTIVE_FAILS:
                    logger.warning(
                        f"[ChipFetcher] 偵測到 TWSE 限流（連續 {api_fail_streak} 次失敗），"
                        f"等待 {RATE_LIMIT_WAIT} 秒後重試...")
                    time.sleep(RATE_LIMIT_WAIT)
                    inst_data, inst_from_api = self._get_daily_institutional(d)
                    if inst_data is None and inst_from_api:
                        logger.warning(
                            "[ChipFetcher] 重試仍失敗，停止 API 抓取，僅使用快取資料")
                        rate_limited = True
                        continue
                    else:
                        api_fail_streak = 0
            else:
                api_fail_streak = 0

            if inst_data is not None and no in inst_data:
                inst_rows.append(inst_data[no])

            # 融資融券
            if not rate_limited:
                margin_data, _ = self._get_daily_margin(d)
                if margin_data is not None and no in margin_data:
                    margin_rows.append(margin_data[no])

        # 合併成 DataFrame
        inst_df = pd.DataFrame()
        margin_df = pd.DataFrame()

        if inst_rows:
            inst_df = pd.DataFrame(inst_rows).set_index("date").sort_index()
            inst_df.index = pd.to_datetime(inst_df.index)

        if margin_rows:
            margin_df = pd.DataFrame(margin_rows).set_index("date").sort_index()
            margin_df.index = pd.to_datetime(margin_df.index)

        frames = [df for df in [inst_df, margin_df] if not df.empty]
        if not frames:
            logger.warning(f"[ChipFetcher] {no} 無可用籌碼資料，將以技術面特徵為主")
            return pd.DataFrame()

        result = frames[0]
        for df in frames[1:]:
            result = result.join(df, how="outer")

        result.sort_index(inplace=True)
        logger.info(f"[ChipFetcher] {no} 籌碼資料取得 {len(result)} 筆")
        return result

    # ── 三大法人（T86 日報）───────────────────────────────────────

    def _get_daily_institutional(self, d: date) -> tuple[dict | None, bool]:
        """
        取得某日三大法人資料（全部個股），回傳 (data_dict, called_api)。
        data_dict: {stock_no: row_dict} 或 None
        called_api: True 表示打了 API（用於限流偵測），False 表示來自快取
        """
        cache_path = os.path.join(CACHE_DIR, f"t86_{d.isoformat()}.json")
        data = self._read_cache(cache_path, d)
        if data is not None:
            return (data if data != {} else None), False

        # 呼叫 TWSE T86 API
        url = "https://www.twse.com.tw/rwd/zh/fund/T86"
        params = {
            "response": "json",
            "date": d.strftime("%Y%m%d"),
            "selectType": "ALLBUT0999",
        }
        try:
            resp = self._session.get(
                url, params=params, timeout=12, allow_redirects=False)

            # 307 = TWSE 限流頁面，立即回報失敗
            if resp.status_code in (301, 302, 307, 308, 403, 429):
                logger.warning(f"[ChipFetcher] T86 被限流 ({d}): HTTP {resp.status_code}")
                time.sleep(REQUEST_DELAY)
                return None, True

            resp.raise_for_status()
            j = resp.json()
            if str(j.get("stat", "")).upper() != "OK" or not j.get("data"):
                # 假日或週末，快取空結果
                self._write_cache(cache_path, d, {})
                time.sleep(REQUEST_DELAY)
                return None, False

            result = {}
            for item in j["data"]:
                if len(item) < 12:
                    continue
                stock_no = str(item[0]).strip()
                if not stock_no:
                    continue
                fi_net = _parse_num(item[4])
                it_net = _parse_num(item[10])
                dealer_net = _parse_num(item[11])
                # item[18] 不一定存在（某些特殊交易日欄位數不足）
                institutional_net = (
                    _parse_num(item[18]) if len(item) > 18
                    else (fi_net + it_net + dealer_net)
                )
                result[stock_no] = {
                    "date":              d.isoformat(),
                    "fi_net":            fi_net,
                    "it_net":            it_net,
                    "dealer_net":        dealer_net,
                    "institutional_net": institutional_net,
                }

            self._write_cache(cache_path, d, result)
            time.sleep(REQUEST_DELAY)
            return result, True

        except Exception as e:
            logger.warning(f"[ChipFetcher] T86 API 失敗 ({d}): {e}")
            time.sleep(REQUEST_DELAY)
            return None, True

    # ── 融資融券（TWT93U 日報）────────────────────────────────────

    def _get_daily_margin(self, d: date) -> tuple[dict | None, bool]:
        """
        取得某日融資融券資料（全部個股），回傳 (data_dict, called_api)。
        """
        cache_path = os.path.join(CACHE_DIR, f"margin_{d.isoformat()}.json")
        data = self._read_cache(cache_path, d)
        if data is not None:
            return (data if data != {} else None), False

        url = "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U"
        params = {
            "response": "json",
            "date": d.strftime("%Y%m%d"),
            "selectType": "ALL",
        }
        try:
            resp = self._session.get(
                url, params=params, timeout=12, allow_redirects=False)

            if resp.status_code in (301, 302, 307, 308, 403, 429):
                logger.warning(f"[ChipFetcher] TWT93U 被限流 ({d}): HTTP {resp.status_code}")
                time.sleep(REQUEST_DELAY)
                return None, True

            resp.raise_for_status()
            j = resp.json()
            if str(j.get("stat", "")).upper() != "OK" or not j.get("data"):
                self._write_cache(cache_path, d, {})
                time.sleep(REQUEST_DELAY)
                return None, False

            result = {}
            for item in j["data"]:
                if len(item) < 13:
                    continue
                stock_no = str(item[0]).strip()
                if not stock_no:
                    continue
                margin_balance = _parse_num(item[6])   # 融資今日餘額
                margin_buy     = _parse_num(item[4])    # 融資買進
                margin_sell    = _parse_num(item[3])     # 融資賣出
                short_balance  = _parse_num(item[12])    # 融券今日餘額
                short_sell     = _parse_num(item[9])     # 融券賣出
                short_buy      = _parse_num(item[10])    # 融券買進/還

                result[stock_no] = {
                    "date":           d.isoformat(),
                    "margin_balance": margin_balance,
                    "margin_change":  margin_buy - margin_sell,
                    "short_balance":  short_balance,
                    "short_change":   short_sell - short_buy,
                }

            self._write_cache(cache_path, d, result)
            time.sleep(REQUEST_DELAY)
            return result, True

        except Exception as e:
            logger.warning(f"[ChipFetcher] TWT93U API 失敗 ({d}): {e}")
            time.sleep(REQUEST_DELAY)
            return None, True

    # ── 快取 ──────────────────────────────────────────────────────

    def _read_cache(self, path: str, d: date) -> dict | None:
        """讀取日快取，回傳 dict 或 None（無快取/過期）。空 dict {} 代表假日。"""
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            saved_on = date.fromisoformat(meta["saved_on"])
            today = date.today()

            # 歷史日期（>7 天前）：永久快取
            if (today - d).days > CACHE_TTL_DAYS:
                return meta["data"]

            # 近期日期：TTL 內有效
            if (today - saved_on).days < CACHE_TTL_DAYS:
                return meta["data"]

        except Exception:
            pass
        return None

    def _has_cache(self, d: date, prefix: str) -> bool:
        """檢查某日的快取檔案是否存在且有效"""
        cache_path = os.path.join(CACHE_DIR, f"{prefix}_{d.isoformat()}.json")
        return self._read_cache(cache_path, d) is not None

    def _write_cache(self, path: str, d: date, data: dict):
        """寫入日快取"""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"saved_on": date.today().isoformat(), "data": data}, f)
        except Exception:
            pass

    # ── 輔助 ──────────────────────────────────────────────────────

    @staticmethod
    def _weekday_range(start: date, end: date) -> list[date]:
        """回傳 start~end 之間的所有週一到週五日期"""
        dates = []
        cur = start
        while cur <= end:
            if cur.weekday() < 5:  # 0=Mon ~ 4=Fri
            	dates.append(cur)
            cur += timedelta(days=1)
        return dates

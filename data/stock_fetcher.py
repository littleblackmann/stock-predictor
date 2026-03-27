"""
台股代號自動抓取模組
從 TWSE / TPEX ISIN 頁面抓取全部上市、上櫃、ETF 代號與中文名稱
快取至 stock_list_cache.json，每 7 天自動更新一次
"""
import json
import os
import re
import urllib.request
from datetime import date, timedelta

from logger.app_logger import get_logger

logger = get_logger(__name__)

from data.data_paths import STOCK_LIST_CACHE as CACHE_PATH
CACHE_DAYS  = 7

# TWSE/TPEX ISIN 公開查詢（strMode=2 上市，strMode=4 上櫃）
_URLS = [
    "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
    "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4",
]

# 股票代號格式：4~7 位英數字（含 ETF 如 00878、00953B）
_CODE_RE = re.compile(r"([0-9A-Za-z]{4,7})\u3000([^\t\r\n<]+)")


def _fetch_raw() -> dict[str, str]:
    """從 TWSE/TPEX 抓取並解析，回傳 {symbol: name} dict（附 .TW 後綴）"""
    result: dict[str, str] = {}

    for url in _URLS:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read()

            # TWSE 頁面以 Big5 編碼，解碼後搜尋「代號\u3000名稱」格式
            html = raw.decode("big5", errors="replace")

            for m in _CODE_RE.finditer(html):
                code = m.group(1).strip()
                name = m.group(2).strip()
                # 排除全數字且長度 < 4、或看起來像日期/頁碼的內容
                if not code or not name or len(code) < 4:
                    continue
                # 補 .TW 後綴（TPEX 部份也掛 .TW，yfinance 都支援）
                symbol = f"{code}.TW"
                result[symbol] = name

        except Exception as e:
            logger.warning(f"股票清單抓取失敗（{url}）：{e}")
            continue

    logger.info(f"從 TWSE/TPEX 抓取 {len(result)} 支股票代號")
    return result


def refresh_cache() -> dict[str, str]:
    """重新抓取並覆寫快取，回傳新資料（失敗回傳空 dict）"""
    data = _fetch_raw()
    if not data:
        return {}
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {"updated": date.today().isoformat(), "stocks": data},
                f, ensure_ascii=False, indent=2
            )
        logger.info(f"股票清單快取已更新：{len(data)} 筆")
    except Exception as e:
        logger.warning(f"快取寫入失敗：{e}")
    return data


def load_cache() -> dict[str, str] | None:
    """讀取本地快取；若不存在或超過 CACHE_DAYS 天回傳 None"""
    if not os.path.exists(CACHE_PATH):
        return None
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        updated = date.fromisoformat(data["updated"])
        if date.today() - updated > timedelta(days=CACHE_DAYS):
            logger.info("股票清單快取已過期，需要更新")
            return None
        stocks = data.get("stocks", {})
        logger.info(f"從快取載入 {len(stocks)} 支股票代號")
        return stocks
    except Exception as e:
        logger.warning(f"快取讀取失敗：{e}")
        return None


def get_stock_dict(fallback: dict[str, str]) -> dict[str, str]:
    """
    取得可用的股票 dict：
    1. 快取存在且新鮮 → 快取 + fallback 合併
    2. 否則 → 只用 fallback（背景會去更新）
    """
    cached = load_cache()
    if cached:
        # fallback 先放，讓快取蓋過去（保留硬編碼中文名稱品質較好的部分）
        return {**fallback, **cached}
    return dict(fallback)


def needs_refresh() -> bool:
    """判斷是否需要背景更新快取"""
    return load_cache() is None

"""
Brave Search API 整合模組
支援 Web Search，提供多重搜尋策略（個股 / 產業 / ETF 成分股連動）
"""
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime
from logger.app_logger import get_logger

logger = get_logger(__name__)


# ── 常見 ETF 前 3 大成分股（權重高，新聞連動性強）─────────────────
ETF_TOP_HOLDINGS: dict[str, list[tuple[str, str]]] = {
    "0050.TW":   [("2330.TW", "台積電"), ("2454.TW", "聯發科"), ("2317.TW", "鴻海")],
    "0056.TW":   [("2882.TW", "國泰金"), ("2881.TW", "富邦金"), ("2884.TW", "玉山金")],
    "006208.TW": [("2330.TW", "台積電"), ("2454.TW", "聯發科"), ("2317.TW", "鴻海")],
    "00878.TW":  [("2882.TW", "國泰金"), ("2891.TW", "中信金"), ("2886.TW", "兆豐金")],
    "00881.TW":  [("2330.TW", "台積電"), ("2454.TW", "聯發科"), ("3711.TW", "日月光投控")],
    "00891.TW":  [("2330.TW", "台積電"), ("2454.TW", "聯發科"), ("3034.TW", "聯詠")],
    "00892.TW":  [("2330.TW", "台積電"), ("2454.TW", "聯發科"), ("3034.TW", "聯詠")],
    "00919.TW":  [("2882.TW", "國泰金"), ("2881.TW", "富邦金"), ("2891.TW", "中信金")],
    "00929.TW":  [("2330.TW", "台積電"), ("2454.TW", "聯發科"), ("2382.TW", "廣達")],
    "00940.TW":  [("2330.TW", "台積電"), ("2317.TW", "鴻海"), ("2454.TW", "聯發科")],
}

# ── 常見個股的產業分類 ─────────────────────────────────────────────
STOCK_INDUSTRY: dict[str, str] = {
    # 半導體
    "2330.TW": "半導體", "2454.TW": "半導體", "3034.TW": "半導體",
    "2303.TW": "半導體", "3711.TW": "半導體封測", "2379.TW": "半導體",
    "3529.TW": "半導體", "6505.TW": "半導體",
    # 電子代工 / AI 伺服器
    "2317.TW": "電子代工", "2382.TW": "AI伺服器", "2353.TW": "電子代工",
    "3231.TW": "電子代工", "2356.TW": "電子代工",
    # 金融
    "2881.TW": "金融", "2882.TW": "金融", "2884.TW": "金融",
    "2886.TW": "金融", "2891.TW": "金融", "2880.TW": "金融",
    "2883.TW": "金融", "2887.TW": "金融", "2890.TW": "金融",
    "2892.TW": "金融", "5880.TW": "金融",
    # 石化 / 塑膠
    "1301.TW": "石化", "1303.TW": "石化", "1326.TW": "石化",
    "6505.TW": "石化",
    # 鋼鐵
    "2002.TW": "鋼鐵", "2014.TW": "鋼鐵",
    # 航運
    "2603.TW": "航運", "2609.TW": "航運", "2615.TW": "航運",
    # 電信
    "2412.TW": "電信", "3045.TW": "電信", "4904.TW": "電信",
    # 食品
    "1216.TW": "食品", "1210.TW": "食品", "2912.TW": "食品",
    # 零售 / 通路
    "2912.TW": "零售", "5903.TW": "零售", "2915.TW": "零售",
    # 光電 / 面板
    "2409.TW": "光電", "3481.TW": "面板",
    # 電池 / 綠能
    "3443.TW": "綠能",
}


class BraveSearchClient:
    """
    Brave Search API 客戶端

    - 支援 Web Search API
    - 多重搜尋策略：個股 / 產業 / ETF 成分股
    - 記憶體快取（同一支股票同一小時不重複搜尋）
    """

    SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
    CACHE_TTL = 1800  # 30 分鐘

    # class-level 快取：{cache_key: (timestamp, results)}
    _cache: dict = {}

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, symbol: str) -> list[dict]:
        """
        搜尋指定股票的相關新聞與分析

        Args:
            symbol: 股票代號（如 "0050.TW"）

        Returns:
            統一格式的搜尋結果列表
        """
        # ── 檢查快取 ──
        cache_key = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H')}"
        if cache_key in self._cache:
            ts, cached_results = self._cache[cache_key]
            if time.time() - ts < self.CACHE_TTL:
                logger.info(f"[{symbol}] Brave Search 命中快取（{len(cached_results)} 則）")
                return cached_results

        # ── 建構搜尋查詢 ──
        queries = self._build_queries(symbol)
        all_results = []
        seen_urls = set()

        for query in queries:
            try:
                results = self._call_brave(query)
                for r in results:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(r)
                # 避免過快連續請求
                time.sleep(0.3)
            except Exception as e:
                logger.warning(f"Brave Search 查詢失敗 [{query}]: {e}")

        # ── 存入快取 ──
        self._cache[cache_key] = (time.time(), all_results)
        logger.info(f"[{symbol}] Brave Search 取得 {len(all_results)} 則結果")
        return all_results

    def _build_queries(self, symbol: str) -> list[str]:
        """建構多重搜尋查詢"""
        code = symbol.replace(".TW", "").replace(".TWO", "")
        name = self._get_stock_name(symbol)
        queries = []

        # Query 1：個股新聞（最重要）
        queries.append(f"{name} {code} 台股")

        # Query 2：產業新聞（有分類時）
        industry = STOCK_INDUSTRY.get(symbol)
        if industry:
            queries.append(f"台股 {industry} 產業 新聞")

        # Query 3：ETF 成分股連動
        if symbol in ETF_TOP_HOLDINGS:
            top_names = [h[1] for h in ETF_TOP_HOLDINGS[symbol][:3]]
            queries.append(f"{' '.join(top_names)} 台股 新聞")

        # Query 4：分析文
        queries.append(f"{name} 股價分析 展望")

        return queries

    def _call_brave(self, query: str, count: int = 10) -> list[dict]:
        """
        呼叫 Brave Web Search API

        Args:
            query: 搜尋關鍵字
            count: 回傳筆數（上限 20）

        Returns:
            統一格式的結果列表
        """
        params = urllib.parse.urlencode({
            "q": query,
            "freshness": "pw",          # 過去一週
            "country": "tw",
            "search_lang": "zh-hant",
            "count": min(count, 20),
            "extra_snippets": "true",
        })

        url = f"{self.SEARCH_URL}?{params}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        })

        with urllib.request.urlopen(req, timeout=15) as resp:
            # 處理 gzip
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw_data = gzip.decompress(resp.read())
            else:
                raw_data = resp.read()
            data = json.loads(raw_data.decode("utf-8"))

        results = []

        # 解析 web results
        for item in data.get("web", {}).get("results", []):
            # 合併 extra_snippets 到 description
            desc = item.get("description", "")
            extra = item.get("extra_snippets", [])
            if extra:
                desc = desc + " " + " ".join(extra[:2])

            results.append({
                "title": item.get("title", ""),
                "description": desc,
                "url": item.get("url", ""),
                "source": item.get("meta_url", {}).get("hostname", ""),
                "age": item.get("age", ""),
            })

        # 解析 news results（如果 API 同時回傳）
        for item in data.get("news", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "url": item.get("url", ""),
                "source": item.get("meta_url", {}).get("hostname", ""),
                "age": item.get("age", ""),
            })

        return results

    def _get_stock_name(self, symbol: str) -> str:
        """從 tw_stock_list 取得股票中文名稱"""
        try:
            from data.tw_stock_list import TW_STOCK_LIST
            return TW_STOCK_LIST.get(symbol, symbol.replace(".TW", "").replace(".TWO", ""))
        except ImportError:
            return symbol.replace(".TW", "").replace(".TWO", "")

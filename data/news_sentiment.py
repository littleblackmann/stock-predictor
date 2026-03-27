"""
OpenAI 新聞情緒分析模組
支援 Brave Search API 深度搜尋（優先）+ Google News RSS（fallback）
透過 GPT 分析情緒分數、影響程度、產業連動
"""
import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import numpy as np
from openai import OpenAI
from logger.app_logger import get_logger

logger = get_logger(__name__)

from data.config_manager import load_config


class NewsSentimentAnalyzer:
    """
    使用 GPT 分析股票新聞情緒

    流程：
    1. Brave Search API 深度搜尋（優先，需要 API Key）
       或 Google News RSS 抓取最新台股新聞（免費 fallback）
    2. 送給 GPT 分析整體市場情緒
    3. 回傳情緒分數 -1.0（極度悲觀）~ +1.0（極度樂觀）
    """

    SYSTEM_PROMPT = """你是一位專業的台股金融分析師。
我會給你一支股票的最新新聞標題列表，請你：
1. 分析這些新聞對該股票短期（明日）走勢的整體情緒
2. 給出一個情緒分數，範圍 -1.0 到 +1.0：
   - +1.0 = 極度樂觀（強力看漲）
   - +0.5 = 偏樂觀
   -  0.0 = 中性
   - -0.5 = 偏悲觀
   - -1.0 = 極度悲觀（強力看跌）
3. 用一句話說明主要判斷依據

請只回傳 JSON 格式，範例：
{"score": 0.6, "reason": "外資持續買超且法說會釋放正向展望"}"""

    BRAVE_ANALYSIS_PROMPT = """你是一位專業的台股金融分析師。
我會給你一支股票的近期新聞摘要（包含標題和內容片段），請你進行深度分析：

1. **情緒分數** (-1.0 ~ +1.0)：整體市場對該股票明日走勢的情緒
   - +1.0 = 極度樂觀, +0.5 = 偏樂觀, 0.0 = 中性, -0.5 = 偏悲觀, -1.0 = 極度悲觀
2. **影響程度** (low / medium / high)：這些新聞對股價的潛在影響力
3. **影響時間** (short / medium / long)：
   - short = 1-2 天內反映
   - medium = 3-7 天
   - long = 超過一週
4. **產業連動**：是否有產業鏈上下游的連帶影響
5. **關鍵事件摘要**：一句話點出最重要的事件

請只回傳 JSON，格式如下（不要加其他文字）：
{"score": 0.6, "impact": "high", "timeframe": "short", "industry_effect": {"has_effect": true, "detail": "台積電法說利多帶動半導體族群"}, "key_event": "台積電上調全年營收展望", "reason": "綜合判斷依據"}"""

    def __init__(self):
        config = load_config()
        api_key = config.get("openai_api_key", "")
        self.model = config.get("openai_model", "gpt-4o-mini")
        self.available = False
        self.brave_client = None

        if not api_key or api_key == "在這裡貼上你的新API Key":
            logger.warning("OpenAI API Key 未設定，新聞情緒分析停用")
            return

        try:
            self.client = OpenAI(api_key=api_key)
            self.available = True
            logger.info(f"NewsSentimentAnalyzer 初始化完成，使用模型：{self.model}")
        except Exception as e:
            logger.error(f"OpenAI 初始化失敗：{e}")

        # Brave Search（選用）
        brave_key = config.get("brave_api_key", "")
        if brave_key:
            try:
                from data.brave_search import BraveSearchClient
                self.brave_client = BraveSearchClient(api_key=brave_key)
                logger.info("Brave Search API 已啟用")
            except Exception as e:
                logger.warning(f"Brave Search 初始化失敗：{e}")

    def analyze(self, symbol: str) -> dict:
        """
        分析指定股票的新聞情緒

        優先使用 Brave Search 深度搜尋，失敗時 fallback 至 Google News RSS。

        Returns:
            {
                "score": float,      # -1.0 ~ +1.0
                "reason": str,       # 判斷依據
                "news_count": int,   # 分析的新聞數量
                "available": bool,
                # 以下欄位僅 Brave 模式提供
                "impact": str,       # "low" / "medium" / "high"
                "timeframe": str,    # "short" / "medium" / "long"
                "industry_effect": dict,
                "key_event": str,
                "source": str,       # "brave" / "google_rss"
            }
        """
        if not self.available:
            return {"score": 0.0, "reason": "OpenAI 未啟用", "news_count": 0, "available": False}

        # ── 優先：Brave Search 深度搜尋 ──
        brave_results = []
        if self.brave_client:
            try:
                brave_results = self.brave_client.search(symbol)
                logger.info(f"[{symbol}] Brave Search 取得 {len(brave_results)} 則結果")
            except Exception as e:
                logger.warning(f"Brave Search 失敗，降級為 Google News: {e}")

        if brave_results:
            return self._analyze_with_brave(symbol, brave_results)

        # ── Fallback：Google News RSS ──
        news_titles = self._fetch_google_news(symbol)

        if not news_titles:
            logger.warning(f"[{symbol}] 找不到新聞，改用技術面情緒分析")
            return self._analyze_no_news(symbol)

        return self._analyze_with_titles(symbol, news_titles)

    def _analyze_with_titles(self, symbol: str, news_titles: list[str]) -> dict:
        """原有的 Google News RSS 標題分析（保持不變）"""
        try:
            news_text = "\n".join([f"{i+1}. {t}" for i, t in enumerate(news_titles)])
            user_message = (
                f"以下是台股 {symbol} 的最新新聞標題，請分析這些新聞對明日股價的情緒。\n\n"
                f"{news_text}\n\n"
                f"請只回傳 JSON，格式如下（不要加其他文字）：\n"
                f'{{"score": 0.6, "reason": "說明原因"}}\n'
                f"score 範圍 -1.0（極悲觀）到 +1.0（極樂觀）。"
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": user_message},
                ],
                max_completion_tokens=2048,
            )

            raw = response.choices[0].message.content or ""
            result = self._parse_json_safe(raw)
            score  = float(np.clip(result.get("score", 0.0), -1.0, 1.0))
            reason = result.get("reason", "")

            logger.info(f"[{symbol}] 情緒分析完成（Google RSS）：{score:.2f}，{reason}")
            return {
                "score":      score,
                "reason":     reason,
                "news_count": len(news_titles),
                "available":  True,
                "source":     "google_rss",
            }

        except Exception as e:
            logger.error(f"GPT 情緒分析失敗：{e}")
            return {"score": 0.0, "reason": f"分析失敗：{e}", "news_count": 0, "available": False}

    def _analyze_with_brave(self, symbol: str, results: list[dict]) -> dict:
        """使用 Brave Search 結果進行深度 GPT 分析"""
        try:
            # 取股票中文名稱
            try:
                from data.tw_stock_list import TW_STOCK_LIST
                stock_name = TW_STOCK_LIST.get(symbol, symbol)
            except ImportError:
                stock_name = symbol

            # 組裝新聞資料（最多 20 則，每則摘要限 200 字）
            news_parts = []
            for i, r in enumerate(results[:20]):
                part = f"{i+1}. [{r.get('source', '未知')}] {r.get('title', '')}"
                desc = r.get("description", "")
                if desc:
                    part += f"\n   摘要：{desc[:200]}"
                age = r.get("age", "")
                if age:
                    part += f"\n   時間：{age}"
                news_parts.append(part)

            news_text = "\n\n".join(news_parts)

            user_message = (
                f"以下是台股 {stock_name}（{symbol}）的近期新聞與分析，"
                f"共 {len(results)} 則，請進行深度分析。\n\n"
                f"{news_text}\n\n"
                f"請只回傳 JSON。"
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.BRAVE_ANALYSIS_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                max_completion_tokens=2048,
            )

            raw = response.choices[0].message.content or ""
            result = self._parse_json_safe(raw)
            score = float(np.clip(result.get("score", 0.0), -1.0, 1.0))

            logger.info(
                f"[{symbol}] Brave 深度分析完成：score={score:.2f}, "
                f"impact={result.get('impact', '?')}, "
                f"timeframe={result.get('timeframe', '?')}"
            )

            return {
                "score":           score,
                "reason":          result.get("reason", ""),
                "news_count":      len(results),
                "available":       True,
                "impact":          result.get("impact", "medium"),
                "timeframe":       result.get("timeframe", "medium"),
                "industry_effect": result.get("industry_effect", {"has_effect": False, "detail": ""}),
                "key_event":       result.get("key_event", ""),
                "source":          "brave",
            }

        except Exception as e:
            logger.error(f"Brave 深度分析失敗，降級為 Google News: {e}")
            # Fallback 到 Google News RSS
            news_titles = self._fetch_google_news(symbol)
            if news_titles:
                return self._analyze_with_titles(symbol, news_titles)
            return self._analyze_no_news(symbol)

    def forecast_3days(self, symbol: str, tech_context: dict, ml_result: dict, sentiment: dict) -> list:
        """
        根據技術指標、ML結果、新聞情緒，讓 GPT 推估未來 3 日走勢

        Args:
            symbol: 股票代號
            tech_context: 技術指標數值 dict
            ml_result: ML 模型預測結果 dict
            sentiment: 新聞情緒分析結果 dict

        Returns:
            list of 3 dicts：[
                {"day": "明日", "trend": "偏多", "color": "green", "confidence": "高", "reason": "..."},
                ...
            ]
        """
        if not self.available:
            return self._default_forecast()

        # 整理技術面快照
        rsi    = tech_context.get("rsi",    50)
        macd   = tech_context.get("macd",    0)
        macd_h = tech_context.get("macd_hist", 0)
        bb_pct = tech_context.get("bb_pct_b", 0.5)
        ma_cross = tech_context.get("ma5_cross_ma20", 0)
        vol_ratio = tech_context.get("vol_ratio", 1.0)
        atr_ratio = tech_context.get("atr_ratio", 0)

        ml_up   = ml_result.get("up_prob",  0.5)
        ml_raw  = ml_result.get("raw_up_prob", ml_up)
        sent_score = sentiment.get("score", 0.0)
        sent_reason = sentiment.get("reason", "無新聞資料")

        prompt = f"""你是一位專業的台股技術分析師。
以下是 {symbol} 的完整分析資料，請根據這些數據推估未來 3 個交易日的走勢。

【ML 模型預測】
- 明日上漲機率（純技術模型）：{ml_raw:.1%}
- 融合新聞情緒後機率：{ml_up:.1%}

【關鍵技術指標】
- RSI(14)：{rsi:.1f}（>70超買，<30超賣）
- MACD 柱狀圖：{macd_h:+.4f}（正值偏多，負值偏空）
- 布林 %b 位置：{bb_pct:.2f}（>1觸上軌，<0觸下軌）
- 均線金死叉強度：{ma_cross:+.4f}（正值MA5>MA20）
- 今日量比：{vol_ratio:.2f}（>1.5為放量）
- ATR 波動率：{atr_ratio:.4f}

【新聞情緒】
- 情緒分數：{sent_score:+.2f}（-1極悲觀 ~ +1極樂觀）
- 判斷依據：{sent_reason}

請嚴格依照以下 JSON 格式回答，不要加其他文字：
{{
  "day1": {{"trend": "偏多", "confidence": "高", "reason": "15字內原因"}},
  "day2": {{"trend": "盤整", "confidence": "中", "reason": "15字內原因"}},
  "day3": {{"trend": "偏弱", "confidence": "低", "reason": "15字內原因"}}
}}
trend 只能填：偏多、偏弱、盤整 其中一個。
confidence 只能填：高、中、低 其中一個。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=8192,
            )
            raw  = response.choices[0].message.content or ""
            data = self._parse_json_safe(raw)

            days  = ["明日", "後天", "+3天"]
            label = ["day1", "day2", "day3"]
            result = []
            for i, key in enumerate(label):
                d = data.get(key, {})
                trend = d.get("trend", "盤整")
                result.append({
                    "day":        days[i],
                    "trend":      trend,
                    "color":      self._trend_color(trend),
                    "confidence": d.get("confidence", "低"),
                    "reason":     d.get("reason", "資料不足"),
                })
            logger.info(f"[{symbol}] 3日走勢預測完成")
            return result

        except Exception as e:
            logger.error(f"3日走勢預測失敗：{e}")
            return self._default_forecast()

    def _trend_color(self, trend: str) -> str:
        if trend == "偏多":
            return "green"
        if trend == "偏弱":
            return "red"
        return "yellow"

    def _default_forecast(self) -> list:
        return [
            {"day": "明日", "trend": "盤整", "color": "yellow", "confidence": "低", "reason": "GPT 未啟用"},
            {"day": "後天", "trend": "盤整", "color": "yellow", "confidence": "低", "reason": "GPT 未啟用"},
            {"day": "+3天", "trend": "盤整", "color": "yellow", "confidence": "低", "reason": "GPT 未啟用"},
        ]

    def _parse_json_safe(self, text: str) -> dict:
        """
        從 GPT 回應中安全地解析 JSON
        支援回應夾雜在 markdown 程式碼區塊中的情況
        """
        import re
        # 嘗試直接解析
        try:
            return json.loads(text)
        except Exception:
            pass
        # 嘗試從 ```json ... ``` 區塊取出
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        # 完全解析失敗，回傳預設值
        logger.warning(f"JSON 解析失敗，原始回應：{text[:500]}")
        return {"score": 0.0, "reason": "GPT 回應格式異常"}

    def _fetch_google_news(self, symbol: str) -> list:
        """
        使用 Google News RSS 抓取台股新聞
        搜尋關鍵字：去掉 .TW 後綴的股票代號
        """
        try:
            # 取出純數字代號（例如 0050.TW → 0050）
            ticker_code = symbol.replace(".TW", "").replace(".TWO", "")

            # 建立搜尋關鍵字（用台股代號 + 台股搜尋）
            query = urllib.parse.quote(f"{ticker_code} 台股")
            url = (
                f"https://news.google.com/rss/search"
                f"?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
            )

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read()

            root   = ET.fromstring(content)
            titles = []
            for item in root.findall(".//item")[:10]:
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    # 移除 " - 媒體名稱" 的後綴
                    title = title_el.text.split(" - ")[0].strip()
                    titles.append(title)

            logger.info(f"[{symbol}] Google News 取得 {len(titles)} 則新聞")
            return titles

        except Exception as e:
            logger.warning(f"Google News 抓取失敗：{e}")
            return []

    def _analyze_no_news(self, symbol: str) -> dict:
        """
        找不到新聞時，讓 GPT 根據大盤環境給出基本情緒判斷
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": (
                        f"台股 {symbol} 目前找不到新聞，請給出中性偏保守的情緒評估。\n"
                        f"請只回傳 JSON，格式：{{\"score\": 0.0, \"reason\": \"說明\"}}\n"
                        f"score 範圍 -0.3 到 +0.3。"
                    )},
                ],
                max_completion_tokens=150,
            )
            raw    = response.choices[0].message.content or ""
            result = self._parse_json_safe(raw)
            score  = float(np.clip(result.get("score", 0.0), -0.3, 0.3))
            reason = result.get("reason", "") + "（無最新新聞，評分保守）"
            return {"score": score, "reason": reason, "news_count": 0, "available": True}

        except Exception as e:
            logger.error(f"備援情緒分析失敗：{e}")
            return {"score": 0.0, "reason": "無法取得情緒資料", "news_count": 0, "available": False}

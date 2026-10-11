"""Offline HTTP/SDK, routing, settings and source-display regression tests."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_home = tempfile.TemporaryDirectory(prefix="stock-search-test-")
os.environ["LOCALAPPDATA"] = _home.name
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

import httpx
from openai import OpenAI
from data.web_search import (PerplexitySearchClient, citation_sources, parse_analysis,
                             search_settings, safe_url)


def completion(content=None, annotations=None, finish="stop", count=1):
    return {"id": "offline-test", "object": "chat.completion", "created": 1,
            "model": "test/chat", "choices": [{"index": 0, "finish_reason": finish,
            "message": {"role": "assistant", "content": content if content is not None else json.dumps({
                "score": .4, "reason": "公告與新聞偏正向", "impact": "high", "timeframe": "short",
                "industry_effect": {"has_effect": True, "detail": "半導體產業連動"}, "key_event": "公司公告"}),
            "annotations": annotations if annotations is not None else [
                {"type": "url_citation", "url_citation": {"url": "https://example.com/news",
                 "title": "測試新聞", "content": "測試摘要", "start_index": 0, "end_index": 3}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30,
                      "server_tool_use": {"web_search_requests": count}}}


class SearchTests(unittest.TestCase):
    def setUp(self):
        PerplexitySearchClient._cache.clear()
        self.calls = []
        self.payload = completion()
        self.status = 200

        def handler(request):
            self.calls.append(json.loads(request.content))
            return httpx.Response(self.status, json=self.payload)
        self.http = httpx.Client(transport=httpx.MockTransport(handler))
        self.client = OpenAI(api_key="FAKE-TEST-NOT-A-KEY", base_url="https://openrouter.ai/api/v1",
                             http_client=self.http, max_retries=0, timeout=60)

    def tearDown(self):
        self.client.close()

    def engine(self, config=None, account="fake-account", model="test/chat"):
        return PerplexitySearchClient(self.client, model, config or {}, account)

    def test_sdk_sends_server_tool_budget_and_preserves_reasoning(self):
        with patch("data.web_search.request_options", return_value={"max_tokens": 4096,
                   "extra_body": {"reasoning": {"effort": "low", "exclude": True}},
                   "response_format": {"type": "json_object"}}):
            result = self.engine({"news_search_max_uses": 2, "news_search_context": "low"}).analyze("2330.TW", "JSON only")
        body = self.calls[0]
        self.assertEqual(body["model"], "test/chat")
        self.assertEqual(body["tools"], [{"type": "openrouter:web_search", "parameters": {
            "engine": "perplexity", "max_results": 5, "max_total_results": 10,
            "search_context_size": "low", "max_uses": 2}}])
        self.assertEqual(body["max_tool_calls"], 2)
        self.assertEqual(body["reasoning"]["effort"], "low")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIn("台積電", body["messages"][1]["content"])
        self.assertIn("最近七天", body["messages"][1]["content"])
        self.assertEqual(result["news_count"], 1)
        self.assertEqual(result["search_requests"], 1)
        self.assertEqual(result["source"], "perplexity")
        self.assertEqual(result["sources"][0]["url"], "https://example.com/news")

    def test_cache_is_defensive_and_separated_by_account_model_settings(self):
        first = self.engine().analyze("2330.TW", "prompt")
        first["sources"].clear()
        cached = self.engine().analyze("2330.TW", "prompt")
        self.assertTrue(cached["cached"])
        self.assertEqual(len(cached["sources"]), 1)
        self.assertEqual(len(self.calls), 1)
        self.engine(account="other").analyze("2330.TW", "prompt")
        self.engine(model="other/model").analyze("2330.TW", "prompt")
        self.engine({"news_search_context": "high"}).analyze("2330.TW", "prompt")
        self.assertEqual(len(self.calls), 4)

    def test_expired_cache_refetches(self):
        self.engine().analyze("2330.TW", "prompt")
        with patch("data.web_search.time.monotonic", return_value=10**15):
            self.assertFalse(self.engine().analyze("2330.TW", "prompt")["cached"])
        self.assertEqual(len(self.calls), 2)

    def test_missing_citations_never_trusts_model_written_sources(self):
        self.payload = completion(json.dumps({"score": .8, "reason": "made up", "news_count": 99,
                                  "sources": [{"url": "https://fake.example/news"}]}), annotations=[])
        with self.assertRaises(ValueError):
            self.engine().analyze("2330.TW", "prompt")
        self.assertFalse(PerplexitySearchClient._cache)

    def test_truncated_invalid_json_and_zero_search_are_not_cached(self):
        for payload in [completion(finish="length"), completion("invalid"), completion(count=0),
                        completion('{"score":true,"reason":"x"}'),
                        completion('{"score":NaN,"reason":"x"}')]:
            with self.subTest(payload=payload):
                self.payload = payload
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    self.engine().analyze("2330.TW", "prompt")
                self.assertFalse(PerplexitySearchClient._cache)

    def test_missing_usage_does_not_invent_a_search_count(self):
        del self.payload["usage"]
        self.assertIsNone(self.engine().analyze("2330.TW", "prompt")["search_requests"])

    def test_http_error_does_not_auto_retry(self):
        self.status = 429
        self.payload = {"error": {"message": "rate limit", "code": 429}}
        with self.assertRaises(Exception):
            self.engine().analyze("2330.TW", "prompt")
        self.assertEqual(len(self.calls), 1)


class NormalizationTests(unittest.TestCase):
    def test_settings_clamp_and_keep_model_and_keys_out_of_normalization(self):
        value = search_settings({"news_search_provider": "bad", "news_search_max_uses": 100,
                                 "news_search_context": "bad", "news_search_rss_fallback": "false"})
        self.assertEqual(value, {"news_search_provider": "perplexity", "news_search_max_uses": 3,
                                "news_search_context": "medium", "news_search_rss_fallback": False})
        self.assertEqual(search_settings({"news_search_max_uses": True})["news_search_max_uses"], 1)

    def test_nested_fenced_json_is_parsed(self):
        text = '```json\n{"score":0.5,"reason":"ok","industry_effect":{"has_effect":true,"detail":"x"}}\n```'
        self.assertTrue(parse_analysis(text)["industry_effect"]["has_effect"])

    def test_untrusted_urls_and_duplicate_citations_filtered(self):
        urls = ["javascript:alert(1)", "file:///C:/x", "https://a.example/x", "https://a.example/x",
                "https://user:secret@example.com", "https://[", "https://bad host/path"]
        annotations = [{"type": "url_citation", "url_citation": {"url": u, "title": "x"}} for u in urls]
        annotations.append({"type": "url_citation", "url": "http://b.example/path", "title": "flat"})
        self.assertEqual([x["url"] for x in citation_sources({"annotations": annotations})],
                         ["https://a.example/x", "http://b.example/path"])
        self.assertEqual(safe_url(None), "")


class RoutingTests(unittest.TestCase):
    def analyzer(self, provider="perplexity", fallback=True):
        from data.news_sentiment import NewsSentimentAnalyzer
        analyzer = NewsSentimentAnalyzer.__new__(NewsSentimentAnalyzer)
        analyzer.available = True
        analyzer.model = "test/chat"
        analyzer.search_settings = search_settings({"news_search_provider": provider,
                                                   "news_search_rss_fallback": fallback})
        analyzer.search_client = MagicMock()
        analyzer.brave_client = MagicMock()
        analyzer._analyze_rss = MagicMock(return_value={"available": True, "source": "google_rss",
                                                       "score": .1, "reason": "RSS", "news_count": 1})
        return analyzer

    def test_perplexity_success_does_not_call_brave_or_rss(self):
        analyzer = self.analyzer()
        analyzer.search_client.analyze.return_value = {"available": True, "source": "perplexity"}
        self.assertEqual(analyzer.analyze("2330.TW")["source"], "perplexity")
        analyzer.brave_client.search.assert_not_called()
        analyzer._analyze_rss.assert_not_called()

    def test_search_failure_labels_rss_fallback_and_does_not_leak_error(self):
        analyzer = self.analyzer()
        analyzer.search_client.analyze.side_effect = TimeoutError("secret FAKE-key")
        result = analyzer.analyze("2330.TW")
        self.assertEqual(result["source"], "google_rss")
        self.assertEqual(result["requested_source"], "perplexity")
        self.assertIn("備援", result["search_warning"])
        self.assertNotIn("secret", str(result))

    def test_no_fallback_when_disabled(self):
        analyzer = self.analyzer(fallback=False)
        analyzer.search_client.analyze.side_effect = ValueError("no sources")
        self.assertFalse(analyzer.analyze("2330.TW")["available"])
        analyzer._analyze_rss.assert_not_called()

    def test_auth_and_balance_errors_never_make_second_paid_call(self):
        for status in (401, 402):
            analyzer = self.analyzer()
            error = RuntimeError("secret body")
            error.status_code = status
            analyzer.search_client.analyze.side_effect = error
            result = analyzer.analyze("2330.TW")
            self.assertFalse(result["available"])
            self.assertNotIn("secret", result["reason"])
            analyzer._analyze_rss.assert_not_called()

    def test_explicit_rss_does_not_call_search_services(self):
        analyzer = self.analyzer(provider="google_rss")
        self.assertEqual(analyzer.analyze("2330.TW")["source"], "google_rss")
        analyzer.search_client.analyze.assert_not_called()
        analyzer.brave_client.search.assert_not_called()

    def test_brave_is_only_used_when_selected(self):
        analyzer = self.analyzer(provider="brave")
        analyzer.brave_client.search.return_value = [{"url": "https://example.com/news"}]
        analyzer._analyze_with_brave = MagicMock(return_value={"source": "brave", "available": True})
        self.assertEqual(analyzer.analyze("2330.TW")["source"], "brave")
        analyzer.search_client.analyze.assert_not_called()

    def test_disabled_ai_does_not_search(self):
        analyzer = self.analyzer()
        analyzer.available = False
        self.assertFalse(analyzer.analyze("2330.TW")["available"])
        analyzer.search_client.analyze.assert_not_called()

    def test_init_never_enables_brave_for_perplexity_selection(self):
        from data.news_sentiment import NewsSentimentAnalyzer
        with patch("data.news_sentiment.load_config", return_value={"openrouter_api_key": "FAKE-key",
                   "openrouter_model": "retired/custom", "brave_api_key": "FAKE-brave"}), \
             patch("data.news_sentiment.OpenAI"):
            analyzer = NewsSentimentAnalyzer()
        self.assertIsNone(analyzer.brave_client)
        self.assertEqual(analyzer.model, "retired/custom")


class SettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_legacy_config_new_fields_and_key_model_preservation(self):
        from data import config_manager as c
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            old = {"openrouter_api_key": "FAKE-key", "openrouter_model": "retired/custom",
                   "brave_api_key": "FAKE-brave", "default_symbol": "0050.TW", "future_option": 7}
            path.write_text(json.dumps(old), encoding="utf-8")
            before = path.read_bytes()
            with patch.object(c, "CONFIG_PATH", str(path)):
                migrated = c.load_config()
                self.assertEqual(migrated["news_search_provider"], "perplexity")
                self.assertEqual(path.read_bytes(), before)
                c.save_config({"news_search_context": "high"})
                saved = c.load_config()
                for key, value in old.items():
                    self.assertEqual(saved[key], value)

    def test_settings_roundtrip_and_conditional_controls(self):
        from ui.settings_dialog import SettingsDialog
        config = {"openrouter_api_key": "FAKE-key", "openrouter_model": "retired/custom",
                  "brave_api_key": "FAKE-brave", "news_search_max_uses": 2,
                  "news_search_context": "high", "news_search_rss_fallback": False}
        with patch("ui.settings_dialog.load_config", return_value=config), patch("ui.settings_dialog.save_config") as save:
            dlg = SettingsDialog()
            self.assertEqual(dlg.combo_search_provider.currentData(), "perplexity")
            self.assertTrue(dlg.brave_settings.isHidden())
            self.assertFalse(dlg.search_options.isHidden())
            self.assertEqual(dlg.spin_search_uses.value(), 2)
            dlg.combo_search_provider.setCurrentIndex(dlg.combo_search_provider.findData("brave"))
            self.assertFalse(dlg.brave_settings.isHidden())
            self.assertTrue(dlg.search_options.isHidden())
            dlg._on_save()
            data = save.call_args.args[0]
            self.assertEqual(data["openrouter_model"], "retired/custom")
            self.assertEqual(data["openrouter_api_key"], "FAKE-key")
            self.assertEqual(data["brave_api_key"], "FAKE-brave")
            self.assertEqual(data["news_search_provider"], "brave")
            self.assertEqual(data["news_search_context"], "high")
            self.assertFalse(data["news_search_rss_fallback"])
            dlg.close()

    def test_panel_escapes_sources_preserves_probability_and_clears(self):
        from ui.prediction_panel import PredictionPanel
        panel = PredictionPanel()
        result = {"prediction": {"up_prob": .55, "down_prob": .45, "prediction": 1},
                  "sentiment": {"available": True, "score": .9, "reason": "<b>新聞</b>",
                    "news_count": 1, "source": "perplexity", "search_requests": 1,
                    "sources": [{"url": "https://example.com/news", "title": "<script>bad</script>"},
                                {"url": "javascript:alert(1)", "title": "bad"}]}}
        panel.update_prediction(result)
        self.assertIn("&lt;script&gt;", panel.label_news_sources.text())
        self.assertNotIn("javascript:", panel.label_news_sources.text())
        self.assertIn("Perplexity", panel.label_news_sources.text())
        self.assertEqual(result["prediction"]["up_prob"], .55)
        panel.update_prediction({"sentiment": {"available": False, "reason": "failed"}})
        self.assertTrue(panel.label_news_sources.isHidden())
        panel.reset()
        self.assertEqual(panel.label_news_sources.text(), "")
        panel.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

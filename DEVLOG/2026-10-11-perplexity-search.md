# 2026-10-11 — v1.7.4 OpenRouter Perplexity 新聞搜尋

## 使用者要求

將原本 Brave 優先的新聞搜尋完整接入 OpenRouter Perplexity，並更新設定頁。沿用既有完整包發布與網站同步流程，保留家人設定及資料。

## 接入方式

- 依 OpenRouter 官方現行 [Web Search Server Tool](https://openrouter.ai/docs/guides/features/server-tools/web-search)，向 chat completions 傳送 `openrouter:web_search`，引擎固定 `perplexity`；不使用已棄用的 `:online` 或 web plugin。
- 共用既有 OpenRouter Key 與使用者所選 AI 模型，不切換成 Sonar 或覆寫原模型。搜尋與情緒整理在同一次 completion 內完成；正式 1／3／5 交易日模型機率不變。
- 預設一次搜尋、每次五筆結果，可設最多 1～3 次；同時設定 `max_uses`、`max_tool_calls`、`max_total_results`。資料量可選 low／medium／high。
- 官方現行 Perplexity 搜尋參考費用 US$0.005／次，另計 AI 模型 token 費；介面明確顯示，免費模型也不代表免費搜尋。
- 同股／同模型／同搜尋設定／同帳號／同台北日期的成功結果記憶體快取 30 分鐘，最多 128 筆；不存放明文金鑰，失敗不快取。
- 必須有 API `url_citation` annotations 才採用搜尋分析；模型寫在 JSON 內的來源與新聞數不當作搜尋證據。來源去重、限制數量、過濾非 HTTP(S) 網址；UI 跳脫標題並讓使用者點開來源。
- Prompt 明確提供台北日期，要求最近七天並區分事件／發布日期、不遵循新聞內指令；不保證搜尋內容本身一定正確或提高預測勝率。
- Brave 原 Key 保留，可選 Brave 或 RSS；Perplexity 失敗依設定使用 RSS 並標示原因，401／402 不再發第二次 AI 請求。未取得新聞或完整分析時不猜測。
- 新設定以預設值補齊，讀取不改寫原檔；保存時保留其他欄位、原 Key、所選模型、自選股與紀錄。

## 驗證與發布狀態

- 搜尋測試以隔離 AppData、假金鑰及 `httpx.MockTransport` 通過 OpenAI SDK 的真實序列化／解析流程，不對外呼叫付費服務。
- 已測試搜尋預算／reasoning 參數合併、annotations、無來源／格式／截斷／限流、401／402、RSS 備援開關、Brave 選擇、快取隔離與設定保存。
- 已檢視 520／680 寬設定頁及新聞來源面板截圖；示範畫面非實際付費搜尋結果。
- Source 全套 70 項通過；EXE 抽出的搜尋／設定／新聞／面板／更新與資源模組共 46 項測試通過。16 個關鍵模組 bytecode 與 source 一致。
- Windows 原生 EXE `--diagnose` exit 0：1／3／5 期限、有限機率、373 模型選項、主畫面／設定／大字模式正常。沒有呼叫付費 AI；`build/verification/native-v174/report.json`。
- 完整 ZIP 351,002,923 bytes，SHA-256 `eac28978f0df3928572a955ce799adf302d0163ff3f8cc7a8a68110fa870f362`。ZIP 路徑／CRC／版本與 4,964 個 manifest 檔案逐一核對通過，無私人設定／紀錄或 TensorFlow。
- 隔離 v1.6.2 格式設定／自選股／舊 CSV 保存與備份通過。v1.6.2 原始更新器接收本機完整 ZIP 串流、解壓 4,964 檔案 hash 一致並準備重啟批次，攔截 installer 子程序，不實際覆蓋使用者軟體。此項不是公開網路整包下載，也未操作媽媽電腦。
- 證據：`tests-v174.txt`、`compiled-updater-v174-report.json`、`embedded-source-v174.json`、`artifact-report-v1.7.4.json`、`legacy-v162-download-v174-report.json`，皆位於 ignored `build/verification/`。
- 公開發布與網站證據於本輪收尾追加；在實際完成前不視為已發布。真實帳號的付費搜尋、模型是否確實呼叫工具及近期資料品質仍待實際使用確認。

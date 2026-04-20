# 台股預測分析系統 — 專案現況

> 最後更新：2026-04-20（Day 15，CSV schema 緊急修復）

## 目前版本
v1.5.5（**已上傳 GitHub Release**）— 修復 v1.5.4 預測記錄欄位錯位 + UI 補「原始機率」欄
- v1.5.4 新增 raw_up_prob 欄位時，舊 CSV header 沒升級造成欄位錯位
- v1.5.5 加自動 migration，啟動時偵測並修復錯位記錄
- 使用者資料已搬遷至 `%LOCALAPPDATA%/台股預測分析系統/`
- 程式更新不再影響使用者的設定、模型、預測記錄
- 內建自動更新檢查（GitHub Releases）— **已實測成功（v1.2.4 → v1.2.5）**
- 差量更新：只下載有變動的檔案（幾 MB），不再每次下載 646MB
- 設定視窗「檢查更新」直接觸發更新（含進度對話框）
- 版本號正確顯示

## 系統可以正常運作的功能
- [x] K線圖 + MA5/MA20 + 成交量副圖（TradingView）
- [x] Transformer + LightGBM 融合預測（明日漲跌機率）
- [x] SHAP 可解釋性分析（前5大驅動因子）
- [x] GPT 新聞情緒分析 + 融合進預測機率
- [x] Brave Search 深度新聞整合（Day 6，取代 Google RSS 為主要來源）
- [x] 情緒權重壓縮調整（Day 6，tanh 緩衝 + 上限 25%→15%）
- [x] GPT 未來 3 日走勢推估
- [x] 模型自動重訓（超過 7 天）
- [x] CSV 報表匯出
- [x] 每個股票有獨立的模型檔案（Day 2 修正）
- [x] Transformer 批次萃取特徵（Day 10 重構，分批 64 筆避免 OOM）
- [x] 自選股抽屜（Day 3+4，手機風格側邊滑入）
  - [x] 左側滑入動畫，半透明遮罩
  - [x] 卡片式清單，含中文名稱
  - [x] 新增/刪除自選股，點擊填入輸入框
- [x] 股票代碼智慧輸入 SmartLineEdit（Day 3）
  - [x] 即時搜尋代碼 + 中文名稱，向上/向下自動彈出
  - [x] 動態抓取全市場代碼（TWSE/TPEX，7天快取）
- [x] 技術訊號掃描（MACD 金叉/死叉、RSI 超買/超賣，Day 4）
- [x] 準確率趨勢圖（每週折線圖，Day 4）
- [x] 全系統台灣慣例顏色（紅漲綠跌，Day 4）
- [x] 全自動準確率驅動重訓（Day 4 補充）
  - [x] 最近 20 筆 < 52% 自動觸發，3 天冷卻期
  - [x] 背景靜默執行，狀態列通知結果
- [x] UI 精簡：移除重訓/匯出按鈕（Day 4 補充）
- [x] 本次查詢記錄 hover 樣式修復（Day 4 補充）
- [x] Splash Screen 啟動畫面（Day 4 補充）
  - [x] 旋轉 Spinner 動畫（QPainter，無需 GIF）
  - [x] 漸層弧線（iOS 風格頭亮尾暗）
  - [x] 底部進度條（隨步驟推進）
  - [x] 依序顯示載入進度（AppLoader 背景執行緒，spinner 不停頓）
  - [x] 首次啟動自動顯示警語
  - [x] App Icon 統一設定（所有視窗繼承）
  - [x] Logo 顯示於 Splash 上方（Day 5，120px，RGBA 透明背景）
  - [x] App Icon 正確顯示於標題列與工作列（Day 5，多尺寸 ICO）
- [x] 籌碼面特徵整合（Day 5 + Day 9 強化）
  - [x] 三大法人淨買超（外資/投信/自營商）
  - [x] 融資融券餘額 + 增減
  - [x] 13 個衍生特徵（含二階：外資加速度、投信連續買超、籌碼共振、融資股價背離等）
  - [x] TWSE API 修復（T86 + TWT93U 新格式，Session cookie，限流偵測）
  - [x] 從最近日期往回抓 + 快取累積機制
- [x] 市場行情狀態辨識（Day 9）
  - [x] 多頭/空頭/盤整自動分類（MA20 vs MA60）
  - [x] 趨勢強度、持續天數、波動率狀態
  - [x] 盤整行情自動降級信心度
  - [x] LightGBM 特徵從 20 維擴充至 36 維
- [x] 預測進度對話框（Day 10）
  - [x] Modal 深色無邊框圓角設計
  - [x] 顯示步驟圖示、百分比、經過時間
  - [x] 籌碼抓取逐日進度回報
- [x] **Transformer 取代 LSTM**（Day 10，架構級升級）
  - [x] 新增 `models/transformer_extractor.py`（3 層 Encoder，107K 參數）
  - [x] 回看窗口 60 天 → 300 天（能捕捉季節性、跨月規律）
  - [x] 輸入維度 17 → 28~41 維（含完整技術面+籌碼+行情）
  - [x] 資料量 1500 → 2500 天（~7 年歷史）
  - [x] 時間衰減權重（近 2 年 1.0 / 2~4年 0.7 / 4~6年 0.4）
  - [x] 分批特徵萃取（避免記憶體爆掉）
  - [x] LightGBM 搭配重訓防呆
  - [x] 舊模型自動清理（`cleanup_legacy_models()`，使用者無感）
  - [x] LSTM 保留作為備用退路
- [x] 全專案 LSTM 殘留引用清理（Day 10，8 個檔案，UI/docstring/變數名全部更新為 Transformer）
- [x] Bug Fix：自動更新後版本號未更新（Day 10，三道防線）
- [x] Bug Fix：Win10 預測記錄表格白色背景（Day 10）
- [x] Bug Fix：差量更新包重複打包覆蓋基準線（Day 10）
- [x] Bug Fix：needs_retrain() 未傳 symbol（Day 5）
- [x] Bug Fix：TWSE API 大小寫問題（holiday_checker + chip_fetcher，Day 5）
- [x] LightGBM 特徵維度防護（維度不符自動重訓，Day 5）
- [x] 原廠重置（清除所有舊模型/快取/記錄，Day 5）
- [x] PyInstaller 打包完成（v1.0，Day 5）
  - [x] 含 App Icon、Logo、原廠空白資料
  - [x] 輸出：台股預測分析系統_v1.0.0.zip（638 MB，含 bug fix）
- [x] factory_defaults 原廠範本機制（Day 6）
  - [x] 打包時自動用乾淨範本覆蓋 dist，不動開發者原始檔案
  - [x] 新增設定或資料檔時只需更新 factory_defaults/ 即可
- [x] 台股假日自動偵測（Day 4 補充）
  - [x] TWSE 官方 API + exchange_calendars 雙重來源
  - [x] 本機快取 7 天，啟動自動更新，永久有效
  - [x] 按預測時自動判斷，休市彈出提示視窗
- [x] UI 主題全面換鐵灰色系（Day 3 補充）
- [x] K 線圖純黑主題（Day 3 補充）
- [x] 啟動回填通知（狀態列顯示回填筆數與準確率，Day 3 補充）
- [x] ★ 按鈕 toggle 修復（Day 3 補充）
- [x] 預測記錄機制（prediction_log.csv，Day 3）
  - [x] 每次預測自動記錄
  - [x] 啟動/預測時自動回填 actual 結果
  - [x] 回測準確率報告（整體 + 按股票）
  - [x] 刪除記錄、匯出 CSV

## 待討論 / 待決定

## Day 13 已完成（2026-04-10）
- [x] 修復即時行情顯示 nan（get_latest_price 啟用 repair + NaN 過濾）
- [x] 修復 K 線圖缺少當日 K 棒（fetch_history 啟用 repair 模式）
- [x] 修復預測記錄回填失敗（backfill 啟用 repair + 「資料延遲」fallback）
- [x] 修復 exe 環境 CSV 寫入未落盤（flush + fsync）
- [x] 修復背景執行緒覆蓋主執行緒資料（_save_all 合併保護）
- [x] 4/8 遺失 9 筆預測記錄從 app log 救回並回填成功
- [x] 預測記錄 UI 增強（資料延遲橘色提示、延遲筆數顯示）
- [x] **v1.5.2 打包上傳**（含 v1.5.1 修復）

## Day 12 已完成（2026-04-03）
- [x] 修復預測記錄 BOM 編碼汙染（utf-8-sig append 模式導致回填永遠失敗）
- [x] 修復自動更新 bat 腳本中文路徑導致無限重啟循環
- [x] CSV 資料救援（從截圖重建 26 筆記錄，全數回填成功）
- [x] **v1.4.3 打包上傳**（兩次，第二次含更新機制修復）
- [x] **成交量異常偵測**（4 維新特徵：Z-score、爆量突破、量價背離、量能趨勢）
- [x] **分市場狀態訓練**（多頭/空頭/盤整各訓練 LightGBM，預測時 65/35 混合）
- [x] SHAP 中文標籤更新（4 個量能特徵）
- [x] **v1.5.0 打包上傳**

## Day 11 已完成（2026-04-01）
- [x] 修復 K 線圖日期缺少當天資料（yfinance end exclusive，+1 day）
- [x] 修復啟動偶發閃退（啟動序列 try/except + AppLoader done signal + os.remove 保護）
- [x] **v1.4.1 打包上傳**
- [x] 修復預測記錄漲跌%顯示 0.00%（pred_close 方向 after→before）
- [x] 修復預測記錄漲跌%顯示 nan%（_near_price NaN 過濾）
- [x] 錯誤回填記錄自動重算機制
- [x] **v1.4.2 打包上傳**

## Day 10 已完成（2026-03-30）
- [x] **★ Transformer 取代 LSTM**（模型架構升級，300天窗口，28~41維輸入，時間衰減權重）
- [x] 資料量擴充 1500→2500 天（含美股同步擴充）
- [x] 舊模型自動清理機制（LSTM→Transformer 無感遷移）
- [x] **全專案 LSTM 引用清理**（8 個檔案）
- [x] 修復自動更新版本號未更新
- [x] 新增預測進度對話框（PredictionProgressDialog）
- [x] 修復 Win10 預測記錄表格白色背景
- [x] v1.3.1 / v1.3.2 發佈

## Day 7 後半（2026-03-27 下午）— v1.2.0 補充
- [x] 設定視窗新增「關於/更新」第三分頁
  - [x] 顯示目前版本號（大綠字）
  - [x] 手動「檢查更新」按鈕
  - [x] 顯示 v1.2.0 / v1.1.0 / v1.0.0 完整更新日誌
- [x] 上傳 v1.2.0 Release 至 GitHub（`台股預測分析系統_v1.2.0.zip`，646 MB）
- [x] GitHub repo 設為 Public（Private 時 API 回 404，自動更新無法運作）
- [x] 實測自動更新成功：v1.1.0 偵測到 v1.2.0 → 彈出更新對話框 → 一鍵更新 ✅（全自動，使用者不需手動解壓縮）
- [x] 修正 GitHub Release 說明（移除誤導的「手動解壓縮」文字）
- [x] v1.2.0 為交付父母的最終版本

> **📦 GitHub 倉庫資訊**
> - URL：https://github.com/littleblackmann/stock-predictor
> - 帳號：littleblackmann / 信箱：b0986816338@gmail.com
> - **必須保持 Public**，否則 API 回 404，自動更新失效

> **⚠️ 注意事項（未來維護必讀）**
> - 「立即更新」按鈕：全自動（下載→解壓→覆蓋→重啟），使用者不需手動操作
> - Release notes 不要寫「手動解壓縮」等文字，會顯示在更新對話框中造成誤解
> - Release 版本 tag 格式必須為 `v1.x.x`（updater 會 lstrip "v" 取數字比對）
> - 每次發佈新版：① 更新 `version.json` ② commit & push ③ `build.py` 打包 ④ `gh release create`
> - `gh` CLI 位置：`/c/Program Files/GitHub CLI/gh.exe`（bash 中需用完整路徑）

## Day 7 已完成
- [x] Bug Fix：特徵工程 inf 問題（00922 等新 ETF 除以零）
- [x] 程式/資料分離架構（AppData）
  - [x] 新增 `data/data_paths.py` 統一管理路徑
  - [x] 10 個模組改用 data_paths 匯入路徑
  - [x] 首次啟動自動遷移舊版資料
  - [x] 程式更新不再影響使用者資料
- [x] 自動更新機制
  - [x] 新增 `updater/auto_updater.py`
  - [x] GitHub Releases API 版本檢查
  - [x] 一鍵下載 + 覆蓋 + 重啟
  - [x] 跳過版本 / 稍後提醒選項
- [x] 版本管理：`version.json`（build.py + updater 共用）
- [x] 打包流程更新（移除 factory_defaults，簡化為 3 步驟）
- [x] .spec 新增 litert hidden import（修復 Win10 TensorFlow 問題）
- [x] 專案報告：技術版 + 簡報版

## Day 6 已完成
- [x] 模型自我進化機制 — 讓系統「越用越準」
  - [x] 累積式訓練窗口（700→1500 天，~6 年歷史資料）
  - [x] Ensemble 投票（TimeSeriesSplit 3 模型平均預測）
  - [x] 增量式訓練（init_model 接續上代模型繼續學習）
  - [x] 特徵自動篩選（min_gain_to_split=0.01 自動忽略雜訊特徵）
  - [x] 準確率門檻提高（52%→55%，逼模型持續進步）

## 待開發功能（未來可選）

### 準確度提升
- [x] 成交量異常偵測（Day 12，Z-score + 爆量突破 + 量價背離 + 量能趨勢，4 維新特徵）
- [ ] 預測結果加權回饋（記錄每次預測的 SHAP top 5，統計哪些特徵組合預測最準，動態調整權重，meta-learning 概念）
- [x] 分市場狀態建模（Day 9，市場行情特徵 + 盤整信心度降級，已整合進現有模型）
- [x] 分市場狀態訓練（Day 12，多頭/空頭/盤整各訓練 LightGBM，65/35 混合預測）
- [x] **Transformer 取代 LSTM**（Day 10，300天窗口 + 28~41維輸入 + 時間衰減權重）

### 美觀 / UX 改進
- [ ] 儀表板首頁（打開時顯示「今日總覽」：自選股紅綠燈快速狀態、昨日預測回顧、累積準確率趨勢小圖、大盤指數快覽）
- [ ] 環形圖（儀表板風格）顯示漲跌機率（取代或搭配目前的進度條）
- [ ] 定時自動預測自選股（每天定時自動預測，結果存起來等使用者打開查看）

## 已知問題 / 技術債
- config.json 中的 API Key 是明文（使用者自用，暫不處理）
- OpenAI 模型名稱需確認（使用者確認有效，暫不處理）

## 技術架構快速參考
| 層級 | 技術 |
|------|------|
| UI | PySide6 + QSS 深色霓虹主題 |
| 圖表 | TradingView Lightweight Charts（QWebEngineView） |
| 資料 | yfinance（2500天 OHLCV）+ Brave Search（主）/ Google News RSS（備） |
| 特徵 | 32~45維（技術指標13+量能異常4+籌碼面13+市場行情4+美股隔夜4+多時間框架2+OHLCV 5） |
| 時序模型 | Transformer(3層 Encoder, 300天窗口) 時序萃取，取代 LSTM |
| 分類模型 | LightGBM Ensemble(×3) + 行情專用模型(×3) 融合分類 |
| AI分析 | OpenAI GPT（新聞情緒 + 3日走勢） |
| 並發 | QThreadPool 背景執行緒 |
| 日誌 | QueueHandler 非同步寫入 |
| 資料存放 | %LOCALAPPDATA%/台股預測分析系統/（AppData 分離） |
| 自動更新 | GitHub Releases API + bat 腳本覆蓋 + 差量更新（patch zip） |

## 工作日誌索引
- [Day 1 (2026-03-19)](./2026-03-19.md) — 系統從零建立
- [Day 2 (2026-03-20)](./2026-03-20.md) — Bug修正（模型分開存、批次萃取、進度條）
- [Day 3 (2026-03-21)](./2026-03-21.md) — 自選股清單功能
- [Day 4 (2026-03-22)](./2026-03-22.md) — 技術訊號、趨勢圖、紅漲綠跌、popup bug 修復
- [Day 5 (2026-03-23)](./2026-03-23.md) — 籌碼面特徵、curl_cffi shim、打包版修復（v1.0.0 正式發行）
- [Day 6 (2026-03-24)](./2026-03-24.md) — Brave Search 深度新聞、情緒壓縮、模型自我進化機制
- [Day 7 (2026-03-27)](./2026-03-27.md) — 程式/資料分離（AppData）、自動更新機制、inf Bug 修復
- [Day 8 (2026-03-28)](./2026-03-28.md) — 更新機制修正、差量更新、Win10 相容性
- [Day 9 (2026-03-29)](./2026-03-29.md) — 籌碼面特徵強化、分行情建模、TWSE API 修復
- [Day 10 (2026-03-30)](./2026-03-30.md) — **Transformer 取代 LSTM**、LSTM 引用清理、更新機制修復、進度對話框
- [Day 11 (2026-04-01)](./2026-04-01.md) — Bug 修復三連發（K線日期+啟動閃退+漲跌%）、v1.4.1 / v1.4.2 上傳
- [Day 12 (2026-04-03)](./2026-04-03.md) — BOM 編碼修復 + 自動更新重啟循環修復 + CSV 資料救援、v1.4.3 上傳
- [Day 13 (2026-04-10)](./2026-04-10.md) — yfinance NaN 全面修復（即時行情+K線+回填）、v1.5.2 上傳
- [Day 14 (2026-04-18)](./2026-04-18.md) — 準確率調校（情緒降權 + 類別平衡 + 美股 NaN）、v1.5.4 上傳
- [Day 15 (2026-04-20)](./2026-04-20.md) — v1.5.4 CSV schema 錯位緊急修復（v1.5.5 上傳）

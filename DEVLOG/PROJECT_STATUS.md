# 台股預測分析系統 — 專案現況

> 最後更新：2026-03-28（Day 8，更新機制修正 + 差量更新）

## 目前版本
v1.2.8（最新穩定版）
- 使用者資料已搬遷至 `%LOCALAPPDATA%/台股預測分析系統/`
- 程式更新不再影響使用者的設定、模型、預測記錄
- 內建自動更新檢查（GitHub Releases）— **已實測成功（v1.2.4 → v1.2.5）**
- 差量更新：只下載有變動的檔案（幾 MB），不再每次下載 646MB
- 設定視窗「檢查更新」直接觸發更新（含進度對話框）
- 版本號正確顯示

## 系統可以正常運作的功能
- [x] K線圖 + MA5/MA20 + 成交量副圖（TradingView）
- [x] LSTM + LightGBM 融合預測（明日漲跌機率）
- [x] SHAP 可解釋性分析（前5大驅動因子）
- [x] GPT 新聞情緒分析 + 融合進預測機率
- [x] Brave Search 深度新聞整合（Day 6，取代 Google RSS 為主要來源）
- [x] 情緒權重壓縮調整（Day 6，tanh 緩衝 + 上限 25%→15%）
- [x] GPT 未來 3 日走勢推估
- [x] 模型自動重訓（超過 7 天）
- [x] CSV 報表匯出
- [x] 每個股票有獨立的模型檔案（Day 2 修正）
- [x] LSTM 批次萃取特徵（Day 2 修正，速度大幅提升）
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
- [x] 籌碼面特徵整合（Day 5）
  - [x] 三大法人淨買超（外資/投信/自營商）
  - [x] 融資融券餘額 + 增減
  - [x] 7 個衍生特徵（含外資連續買超天數、軋空比等）
  - [x] TWSE API + 本機快取，無縫降級機制
  - [x] LightGBM 特徵從 13 維擴充至 20 維
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
- [ ] 成交量異常偵測（volume_ratio = volume / volume_ma20，突然放量 2x 以上代表主力進出，預估 +1~2%）
- [ ] 預測結果加權回饋（記錄每次預測的 SHAP top 5，統計哪些特徵組合預測最準，動態調整權重，meta-learning 概念）
- [ ] 分市場狀態訓練（多頭/空頭/盤整各訓練專門模型，預測時先判斷市場狀態再用對應模型，預估 +3~5%）
- [ ] Transformer 時序模型取代 LSTM（Attention 機制更能捕捉遠距離模式，開發成本較高，等系統穩定後再考慮）

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
| 資料 | yfinance（1500天 OHLCV）+ Brave Search（主）/ Google News RSS（備） |
| 特徵 | 13維技術指標（RSI/MACD/布林/ATR/量比等） |
| 模型 | LSTM(128→64) 時序萃取 + LightGBM Ensemble(×3) 融合分類 |
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

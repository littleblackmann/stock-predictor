台股預測分析系統 v1.7.0
Windows 10 / 11 (64-bit)，需連線取得行情與新聞。

【安裝與更新】
既有使用者：重新開啟程式，點「立即更新」；也可從設定的「關於 / 更新」檢查。
新使用者：到 GitHub Releases 下載 StockPredictor-v1.7.0.zip，解壓後執行
「台股預測分析系統.exe」。不需要安裝 Python。
https://github.com/littleblackmann/stock-predictor/releases/latest
本次提供完整更新包，下載較大；請等待下載、解壓與重新啟動完成。
設定、API Key、自選股、模型與紀錄存放在 %LOCALAPPDATA%\台股預測分析系統\。
更新保留原有資料，首次讀取舊紀錄時另外建立 .pre-v1.7.bak 備份。

【短線分析】
輸入代號，例如 0050、2330 或完整代號 6488.TWO，按「短線分析」。
查看未來 1、3、5 個交易日相對於資料日收盤價的上漲／下跌機率。
每個期間都有獨立模型，畫面列出資料日、目標日與時間分段回測結果。
只使用完成的日線資料，台北時間 15:00 前不把當日日線當作已完成。
機率接近五成，或回測未同時勝過基準的命中率與機率誤差時，顯示「方向不明」。
模型會在行情更新時重新計算；查詢相同資料使用快取。
新增大字模式與自選股總覽，總覽只讀取既有結果，不會呼叫付費 AI。

【OpenRouter 模型】
量化預測不需要 API Key；填入 OpenRouter Key 後可使用 AI 新聞分析。
在設定搜尋模型，查看每百萬 token 的參考費用，也能按「更新模型清單」。
內建清單取自 OpenRouter 公開目錄，包含 GPT-6.1 Sol、Claude Sonnet 5.5、
Claude Opus 5.5、GPT-6 Astra、Gemini 3.8 Flash 等選項。
更新程式或模型清單不會替換原本選好的模型。可用性及實際費用依帳號與供應商為準。
新聞 AI 用於解釋新聞，不直接改寫量化機率；找不到新聞時會明確顯示無資料。
Brave Search Key 為選填，未填時使用 Google News RSS。

【紀錄與驗證】
1、3、5 日紀錄分開保存，同一資料日、目標日和模型版本不重複覆寫。
目標日行情完成後才回填結果；缺少精確目標日資料時繼續等待。
舊版紀錄仍可查看，但不混入新版命中率，避免不同日期定義造成誤導。
歷史回測不代表未來報酬，也不包含交易成本。本軟體提供研究參考，不保證獲利。

【開發者】
啟動：python main.py
測試：python -m unittest discover -s tests -v
打包：python build.py
隔離診斷：python main.py --diagnose OUTPUT_DIR [--network-smoke]
診斷不使用現有 API Key；--network-smoke 只測行情及交易日曆，不呼叫付費 AI。
現行量化路徑：models/short_term.py，使用分時訓練、獨立校準與保留時段驗證。
舊 Transformer 程式與模型保留供研究；正式短線預測不載入舊模型。
完整技術與驗證紀錄：DEVLOG/2026-10-04.md。

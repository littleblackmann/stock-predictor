"""
yfinance 資料獲取模組
負責從 Yahoo Finance 下載台股歷史 OHLCV 資料
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from logger.app_logger import get_logger

logger = get_logger(__name__)


class YFinanceAdapter:
    """
    yfinance 資料獲取器
    提供標準化的 DataFrame 輸出供特徵工程使用
    """

    # 台股代號格式範例
    TW_STOCK_SUFFIX = ".TW"
    TW_OTC_SUFFIX = ".TWO"

    def __init__(self):
        logger.info("YFinanceAdapter 初始化完成")

    def normalize_symbol(self, symbol: str) -> str:
        """
        自動補全台股代號後綴
        例如：0050 → 0050.TW，2330 → 2330.TW
        """
        symbol = symbol.strip().upper()
        if not symbol.endswith((".TW", ".TWO", ".NYSE", ".NASDAQ")):
            symbol = symbol + self.TW_STOCK_SUFFIX
        return symbol

    def fetch_history(
        self,
        symbol: str,
        period_days: int = 500,
        progress_callback=None
    ) -> pd.DataFrame:
        """
        下載指定股票的歷史資料

        Args:
            symbol: 股票代號（如 0050 或 0050.TW）
            period_days: 往前抓取幾天的資料（需 > 300 以供 Transformer 使用）
            progress_callback: 進度回呼函數 (int 0-100, str 訊息)

        Returns:
            包含 Open, High, Low, Close, Volume 的 DataFrame
            索引為日期（DatetimeIndex），已排除空值
        """
        symbol = self.normalize_symbol(symbol)
        logger.info(f"開始下載 [{symbol}] 的歷史資料，請求 {period_days} 天")

        if progress_callback:
            progress_callback(10, f"正在連線 Yahoo Finance，下載 {symbol}...")

        try:
            end_date = datetime.today() + timedelta(days=1)  # yfinance end 是 exclusive，+1 才能含今天
            start_date = end_date - timedelta(days=period_days)

            ticker = yf.Ticker(symbol)
            try:
                df = ticker.history(
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                    auto_adjust=True,  # 自動還原除權息
                    repair=True,       # 修復 NaN / 幣值混淆
                )
            except TypeError:
                # yfinance timezone 快取未命中（打包環境首次執行常見）
                # 改用 period 參數繞過時區轉換
                logger.warning(f"[{symbol}] yfinance timezone cache miss，切換 period 模式重試")
                period_str = "2y" if period_days >= 700 else ("1y" if period_days >= 365 else "6mo")
                df = ticker.history(period=period_str, auto_adjust=True, repair=True)

            if df.empty:
                raise ValueError(f"找不到 [{symbol}] 的資料，請確認代號是否正確")

            if progress_callback:
                progress_callback(30, f"下載完成，共取得 {len(df)} 筆交易日資料")

            df = self._clean_data(df)

            logger.info(f"[{symbol}] 資料下載成功，共 {len(df)} 筆，"
                        f"期間 {df.index[0].date()} ~ {df.index[-1].date()}")
            return df

        except Exception as e:
            logger.warning(f"[{symbol}] yfinance 連線失敗，改用 Yahoo 行情端點：{type(e).__name__}")
            return self.fetch_chart(symbol, period_days)

    @staticmethod
    def fetch_chart(symbol, period_days=2500):
        """Cookie-independent Yahoo chart fallback with adjusted OHLC prices."""
        import requests
        from urllib.parse import quote
        from data.market_time import taipei_now
        last_error = None
        for host in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com'):
            try:
                response = requests.get(
                    f'https://{host}/v8/finance/chart/{quote(symbol, safe="")}',
                    params={'range':'10y', 'interval':'1d'},
                    headers={'User-Agent':'Mozilla/5.0'}, timeout=15)
                response.raise_for_status()
                payload = response.json()['chart']
                if payload.get('error') or not payload.get('result'):
                    raise ValueError('行情來源未提供資料')
                chart = payload['result'][0]
                quotes = chart['indicators']['quote'][0]
                idx = pd.to_datetime(chart['timestamp'], unit='s', utc=True)
                idx = idx.tz_convert(chart['meta']['exchangeTimezoneName']).tz_localize(None).normalize()
                frame = pd.DataFrame({key.title():quotes[key] for key in ('open','high','low','close','volume')}, index=idx)
                adjusted = chart['indicators'].get('adjclose')
                if adjusted:
                    factor = pd.Series(adjusted[0]['adjclose'],index=idx)/frame['Close']
                    for col in ('Open','High','Low','Close'):
                        frame[col] *= factor
                frame = frame.replace([np.inf,-np.inf], np.nan).dropna()
                frame = frame.loc[frame['Close']>0]
                cutoff = (taipei_now()-timedelta(days=period_days)).date()
                frame = frame.loc[frame.index.date>=cutoff].sort_index()
                frame = frame.loc[~frame.index.duplicated(keep='last')]
                if frame.empty:
                    raise ValueError('行情資料不足')
                if symbol.endswith('.TW') and idx[-1] > frame.index[-1]:
                    frame = YFinanceAdapter.repair_recent_twse(frame, symbol, idx[-1].date())
                return frame
            except Exception as e:
                last_error = e
        raise ValueError(f'無法取得 {symbol} 行情，請稍後再試') from last_error

    @staticmethod
    def repair_recent_twse(frame, symbol, target_date):
        """Fill missing tail sessions from TWSE's monthly official OHLC report.

        Existing adjusted Yahoo history is retained. Only append missing tail
        dates, with official volume in shares. Never fill a missing day by ffill.
        """
        import requests
        try:
            response = requests.get('https://www.twse.com.tw/exchangeReport/STOCK_DAY',
                params={'response':'json','date':target_date.strftime('%Y%m%d'),
                        'stockNo':symbol.split('.')[0]}, timeout=15)
            response.raise_for_status()
            payload = response.json()
            if payload.get('stat') != 'OK':
                return frame
            rows=[]
            for item in payload.get('data',[]):
                year,month,day=map(int,item[0].split('/'))
                stamp=pd.Timestamp(year+1911,month,day)
                if stamp <= frame.index[-1] or stamp.date() > target_date:
                    continue
                nums=[float(str(item[i]).replace(',','')) for i in (3,4,5,6,1)]
                if not all(np.isfinite(nums)) or nums[3]<=0:
                    continue
                rows.append(dict(zip(('Open','High','Low','Close','Volume'),nums),date=stamp))
            if rows:
                tail=pd.DataFrame(rows).set_index('date')
                frame=pd.concat([frame,tail]).sort_index()
                logger.info('[%s] 已用 TWSE 官方資料補齊 %d 個交易日',symbol,len(tail))
            return frame
        except Exception:
            logger.warning('[%s] 官方尾端行情暫不可用，保留缺漏狀態',symbol)
            return frame

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        清理資料：
        - 只保留 OHLCV 欄位
        - 移除成交量為 0 的非交易日
        - 移除含有 NaN 的列
        - 確保索引為 UTC 無時區的日期
        """
        # 只保留核心欄位
        cols = ["Open", "High", "Low", "Close", "Volume"]
        df = df[cols].copy()

        # 移除非交易日（成交量為 0）
        df = df[df["Volume"] > 0]

        # 移除空值
        df.dropna(inplace=True)

        # 統一索引格式（移除時區資訊）
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # 確保資料按日期升序排列
        df.sort_index(inplace=True)

        return df

    def get_latest_price(self, symbol: str) -> dict:
        """
        取得最新收盤價資訊（用於狀態列顯示）

        Returns:
            dict: {'price': float, 'change': float, 'change_pct': float, 'date': str}
        """
        symbol = self.normalize_symbol(symbol)
        try:
            ticker = yf.Ticker(symbol)
            try:
                hist = ticker.history(period="5d", auto_adjust=True, repair=True)
            except TypeError:
                return {}

            if len(hist) < 2:
                return {}

            # 移除 NaN 列，避免回傳 nan
            hist = hist.dropna(subset=["Close"])
            if len(hist) < 2:
                return {}

            latest = hist.iloc[-1]
            prev = hist.iloc[-2]
            change = latest["Close"] - prev["Close"]
            change_pct = (change / prev["Close"]) * 100

            return {
                "price": round(latest["Close"], 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "date": hist.index[-1].strftime("%Y-%m-%d")
            }
        except Exception as e:
            logger.warning(f"取得最新價格失敗：{e}")
            return {}

    def validate_symbol(self, symbol: str) -> bool:
        """快速驗證股票代號是否存在"""
        try:
            symbol = self.normalize_symbol(symbol)
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            return not hist.empty
        except Exception:
            return False

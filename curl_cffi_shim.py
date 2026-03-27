"""
curl_cffi 替身模組（Shim）

在 PyInstaller 打包環境中，curl_cffi 可以讀取 SQLite 快取，
但無法正確發送 HTTPS 請求（底層 C 擴展在打包後路徑異常）。

yfinance 1.2.0 硬依賴 curl_cffi（8 個檔案無 try/except），
直接封鎖會導致 yfinance 無法 import。

此模組用標準 requests 庫模擬 curl_cffi.requests 的 API，
讓 yfinance 在打包環境中正常運作。
"""
import sys
import types
import requests as _requests


# ── Session 替身 ─────────────────────────────────────────────────

class ShimSession(_requests.Session):
    """用 standard requests.Session 模擬 curl_cffi.requests.Session"""

    def __init__(self, impersonate=None, **kwargs):
        super().__init__(**kwargs)
        # curl_cffi 的 impersonate="chrome" 會偽裝 TLS 指紋和 HTTP 標頭
        # 標準 requests 沒有 TLS 偽裝，但至少設定 Chrome-like User-Agent
        # 避免 Yahoo Finance 把請求當機器人而 rate limit
        self.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/131.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
        })
        # curl_cffi 的 session.cookies 有 .jar 屬性指向底層 CookieJar
        # standard requests 的 cookies IS the CookieJar，沒有 .jar
        # 直接加上 .jar 指向自己，讓 yfinance 的 cookies.jar._cookies 能運作
        self.cookies.jar = self.cookies


# ── 例外類別 ─────────────────────────────────────────────────────

class DNSError(_requests.exceptions.ConnectionError):
    """curl_cffi 有 DNSError，standard requests 沒有"""
    pass


# ── 安裝到 sys.modules ──────────────────────────────────────────

def install():
    """將替身模組安裝進 sys.modules，必須在 import yfinance 前呼叫"""

    # 頂層 curl_cffi
    mod_curl_cffi = types.ModuleType('curl_cffi')
    mod_curl_cffi.__path__ = []  # 讓 Python 認為是 package

    # curl_cffi.requests
    mod_requests = types.ModuleType('curl_cffi.requests')
    mod_requests.Session = ShimSession
    mod_requests.Response = _requests.Response
    mod_requests.__path__ = []

    # curl_cffi.requests.session
    mod_session = types.ModuleType('curl_cffi.requests.session')
    mod_session.Session = ShimSession

    # curl_cffi.requests.exceptions
    mod_exceptions = types.ModuleType('curl_cffi.requests.exceptions')
    mod_exceptions.HTTPError = _requests.exceptions.HTTPError
    mod_exceptions.RequestException = _requests.exceptions.RequestException
    mod_exceptions.ConnectionError = _requests.exceptions.ConnectionError
    mod_exceptions.Timeout = _requests.exceptions.Timeout
    mod_exceptions.ChunkedEncodingError = _requests.exceptions.ChunkedEncodingError
    mod_exceptions.DNSError = DNSError

    # curl_cffi.requests.cookies
    mod_cookies = types.ModuleType('curl_cffi.requests.cookies')

    # 組裝模組階層
    mod_requests.session = mod_session
    mod_requests.exceptions = mod_exceptions
    mod_requests.cookies = mod_cookies
    mod_curl_cffi.requests = mod_requests

    # 寫入 sys.modules
    sys.modules['curl_cffi'] = mod_curl_cffi
    sys.modules['curl_cffi.requests'] = mod_requests
    sys.modules['curl_cffi.requests.session'] = mod_session
    sys.modules['curl_cffi.requests.exceptions'] = mod_exceptions
    sys.modules['curl_cffi.requests.cookies'] = mod_cookies

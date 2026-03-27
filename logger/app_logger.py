"""
執行緒安全的非同步日誌系統
使用 QueueHandler 避免磁碟 I/O 阻塞背景執行緒
"""
import logging
import logging.handlers
import queue
import os
from datetime import datetime


# 日誌檔案存放路徑
from data.data_paths import LOG_DIR
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"stock_app_{datetime.now().strftime('%Y%m%d')}.log")

# 全域日誌佇列（所有執行緒共用）
_log_queue = queue.Queue(-1)
_queue_listener = None


def setup_logging():
    """
    初始化整個應用程式的日誌系統
    只需在 main.py 呼叫一次
    """
    global _queue_listener

    # 自訂格式：時間戳記(毫秒) | 執行緒 | 模組 | 等級 | 訊息
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d | TID:%(thread)d | %(name)-20s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 檔案處理器（寫入磁碟）
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)

    # 終端機處理器（開發時方便觀察）
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    # 啟動專用的日誌監聽執行緒（非同步寫入）
    _queue_listener = logging.handlers.QueueListener(
        _log_queue,
        file_handler,
        console_handler,
        respect_handler_level=True
    )
    _queue_listener.start()

    # 設定 Root Logger 只做轉發
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(logging.handlers.QueueHandler(_log_queue))


def get_logger(name: str) -> logging.Logger:
    """
    取得指定模組的命名 Logger
    用法：logger = get_logger(__name__)
    """
    return logging.getLogger(name)


def shutdown_logging():
    """應用程式關閉時安全停止日誌系統"""
    global _queue_listener
    if _queue_listener:
        _queue_listener.stop()

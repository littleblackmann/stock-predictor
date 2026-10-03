"""A read-only watchlist overview; opening it never starts paid analysis."""
import json
from pathlib import Path
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView
from data.data_paths import WATCHLIST_PATH
from data.prediction_logger import PredictionLogger


class OverviewDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('自選股總覽')
        self.resize(860, 430)
        layout = QVBoxLayout(self)
        hint = QLabel('最近保存的分析 · 日期不同時請重新查詢\n方向不明表示目前沒有足夠依據；開啟總覽不會產生 AI 費用。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        try:
            watchlist = json.loads(Path(WATCHLIST_PATH).read_text(encoding='utf-8'))
        except (ValueError, OSError):
            watchlist = []
        if isinstance(watchlist,dict):
            watchlist = watchlist.get("symbols",[])
        symbols = [s for s in watchlist if isinstance(s,str)]
        records = PredictionLogger.load_all()
        latest = {}
        for row in records:
            if row['horizon'] == '1':
                latest[row['symbol']] = row
        if not symbols:
            symbols = list(latest)[-12:]
        table = QTableWidget(len(symbols), 5)
        table.setHorizontalHeaderLabels(['股票','資料日期','目標日期','最近方向','實際結果'])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(44)
        for i, symbol in enumerate(symbols):
            row = latest.get(symbol, {})
            values = [symbol, row.get('data_date') or '尚未分析', row.get('target_date') or '—',
                      {'up':'偏多','down':'偏空','uncertain':'方向不明'}.get(row.get('predicted'),'—'),
                      {'up':'上漲','down':'未上漲'}.get(row.get('actual'),'等待驗證')]
            if row.get('model_version') == 'legacy':
                values[1] = row.get('prediction_date', '') + '（舊版）'
            for j, value in enumerate(values):
                table.setItem(i,j,QTableWidgetItem(value))
        layout.addWidget(table)

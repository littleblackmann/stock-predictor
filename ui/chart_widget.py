"""
高效能 TradingView K 線圖元件
使用 QWebEngineView 嵌入 TradingView Lightweight Charts
"""
import json
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QUrl, QTimer
from logger.app_logger import get_logger

logger = get_logger(__name__)

# TradingView Lightweight Charts HTML 模板
CHART_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background-color: #0D0D0D;
            overflow: hidden;
        }
        #chart-container {
            width: 100vw;
            height: 75vh;
        }
        #volume-container {
            width: 100vw;
            height: 22vh;
            margin-top: 3px;
        }
        #tooltip {
            position: absolute;
            top: 8px;
            left: 60px;
            background: rgba(20, 20, 20, 0.92);
            color: #E0E6F0;
            font-family: Arial, sans-serif;
            font-size: 12px;
            font-weight: bold;
            padding: 6px 10px;
            border-radius: 5px;
            border: 1px solid #3A3A3A;
            pointer-events: none;
            display: none;
            z-index: 100;
        }
        #loading {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #4A8ACA;
            font-family: Arial, sans-serif;
            font-size: 16px;
            font-weight: bold;
        }
        #placeholder {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            z-index: 50;
            pointer-events: none;
        }
        #placeholder .icon {
            font-size: 72px;
            opacity: 0.15;
            margin-bottom: 16px;
            animation: float 3s ease-in-out infinite;
        }
        #placeholder .text {
            color: #3A5A7A;
            font-family: 'Microsoft JhengHei', Arial, sans-serif;
            font-size: 18px;
            font-weight: bold;
            text-align: center;
            line-height: 1.8;
        }
        #placeholder .sub {
            color: #2A3A4A;
            font-family: 'Microsoft JhengHei', Arial, sans-serif;
            font-size: 13px;
            margin-top: 8px;
        }
        @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-12px); }
        }
        @keyframes pulse-line {
            0% { opacity: 0.08; }
            50% { opacity: 0.2; }
            100% { opacity: 0.08; }
        }
        #placeholder .fake-chart {
            display: flex;
            align-items: flex-end;
            gap: 3px;
            margin-bottom: 20px;
            height: 60px;
        }
        #placeholder .bar {
            width: 4px;
            border-radius: 2px;
            animation: pulse-line 2s ease-in-out infinite;
        }
    </style>
</head>
<body>
    <div id="placeholder">
        <div class="fake-chart" id="fakeBars"></div>
        <div class="icon">📈</div>
        <div class="text">輸入股票代號，開始預測</div>
        <div class="sub">支援台股代號（如 2330）或名稱（如 台積電）</div>
    </div>
    <div id="loading">載入圖表引擎...</div>
    <div id="tooltip"></div>
    <div id="chart-container"></div>
    <div id="volume-container"></div>

    <!-- TradingView Lightweight Charts CDN -->
    <script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>

    <script>
        let mainChart, candleSeries, ma5Series, ma20Series;
        let volChart, volSeries;
        let isReady = false;

        // 生成假的 K 線柱狀背景
        (function() {
            const container = document.getElementById('fakeBars');
            const heights = [20,35,25,45,30,50,35,55,40,28,48,32,52,38,22,42,30,50,36,46,28,40,34,56,42,30];
            heights.forEach((h, i) => {
                const bar = document.createElement('div');
                bar.className = 'bar';
                bar.style.height = h + 'px';
                bar.style.background = i % 2 === 0 ? '#FF335530' : '#00CC6630';
                bar.style.animationDelay = (i * 0.08) + 's';
                container.appendChild(bar);
            });
        })();

        function initCharts() {
            const mainEl = document.getElementById('chart-container');
            const volEl  = document.getElementById('volume-container');

            // ── 主圖（K 線）──
            mainChart = LightweightCharts.createChart(mainEl, {
                width:  mainEl.clientWidth,
                height: mainEl.clientHeight,
                layout: {
                    background: { color: '#0D0D0D' },
                    textColor:  '#8A8A8A',
                },
                grid: {
                    vertLines: { color: '#1A1A1A' },
                    horzLines: { color: '#1A1A1A' },
                },
                crosshair: {
                    mode: LightweightCharts.CrosshairMode.Normal,
                    vertLine: { color: '#5A5A5A', labelBackgroundColor: '#222222' },
                    horzLine: { color: '#5A5A5A', labelBackgroundColor: '#222222' },
                },
                rightPriceScale: {
                    borderColor: '#2A2A2A',
                    textColor:   '#8A8A8A',
                },
                timeScale: {
                    borderColor:  '#2A2A2A',
                    timeVisible:  true,
                    secondsVisible: false,
                    barSpacing:   6,
                },
                handleScroll:  { mouseWheel: true, pressedMouseMove: true },
                handleScale:   { mouseWheel: true, pinch: true },
            });

            // K 線系列
            candleSeries = mainChart.addCandlestickSeries({
                upColor:         '#FF3355',
                downColor:       '#00CC66',
                borderUpColor:   '#FF3355',
                borderDownColor: '#00CC66',
                wickUpColor:     '#FF3355',
                wickDownColor:   '#00CC66',
            });

            // MA5 均線（紅色）
            ma5Series = mainChart.addLineSeries({
                color:       '#FF8844',
                lineWidth:   1.5,
                priceLineVisible: false,
                lastValueVisible: true,
                title: 'MA5',
            });

            // MA20 均線（藍色）
            ma20Series = mainChart.addLineSeries({
                color:       '#4488FF',
                lineWidth:   1.5,
                priceLineVisible: false,
                lastValueVisible: true,
                title: 'MA20',
            });

            // ── 副圖（成交量）──
            volChart = LightweightCharts.createChart(volEl, {
                width:  volEl.clientWidth,
                height: volEl.clientHeight,
                layout: {
                    background: { color: '#0D0D0D' },
                    textColor:  '#8A8A8A',
                },
                grid: {
                    vertLines: { color: '#1A1A1A' },
                    horzLines: { color: '#1A1A1A' },
                },
                rightPriceScale: {
                    borderColor: '#2A2A2A',
                    scaleMargins: { top: 0.1, bottom: 0 },
                },
                timeScale: {
                    borderColor:    '#2A2A2A',
                    timeVisible:    true,
                    secondsVisible: false,
                },
                handleScroll: { mouseWheel: true },
                handleScale:  { mouseWheel: true },
            });

            volSeries = volChart.addHistogramSeries({
                priceFormat:       { type: 'volume' },
                priceScaleId:      'right',
                scaleMargins:      { top: 0.1, bottom: 0 },
            });

            // 時間軸同步
            mainChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (range) volChart.timeScale().setVisibleLogicalRange(range);
            });
            volChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (range) mainChart.timeScale().setVisibleLogicalRange(range);
            });

            // 滑鼠懸停顯示詳細數值
            mainChart.subscribeCrosshairMove(param => {
                const tooltip = document.getElementById('tooltip');
                if (!param.time || param.point.x < 0) {
                    tooltip.style.display = 'none';
                    return;
                }
                const data = param.seriesData.get(candleSeries);
                if (!data) return;
                const price_change = ((data.close - data.open) / data.open * 100).toFixed(2);
                const color = data.close >= data.open ? '#FF3355' : '#00CC66';
                tooltip.innerHTML = `
                    <span style="color:#7A9ABE">${param.time}</span> &nbsp;
                    開 <span style="color:${color}">${data.open}</span> &nbsp;
                    高 <span style="color:#FF3355">${data.high}</span> &nbsp;
                    低 <span style="color:#00CC66">${data.low}</span> &nbsp;
                    收 <span style="color:${color}">${data.close}</span> &nbsp;
                    <span style="color:${color}">${price_change > 0 ? '+' : ''}${price_change}%</span>
                `;
                tooltip.style.display = 'block';
            });

            // 視窗縮放自動調整
            window.addEventListener('resize', () => {
                mainChart.applyOptions({ width: mainEl.clientWidth, height: mainEl.clientHeight });
                volChart.applyOptions({ width: volEl.clientWidth, height: volEl.clientHeight });
            });

            document.getElementById('loading').style.display = 'none';
            isReady = true;
        }

        function updateChartData(dataJson) {
            if (!isReady) return;
            const data = JSON.parse(dataJson);
            // 隱藏空白 placeholder
            const ph = document.getElementById('placeholder');
            if (ph) ph.style.display = 'none';

            if (data.candles && data.candles.length > 0) {
                candleSeries.setData(data.candles);
            }
            if (data.ma5 && data.ma5.length > 0) {
                ma5Series.setData(data.ma5);
            }
            if (data.ma20 && data.ma20.length > 0) {
                ma20Series.setData(data.ma20);
            }
            if (data.volumes && data.volumes.length > 0) {
                volSeries.setData(data.volumes);
            }

            // 自動縮放至最新資料
            mainChart.timeScale().fitContent();
            volChart.timeScale().fitContent();
        }

        function addSignalMarkers(markersJson) {
            if (!isReady) return;
            const markers = JSON.parse(markersJson);
            candleSeries.setMarkers(markers);
        }

        function clearChart() {
            if (!isReady) return;
            candleSeries.setData([]);
            ma5Series.setData([]);
            ma20Series.setData([]);
            volSeries.setData([]);
            const ph = document.getElementById('placeholder');
            if (ph) ph.style.display = 'flex';
        }

        // 頁面載入後初始化圖表
        window.onload = initCharts;
    </script>
</body>
</html>
"""


class ChartWidget(QWidget):
    """
    嵌入 TradingView K 線圖的 PySide6 元件
    透過 runJavaScript 將 Python 資料推送至前端圖表
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        logger.info("ChartWidget 初始化完成")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.web_view = QWebEngineView()
        self.web_view.setHtml(CHART_HTML, QUrl("https://localhost/"))
        layout.addWidget(self.web_view)

    def update_chart(self, chart_data: dict):
        """
        將圖表資料（K線、均線、成交量）推送至 JS 圖表
        chart_data 來自 FeatureEngineer.get_chart_data()
        """
        data_json = json.dumps(chart_data, ensure_ascii=False)
        # 轉義單引號以防 JS 注入
        data_json = data_json.replace("\\", "\\\\").replace("`", "\\`")
        js_code = f"updateChartData(`{data_json}`);"
        self.web_view.page().runJavaScript(js_code)
        logger.info(f"圖表資料更新：{len(chart_data.get('candles', []))} 根 K 線")

    def add_prediction_markers(self, date_str: str, is_up: bool):
        """
        在最新 K 線上標記模型的預測訊號箭頭
        """
        marker = [{
            "time":     date_str,
            "position": "belowBar" if is_up else "aboveBar",
            "color":    "#FF3355" if is_up else "#00CC66",
            "shape":    "arrowUp" if is_up else "arrowDown",
            "text":     "預測上漲" if is_up else "預測下跌",
            "size":     2,
        }]
        markers_json = json.dumps(marker)
        self.web_view.page().runJavaScript(f"addSignalMarkers('{markers_json}');")

    def clear(self):
        """清除圖表資料"""
        self.web_view.page().runJavaScript("clearChart();")
        logger.info("圖表已清除")

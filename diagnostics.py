"""Explicit isolated package verification, invoked with --diagnose OUTPUT_DIR."""
import json
import os
import sys
from pathlib import Path


def run(output_dir, network=False):
    out=Path(output_dir).resolve()
    out.mkdir(parents=True,exist_ok=True)
    os.environ['LOCALAPPDATA']=str(out/'appdata')
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    import numpy as np
    import pandas as pd
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from unittest.mock import patch
    from data.data_paths import ensure_dirs
    ensure_dirs()
    from data.config_manager import save_config
    save_config({'welcome_shown':True,'openrouter_api_key':'','openrouter_model':'openai/gpt-6.1-sol'})
    from features.feature_engineer import FeatureEngineer
    from models.short_term import forecast_frame
    from data.model_catalog import load_catalog
    from updater.auto_updater import get_current_version
    rng=np.random.default_rng(42)
    close=100*np.exp(np.cumsum(rng.normal(0,.013,650)))
    raw=pd.DataFrame({'Open':close*.997,'High':close*1.02,'Low':close*.98,
                     'Close':close,'Volume':rng.integers(100000,300000,len(close))},
                    index=pd.bdate_range('2023-01-02',periods=len(close)))
    eng=FeatureEngineer();features=eng.build_features(raw,include_latest=True)
    horizons=forecast_frame(features,eng.get_feature_cols(),raw.Close)
    result={'symbol':'0050.TW · 測試資料','prediction':horizons[0], 'horizons':horizons,
            'eval_metrics':horizons[0]['eval_metrics'],'chart_data':eng.get_chart_data(raw,features),
            'data_date':str(raw.index[-1].date()),'target_date':'2026-10-05',
            'explanations':['時間分段驗證；示範畫面使用合成資料。'],
            'price_info':{'price':100.00,'change':1.2,'change_pct':1.21},
            'sentiment':{'available':False,'reason':'測試模式，未呼叫付費 AI'},
            'forecast_3d':[{'day':f"{r['horizon']} 交易日 · 10/05",'trend':f"方向不明 · 上漲 {r['up_prob']:.0%}",'confidence':'待驗證','reason':f"回測 {r['eval_metrics']['accuracy']:.0%} / 基準 {r['eval_metrics']['baseline_accuracy']:.0%}"} for r in horizons]}
    report={'version':get_current_version(),'catalog_count':len(load_catalog()['models']),
            'horizons':[r['horizon'] for r in horizons],'finite_probabilities':all(np.isfinite(r['up_prob']) for r in horizons)}
    if network:
        from data.holiday_checker import get_calendar
        get_calendar().refresh()
        from workers.prediction_worker import run_prediction
        actual=run_prediction('0050.TW', include_news=False)
        report['network']={'symbol':actual['symbol'],'data_date':actual['data_date'],
                           'targets':[r['target_date'] for r in actual['horizons']],
                           'metrics':[r['eval_metrics'] for r in actual['horizons']]}
    app=QApplication.instance() or QApplication([])
    from PySide6.QtGui import QFontDatabase, QFont
    for filename in ('msjh.ttc','msjhbd.ttc','arial.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+filename)
    app.setFont(QFont('Microsoft JhengHei',10))
    from ui.main_window import MainWindow
    with patch('ui.main_window.needs_refresh',return_value=False), patch('ui.main_window.is_first_run',return_value=False), patch.object(QTimer,'singleShot'):
        window=MainWindow()
    window.resize(1280,850)
    window.show()
    window._display_result(result)
    from ui.settings_dialog import SettingsDialog
    settings=SettingsDialog(window)
    from ui.prediction_log_dialog import PredictionLogDialog
    logs=PredictionLogDialog(window)
    from ui.overview_dialog import OverviewDialog
    overview=OverviewDialog(window)

    def capture():
        try:
            window.grab().save(str(out/'main.png'))
            window.pred_panel.grab().save(str(out/'prediction-panel.png'))
            settings.show();app.processEvents();settings.grab().save(str(out/'settings.png'))
            settings.close()
            window._set_large_text(True,persist=False);window.resize(1100,760);app.processEvents()
            window.grab().save(str(out/'main-large-1100.png'))
            report['ui']={'main_size':[window.width(),window.height()],
                          'selected_model':settings.combo_model.currentData(),
                          'model_entries':settings.combo_model.count(),
                          'log_columns':logs.table.columnCount()}
            (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception:
            import traceback
            (out/'error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        finally:
            window.close();app.quit()
    QTimer.singleShot(2000, lambda: window.chart_widget.update_chart(result['chart_data']))
    QTimer.singleShot(5000,capture)
    app.exec()
    return 0 if (out/'report.json').exists() else 1

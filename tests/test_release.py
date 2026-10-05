import ast
import csv
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

# Set an isolated home before importing any application module.
_home = tempfile.TemporaryDirectory(prefix='stock-test-')
os.environ['LOCALAPPDATA'] = _home.name
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import numpy as np
import pandas as pd
from data.market_time import completed_history, TAIPEI
from data.record_store import LEGACY_FIELDS, FIELDS, locked, read_rows, write_rows
from data.prediction_logger import PredictionLogger
from features.feature_engineer import FeatureEngineer
from models.short_term import make_target, temporal_partitions, forecast_frame


def prices(n=650):
    rng=np.random.default_rng(50)
    close=100*np.exp(np.cumsum(rng.normal(0,.013,n)))
    return pd.DataFrame({'Open':close*.997,'High':close*1.02,'Low':close*.98,
                         'Close':close,'Volume':rng.integers(100000,300000,n)},
                        index=pd.bdate_range('2022-01-03',periods=n))


class ForecastTests(unittest.TestCase):
    def test_latest_row_kept_only_for_inference(self):
        raw=prices()
        engineer=FeatureEngineer()
        live=engineer.build_features(raw, include_latest=True)
        train=engineer.build_features(raw)
        self.assertEqual(live.index[-1],raw.index[-1])
        self.assertTrue(pd.isna(live.label.iloc[-1]))
        self.assertEqual(train.index[-1],raw.index[-2])

    def test_prefix_features_unchanged_by_future(self):
        raw=prices()
        a=FeatureEngineer().build_features(raw.iloc[:500],include_latest=True)
        b=FeatureEngineer().build_features(raw,include_latest=True)
        cols=[c for c in a if c!='label']
        pd.testing.assert_frame_equal(a[cols],b.loc[a.index,cols])

    def test_labels_use_requested_sessions(self):
        s=pd.Series([10,9,11,8,12,14])
        self.assertEqual(make_target(s,3).iloc[0],0)
        self.assertEqual(make_target(s,5).iloc[0],1)
        self.assertTrue(make_target(s,3).iloc[-3:].isna().all())

    def test_all_partitions_purge_label_overlap(self):
        for horizon in (1,3,5):
            for fit,cal,test in temporal_partitions(650,horizon):
                self.assertLess(fit[-1]+horizon,cal[0])
                self.assertLess(cal[-1]+horizon,test[0])

    def test_complete_session_cutoff(self):
        df=prices(4)
        last=df.index[-1]
        morning=datetime(last.year,last.month,last.day,10,tzinfo=TAIPEI)
        evening=morning.replace(hour=16)
        self.assertEqual(len(completed_history(df,morning)),3)
        self.assertEqual(len(completed_history(df,evening)),4)

    def test_old_sequence_window_label_alignment(self):
        tree=ast.parse(Path('models/transformer_extractor.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TransformerExtractor')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_create_sequences')
        ns={'np':np,'SEQUENCE_LEN':3}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'sequence','exec'),ns)
        X,y=ns['_create_sequences'](None,np.arange(8).reshape(-1,1),np.arange(8))
        np.testing.assert_array_equal(X[:,-1,0],y)
        self.assertEqual(y[-1],7)

    def test_end_to_end_all_horizons(self):
        raw=prices();eng=FeatureEngineer();features=eng.build_features(raw,include_latest=True)
        results=forecast_frame(features,eng.get_feature_cols(),raw.Close)
        self.assertEqual([r['horizon'] for r in results],[1,3,5])
        for r in results:
            self.assertAlmostEqual(r['up_prob']+r['down_prob'],1)
            self.assertTrue(np.isfinite(r['eval_metrics']['brier']))
            self.assertEqual(len(r['eval_metrics']['fold_details']),3)
            self.assertGreater(r['eval_metrics']['test_samples'],200)
            if r['eval_metrics']['accuracy']<=r['eval_metrics']['baseline_accuracy']:
                self.assertEqual(r['prediction'],-1)


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'log.csv')
        self.mock=patch('data.prediction_logger.LOG_PATH',self.path);self.mock.start()

    def tearDown(self):
        self.mock.stop();self.tmp.cleanup()

    def result(self):
        return {'symbol':'0050.TW','data_date':'2026-04-07','created_at':'2026-04-07T17:00:00+08:00',
                'target_date':'2026-04-08','horizons':[{'horizon':1,'up_prob':.6,'down_prob':.4,
                'raw_up_prob':.6,'prediction':1,'model_version':'short-term-1','target_date':'2026-04-08'}]}

    def test_legacy_migration_preserves_values_and_backup(self):
        with open(self.path,'w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(LEGACY_FIELDS);w.writerow(['2026-04-07','0050.TW','up','.6','.4','.6','test','up','1','True'])
        rows=PredictionLogger.load_all()
        self.assertEqual(rows[0]['correct'],'True')
        self.assertEqual(rows[0]['evaluation_status'],'legacy')
        self.assertTrue(Path(self.path+'.pre-v1.7.bak').exists())
        self.assertEqual(PredictionLogger.get_stats()['total'],0)

    def test_old_nine_column_and_misaligned_ten_column_migrate(self):
        header=[x for x in LEGACY_FIELDS if x!='raw_up_prob']
        with open(self.path,'w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(header)
            w.writerow(['2026-04-07','0050.TW','up','.6','.4','note','up','1','True'])
            w.writerow(['2026-04-08','0050.TW','up','.6','.4','.55','note2','down','-1','False'])
        rows=PredictionLogger.load_all()
        self.assertEqual(rows[0]['raw_up_prob'],'')
        self.assertEqual(rows[1]['gpt_3day'],'note2')
        self.assertEqual(rows[1]['correct'],'False')

    def test_repeat_query_is_immutable(self):
        r=self.result();PredictionLogger.append(r)
        r['horizons'][0]['up_prob']=.1
        PredictionLogger.append(r)
        rows=PredictionLogger.load_all()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['up_prob'],'0.6000')

    def test_concurrent_append_no_loss(self):
        from concurrent.futures import ThreadPoolExecutor
        def append(i):
            r=self.result();r['symbol']=f'{i}.TW';PredictionLogger.append(r)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(append,range(20)))
        self.assertEqual(len(PredictionLogger.load_all()),20)

    def test_intraday_not_final_then_correct_close_used(self):
        PredictionLogger.append(self.result())
        hist=pd.DataFrame({'Close':[100.,103.]},index=pd.to_datetime(['2026-04-07','2026-04-08']))
        ticker=MagicMock();ticker.history.return_value=hist
        with patch('yfinance.Ticker',return_value=ticker),patch('data.prediction_logger.taipei_now',return_value=datetime(2026,4,8,10,tzinfo=TAIPEI)):
            self.assertEqual(PredictionLogger.backfill_actuals(),0)
        hist.iloc[-1,0]=99
        with patch('yfinance.Ticker',return_value=ticker),patch('data.prediction_logger.taipei_now',return_value=datetime(2026,4,8,16,tzinfo=TAIPEI)):
            self.assertEqual(PredictionLogger.backfill_actuals(),1)
        self.assertEqual(PredictionLogger.load_all()[0]['correct'],'False')

    def test_missing_target_not_substituted(self):
        PredictionLogger.append(self.result())
        hist=pd.DataFrame({'Close':[100.,103.]},index=pd.to_datetime(['2026-04-07','2026-04-09']))
        ticker=MagicMock();ticker.history.return_value=hist
        with patch('yfinance.Ticker',return_value=ticker),patch('data.prediction_logger.taipei_now',return_value=datetime(2026,4,10,16,tzinfo=TAIPEI)):
            self.assertEqual(PredictionLogger.backfill_actuals(),0)


class CatalogTests(unittest.TestCase):
    def test_featured_models_in_snapshot(self):
        from data.model_catalog import load_catalog,FEATURED
        ids={m['id'] for m in load_catalog()['models']}
        self.assertTrue(set(FEATURED)<=ids)

    def test_catalog_rejects_nonchat_and_batch(self):
        from data.model_catalog import normalize_models
        model={'id':'test/chat','architecture':{'input_modalities':['text'],'output_modalities':['text']},'pricing':{'prompt':'0','completion':'0'}}
        result=normalize_models([model,{**model,'id':'test/chat:batch'}, {**model,'id':'test/image','architecture':{'input_modalities':['text'],'output_modalities':['image']}}])
        self.assertEqual([m['id'] for m in result],['test/chat'])

    def test_no_news_never_calls_api(self):
        from data.news_sentiment import NewsSentimentAnalyzer
        analyzer=NewsSentimentAnalyzer.__new__(NewsSentimentAnalyzer)
        analyzer.client=MagicMock()
        self.assertFalse(analyzer._analyze_no_news('0050.TW')['available'])
        analyzer.client.chat.completions.create.assert_not_called()

    def test_model_options_bounded(self):
        from data.model_catalog import request_options
        self.assertEqual(request_options('openai/gpt-6.1-sol')['max_tokens'],4096)
        self.assertEqual(request_options('unknown/model'),{'max_tokens':4096})


class MarketFallbackTests(unittest.TestCase):
    def test_official_tail_preserves_history_and_target_limit(self):
        from data.yfinance_adapter import YFinanceAdapter
        frame=prices(3)
        frame.index=pd.to_datetime(['2026-09-28','2026-09-29','2026-09-30'])
        response=MagicMock()
        response.json.return_value={'stat':'OK','data':[
            ['115/09/30','1,000','0','999','999','999','999'],
            ['115/10/01','1,200','0','100','104','98','102'],
            ['115/10/02','1,300','0','102','106','101','105'],
            ['115/10/05','1,500','0','105','108','102','107']]}
        with patch('requests.get',return_value=response):
            result=YFinanceAdapter.repair_recent_twse(frame,'0050.TW',datetime(2026,10,2).date())
        pd.testing.assert_frame_equal(result.loc[frame.index],frame,check_dtype=False,check_freq=False)
        self.assertEqual(len(result),5)
        self.assertEqual(result.iloc[-1].Close,105)
        self.assertEqual(result.iloc[-1].Volume,1300)

    def test_unavailable_official_data_does_not_invent_price(self):
        from data.yfinance_adapter import YFinanceAdapter
        frame=prices(3)
        with patch('requests.get',side_effect=TimeoutError):
            result=YFinanceAdapter.repair_recent_twse(frame,'0050.TW',datetime(2026,10,2).date())
        pd.testing.assert_frame_equal(frame,result)

    def test_invalid_or_truncated_ai_is_unavailable(self):
        from data.news_sentiment import NewsSentimentAnalyzer
        analyzer=NewsSentimentAnalyzer.__new__(NewsSentimentAnalyzer)
        analyzer.client=MagicMock()
        analyzer.model='unknown/model'
        for finish,content in [('length','{"score":0.9,"reason":"test"}'),('stop','{"score":"bullish","reason":"test"}'),('stop','')]:
            response=MagicMock()
            response.choices[0].finish_reason=finish
            response.choices[0].message.content=content
            analyzer.client.chat.completions.create.return_value=response
            self.assertFalse(analyzer._analyze_with_titles('0050.TW',['test headline'])['available'])


class UpdateTests(unittest.TestCase):
    def test_zip_paths_rejected(self):
        from updater.auto_updater import _validate_archive
        import io,zipfile
        for path in ['../bad','root/../../bad','C:/bad','root/../bad','/bad']:
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as z:z.writestr(path,'x')
            with zipfile.ZipFile(stream) as z:
                with self.assertRaises(ValueError):_validate_archive(z,Path(_home.name)/'extract')

    def test_update_does_not_use_source_archive_or_unbased_patch(self):
        from updater import auto_updater as u
        data={'tag_name':'v9.0.0','zipball_url':'https://github.com/source.zip','assets':[{'name':'x_patch.zip','browser_download_url':'https://github.com/patch.zip'}]}
        response=MagicMock();response.read.return_value=json.dumps(data).encode()
        with patch.object(u,'get_current_version',return_value='1.6.2'),patch.object(u,'_urlopen_safe') as url,patch.object(u,'_load_skipped_version',return_value=''):
            url.return_value.__enter__.return_value=response
            self.assertIsNone(u.check_for_update())
            data['assets'].append({'name':'StockPredictor-v9.0.0.zip','browser_download_url':'https://github.com/full.zip'})
            response.read.return_value=json.dumps(data).encode()
            self.assertEqual(u.check_for_update()['download_url'],'https://github.com/full.zip')


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_settings_preserves_missing_selected_model(self):
        from ui.settings_dialog import SettingsDialog
        config={'openrouter_api_key':'FAKE-TEST-NOT-A-KEY','openrouter_model':'retired/custom','brave_api_key':''}
        with patch('ui.settings_dialog.load_config',return_value=config),patch('ui.settings_dialog.save_config') as save:
            dlg=SettingsDialog()
            self.assertEqual(dlg.combo_model.currentData(),'retired/custom')
            dlg._on_save()
            self.assertEqual(save.call_args.args[0]['openrouter_model'],'retired/custom')
            self.assertEqual(save.call_args.args[0]['openrouter_api_key'],'FAKE-TEST-NOT-A-KEY')
            dlg.close()

    def test_model_refresh_preserves_selection(self):
        from ui.settings_dialog import SettingsDialog
        from data.model_catalog import load_catalog
        with patch('ui.settings_dialog.load_config',return_value={'openrouter_model':'openai/gpt-6.1-sol'}):
            dlg=SettingsDialog();before=dlg.combo_model.currentData()
            dlg._catalog_ready(load_catalog(),'')
            self.assertEqual(dlg.combo_model.currentData(),before)
            dlg._catalog_ready(None,'offline')
            self.assertEqual(dlg.combo_model.currentData(),before)
            dlg.close()


if __name__=='__main__':
    unittest.main(verbosity=2)

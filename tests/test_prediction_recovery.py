"""Regression cases for the supplied screenshots; no user data or network."""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

_home = tempfile.TemporaryDirectory(prefix='stock-record-test-')
os.environ['LOCALAPPDATA'] = _home.name
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pandas as pd
from data.market_time import TAIPEI
from data.prediction_logger import PredictionLogger
from data.record_store import FIELDS, write_rows
from data.prediction_summary import describe_prediction, probability_correct


def frame(dates=('2026-10-02', '2026-10-05'), values=(100., 102.79)):
    return pd.DataFrame({'Close': values}, index=pd.to_datetime(dates))


class Calendar:
    def refresh(self):
        pass

    def is_trading_day(self, day):
        return day.weekday() < 5 and day != date(2026, 10, 9)

    def next_trading_day_after(self, day):
        day += timedelta(days=1)
        while not self.is_trading_day(day):
            day += timedelta(days=1)
        return day


class ExplanationTests(unittest.TestCase):
    def test_fifty_two_percent_with_edge_is_still_near_even(self):
        title, reason = describe_prediction({'prediction': -1, 'up_prob': .521,
            'eval_metrics': {'accuracy': .526, 'baseline_accuracy': .519, 'brier': .24, 'baseline_brier': .25}})
        self.assertIn('五五波', title)
        self.assertIn('50%', reason)
        self.assertNotIn('命中率未超過', reason)

    def test_high_probability_explains_failed_baseline(self):
        for up in (.65, .73):
            pred = {'prediction': -1, 'up_prob': up,
                    'eval_metrics': {'accuracy': .53, 'baseline_accuracy': .56, 'brier': .26, 'baseline_brier': .24}}
            title, reason = describe_prediction(pred)
            self.assertEqual(title, '模型偏多（驗證不足）')
            self.assertIn('命中率未超過', reason)
            self.assertIn('Brier', reason)
            self.assertEqual(pred['prediction'], -1)

    def test_brier_can_block_even_if_hit_rate_improves(self):
        title, reason = describe_prediction({'prediction': -1, 'up_prob': .30,
            'eval_metrics': {'accuracy': .60, 'baseline_accuracy': .55, 'brier': .26, 'baseline_brier': .25}})
        self.assertIn('模型偏空', title)
        self.assertNotIn('命中率未超過', reason)
        self.assertIn('Brier', reason)

    def test_probabilities_score_observation_but_not_legacy_or_fifty_percent(self):
        row = {'evaluation_status': 'final', 'model_version': 'short-term-1', 'predicted': 'uncertain', 'up_prob': '.521', 'actual': 'up'}
        self.assertTrue(probability_correct(row))
        self.assertFalse(probability_correct({**row, 'actual': 'down'}))
        for val in ('.5', 'nan', 'inf', '-.1', '1.1', ''):
            self.assertIsNone(probability_correct({**row, 'up_prob': val}))
        for changes in ({'model_version': 'legacy'}, {'evaluation_status': 'pending'}, {'actual': ''}):
            self.assertIsNone(probability_correct({**row, **changes}))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'records.csv')
        self.patches = [patch('data.prediction_logger.LOG_PATH', self.path),
            patch('data.prediction_logger.taipei_now', return_value=datetime(2026, 10, 12, 0, 18, tzinfo=TAIPEI)),
            patch('data.holiday_checker.get_calendar', return_value=Calendar()),
            patch('data.yfinance_adapter.YFinanceAdapter.fetch_chart', return_value=pd.DataFrame()),
            patch('yfinance.Ticker')]
        self.mocks = [p.start() for p in self.patches]
        self.ticker = self.mocks[-1].return_value
        self.ticker.history.return_value = frame()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def row(self, **overrides):
        row = dict.fromkeys(FIELDS, '')
        row.update(record_id='record-1', prediction_date='2026-10-04', symbol='0050.TW',
                   data_date='2026-10-02', target_date='2026-10-05', horizon='1',
                   predicted='uncertain', up_prob='.53', model_version='short-term-1', evaluation_status='pending')
        row.update(overrides)
        return row

    def save(self, *rows):
        write_rows(self.path, rows)

    def test_uncertain_actual_is_final_and_probability_scored_without_rewriting_signal(self):
        self.save(self.row())
        report = PredictionLogger.backfill_actuals(details=True)
        self.assertEqual(report['updated'], 1)
        row = PredictionLogger.load_all()[0]
        self.assertEqual(row['predicted'], 'uncertain')
        self.assertEqual(row['correct'], '')
        self.assertEqual(row['actual_return'], '2.7900')
        self.assertTrue(probability_correct(row))
        self.assertEqual(PredictionLogger.get_stats()['probability_total'], 1)
        self.assertEqual(PredictionLogger.get_stats()['total'], 0)

    def test_current_target_before_close_waits_without_fetch(self):
        self.save(self.row(data_date='2026-10-08', target_date='2026-10-12'))
        report = PredictionLogger.backfill_actuals(details=True)
        self.assertEqual(report['waiting'], 1)
        self.ticker.history.assert_not_called()
        self.mocks[-2].assert_not_called()
        self.assertEqual(PredictionLogger.load_all()[0]['evaluation_status'], 'pending')

    def test_empty_primary_uses_fallback(self):
        self.save(self.row(predicted='up'))
        self.ticker.history.return_value = pd.DataFrame()
        self.mocks[-2].return_value = frame()
        self.assertEqual(PredictionLogger.backfill_actuals(), 1)
        self.assertEqual(PredictionLogger.load_all()[0]['correct'], 'True')

    def test_missing_target_uses_complete_pair_from_fallback(self):
        self.save(self.row())
        self.ticker.history.return_value = frame(('2026-10-02',), (200.,))
        self.mocks[-2].return_value = frame()
        PredictionLogger.backfill_actuals()
        self.assertEqual(PredictionLogger.load_all()[0]['actual_return'], '2.7900')

    def test_missing_target_never_uses_later_session(self):
        self.save(self.row())
        self.ticker.history.return_value = frame(('2026-10-02', '2026-10-06'))
        report = PredictionLogger.backfill_actuals(details=True)
        self.assertEqual(report['missing_data'], 1)
        self.assertEqual(report['updated'], 0)
        self.assertEqual(PredictionLogger.load_all()[0]['actual'], '')

    def test_failed_fetch_reports_failure_and_can_retry(self):
        self.save(self.row())
        self.ticker.history.side_effect = TimeoutError
        self.mocks[-2].side_effect = TimeoutError
        before = Path(self.path).read_bytes()
        report = PredictionLogger.backfill_actuals(details=True)
        self.assertEqual(report['fetch_failed'], 1)
        self.assertEqual(before, Path(self.path).read_bytes())
        self.ticker.history.side_effect = None
        self.assertEqual(PredictionLogger.backfill_actuals(), 1)

    def test_legacy_weekend_dates_restored_without_mixing_new_statistics(self):
        self.save(self.row(model_version='legacy', evaluation_status='legacy', data_date='', target_date='', predicted='up'))
        report = PredictionLogger.backfill_actuals(details=True)
        self.assertEqual(report['updated_legacy'], 1)
        row = PredictionLogger.load_all()[0]
        self.assertEqual((row['data_date'], row['target_date']), ('2026-10-02', '2026-10-05'))
        self.assertEqual(row['correct'], 'True')
        self.assertEqual(row['evaluation_status'], 'legacy')
        self.assertTrue(Path(self.path + '.pre-v1.7.5-backfill.bak').exists())
        self.assertEqual(PredictionLogger.get_stats()['total'], 0)
        self.assertEqual(PredictionLogger.get_stats()['probability_total'], 0)

    def test_legacy_holiday_uses_exact_expected_session(self):
        self.save(self.row(prediction_date='2026-10-09', model_version='legacy', evaluation_status='legacy', data_date='', target_date=''))
        report = PredictionLogger.backfill_actuals(details=True)
        self.assertEqual(report['waiting'], 1)  # 10/12 before the close

    def test_legacy_zero_return_and_existing_correctness_are_preserved(self):
        self.save(self.row(model_version='legacy', evaluation_status='legacy', actual='down', actual_return='0.00', correct='True'))
        before = Path(self.path).read_bytes()
        self.assertEqual(PredictionLogger.backfill_actuals(), 0)
        self.assertEqual(before, Path(self.path).read_bytes())
        self.ticker.history.assert_not_called()

    def test_bad_row_does_not_prevent_valid_row_same_symbol(self):
        self.save(self.row(record_id='bad', data_date='broken'), self.row())
        report = PredictionLogger.backfill_actuals(details=True)
        self.assertEqual(report['invalid'], 1)
        self.assertEqual(report['updated'], 1)

    def test_one_symbol_failure_does_not_block_others(self):
        self.save(self.row(record_id='failed', symbol='3481.TW'), self.row())
        failed = MagicMock(); failed.history.side_effect = TimeoutError
        self.mocks[-1].side_effect = lambda symbol: failed if symbol == '3481.TW' else self.ticker
        self.mocks[-2].side_effect = TimeoutError
        report = PredictionLogger.backfill_actuals(details=True)
        self.assertEqual(report['fetch_failed'], 1)
        self.assertEqual(report['updated'], 1)

    def test_three_and_five_day_targets_are_scored_independently(self):
        self.save(self.row(horizon='3', target_date='2026-10-07', predicted='up'),
                  self.row(record_id='five', horizon='5', target_date='2026-10-12', predicted='up'))
        self.ticker.history.return_value = frame(('2026-10-02', '2026-10-07'), (100., 99.))
        report = PredictionLogger.backfill_actuals(details=True)
        self.assertEqual((report['updated'], report['waiting']), (1, 1))
        self.assertEqual(PredictionLogger.get_stats(3)['accuracy'], 0)
        self.assertEqual(PredictionLogger.get_stats(5)['total'], 0)

    def test_concurrent_append_survives_backfill(self):
        self.save(self.row())
        def fetch(**kwargs):
            rows = PredictionLogger.load_all()
            write_rows(self.path, rows + [self.row(record_id='new', symbol='2330.TW')])
            return frame()
        self.ticker.history.side_effect = fetch
        PredictionLogger.backfill_actuals()
        rows = PredictionLogger.load_all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['record_id'], 'new')


class RecordUITests(unittest.TestCase):
    setUp = RecoveryTests.setUp
    tearDown = RecoveryTests.tearDown
    row = RecoveryTests.row
    save = RecoveryTests.save
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_shows_probability_check_and_observation_without_dash(self):
        from ui.prediction_log_dialog import PredictionLogDialog
        self.save(self.row(actual='up', actual_return='2.79', evaluation_status='final'))
        dlg = PredictionLogDialog()
        columns = {key: i for i, (_, key, _) in enumerate(dlg.COLUMNS)}
        self.assertEqual(dlg.table.item(0, columns['correct']).text(), '觀望不評分')
        self.assertEqual(dlg.table.item(0, columns['probability_correct']).text(), '✓')
        self.assertIn('1/1', dlg.lbl_stats.text())
        dlg.close()

    def test_dialog_failed_fetch_does_not_claim_latest(self):
        from ui.prediction_log_dialog import PredictionLogDialog
        self.save(self.row())
        self.ticker.history.side_effect = TimeoutError
        self.mocks[-2].side_effect = TimeoutError
        dlg = PredictionLogDialog()
        dlg._on_backfill_done(PredictionLogger.backfill_actuals(details=True))
        self.assertIn('取得失敗', dlg.lbl_status.text())
        self.assertNotIn('最新', dlg.lbl_status.text())
        self.assertTrue(dlg.btn_backfill.isEnabled())
        dlg.close()

    def test_worker_file_failure_always_signals_finished(self):
        from ui.prediction_log_dialog import _BackfillWorker
        worker = _BackfillWorker(); reports = []
        worker.signals.finished.connect(reports.append)
        with patch.object(PredictionLogger, 'backfill_actuals', side_effect=PermissionError):
            worker.run()
        self.assertIn('error', reports[0])

    def test_panel_explains_near_even_and_baseline_in_readable_label(self):
        from ui.prediction_panel import PredictionPanel
        panel = PredictionPanel()
        pred = {'prediction': -1, 'up_prob': .73, 'confidence_level': 'low',
                'eval_metrics': {'accuracy': .54, 'baseline_accuracy': .57, 'brier': .26, 'baseline_brier': .24}}
        panel.update_prediction({'prediction': pred})
        self.assertIn('模型偏多', panel.label_prediction.text())
        self.assertIn('Brier', panel.label_direction_reason.text())
        self.assertTrue(panel.label_direction_reason.wordWrap())
        panel.reset()
        self.assertEqual(panel.label_direction_reason.text(), '')
        panel.close()


if __name__ == '__main__':
    unittest.main()

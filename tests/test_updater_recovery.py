import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from updater import auto_updater as u


class CheckRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        prefs = Path(self.home.name) / 'update_prefs.json'
        prefs.write_text('{"skipped_version":"1.7.1"}', encoding='utf-8')
        self.prefs = prefs
        self.release = {'tag_name': 'v1.7.1', 'assets': [{
            'name': 'StockPredictor-v1.7.1.zip',
            'browser_download_url': 'https://github.com/littleblackmann/stock-predictor/releases/download/v1.7.1/StockPredictor-v1.7.1.zip'}]}
        for obj, name, kwargs in [
            (u, 'UPDATE_PREFS', {'new': str(prefs)}),
            (u, 'get_current_version', {'return_value': '1.6.2'}),
            (u, '_get_update_config', {'return_value': {'owner': 'littleblackmann', 'repo': 'stock-predictor'}}),
        ]:
            mock = patch.object(obj, name, **kwargs)
            mock.start()
            self.addCleanup(mock.stop)

    def check(self, payload=None, manual=False):
        data = self.release if payload is None else payload
        with patch.object(u, '_urlopen_safe', return_value=io.BytesIO(json.dumps(data).encode())):
            return u.check_for_update(manual=manual)

    def test_manual_can_update_skipped_release_without_erasing_preference(self):
        original = self.prefs.read_bytes()
        self.assertIsNone(self.check())
        self.assertEqual(self.check(manual=True)['version'], '1.7.1')
        self.assertEqual(self.prefs.read_bytes(), original)

    def test_old_skip_does_not_hide_next_release(self):
        self.prefs.write_text('{"skipped_version":"1.7.0"}', encoding='utf-8')
        self.assertEqual(self.check()['version'], '1.7.1')

    def test_current_version_is_latest_for_both_modes(self):
        with patch.object(u, 'get_current_version', return_value='1.7.1'):
            self.assertIsNone(self.check())
            self.assertIsNone(self.check(manual=True))

    def test_network_failure_is_not_latest(self):
        with patch.object(u, '_urlopen_safe', side_effect=URLError('offline')):
            self.assertIsNone(u.check_for_update())
            with self.assertRaises(u.UpdateCheckError):
                u.check_for_update(manual=True)

    def test_bad_json_is_not_latest(self):
        with patch.object(u, '_urlopen_safe', return_value=io.BytesIO(b'bad json')):
            with self.assertRaises(u.UpdateCheckError):
                u.check_for_update(manual=True)

    def test_invalid_version_payload_and_missing_asset_are_not_latest(self):
        for payload in ([], {'tag_name': ''}, {'tag_name': None}, {'tag_name': 'not-a-version'},
                        {'tag_name': 'v1.7.1', 'assets': []}, {'tag_name': 'v1.7.1', 'assets': None}):
            with self.subTest(payload=payload), self.assertRaises(u.UpdateCheckError):
                self.check(payload, manual=True)


class RecoveryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_requests_manual_check_and_displays_failure(self):
        from ui.settings_dialog import SettingsDialog
        with patch('ui.settings_dialog.load_config', return_value={}):
            dialog = SettingsDialog()
        with patch.object(u, 'check_for_update', side_effect=u.UpdateCheckError('無法取得更新資訊')) as check:
            dialog._on_check_update()
            check.assert_called_once_with(manual=True)
        self.assertIn('檢查失敗', dialog.update_status_label.text())
        self.assertNotIn('最新版本', dialog.update_status_label.text())
        self.assertTrue(dialog.btn_check_update.isEnabled())
        dialog.close()

    def test_window_close_and_escape_do_not_skip_but_explicit_skip_does(self):
        from PySide6.QtCore import QTimer, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QWidget, QMessageBox
        from ui.main_window import MainWindow

        class Parent(QWidget):
            def statusBar(self):
                return self
            def showMessage(self, *args):
                pass

        parent = Parent()
        for action in ('close', 'escape', 'later', 'skip'):
            def interact(action=action):
                msg = next(w for w in self.app.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible())
                if action == 'close':
                    msg.close()
                elif action == 'escape':
                    self.app.sendEvent(msg, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
                else:
                    next(b for b in msg.buttons() if b.text() == ('跳過此版本' if action == 'skip' else '稍後提醒')).click()
            with self.subTest(action=action), patch.object(u, 'skip_version') as skip:
                QTimer.singleShot(0, interact)
                MainWindow._show_update_dialog(parent, {'version': '1.7.1'})
                if action == 'skip':
                    skip.assert_called_once_with('1.7.1')
                else:
                    skip.assert_not_called()
        parent.close()


if __name__ == '__main__':
    unittest.main()

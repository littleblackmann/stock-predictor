import hashlib
import http.client
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from updater.download import download_asset


class Response(io.BytesIO):
    def __init__(self, data, code=200, headers=None, fail=False):
        super().__init__(data)
        self.code = code
        self.headers = headers or {'Content-Length': str(len(data)), 'ETag': 'fixed'}
        self.fail = fail

    def getcode(self):
        return self.code

    def read(self, amount=-1):
        if self.fail:
            self.fail = False
            raise http.client.IncompleteRead(super().read(3), 10)
        return super().read(amount)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.path = Path(self.home.name) / 'update.zip'
        self.data = b'0123456789abcdef'
        self.sha = hashlib.sha256(self.data).hexdigest()

    def download(self, opener, **kwargs):
        return download_asset('https://github.com/repo/update.zip', self.path, opener,
                              expected_size=len(self.data), expected_sha256=self.sha,
                              delay=lambda _: None, **kwargs)

    def test_disconnect_partial_bytes_are_saved_and_range_resumes(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            if len(requests) == 1:
                return Response(self.data, fail=True)
            self.assertEqual(request.get_header('Range'), 'bytes=3-')
            self.assertEqual(request.get_header('If-range'), 'fixed')
            return Response(self.data[3:], 206, {'Content-Range': 'bytes 3-15/16', 'ETag': 'fixed'})
        self.download(opener)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertEqual(len(requests), 2)

    def test_early_eof_is_retried_and_cross_call_progress_is_retained(self):
        with self.assertRaises(ConnectionError):
            self.download(lambda *a, **k: Response(self.data[:4], headers={'Content-Length': '16'}), attempts=1)
        self.assertEqual(self.path.read_bytes(), self.data[:4])
        def opener(request, timeout):
            self.assertEqual(request.get_header('Range'), 'bytes=4-')
            return Response(self.data[4:], 206, {'Content-Range': 'bytes 4-15/16'})
        self.download(opener)
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_server_ignores_range_restart_does_not_append_duplicate_bytes(self):
        self.path.write_bytes(self.data[:5])
        self.download(lambda *a, **k: Response(self.data))
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_wrong_range_and_wrong_size_are_rejected(self):
        self.path.write_bytes(self.data[:5])
        for response in [Response(self.data[5:], 206, {'Content-Range': 'bytes 0-10/16'}),
                         Response(self.data, headers={'Content-Length': '17'})]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.download(lambda *a, **k: response)
        self.assertEqual(self.path.read_bytes(), self.data[:5])

    def test_hash_mismatch_removes_corrupt_cache(self):
        with self.assertRaises(ValueError):
            self.download(lambda *a, **k: Response(b'x' * len(self.data)))
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.with_suffix('.json').exists())

    def test_completed_cache_is_validated_without_redownloading(self):
        self.path.write_bytes(self.data)
        def opener(*a, **k):
            self.fail('completed cache should not download again')
        self.download(opener)

    def test_timeout_retries_are_bounded(self):
        calls = []
        def opener(*a, **k):
            calls.append(1)
            raise TimeoutError('stalled')
        with self.assertRaises(ConnectionError):
            self.download(opener, attempts=3)
        self.assertEqual(len(calls), 3)


class ApplyDownloadTests(unittest.TestCase):
    def test_invalid_digest_never_starts_install_and_exposes_cause(self):
        from updater import auto_updater as u
        with tempfile.TemporaryDirectory() as home, patch.object(u, 'DATA_ROOT', home), \
             patch.object(u.subprocess, 'Popen') as launch:
            self.assertFalse(u.download_and_apply('https://github.com/repo/a.zip', '1.7.2', expected_digest='bad'))
            self.assertIn('雜湊資訊無效', u.get_last_update_error())
            launch.assert_not_called()

    def test_valid_archive_prepares_only_verified_install(self):
        from updater import auto_updater as u
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('app/台股預測分析系統.exe', b'test exe')
            archive.writestr('app/_internal/version.json', json.dumps({'version': '1.7.2'}))
        data = buffer.getvalue()
        with tempfile.TemporaryDirectory() as home, patch.object(u, 'DATA_ROOT', home), \
             patch.object(u.tempfile, 'mkdtemp', return_value=str(Path(home) / 'staging')), \
             patch.object(u, '_urlopen_safe', return_value=Response(data)), \
             patch.object(u.subprocess, 'Popen') as launch:
            Path(home, 'staging').mkdir()
            self.assertTrue(u.download_and_apply('https://github.com/repo/a.zip', '1.7.2',
                           expected_size=len(data), expected_digest='sha256:' + hashlib.sha256(data).hexdigest()))
            launch.assert_called_once()
            self.assertTrue(Path(home, 'staging/extracted/app/台股預測分析系統.exe').exists())


class BackgroundUpdateTests(unittest.TestCase):
    def test_update_io_runs_off_gui_thread_and_failure_displays_reason(self):
        import os
        import threading
        import time
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QWidget, QMessageBox
        from ui.main_window import MainWindow
        from updater import auto_updater as u
        app = QApplication.instance() or QApplication([])

        class Parent(QWidget):
            def statusBar(self):
                return self
            def showMessage(self, *args):
                pass

        parent = Parent()
        threads, ticks = [], []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(10)
        def download(*args, **kwargs):
            threads.append(threading.get_ident())
            kwargs['progress_callback'](3, 16)
            kwargs['status_callback']('連線中斷，正在重試')
            time.sleep(.15)
            return False
        with patch.object(u, 'download_and_apply', side_effect=download), \
             patch.object(u, 'get_last_update_error', return_value='磁碟空間不足'), \
             patch.object(QMessageBox, 'warning') as warning:
            MainWindow._do_update(parent, {'version': '1.7.2', 'download_url': 'https://github.com/repo/a.zip'})
            deadline = time.monotonic() + 3
            while parent._update_running and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.005)
            self.assertFalse(parent._update_running)
            self.assertNotEqual(threads[0], threading.get_ident())
            self.assertGreater(len(ticks), 3)
            self.assertIn('磁碟空間不足', warning.call_args.args[2])
        timer.stop()
        parent.close()


if __name__ == '__main__':
    unittest.main()

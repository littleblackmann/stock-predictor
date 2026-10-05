import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from resource_budget import ProgressThrottle, RateLimiter, background_resources
from updater import auto_updater as u


class ResourceTests(unittest.TestCase):
    def test_startup_modules_do_not_load_analysis_libraries(self):
        code = '''
import sys, json
from resource_budget import configure_numeric_threads
configure_numeric_threads()
import ui.main_window, workers.signal_scan_worker
print(json.dumps([m for m in ('numpy','pandas','yfinance','openai','lightgbm') if m in sys.modules]))
'''
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, LOCALAPPDATA=home)
            result = subprocess.run([sys.executable, '-c', code], env=env,
                                    capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [])

    def test_progress_throttle_and_completion_and_restart(self):
        now = [0.0]
        events = []
        progress = ProgressThrottle(lambda *args: events.append(args), clock=lambda: now[0])
        for count in range(1000):
            now[0] = count / 10000
            progress(count, 1000)
        progress(1000, 1000)
        progress(0, 1000)
        self.assertEqual(events, [(0, 1000), (1000, 1000), (0, 1000)])

    def test_rate_limit_sleeps_instead_of_busy_waiting(self):
        now = [0.0]
        waits = []
        def sleep(seconds):
            waits.append(seconds)
            now[0] += seconds
        limiter = RateLimiter(100, clock=lambda: now[0], sleep=sleep)
        limiter.consume(50)
        limiter.consume(50)
        self.assertEqual(waits, [.5, .5])
        now[0] += 10
        limiter.consume(50)
        self.assertEqual(waits[-1], .5)  # Idle time cannot buy a large burst.

    @unittest.skipUnless(os.name == 'nt', 'Windows priority API')
    def test_background_priority_restored_even_on_error(self):
        import ctypes
        kernel = Mock()
        kernel.GetCurrentThread.return_value = 123
        kernel.SetThreadPriority.return_value = True
        with patch.object(ctypes, 'WinDLL', return_value=kernel):
            with self.assertRaises(RuntimeError), background_resources():
                raise RuntimeError('worker failed')
        self.assertEqual([c.args for c in kernel.SetThreadPriority.call_args_list],
                         [(123, 0x10000), (123, 0x20000)])

    def test_extract_checks_crc_without_second_decompression(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w', zipfile.ZIP_STORED) as z:
            z.writestr('app/large.dll', b'UNIQUE-PAYLOAD')
        with tempfile.TemporaryDirectory() as home:
            with zipfile.ZipFile(io.BytesIO(payload.getvalue())) as z:
                with patch.object(z, 'testzip', side_effect=AssertionError('double decompression')):
                    u._extract_archive(z, home, bytes_per_second=0)
            self.assertEqual((Path(home)/'app/large.dll').read_bytes(), b'UNIQUE-PAYLOAD')
            # Equal-length corruption preserves central directory offsets.
            damaged = payload.getvalue().replace(b'UNIQUE-PAYLOAD', b'BROKEN-PAYLOAD')
            with zipfile.ZipFile(io.BytesIO(damaged)) as z:
                with self.assertRaises(zipfile.BadZipFile):
                    u._extract_archive(z, home, bytes_per_second=0)

    def test_corrupt_archive_never_starts_installer(self):
        with tempfile.TemporaryDirectory() as home:
            archive = Path(home)/'corrupt.zip'
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_STORED) as z:
                z.writestr('app/file', b'UNIQUE-PAYLOAD')
            archive.write_bytes(archive.read_bytes().replace(b'UNIQUE-PAYLOAD', b'BROKEN-PAYLOAD'))
            def supply(url, destination, *args, **kwargs):
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                Path(destination).write_bytes(archive.read_bytes())
            with patch.object(u, 'DATA_ROOT', home), patch.object(u, 'APP_ROOT', home), \
                 patch('updater.download.download_asset', side_effect=supply), \
                 patch.object(u.subprocess, 'Popen') as launch:
                self.assertFalse(u.download_and_apply('https://github.com/repo/file.zip', '1.7.3'))
                launch.assert_not_called()
            self.assertIn('CRC', u.get_last_update_error())

    def test_maintenance_defers_during_analysis_update_or_another_worker(self):
        from ui.main_window import MainWindow
        parent = Mock()
        callback = Mock()
        for busy, updating, active in ((True, False, 0), (False, True, 0), (False, False, 1)):
            parent._busy = busy
            parent._update_running = updating
            parent._pool.activeThreadCount.return_value = active
            with patch('ui.main_window.QTimer.singleShot') as later:
                self.assertTrue(MainWindow._defer_maintenance(parent, callback))
                later.assert_called_once_with(10000, callback)
        parent._busy = parent._update_running = False
        parent._pool.activeThreadCount.return_value = 0
        self.assertFalse(MainWindow._defer_maintenance(parent, callback))


if __name__ == '__main__':
    unittest.main()

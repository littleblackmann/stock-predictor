"""Atomic CSV storage with an interprocess lock; legacy records stay readable."""
import csv
import os
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

LEGACY_FIELDS = ['prediction_date', 'symbol', 'predicted', 'up_prob', 'down_prob',
                 'raw_up_prob', 'gpt_3day', 'actual', 'actual_return', 'correct']
FIELDS = LEGACY_FIELDS + ['record_id', 'created_at', 'data_date', 'target_date',
                          'horizon', 'model_version', 'evaluation_status']
_lock = threading.RLock()


@contextmanager
def locked(path):
    with _lock:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(str(path) + '.lock', 'a+b') as f:
            f.seek(0, 2)
            if not f.tell():
                f.write(b'0'); f.flush()
            deadline = time.monotonic() + 15
            while True:
                try:
                    f.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('預測紀錄忙碌，請稍後再試')
                    time.sleep(.05)
            try:
                yield
            finally:
                f.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(f, fcntl.LOCK_UN)


def write_rows(path, rows):
    fd, tmp = tempfile.mkstemp(dir=Path(path).parent, suffix='.csv.tmp')
    with os.fdopen(fd, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='raise')
        writer.writeheader(); writer.writerows(rows)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def read_rows(path):
    if not Path(path).exists() or Path(path).stat().st_size == 0:
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        records = list(csv.reader(f))
    header = records[0]
    current = header == FIELDS
    rows = []
    for values in records[1:]:
        if not values:
            continue
        if len(values) == 9 and 'record_id' not in header:
            values.insert(5, '')
        if len(values) == 10 and 'record_id' not in header:
            row = dict(zip(LEGACY_FIELDS, values))
        elif len(values) == len(header) and set(header).issubset(FIELDS):
            row = dict(zip(header, values))
        else:
            raise ValueError('預測紀錄欄位異常，原始檔案已保留，請勿重置資料')
        row['prediction_date'] = row.get('prediction_date', '').lstrip('\ufeff')
        for key in FIELDS:
            row.setdefault(key, '')
        if not row['record_id']:
            row['record_id'] = uuid.uuid4().hex
            row['horizon'] = '1'
            row['model_version'] = 'legacy'
            row['evaluation_status'] = 'legacy'
            current = False
        rows.append(row)
    if not current:
        backup = str(path) + '.pre-v1.7.bak'
        if not Path(backup).exists():
            shutil.copy2(path, backup)
        write_rows(path, rows)
    return rows

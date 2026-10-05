"""App-local resource limits; never changes persistent Windows settings."""
import os
import time
from contextlib import contextmanager


def configure_numeric_threads():
    # Must run before importing numerical libraries, including in frozen builds.
    for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                 'NUMEXPR_NUM_THREADS', 'BLIS_NUM_THREADS'):
        os.environ[name] = '1'


@contextmanager
def background_resources():
    """Lower CPU/I/O priority only for the calling worker, then restore it."""
    kernel = None
    handle = None
    entered = False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentThread.restype = wintypes.HANDLE
        kernel.SetThreadPriority.argtypes = (wintypes.HANDLE, ctypes.c_int)
        kernel.SetThreadPriority.restype = wintypes.BOOL
        handle = kernel.GetCurrentThread()
        entered = bool(kernel.SetThreadPriority(handle, 0x10000))
    try:
        yield
    finally:
        if entered:
            kernel.SetThreadPriority(handle, 0x20000)


class RateLimiter:
    """Pace bytes with bounded chunk-size bursts, without busy waiting."""
    def __init__(self, bytes_per_second, clock=time.monotonic, sleep=time.sleep):
        self.rate = bytes_per_second
        self.clock = clock
        self.sleep = sleep
        self.deadline = clock()

    def consume(self, count):
        if self.rate:
            now = self.clock()
            self.deadline = max(now, self.deadline) + count / self.rate
            self.sleep(max(0, self.deadline - now))


class ProgressThrottle:
    """At most 10 GUI updates/sec, plus initial/reset/final notifications."""
    def __init__(self, callback, clock=time.monotonic):
        self.callback = callback
        self.clock = clock
        self.last_time = float('-inf')
        self.last_bytes = None

    def __call__(self, count, total):
        now = self.clock()
        boundary = self.last_bytes is None or count < self.last_bytes or (total and count >= total)
        if boundary or now - self.last_time >= .1:
            self.callback(count, total)
            self.last_time = now
            self.last_bytes = count

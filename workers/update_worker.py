"""Keep download retries, ZIP validation and extraction off the GUI thread."""
from PySide6.QtCore import QObject, QRunnable, Signal


class UpdateSignals(QObject):
    progress = Signal(object, object)
    status = Signal(str)
    finished = Signal(bool, str)


class UpdateWorker(QRunnable):
    def __init__(self, info):
        super().__init__()
        self.info = info
        self.signals = UpdateSignals()

    def run(self):
        from resource_budget import background_resources
        with background_resources():
            self._apply()

    def _apply(self):
        from updater.auto_updater import download_and_apply, get_last_update_error
        from resource_budget import ProgressThrottle
        try:
            success = download_and_apply(
                self.info['download_url'], self.info['version'],
                progress_callback=ProgressThrottle(self.signals.progress.emit),
                full_url=self.info.get('full_url'), is_patch=self.info.get('is_patch', False),
                status_callback=self.signals.status.emit,
                expected_size=self.info.get('size', 0), expected_digest=self.info.get('digest'),
            )
            self.signals.finished.emit(success, get_last_update_error())
        except Exception as error:
            self.signals.finished.emit(False, str(error))

"""Background job runner for the Qt GUI.

Blocking work (rclone, SSH dumps, ``asyncio.run`` against pymysql/asyncpg,
checksum hashing) must never run on the GUI thread. ``JobRunner`` starts each
job in its own ``QThread`` so independent jobs (Create + Refresh + Verify +
Monitoring poll) can run at the same time. Jobs sharing a *group* are
serialized: a second submit for a busy group is rejected (or queued, keeping
only the newest queued job) so one long job never gets killed or duplicated.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Set, Tuple

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class JobWorker(QThread):
    """Run a callable off the Qt GUI thread and report the result via signals."""

    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, job: Callable[[], Any], *, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._job = job

    def run(self) -> None:
        try:
            result = self._job()
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI status line
            self.failed.emit(str(exc) or type(exc).__name__)
            return
        self.finished_ok.emit(result)


_Queued = Tuple[
    Callable[[], Any],
    Callable[[Any], None],
    Optional[Callable[[str], None]],
    Optional[Callable[[], None]],
]


class JobRunner(QObject):
    """Run background jobs, one active job per group, many groups in parallel."""

    state_changed = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._workers: Dict[str, JobWorker] = {}
        self._queued: Dict[str, _Queued] = {}
        # Workers whose group slot is free but whose thread is still unwinding.
        self._retiring: Set[JobWorker] = set()

    def is_busy(self, group: str) -> bool:
        return group in self._workers

    def busy_groups(self) -> Set[str]:
        return set(self._workers)

    def any_busy(self) -> bool:
        return bool(self._workers) or bool(self._retiring)

    def submit(
        self,
        group: str,
        job: Callable[[], Any],
        on_ok: Callable[[Any], None],
        on_fail: Optional[Callable[[str], None]] = None,
        *,
        on_start: Optional[Callable[[], None]] = None,
        queue: bool = False,
    ) -> bool:
        """Start ``job`` unless ``group`` is already running.

        Returns True when the job started or was queued; False when rejected.
        ``queue=True`` keeps only the newest pending job for the group.
        """
        if group in self._workers:
            if queue:
                self._queued[group] = (job, on_ok, on_fail, on_start)
                return True
            return False

        worker = JobWorker(job, parent=self)
        self._workers[group] = worker

        def _release() -> None:
            if self._workers.get(group) is worker:
                del self._workers[group]
            self._retiring.add(worker)

        def _ok(result: Any) -> None:
            _release()
            try:
                on_ok(result)
            finally:
                self._after(group)

        def _fail(message: str) -> None:
            _release()
            try:
                if on_fail is not None:
                    on_fail(message)
            finally:
                self._after(group)

        def _finished() -> None:
            self._retiring.discard(worker)
            worker.deleteLater()
            self.state_changed.emit()

        worker.finished_ok.connect(_ok)
        worker.failed.connect(_fail)
        worker.finished.connect(_finished)
        if on_start is not None:
            on_start()
        worker.start()
        self.state_changed.emit()
        return True

    def _after(self, group: str) -> None:
        self.state_changed.emit()
        queued = self._queued.pop(group, None)
        if queued is not None:
            job, on_ok, on_fail, on_start = queued
            self.submit(group, job, on_ok, on_fail, on_start=on_start)

    def wait_all(self, timeout_ms: int = 5000) -> None:
        """Block until every running worker thread finished (shutdown / tests)."""
        for worker in list(self._workers.values()) + list(self._retiring):
            worker.wait(timeout_ms)

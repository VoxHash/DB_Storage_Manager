"""GUI-thread offload for backup jobs (freeze regression guard)."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QCoreApplication

from db_storage_manager.gui.backups import BackupJobWorker


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_backup_job_worker_runs_off_caller_thread(qapp):
    results = []
    errors = []

    def job():
        time.sleep(0.05)
        return "done"

    worker = BackupJobWorker(job)
    worker.finished_ok.connect(results.append)
    worker.failed.connect(errors.append)
    worker.start()
    deadline = time.time() + 5
    while worker.isRunning() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    worker.wait(2000)
    qapp.processEvents()
    assert errors == []
    assert results == ["done"]


def test_backup_job_worker_surfaces_errors(qapp):
    results = []
    errors = []

    def job():
        raise RuntimeError("boom")

    worker = BackupJobWorker(job)
    worker.finished_ok.connect(results.append)
    worker.failed.connect(errors.append)
    worker.start()
    deadline = time.time() + 5
    while worker.isRunning() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    worker.wait(2000)
    qapp.processEvents()
    assert results == []
    assert errors and "boom" in errors[0]

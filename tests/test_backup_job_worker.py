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


def test_job_runner_reports_restore_results_on_the_gui_thread(qapp):
    """Status callbacks must not run on the worker (QLabel would stay unchanged)."""
    from PyQt6.QtCore import QThread

    from db_storage_manager.gui.jobs import JobRunner

    runner = JobRunner()
    seen = []

    def on_ok(result):
        seen.append(("ok", result, QThread.currentThread() is qapp.thread()))

    def on_fail(message):
        seen.append(("fail", message, QThread.currentThread() is qapp.thread()))

    assert runner.submit(
        "restore",
        lambda: {"ok": True, "restoreNotice": "Skipped ACLs the session cannot apply."},
        on_ok,
        on_fail,
    )
    deadline = time.time() + 5
    while (not seen or runner.any_busy()) and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert seen == [
        ("ok", {"ok": True, "restoreNotice": "Skipped ACLs the session cannot apply."}, True)
    ]
    assert runner.any_busy() is False

    seen.clear()

    def boom():
        raise RuntimeError("")

    assert runner.submit("restore", boom, on_ok, on_fail)
    deadline = time.time() + 5
    while not seen and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert len(seen) == 1
    assert seen[0][0] == "fail"
    assert "RuntimeError" in seen[0][1]
    assert seen[0][2] is True
    runner.wait_all(2000)


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

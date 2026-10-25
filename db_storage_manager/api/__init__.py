"""
Local REST + Web UI companion for DB Storage Manager.

Desktop (PyQt6) remains primary. Start the companion with::

    python -m db_storage_manager.api
    # or: db-storage-manager-api

Defaults to ``127.0.0.1:8765``. Set ``DSM_API_TOKEN`` to require Bearer auth.
"""

from .server import CompanionServer, create_server, main, run_server

__all__ = [
    "CompanionServer",
    "create_server",
    "main",
    "run_server",
]

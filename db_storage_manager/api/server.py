"""stdlib HTTP REST + static Web UI companion server."""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from ..config import BACKUP_DIR
from . import service

STATIC_DIR = Path(__file__).resolve().parent / "static"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _env_token() -> Optional[str]:
    token = os.environ.get("DSM_API_TOKEN", "").strip()
    return token or None


def _json_bytes(payload: Any, status: int = 200) -> Tuple[int, bytes, str]:
    body = json.dumps(payload, indent=2, default=str).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


class CompanionHandler(BaseHTTPRequestHandler):
    """HTTP handler bound to a CompanionServer instance via server reference."""

    server_version = "DBStorageManagerAPI/1.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    @property
    def companion(self) -> "CompanionServer":
        return self.server  # type: ignore[return-value]

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # Local companion — allow same-origin web UI fetch
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _unauthorized(self) -> None:
        status, body, ctype = _json_bytes(
            {"ok": False, "error": "Unauthorized", "hint": "Bearer DSM_API_TOKEN"},
            401,
        )
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("WWW-Authenticate", 'Bearer realm="db-storage-manager-api"')
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        expected = self.companion.api_token
        if not expected:
            return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer ") and header[7:].strip() == expected:
            return True
        return False

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET(head_only=True)

    def do_GET(self, head_only: bool = False) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/") :])

        if path in ("/", "/index.html"):
            return self._serve_static("index.html")

        if path == "/api/v1/health":
            status, body, ctype = _json_bytes(service.health_payload())
            return self._send(status, body, ctype)

        if not self._check_auth():
            return self._unauthorized()

        if path == "/api/v1/info":
            status, body, ctype = _json_bytes(service.info_payload())
            return self._send(status, body, ctype)

        if path == "/api/v1/connections":
            status, body, ctype = _json_bytes(
                {"ok": True, "connections": service.list_connections()}
            )
            return self._send(status, body, ctype)

        if path == "/api/v1/backups":
            backup_dir = self._backup_dir_from_query(query)
            status, body, ctype = _json_bytes(
                {
                    "ok": True,
                    "backup_dir": str(backup_dir),
                    "backups": service.list_backups(backup_dir),
                }
            )
            return self._send(status, body, ctype)

        if path.startswith("/api/v1/backups/"):
            parts = path.split("/")
            # /api/v1/backups/{id}
            if len(parts) == 5:
                backup_id = parts[4]
                backup_dir = self._backup_dir_from_query(query)
                item = service.get_backup(backup_id, backup_dir)
                if item is None:
                    status, body, ctype = _json_bytes(
                        {"ok": False, "error": "Backup not found"}, 404
                    )
                else:
                    status, body, ctype = _json_bytes({"ok": True, "backup": item})
                return self._send(status, body, ctype)

        status, body, ctype = _json_bytes({"ok": False, "error": "Not found"}, 404)
        self._send(status, body, ctype)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if not self._check_auth():
            return self._unauthorized()

        try:
            payload = self._read_json()
        except ValueError as exc:
            status, body, ctype = _json_bytes({"ok": False, "error": str(exc)}, 400)
            return self._send(status, body, ctype)

        backup_dir = self._backup_dir_from_query(query)
        if "backup_dir" in payload and payload["backup_dir"]:
            backup_dir = Path(str(payload["backup_dir"]))

        if path == "/api/v1/backups/verify":
            result = service.verify_backup(
                backup_id=payload.get("id") or payload.get("backup_id"),
                path=payload.get("path"),
                backup_dir=backup_dir,
                encryption_key=payload.get("encryption_key")
                or payload.get("encryptionKey"),
            )
            code = 200 if result.get("ok") or result.get("status") != "not_found" else 404
            if result.get("status") == "not_found":
                code = 404
            status, body, ctype = _json_bytes(result, code)
            return self._send(status, body, ctype)

        if path == "/api/v1/backups/dry-run":
            result = service.dry_run_backup(
                backup_id=payload.get("id") or payload.get("backup_id"),
                path=payload.get("path"),
                backup_dir=backup_dir,
                encryption_key=payload.get("encryption_key")
                or payload.get("encryptionKey"),
            )
            code = 404 if result.get("status") == "not_found" else 200
            status, body, ctype = _json_bytes(result, code)
            return self._send(status, body, ctype)

        # /api/v1/backups/{id}/verify|dry-run
        parts = path.split("/")
        if len(parts) == 6 and parts[1:4] == ["api", "v1", "backups"]:
            backup_id = parts[4]
            action = parts[5]
            if action == "verify":
                result = service.verify_backup(
                    backup_id=backup_id, backup_dir=backup_dir
                )
            elif action == "dry-run":
                result = service.dry_run_backup(
                    backup_id=backup_id,
                    backup_dir=backup_dir,
                    encryption_key=payload.get("encryption_key")
                    or payload.get("encryptionKey"),
                )
            else:
                status, body, ctype = _json_bytes(
                    {"ok": False, "error": "Not found"}, 404
                )
                return self._send(status, body, ctype)
            code = 404 if result.get("status") == "not_found" else 200
            status, body, ctype = _json_bytes(result, code)
            return self._send(status, body, ctype)

        status, body, ctype = _json_bytes({"ok": False, "error": "Not found"}, 404)
        self._send(status, body, ctype)

    def _backup_dir_from_query(self, query: Dict[str, list]) -> Path:
        values = query.get("backup_dir") or query.get("dir") or []
        if values and values[0]:
            return Path(values[0])
        return self.companion.backup_dir

    def _serve_static(self, relative: str) -> None:
        # Prevent path traversal
        candidate = (STATIC_DIR / relative).resolve()
        if not str(candidate).startswith(str(STATIC_DIR.resolve())):
            status, body, ctype = _json_bytes({"ok": False, "error": "Forbidden"}, 403)
            return self._send(status, body, ctype)
        if not candidate.is_file():
            status, body, ctype = _json_bytes({"ok": False, "error": "Not found"}, 404)
            return self._send(status, body, ctype)
        data = candidate.read_bytes()
        suffix = candidate.suffix.lower()
        types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".json": "application/json; charset=utf-8",
        }
        ctype = types.get(suffix, "application/octet-stream")
        self._send(200, data, ctype)


class CompanionServer(ThreadingHTTPServer):
    """Threading HTTP server with companion configuration."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        api_token: Optional[str] = None,
        backup_dir: Optional[Path] = None,
    ):
        self.api_token = api_token if api_token is not None else _env_token()
        self.backup_dir = Path(backup_dir) if backup_dir else BACKUP_DIR
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        super().__init__((host, port), CompanionHandler)

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        display = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        return f"http://{display}:{port}"


def create_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    api_token: Optional[str] = None,
    backup_dir: Optional[Path] = None,
) -> CompanionServer:
    return CompanionServer(
        host, port, api_token=api_token, backup_dir=backup_dir
    )


def run_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    api_token: Optional[str] = None,
    backup_dir: Optional[Path] = None,
) -> None:
    server = create_server(
        host, port, api_token=api_token, backup_dir=backup_dir
    )
    auth = "Bearer token required" if server.api_token else "open (no DSM_API_TOKEN)"
    print(
        f"{service.health_payload()['app']} companion listening on {server.base_url} ({auth})",
        flush=True,
    )
    print(f"Web UI: {server.base_url}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down companion.", flush=True)
    finally:
        server.server_close()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="DB Storage Manager REST + Web UI companion (desktop remains primary)"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("DSM_API_HOST", DEFAULT_HOST),
        help="Bind host (default 127.0.0.1; use 0.0.0.0 only on trusted networks)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("DSM_API_PORT", str(DEFAULT_PORT))),
        help="Bind port (default 8765)",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="Override local backup directory (default: app BACKUP_DIR)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="API Bearer token (default: DSM_API_TOKEN env)",
    )
    args = parser.parse_args(argv)
    backup_dir = Path(args.backup_dir) if args.backup_dir else None
    run_server(
        args.host,
        args.port,
        api_token=args.token if args.token is not None else _env_token(),
        backup_dir=backup_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

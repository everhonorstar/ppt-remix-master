from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .workflow import assemble, run


def serve(host: str, port: int, root: Path, config_path: Path | None) -> None:
    root = root.resolve()
    config_path = config_path.resolve() if config_path else None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if urlparse(self.path).path == "/health":
                self._json({"ok": True, "root": str(root)})
                return
            self._json({"error": "not found"}, status=404)

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                path = urlparse(self.path).path
                if path == "/run":
                    input_pptx = _safe_path(root, payload["input_pptx"])
                    output_dir = _safe_path(root, payload.get("output_dir", "jobs"))
                    concurrency = int(payload.get("concurrency", 3))
                    result = run(input_pptx, output_dir, config_path, concurrency)
                    self._json({"status": "ok", "result": str(result)})
                    return
                if path == "/assemble":
                    job_dir = _safe_path(root, payload["job_dir"])
                    result = assemble(job_dir, approved=bool(payload.get("approved", False)))
                    self._json({"status": "ok", "result": str(result)})
                    return
                self._json({"error": "not found"}, status=404)
            except Exception as exc:
                self._json({"status": "error", "error": str(exc)}, status=500)

        def log_message(self, format: str, *args) -> None:
            return

        def _json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"ppt-remix server listening on http://{host}:{port} root={root}")
    server.serve_forever()


def _safe_path(root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"Path is outside server root: {value}")
    return resolved

"""Short-lived, bearer-protected MP4 handoff from private Kaggle kernels.

This uses a Cloudflare Quick Tunnel only as a temporary transport for one
GitHub Actions job. It is not a permanent production ingress or file host.
The tunnel, random route, and bearer token are destroyed when the batch ends.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable

CLOUDFLARED_VERSION = "2026.11.2"
CLOUDFLARED_URL = (
    "https://github.com/cloudflare/cloudflared/releases/download/"
    f"{CLOUDFLARED_VERSION}/cloudflared-linux-amd64"
)
MAX_UPLOAD_BYTES = 95 * 1024 * 1024


def _safe_filename(value: str) -> bool:
    return bool(re.fullmatch(r"musetalk_preview_[0-9]+\.mp4", value))


class OutputRelay:
    """One-run private MP4 receiver with an optional short-lived Cloudflare tunnel."""

    def __init__(
        self,
        expected_filenames: Iterable[str],
        output_dir: Path,
        *,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
    ) -> None:
        self.expected = set(expected_filenames)
        if not self.expected or any(not _safe_filename(name) for name in self.expected):
            raise ValueError("Relay accepts only expected musetalk_preview_N.mp4 filenames.")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_upload_bytes = int(max_upload_bytes)
        self.route = os.urandom(24).hex()
        self.token = os.urandom(32).hex()
        self.base_url: str | None = None
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._tunnel: subprocess.Popen[str] | None = None
        self._tunnel_thread: threading.Thread | None = None
        self._tunnel_lines: queue.Queue[str] = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()

    def start_local(self) -> str:
        """Start the receiver on loopback. This method is also used by unit tests."""
        if self._server is not None:
            return f"http://127.0.0.1:{self._server.server_port}"

        relay = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _reply(self, status: int, body: dict) -> None:
                payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)

            def _authorized(self) -> bool:
                supplied = self.headers.get("Authorization", "")
                expected = f"Bearer {relay.token}"
                return hmac.compare_digest(supplied, expected)

            def do_GET(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._reply(401, {"ok": False, "error": "unauthorized"})
                    return
                if self.path != f"/health/{relay.route}":
                    self._reply(404, {"ok": False, "error": "not_found"})
                    return
                self._reply(200, {"ok": True})

            def do_PUT(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._reply(401, {"ok": False, "error": "unauthorized"})
                    return
                prefix = f"/upload/{relay.route}/"
                if not self.path.startswith(prefix):
                    self._reply(404, {"ok": False, "error": "not_found"})
                    return
                filename = self.path[len(prefix):]
                if not _safe_filename(filename) or filename not in relay.expected:
                    self._reply(404, {"ok": False, "error": "file_not_allowed"})
                    return
                if "/" in filename or "\\" in filename or ".." in filename:
                    self._reply(400, {"ok": False, "error": "invalid_filename"})
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    self._reply(411, {"ok": False, "error": "content_length_required"})
                    return
                if content_length <= 0 or content_length > relay.max_upload_bytes:
                    self._reply(413, {"ok": False, "error": "file_size_not_allowed"})
                    return
                expected_hash = self.headers.get("X-Content-SHA256", "").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                    self._reply(400, {"ok": False, "error": "sha256_required"})
                    return

                target = relay.output_dir / filename
                partial = relay.output_dir / f".{filename}.{os.urandom(8).hex()}.part"
                digest = hashlib.sha256()
                remaining = content_length
                try:
                    with partial.open("xb") as handle:
                        while remaining:
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise ConnectionError("upload ended before Content-Length bytes arrived")
                            handle.write(chunk)
                            digest.update(chunk)
                            remaining -= len(chunk)
                    actual_hash = digest.hexdigest()
                    if not hmac.compare_digest(actual_hash, expected_hash):
                        raise ValueError("SHA-256 mismatch")
                    if partial.stat().st_size < 100_000:
                        raise ValueError("file is too small to be a valid MP4")
                    with relay._lock:
                        if target.exists():
                            raise FileExistsError("this output filename has already been uploaded")
                        os.replace(partial, target)
                    self._reply(201, {
                        "ok": True,
                        "file": filename,
                        "bytes": content_length,
                        "sha256": actual_hash,
                    })
                except FileExistsError:
                    partial.unlink(missing_ok=True)
                    self._reply(409, {"ok": False, "error": "already_uploaded"})
                except Exception as exc:  # noqa: preserve HTTP server process
                    partial.unlink(missing_ok=True)
                    self._reply(400, {"ok": False, "error": str(exc)[:180]})

            def log_message(self, fmt: str, *args) -> None:
                # Do not log bearer paths, user clips, or uploaded filenames.
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="musetalk-output-relay",
            daemon=True,
        )
        self._server_thread.start()
        return f"http://127.0.0.1:{self._server.server_port}"

    @staticmethod
    def _cloudflared_binary(work_dir: Path) -> Path:
        existing = shutil.which("cloudflared")
        if existing:
            binary = Path(existing)
        else:
            binary = work_dir / "cloudflared"
            request = urllib.request.Request(
                CLOUDFLARED_URL,
                headers={"User-Agent": "MuseTalk-Private-Output-Relay/1.0"},
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read(60 * 1024 * 1024 + 1)
            if not data or len(data) > 60 * 1024 * 1024:
                raise RuntimeError("Cloudflared release binary size is unexpected.")
            binary.write_bytes(data)
            binary.chmod(0o755)

        check = subprocess.run(
            [str(binary), "version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        if CLOUDFLARED_VERSION not in (check.stdout + check.stderr):
            raise RuntimeError("Cloudflared binary version does not match the pinned release.")
        return binary

    def start_quick_tunnel(self, work_dir: Path) -> dict:
        """Expose only this temporary receiver; returns private run-only callback data."""
        local_url = self.start_local()
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        binary = self._cloudflared_binary(work_dir)
        self._tunnel = subprocess.Popen(
            [
                str(binary),
                "tunnel",
                "--url",
                local_url,
                "--no-autoupdate",
                "--loglevel",
                "info",
                "--protocol",
                "http2",
            ],
            stdin=subprocess.DEVNULL,
            env={**os.environ, "HOME": str(work_dir.resolve())},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        def read_tunnel_output() -> None:
            assert self._tunnel and self._tunnel.stdout
            for line in self._tunnel.stdout:
                self._tunnel_lines.put(line)

        self._tunnel_thread = threading.Thread(
            target=read_tunnel_output,
            name="cloudflared-output-reader",
            daemon=True,
        )
        self._tunnel_thread.start()

        deadline = time.monotonic() + 90
        public_url = None
        pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)
        while time.monotonic() < deadline:
            if self._tunnel.poll() is not None:
                raise RuntimeError("Cloudflared Quick Tunnel exited before it published a URL.")
            try:
                line = self._tunnel_lines.get(timeout=1)
            except queue.Empty:
                continue
            match = pattern.search(line)
            if match:
                public_url = match.group(0).rstrip("/")
                break
        if not public_url:
            raise TimeoutError("Cloudflared did not publish a Quick Tunnel URL within 90 seconds.")

        self.base_url = public_url
        health_url = f"{public_url}/health/{self.route}"
        health_ok = False
        for _ in range(20):
            if self._tunnel.poll() is not None:
                break
            try:
                request = urllib.request.Request(
                    health_url,
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                with urllib.request.urlopen(request, timeout=8) as response:
                    health_ok = response.status == 200
                if health_ok:
                    break
            except Exception:
                time.sleep(2)
        if not health_ok:
            raise RuntimeError("Cloudflare Quick Tunnel did not pass the authenticated health check.")

        print(
            "Temporary authenticated output relay is ready; route hostname is "
            f"{public_url}. The bearer token is not logged.",
            flush=True,
        )
        return {
            "base_url": public_url,
            "route": self.route,
            "token": self.token,
            "max_upload_bytes": self.max_upload_bytes,
        }

    def wait_for_outputs(self, filenames: Iterable[str], timeout: int = 300) -> bool:
        expected = set(filenames)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready = all(
                (self.output_dir / filename).is_file()
                and (self.output_dir / filename).stat().st_size >= 100_000
                for filename in expected
            )
            if ready:
                return True
            if self._tunnel and self._tunnel.poll() is not None:
                break
            time.sleep(2)
        return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._tunnel is not None:
            self._tunnel.terminate()
            try:
                self._tunnel.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._tunnel.kill()
                self._tunnel.wait(timeout=5)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._server_thread is not None:
            self._server_thread.join(timeout=5)

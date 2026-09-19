"""Local dev server with the same routes as the Lambda. Fire TV reaches it over your LAN:

    python local_server.py            # listens on 0.0.0.0:8080

Also serves ../media/* at /media/* (with HTTP Range, so the player can seek), which keeps
demo playback smooth on the emulator instead of streaming 1080p from the internet.
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.handler import route

MEDIA_DIR = Path(__file__).resolve().parents[1] / "media"
MEDIA_TYPES = {".mp4": "video/mp4", ".mkv": "video/x-matroska", ".srt": "application/x-subrip"}


class Handler(BaseHTTPRequestHandler):
    def _handle(self, method: str):
        length = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            body = {}
        try:
            status, out = route(method, self.path.split("?")[0], body)
        except Exception as e:  # surface errors to the TV during dev
            status, out = 500, {"error": repr(e)}
        data = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _media(self):
        name = self.path.split("?")[0].removeprefix("/media/")
        path = (MEDIA_DIR / name).resolve()
        if MEDIA_DIR.resolve() not in path.parents or not path.is_file():
            self.send_error(404)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("range", ""))
        if m and (m[1] or m[2]):
            if m[1]:
                start, end = int(m[1]), int(m[2]) if m[2] else size - 1
            else:  # suffix range: last N bytes
                start = max(0, size - int(m[2]))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("content-range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("content-range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("accept-ranges", "bytes")
        self.send_header("content-type", MEDIA_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("content-length", str(end - start + 1))
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            try:
                while remaining > 0:
                    chunk = f.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # player seeked away and dropped the connection

    def do_GET(self):
        if self.path.startswith("/media/"):
            self._media()
        else:
            self._handle("GET")

    def do_POST(self):
        self._handle("POST")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"Companion backend on http://0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()

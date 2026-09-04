#!/usr/bin/env python3
"""Serve a directory over localhost, taking the first free port at or above 8000.

    python serve.py [directory] [port]      # either, both, or neither

Both default to config.toml, so plain `python serve.py` serves the browser
directory the generator writes to.

GET /audio?i=<n> streams one track, with byte-range support so the browser can
seek. POST /play with {"name": ..., "indices": [...]} writes those tracks, in
that order, to _now_playing.m3u8 and hands it to VLC instead.

Both take row numbers only; paths come from the server's own paths.json, so
neither can be talked into opening a file that isn't in the library. Bound to
127.0.0.1 only.

Binding to a fixed port dies with 'Address already in use' the moment something
is left over on it, so probe upward and report the port actually taken.
"""
import functools
import http.server
import json
import os
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import urllib.parse

from config import BROWSER_DIR, PORT

# How far to probe upward before giving up. Fifty is well past any plausible
# pile-up of stale servers, and short enough to fail quickly if something is
# holding the whole range.
PORT_SEARCH_SPAN = 50

# Streaming granularity. Small enough that a seek abandons little work, large
# enough not to syscall per packet.
CHUNK_BYTES = 64 * 1024


def first_free(start, tries=PORT_SEARCH_SPAN):
    for port in range(start, start + tries):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit(f"no free port in {start}..{start + tries}")


# What the browser needs told to it before it will decode a file. m4b and m4r
# are AAC in a different costume; served as audio/mp4 they play like any m4a.
MIME = {
    ".mp3": "audio/mpeg", ".mpga": "audio/mpeg",
    ".m4a": "audio/mp4", ".m4b": "audio/mp4", ".m4r": "audio/mp4",
    ".mp4": "audio/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".wav": "audio/wav", ".aif": "audio/aiff", ".aiff": "audio/aiff",
    ".flac": "audio/flac", ".ogg": "audio/ogg",
}


def parse_range(header, size):
    """Return (start, end) inclusive for a single byte range, or None.

    Only the single-range form is handled; a multipart response is more than an
    audio element ever asks for.
    """
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    spec = header[len("bytes="):].strip()
    start_s, _, end_s = spec.partition("-")
    try:
        if not start_s:                      # bytes=-500 -> the last 500 bytes
            length = int(end_s)
            if length <= 0:
                return None
            return max(0, size - length), size - 1
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    except ValueError:
        return None
    end = min(end, size - 1)
    if start > end or start >= size:
        return None
    return start, end


class Handler(http.server.SimpleHTTPRequestHandler):
    # 1.1 keeps the connection alive between range requests while seeking.
    protocol_version = "HTTP/1.1"
    paths = []
    out_dir = None

    def do_POST(self):
        if self.path.split("?")[0] == "/play":
            return self.play()
        return self.reply(404, {"error": "not found"})

    def do_GET(self):
        if self.path.split("?")[0] == "/audio":
            return self.audio()
        return super().do_GET()

    def track_path(self):
        """The file for ?i=<n>, or None. Row numbers only, never a path."""
        query = urllib.parse.urlparse(self.path).query
        raw = urllib.parse.parse_qs(query).get("i", [""])[0]
        try:
            index = int(raw)
        except ValueError:
            return None
        if not 0 <= index < len(self.paths):
            return None
        path = self.paths[index]
        return path if path and os.path.isfile(path) else None

    def audio(self):
        path = self.track_path()
        if not path:
            return self.reply(404, {"error": "no such track"})

        size = os.path.getsize(path)
        ctype = MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        span = parse_range(self.headers.get("Range"), size)

        if self.headers.get("Range") and span is None:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return

        start, end = span if span else (0, size - 1)
        self.send_response(206 if span else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if span:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        if self.command == "HEAD":
            return
        remaining = end - start + 1
        with open(path, "rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(CHUNK_BYTES, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return          # the element seeked away or the tab closed
                remaining -= len(chunk)

    def reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def play(self):
        if not self.paths:
            return self.reply(503, {"error": "paths.json was not loaded"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            indices = body["indices"]
            name = str(body.get("name", "playlist"))
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {"error": "expected {name, indices}"})

        if not isinstance(indices, list) or not indices:
            return self.reply(400, {"error": "no tracks to play"})
        # Row numbers only: anything outside the pool is refused outright, so a
        # crafted request cannot name a file of its own.
        if not all(isinstance(i, int) and 0 <= i < len(self.paths) for i in indices):
            return self.reply(400, {"error": "track index out of range"})

        vlc = shutil.which("vlc")
        if not vlc:
            return self.reply(500, {"error": "vlc is not installed"})

        target = os.path.join(self.out_dir, "_now_playing.m3u8")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("#EXTM3U\n#PLAYLIST:" + name.replace("\n", " ") + "\n")
            for i in indices:
                fh.write(self.paths[i] + "\n")

        subprocess.Popen([vlc, "--", target],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self.reply(200, {"ok": True, "playing": name, "tracks": len(indices)})

    def log_message(self, fmt, *args):
        # send_error passes an HTTPStatus here, not a string, so coerce before
        # matching -- otherwise every 404 dies inside the logger.
        if args and "/play" in str(args[0]):
            super().log_message(fmt, *args)


def main():
    # Either argument may be given alone: a bare number is a port, anything
    # else is a directory. Both fall back to config.toml.
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ports = [a for a in args if a.isdigit()]
    dirs = [a for a in args if not a.isdigit()]
    directory = dirs[0] if dirs else BROWSER_DIR
    wanted = int(ports[0]) if ports else PORT

    out = os.path.abspath(directory)
    Handler.out_dir = out
    paths_file = os.path.join(out, "paths.json")
    if os.path.isfile(paths_file):
        with open(paths_file, encoding="utf-8") as fh:
            Handler.paths = json.load(fh)

    # VLC is launched and never waited on; let the kernel reap it so repeated
    # clicks don't pile up zombie processes.
    if hasattr(signal, "SIGCHLD"):
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)

    port = first_free(wanted)
    if port != wanted:
        print(f"note: {wanted} was busy, using {port}")

    handler = functools.partial(Handler, directory=directory)
    # Threaded, or streaming one track would block the page that requested it.
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), handler) as srv:
        print(f"http://127.0.0.1:{port}/", flush=True)
        print(f"play endpoint knows {len(Handler.paths)} tracks", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()

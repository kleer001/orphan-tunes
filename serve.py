#!/usr/bin/env python3
"""Serve a directory over localhost, taking the first free port at or above 8000.

    python serve.py <directory> [port]

POST /play with {"name": ..., "indices": [...]} writes those tracks, in that
order, to _now_playing.m3u8 and hands it to VLC. The page sends row numbers
only; paths come from the server's own paths.json, so the endpoint cannot be
talked into opening a file that isn't in the library. Bound to 127.0.0.1 only.

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


def first_free(start, tries=50):
    for port in range(start, start + tries):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit(f"no free port in {start}..{start + tries}")


class Handler(http.server.SimpleHTTPRequestHandler):
    paths = []
    out_dir = None

    def do_POST(self):
        if self.path.split("?")[0] == "/play":
            return self.play()
        return self.reply(404, {"error": "not found"})

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
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    directory = args[0]
    wanted = int(args[1]) if len(args) > 1 else 8000

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
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as srv:
        print(f"http://127.0.0.1:{port}/", flush=True)
        print(f"play endpoint knows {len(Handler.paths)} tracks", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()

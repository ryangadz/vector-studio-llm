#!/usr/bin/env python3
"""vector-studio v0 server — stdlib only, no deps.

Serves this folder on http://127.0.0.1:8103 and gives viewer.html three
small APIs:

  GET  /api/list                 -> {"files": ["test/plate-v2-layout.svg", ...]}
  GET  /api/mtime?file=<rel.svg> -> {"mtime": ..., "pins_mtime": ...}
  GET  /api/pins?file=<rel.svg>  -> sidecar JSON ({} if none yet)
  POST /api/pins                 -> body {"file": <rel.svg>, "data": {...}}
                                    writes <file>.pins.json atomically
  POST /api/save                 -> body {"file": <rel.svg>, "svg": "<svg...>"}
                                    rewrites the drawing (sketch mode edits)
  POST /api/new                  -> body {"name": "kitchen", "w_mm": 400, "h_mm": 300}
                                    creates sketches/<name>.svg (blank, 2 px = 1 mm)

Run:  python serve.py            (root = this folder)
      python serve.py --root ..  (serve a different folder, e.g. repo root)
"""

import argparse
import json
import re
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HOST, PORT = "127.0.0.1", 8103
HERE = Path(__file__).resolve().parent
ROOT = HERE  # overridable via --root

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".claude"}


def safe_resolve(rel: str) -> Path | None:
    """Map a client-supplied relative path to a real file under ROOT, or None."""
    if not rel or "\x00" in rel:
        return None
    p = (ROOT / rel).resolve()
    if not p.is_relative_to(ROOT):
        return None
    return p


def list_svgs() -> list[str]:
    out = []
    for p in ROOT.rglob("*.svg"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p.relative_to(ROOT).as_posix())
    return sorted(out)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):  # keep the console quiet except errors
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            super().log_message(fmt, *args)

    def end_headers(self):
        # live-reload depends on nothing being cached
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/list":
            return self.send_json({"files": list_svgs()})
        if url.path in ("/api/mtime", "/api/pins"):
            rel = parse_qs(url.query).get("file", [""])[0]
            p = safe_resolve(rel)
            if p is None or p.suffix.lower() != ".svg" or not p.is_file():
                return self.send_json({"error": "no such svg"}, 404)
            if url.path == "/api/mtime":
                sc = p.with_name(p.name + ".pins.json")
                return self.send_json({
                    "mtime": p.stat().st_mtime,
                    "pins_mtime": sc.stat().st_mtime if sc.is_file() else 0,
                })
            sidecar = p.with_name(p.name + ".pins.json")
            if sidecar.is_file():
                try:
                    return self.send_json(json.loads(sidecar.read_text("utf-8")))
                except (json.JSONDecodeError, OSError):
                    return self.send_json({"error": "sidecar unreadable"}, 500)
            return self.send_json({})
        if url.path == "/":
            self.send_response(302)
            self.send_header("Location", "/viewer.html")
            self.end_headers()
            return
        if url.path == "/viewer.html" and not (ROOT / "viewer.html").is_file():
            # --root pointed elsewhere; the viewer still lives next to serve.py
            body = (HERE / "viewer.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            return self.send_json({"error": "bad request"}, 400)

        if url.path == "/api/new":
            name = str(payload.get("name", ""))
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,60}", name):
                return self.send_json({"error": "name: letters/digits/dash/underscore only"}, 400)
            try:
                w = min(max(float(payload.get("w_mm", 400)), 10), 10000)
                h = min(max(float(payload.get("h_mm", 300)), 10), 10000)
            except (TypeError, ValueError):
                return self.send_json({"error": "bad size"}, 400)
            wu, hu = int(w * 2), int(h * 2)  # 2 px = 1 mm
            d = ROOT / "sketches"
            d.mkdir(exist_ok=True)
            p = d / (name + ".svg")
            rel = p.relative_to(ROOT).as_posix()
            if p.exists():
                return self.send_json({"ok": True, "file": rel, "existed": True})
            p.write_text(
                f'<svg viewBox="0 0 {wu} {hu}" xmlns="http://www.w3.org/2000/svg">\n'
                f'  <!-- vector-studio sketch · 2 px = 1 mm · {w:g} x {h:g} mm · dark ground, white lines -->\n'
                f'  <rect data-vs-bg="1" width="{wu}" height="{hu}" fill="#1A1916"/>\n'
                f'</svg>\n', "utf-8")
            return self.send_json({"ok": True, "file": rel, "existed": False})

        if url.path == "/api/save":
            rel, svg = payload.get("file"), payload.get("svg")
            p = safe_resolve(rel or "")
            if p is None or p.suffix.lower() != ".svg" or not p.is_file():
                return self.send_json({"error": "no such svg"}, 404)
            if not isinstance(svg, str) or "<svg" not in svg[:500]:
                return self.send_json({"error": "not svg content"}, 400)
            tmp = p.with_suffix(".svg.tmp")
            tmp.write_text(svg if svg.endswith("\n") else svg + "\n", "utf-8")
            tmp.replace(p)  # atomic on the same volume
            return self.send_json({"ok": True, "mtime": p.stat().st_mtime})

        if url.path == "/api/pins":
            try:
                rel, data = payload["file"], payload["data"]
            except (KeyError, TypeError):
                return self.send_json({"error": "bad request"}, 400)
            p = safe_resolve(rel)
            if p is None or p.suffix.lower() != ".svg" or not p.is_file():
                return self.send_json({"error": "no such svg"}, 404)
            data["file"] = rel
            data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            sidecar = p.with_name(p.name + ".pins.json")
            tmp = sidecar.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
            tmp.replace(sidecar)  # atomic on the same volume
            return self.send_json({"ok": True, "pins_mtime": sidecar.stat().st_mtime,
                                   "sidecar": sidecar.relative_to(ROOT).as_posix()})

        return self.send_json({"error": "not found"}, 404)


def main():
    global ROOT
    ap = argparse.ArgumentParser(description="vector-studio v0 server")
    ap.add_argument("--root", default=None, help="folder to serve (default: this folder)")
    args = ap.parse_args()
    if args.root:
        ROOT = Path(args.root).resolve()
    print(f"vector-studio v0 · http://{HOST}:{PORT}/viewer.html · root {ROOT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

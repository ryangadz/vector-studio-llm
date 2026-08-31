#!/usr/bin/env python3
"""MCP process manager for the vector-studio viewer.

Claude Desktop / Claude Code launches this automatically (declared in the
plugin's .mcp.json) and sessions call its tools, so starting the viewer is
a normal tool-permission prompt instead of needing shell access:

    viewer_status(port?)        is the viewer answering on that port?
    start_viewer(root, port?)   spawn serve.py --root <root>, detached
    stop_viewer(port?)          stop a viewer this manager started

This is a process manager and nothing more - editing stays on the
filesystem (SVG + pins sidecar), exactly as the README says. No
dependencies: JSON-RPC 2.0 over stdio, one message per line.
"""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent.parent  # plugin root == repo root
SERVE = TOOL_ROOT / "serve.py"
DEFAULT_PORT = 8103
# Pidfile lives in the user's home, not the plugin folder - plugin updates
# replace the plugin folder and would orphan the pid.
PIDFILE = Path.home() / ".vector-studio-viewer.json"


def alive(port):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=1.5)
        return True
    except urllib.error.HTTPError:
        return True  # an HTTP error is still an answer - something is serving
    except Exception:
        return False


def my_version():
    try:
        return json.loads((TOOL_ROOT / ".claude-plugin" / "plugin.json")
                          .read_text("utf-8"))["version"]
    except Exception:
        return "unknown"


def served_version(port):
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/version" % port, timeout=1.5) as r:
            return json.loads(r.read().decode())["version"]
    except Exception:
        return None  # pre-0.3.4 server, or not a vector-studio server


def ver_tuple(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return None


def read_pids():
    try:
        return {int(k): v for k, v in json.loads(PIDFILE.read_text()).items()}
    except Exception:
        return {}


def write_pids(pids):
    try:
        PIDFILE.write_text(json.dumps({str(k): v for k, v in pids.items()}))
    except Exception:
        pass  # tracking is best-effort; status/start still work without it


def viewer_status(args):
    port = int(args.get("port") or DEFAULT_PORT)
    if alive(port):
        root = read_pids().get(port, {}).get("root")
        where = " serving %s" % root if root else ""
        mine, served = my_version(), served_version(port)
        if served != mine:
            sv, mv = ver_tuple(served or ""), ver_tuple(mine)
            if served is not None and sv and mv and sv > mv:
                return ("Viewer is running at http://127.0.0.1:%d%s and is a "
                        "NEWER build (%s) than this session's plugin snapshot "
                        "(%s) - leave it running." % (port, where, served, mine))
            return ("Viewer is running at http://127.0.0.1:%d%s BUT it's an "
                    "older build (%s; this plugin is %s). Ask the user first "
                    "- they may be mid-sketch - then stop_viewer + "
                    "start_viewer with the same root to pick up the update."
                    % (port, where, served or "pre-0.3.4, no version endpoint",
                       mine))
        return "Viewer is running at http://127.0.0.1:%d%s (v%s, current)" % (
            port, where, mine)
    return ("No viewer on port %d. Use start_viewer with root = the folder "
            "of the user's sketches (ask them which folder if unclear)." % port)


def start_viewer(args):
    root = args.get("root")
    port = int(args.get("port") or DEFAULT_PORT)
    if not root:
        return "root is required: the folder of SVG sketches to serve."
    root_path = Path(root).expanduser()
    if not root_path.is_dir():
        return "Not a folder: %s" % root
    if alive(port):
        return ("A viewer already answers on port %d - not starting a second "
                "copy. Use another --port for a second project." % port)
    cmd = [sys.executable, str(SERVE), "--root", str(root_path),
           "--port", str(port)]
    kwargs = dict(cwd=str(TOOL_ROOT), stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000208  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    deadline = time.time() + 6
    while time.time() < deadline:
        if alive(port):
            pids = read_pids()
            pids[port] = {"pid": proc.pid, "root": str(root_path)}
            write_pids(pids)
            return ("Viewer running at http://127.0.0.1:%d serving %s - "
                    "tell the user the URL." % (port, root_path))
        if proc.poll() is not None:
            return ("serve.py exited immediately (code %s). Check that "
                    "Python can run %s." % (proc.returncode, SERVE))
        time.sleep(0.25)
    proc.terminate()
    return "Viewer did not answer on port %d within 6s; gave up." % port


def stop_viewer(args):
    port = int(args.get("port") or DEFAULT_PORT)
    if not alive(port):
        return "Nothing is running on port %d." % port
    entry = read_pids().get(port)
    if not entry:
        return ("A viewer answers on port %d but this manager didn't start "
                "it, so it won't kill it. The user can close it themselves." % port)
    try:
        os.kill(entry["pid"], signal.SIGTERM)
    except OSError as e:
        return "Could not stop pid %s: %s" % (entry["pid"], e)
    time.sleep(0.5)
    pids = read_pids()
    pids.pop(port, None)
    write_pids(pids)
    return ("Stopped." if not alive(port)
            else "Sent stop to pid %s but port %d still answers." % (entry["pid"], port))


TOOLS = [
    {
        "name": "viewer_status",
        "description": ("Check whether the vector-studio viewer is running "
                        "(http://127.0.0.1:<port>). Call this first whenever "
                        "the vector-studio skill is invoked."),
        "inputSchema": {"type": "object", "properties": {
            "port": {"type": "integer",
                     "description": "Port to check (default 8103)."}}},
    },
    {
        "name": "start_viewer",
        "description": ("Start the vector-studio viewer: serves the given "
                        "sketch folder in the user's browser. root = the "
                        "folder holding the user's SVG sketches - their "
                        "call; ask which folder if unclear."),
        "inputSchema": {"type": "object", "properties": {
            "root": {"type": "string",
                     "description": "Folder of sketches to serve."},
            "port": {"type": "integer",
                     "description": "Port to listen on (default 8103)."}},
            "required": ["root"]},
    },
    {
        "name": "stop_viewer",
        "description": ("Stop a viewer this manager started. Only when the "
                        "user asks - never tidy up unprompted."),
        "inputSchema": {"type": "object", "properties": {
            "port": {"type": "integer",
                     "description": "Port of the viewer (default 8103)."}}},
    },
]

DISPATCH = {"viewer_status": viewer_status, "start_viewer": start_viewer,
            "stop_viewer": stop_viewer}


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        mid, method = req.get("id"), req.get("method")
        params = req.get("params") or {}
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "vector-studio-viewer",
                               "version": my_version()}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            fn = DISPATCH.get(params.get("name"))
            if fn is None:
                text, is_err = "Unknown tool: %s" % params.get("name"), True
            else:
                try:
                    text, is_err = fn(params.get("arguments") or {}), False
                except Exception as e:
                    text, is_err = "%s: %s" % (type(e).__name__, e), True
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_err}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32601, "message": "unknown method: %s" % method}})


if __name__ == "__main__":
    main()

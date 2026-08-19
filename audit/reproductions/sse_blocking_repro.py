"""
Pass 14 (Performance) repro: does web_app.py's `/api/stream` SSE endpoint
(time.sleep(10) inside an infinite generator loop, per web_app.py ~L358-384)
block ALL other HTTP requests to the dashboard, given that `start_web()`
calls `_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)`
(web_app.py L3323) WITHOUT passing threaded=True or processes=N?

This launches the real web_app._build_app(None) app (paper-mode, no live
client) via werkzeug's dev server with THE EXACT SAME run() kwargs used in
production (no threaded=, no processes=), on a background thread, then:
  1. opens a streaming GET to /api/stream and reads the first SSE chunk
     (confirms the connection is live and the generator has started its
     first `time.sleep(10)`)
  2. immediately (while still connected to /api/stream, mid-sleep) fires a
     plain GET to /api/status from a second thread and times how long it
     takes to get a response.

If the dev server is truly single-threaded/single-process, the /api/status
request will not complete until the SSE generator wakes up from sleep,
finishes 10s later, loops, and (since the WSGI callable never returns for a
streaming response) hangs the request queue for as long as the SSE
connection is alive -- i.e. this script's /api/status call should take
~10s+ (or hang until the SSE client disconnects), not the <50ms a healthy
concurrent server would take.

Read-only local-only test: binds 127.0.0.1, no live Kalshi credentials
used (client=None -> paper/read-only mode), no orders, no writes outside
this process's memory.
"""
import sys
import threading
import time

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

import web_app  # noqa: E402

PORT = 58432

app = web_app._build_app(None)
if app is None:
    print("FAILED: _build_app(None) returned None -- cannot run repro")
    sys.exit(1)

import utils as _dbg_utils
print("DEBUG utils.DASHBOARD_PASSWORD repr:", repr(_dbg_utils.DASHBOARD_PASSWORD))
import os as _dbg_os
print("DEBUG os.environ DASHBOARD_PASSWORD set:", "DASHBOARD_PASSWORD" in _dbg_os.environ)

server_thread = threading.Thread(
    target=lambda: app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False),
    daemon=True,
)
server_thread.start()
time.sleep(1.5)  # let the dev server bind

import urllib.request

results = {}


def open_sse():
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/stream")
        resp = urllib.request.urlopen(req, timeout=30)
        chunk = resp.read(200)  # read the first SSE event
        results["sse_first_chunk_s"] = time.perf_counter() - t0
        results["sse_chunk"] = chunk[:120]
        # keep the connection open for 12s (longer than the server's 10s
        # sleep-per-iteration) by reading a bit more, simulating a real
        # browser tab that stays connected
        try:
            resp.read(50)
        except Exception:
            pass
    except Exception as e:
        results["sse_error"] = repr(e)


def hit_status_while_sse_open():
    time.sleep(2.0)  # let the SSE connection establish + enter its sleep(10)
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/status")
        resp = urllib.request.urlopen(req, timeout=20)
        resp.read()
        results["status_latency_s"] = time.perf_counter() - t0
    except Exception as e:
        results["status_error"] = repr(e)
        results["status_latency_s"] = time.perf_counter() - t0


t_sse = threading.Thread(target=open_sse, daemon=True)
t_status = threading.Thread(target=hit_status_while_sse_open, daemon=True)
t_sse.start()
t_status.start()
t_sse.join(timeout=25)
t_status.join(timeout=25)

print("RESULTS:", results)
if "status_latency_s" in results:
    lat = results["status_latency_s"]
    print(f"\n/api/status latency while /api/stream SSE connection is open+sleeping: {lat:.2f}s")
    if lat > 3.0:
        print("CONFIRMED: dev server appears single-threaded -- /api/status was blocked "
              "for multiple seconds by the concurrently-open SSE stream's time.sleep(10).")
    else:
        print("NOT CONFIRMED at this latency threshold -- server may be threaded after all "
              "(check werkzeug version defaults).")

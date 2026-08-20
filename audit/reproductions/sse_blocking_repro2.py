"""
Pass 14 (Performance) repro v2 -- cleaner test of whether web_app.py's dev
server (run via the exact production kwargs: no threaded=, no processes=)
blocks concurrent requests while an /api/stream SSE connection is open and
sleeping.

Keeps ONE /api/stream connection open continuously in a background thread
(reading data as it trickles in, never closing it) while firing 8x
/api/status requests spaced 1s apart from the main thread, recording each
one's latency. If the server serializes all request handling behind the
long-lived SSE connection, we'd expect /api/status latencies to spike to
multiple seconds (waiting for the SSE generator's current sleep/iteration
to yield control back to the accept loop) rather than staying uniformly
fast (<100ms, typical for a localhost Flask route with no real I/O).
"""
import sys
import threading
import time

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

import utils  # noqa: E402

print("BEFORE utils.DASHBOARD_PASSWORD:", repr(utils.DASHBOARD_PASSWORD))
utils.DASHBOARD_PASSWORD = ""  # force-disable auth for this repro, regardless of source
import web_app  # noqa: E402

PORT = 58433
app = web_app._build_app(None)
if app is None:
    print("FAILED: _build_app(None) returned None")
    sys.exit(1)
print("AFTER utils.DASHBOARD_PASSWORD:", repr(utils.DASHBOARD_PASSWORD))

server_thread = threading.Thread(
    target=lambda: app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False),
    daemon=True,
)
server_thread.start()
time.sleep(1.5)

import urllib.request  # noqa: E402

sse_open_evt = threading.Event()
sse_stop = threading.Event()


def keep_sse_open():
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/stream")
        resp = urllib.request.urlopen(req, timeout=60)
        sse_open_evt.set()
        while not sse_stop.is_set():
            chunk = resp.read(1)
            if not chunk:
                break
    except Exception as e:
        print("SSE thread error:", e)
        sse_open_evt.set()  # unblock main thread even on failure


t_sse = threading.Thread(target=keep_sse_open, daemon=True)
t_sse.start()
sse_open_evt.wait(timeout=10)
print(f"SSE connection established: {sse_open_evt.is_set()}")

latencies = []
for i in range(8):
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/status")
        resp = urllib.request.urlopen(req, timeout=20)
        resp.read()
        lat = time.perf_counter() - t0
    except Exception as e:
        lat = time.perf_counter() - t0
        print(f"  request {i} error: {e}")
    latencies.append(lat)
    print(f"  /api/status request {i} (t={i}s): {lat*1000:.1f}ms")
    time.sleep(1.0)

sse_stop.set()
print("\nAll latencies (ms):", [round(x * 1000, 1) for x in latencies])
print("Max latency (ms):", round(max(latencies) * 1000, 1))
print("Mean latency (ms):", round(sum(latencies) / len(latencies) * 1000, 1))
if max(latencies) > 2.0:
    print("CONFIRMED: at least one /api/status request was significantly delayed "
          "(>2s) while the SSE connection was open -- consistent with a "
          "single-threaded dev server serializing requests behind the SSE stream.")
else:
    print("NOT CONFIRMED: /api/status stayed fast throughout -- server appears to "
          "service requests concurrently despite threaded= not being passed "
          "(needs further investigation into werkzeug's actual behavior here).")

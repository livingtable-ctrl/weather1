import os
import sys

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

# Simulate a fresh .env.example checkout: no DASHBOARD_PASSWORD, no DASHBOARD_UNPROTECTED
os.environ.pop("DASHBOARD_PASSWORD", None)
os.environ.pop("DASHBOARD_UNPROTECTED", None)

import web_app


class DummyClient:
    base_url = "https://demo-api.kalshi.co"

try:
    app = web_app._build_app(DummyClient())
    print("NO EXCEPTION RAISED -- app object:", app)
except RuntimeError as e:
    print("RuntimeError raised as predicted:", e)
except Exception as e:
    print("Different exception:", type(e), e)

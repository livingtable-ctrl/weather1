# Pass 13 — Security: Independent verification notes

All 6 findings independently re-derived from current source (not trusted from the original claim text).

1. Exposure-cap / VaR blindness to execution_log live positions — CONFIRMED.
   - paper.py:1298-1300 `get_open_trades()` reads only `_load()["trades"]` (paper_trades.json).
   - get_city_date_exposure/get_directional_exposure/get_total_exposure/get_correlated_exposure/
     portfolio_kelly_fraction (paper.py ~1598-1760) all call get_open_trades(), no execution_log import anywhere in paper.py.
   - order_executor.py:2364 seeds `_open_trades_list = get_open_trades()` once per cycle; :2930 feeds it into
     `portfolio_var()`; in-cycle live fills are appended in-memory only (order_executor.py:3042 comment "F6", :3122).
     Nothing persists this list or re-seeds it from execution_log on the next cycle.
   - Confirmed sibling fix exists only for MAX_DAILY_SPEND: order_executor.py:1595-1602 explicitly comments that
     `_daily_paper_spend`/`_daily_sameday_spend` are blind to live orders and routes that one check through
     `execution_log.get_today_live_spend()` — Kelly-scaling/VaR caps were NOT given the same fix.

2. Stale prod-mode banner (main.py) — CONFIRMED.
   - main.py:9567 `_live_orders_possible = cmd == "watch" and "--auto" in args and "--live" in args`.
   - main.py:4528 `cmd_order`'s own live-ness check: `_is_live = getattr(client, "base_url", None) != DEMO_BASE`,
     independent of any flag; main.py:4531-ish gates via `pre_live_trade_check(client)`.
   - main.py dispatch: `elif cmd in ("buy", "sell"): cmd_order(client, cmd, args[1:])` — confirms buy/sell reach
     cmd_order directly, bypassing the banner's hardcoded `cmd == "watch"` check.

3. tracker.count_settled_signal_rows f-string SQL construction — CONFIRMED, exploitability unchanged (LOW).
   - tracker.py:2727-2738 interpolates `json_key`/`column`/`table` directly into SQL text via f-strings.
   - All call sites are hardcoded string literals: weather_markets.py's `_count_signal_column`/`_count_signal_json_key`
     closures (weather_markets.py:6946-7088) and tests/test_tracker.py — no external/config/request-derived value
     reaches this function anywhere in the repo today.

4. .env.example DASHBOARD_PASSWORD comment vs. web_app.py fail-closed behavior — CONFIRMED.
   - .env.example:45-47 "Leave empty to disable auth (default for local use)".
   - web_app.py:153-164: empty DASHBOARD_PASSWORD + no DASHBOARD_UNPROTECTED=true raises RuntimeError at startup.

5. Two orphaned @_require_auth decorators despite WA-16 comment — CONFIRMED.
   - web_app.py:169-171 comment claims all route-level decorators were removed.
   - web_app.py:1910-1911 (`api_emos_status`) and :1951-1952 (`api_weather_alerts`) still carry `@_require_auth`.
   - Functionally harmless: `before_request`/`_check_auth` (web_app.py:165-166) runs unconditionally first.

6. Unvalidated ticker into Kalshi URL path — CONFIRMED as theoretical/low, could not test exploitability.
   - kalshi_client.py:339-341 `get_market()` → `self._get(f"/markets/{ticker}", ...)`; `_get` (kalshi_client.py:266-268)
     does `url = self.base_url + path` with no format check.
   - web_app.py:2684 `ticker = body.get("ticker", "").strip()` has no regex/allowlist before reaching
     `_kc.get_market(ticker)` at web_app.py:2787.
   - base_url is a hardcoded constant (kalshi_client.py:186-187, PROD_BASE/DEMO_BASE) — confirms original finding's
     "no SSRF" reasoning (base host not attacker-influenced) and that /api/paper-order is behind before_request auth.
   - Not runtime-tested (no live credentials in this worktree); severity/confidence as originally assessed is reasonable.

No files modified outside audit/. No live/network calls made.

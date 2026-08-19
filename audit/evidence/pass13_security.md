# Pass 13 — Security audit evidence

Scope: trust boundaries, authn/authz, secrets handling, env vars, logging,
injection, unsafe deserialization, SSRF, path traversal, external request
construction, permission boundaries, unsafe defaults. Focus commits: CSRF/auth
dedupe (0edf818b), kalshi_client.py, config.py, paths.py routing changes, plus
broader repo per SCOPE D.

## Areas checked clean (no finding)

- web_app.py auth (`_check_auth`/`_require_auth`): HMAC `compare_digest` on
  password comparison (bytes-encoded to dodge non-ASCII TypeError), CSRF via
  `X-Requested-With` required for all non-GET/HEAD/OPTIONS state-changing
  routes, bound to `127.0.0.1` only, `debug=False`, no CORS headers set (so a
  cross-origin browser can't read GET responses even blind). Verified every
  `@app.route(..., methods=["POST"|"DELETE"])` in web_app.py's before_request
  path is subject to the CSRF check.
- Frontend CSRF coverage (0edf818b fix): grepped every `fetch(...)` call
  across `frontend/src/` and `weather app site V_3 (3)/src/` for the 8
  state-changing endpoints (`/api/close-position`, `/api/paper-order`,
  `/api/override` POST/DELETE, `/api/halt`, `/api/resume`, `/api/run_cron`,
  `/api/cancel-cron`) — all pass `...authHeader()` / `headers: authHeader()`.
  No CSRF gap remains in either tree.
- No `dangerouslySetInnerHTML`, `eval(`, or `new Function(` in either frontend
  tree — Kalshi-sourced ticker/title/city text can't reach raw DOM injection.
- web_app.py's raw-HTML routes (`/analyze`, `/trades`, error paths) escape all
  Kalshi-controlled dynamic text via `markupsafe.escape` and deliberately
  avoid `render_template_string` on external data (explicit WA-security
  comments citing an SSTI concern) — checked every `<td>{...}</td>` and
  found no unescaped injection of externally-sourced strings.
- kalshi_client.py: RSA-PSS request signing, Windows icacls / Unix chmod
  warnings on the private key file, no secrets in log statements, `PROD_BASE`/
  `DEMO_BASE` are fixed constants, idempotency keys via SHA-256 (no secret
  material in the hash input).
- config.py / paths.py: all secret-bearing env vars default to `""` (fail
  closed, not fail open); `paths.py` builds every data path from fixed
  literals (no user input reaches a path join) — no path traversal surface.
- ml_bias.py bias-model pickle load: HMAC-SHA256-gated (`MODEL_HMAC_SECRET`)
  before `pickle.loads`, fails closed (returns `{}`) on missing secret,
  missing sidecar, or HMAC mismatch — the RCE-via-pickle vector is already
  mitigated. Only `pickle.` usage in the whole repo (grepped).
- No `eval(`/`exec(`/`os.system(` with non-literal input anywhere in the repo
  (one `os.system("cls"/"clear")` with a hardcoded literal).
  `subprocess.run(..., shell=True)` in `cmd_schedule` builds its command only
  from `sys.executable`/`Path(__file__)` — no external input.
  `subprocess.Popen` in `/api/run_cron` uses an argv list, no `shell=True`.
- SQL: swept execution_log.py and tracker.py for f-string-built queries;
  all found interpolations are either literal/internal values (schema
  version int, table name toggling between two hardcoded literals, a 0/1
  live flag) or fully parameterized with `?` placeholders. One exception
  logged below (tracker.py `count_settled_signal_rows`).
- Confirmed the `admin accuracy-override` mechanism (251e838e) is isolated
  via its own `_ACCURACY_HALT_OVERRIDE_PATH` sentinel file and cannot reach
  `is_paused_drawdown()`/kill-switch — asymmetry claimed in the commit
  message verified true in code, not just docstring.
- Secret scan of all `.py`/`.js`/`.jsx` diffs since 2026-08-02 for AWS-key /
  PEM-header / hardcoded-api-key patterns: no hits.

## Findings

See structured output. Summary:
1. Exposure-cap subsystem (`paper.get_total_exposure`/`get_city_date_exposure`/
   `get_directional_exposure`/`get_correlated_exposure`/`portfolio_kelly_fraction`,
   and `monte_carlo.portfolio_var` via `order_executor`'s `_open_trades_list`)
   is sourced exclusively from `paper.get_open_trades()` → `paper_trades.json`.
   Live positions recorded in `execution_log.db` (both `cmd_order`-placed,
   confirmed by e5331a8d, and cron-automated live fills from a prior cycle)
   are invisible to these caps beyond the cycle they were placed in. The
   coarse `MAX_DAILY_SPEND` cap was independently patched to read
   `execution_log.get_today_live_spend()` (order_executor.py:1595-1602,
   with an explicit code comment describing this exact blindness), but the
   Kelly-scaling city/date/directional/correlated/global-fraction caps and
   the VaR gate were not given the same fix.
2. Prod-mode startup banner (main.py:9558-9584) unconditionally claims "only
   `watch --auto --live` can [place live orders]" whenever the *displayed*
   command isn't `watch --auto --live`, but `cmd_order` (`buy`/`sell`, called
   from main.py:9696-9697) independently determines live-ness from
   `client.base_url != DEMO_BASE` (main.py:4528) and proceeds through
   `pre_live_trade_check` with no `--live` flag requirement at all.
3. `tracker.count_settled_signal_rows()` (tracker.py:2724-2742) builds SQL via
   f-string interpolation of `column`/`json_key` parameters rather than
   parameterized placeholders. Every current call site passes a hardcoded
   literal (verified via grep), so not exploitable today — logged as a
   defense-in-depth pattern gap.
4. `.env.example`'s comment for `DASHBOARD_PASSWORD` ("Leave empty to disable
   auth (default for local use)") no longer matches `_build_app()`'s actual
   enforcement, which raises `RuntimeError` unless `DASHBOARD_UNPROTECTED=true`
   is also set explicitly. Code is stricter than the doc, so not a security
   regression, but a stale/misleading comment.
5. Two `@_require_auth` route decorators remain (web_app.py:1911, 1952)
   despite a `before_request` comment stating "Route-level @_require_auth
   decorators were removed (WA-16)" — harmless (before_request already
   covers them) but a minor code/comment drift.
6. Kalshi API `ticker` values flow unvalidated into URL path segments
   (`kalshi_client.py` `f"/markets/{ticker}"` etc.), reachable from
   `/api/paper-order`'s JSON body. Theoretical path-segment concern only —
   no SSRF (base URL fixed to Kalshi's own host), same-privilege (operator's
   own signed request), and no live environment available this session to
   test any real effect.

No repro scripts were needed for findings 1-6 — grounded in direct code
reading (E1). No `.env`/credentials exist in this worktree so no live-request
testing (E2/E3) against the real Kalshi API was possible or attempted,
consistent with the read-only audit constraints.

## Session 2 addendum (re-verification + new finding)

Re-verified findings 1-6 above against current source this session (all still
accurate — grep/read confirmed: paper.py exposure functions all source
`get_open_trades()`/`paper_trades.json` only, `order_executor.py:1602` is the
sole live-spend-aware cap via `execution_log.get_today_live_spend()`; main.py
banner at L9558-9584 unchanged, blame shows it predates the audit window
(2026-06-29, `69fd66a10`) and was NOT touched by `e5331a8d` despite that
commit rewriting the exact cmd_order live-fill path the banner describes;
`.env.example:47` comment unchanged; duplicate `@_require_auth` decorators
confirmed still present at web_app.py:1911 (`api_emos_status`) and 1952
(`api_weather_alerts`); frontend CSRF header coverage re-confirmed via grep
across all `fetch(...)` call sites in `frontend/src/`).

7. **NEW — `KalshiClient.__init__`'s env comparison fails open to PROD_BASE
   for any non-exact-match `env` string** (kalshi_client.py:217):
   `self.base_url = DEMO_BASE if env == "demo" else PROD_BASE`. Demonstrated
   this session by actually running it (E2):
   ```
   py -c "from kalshi_client import KalshiClient, PROD_BASE
   for env in ['demo','Demo','DEMO',' demo','demo ','sandbox','test','prod']:
       c = KalshiClient(env=env)
       print(env, '->', 'PROD' if c.base_url==PROD_BASE else 'DEMO')"
   ```
   Result: only the exact literal `'demo'` produces `DEMO_BASE`; every other
   value tested (`'Demo'`, `'DEMO'`, `' demo'`, `'demo '`, `'sandbox'`,
   `'test'`, `'prod'`, `'production'`) produces `PROD_BASE`. `main._kalshi_env()`
   passes `os.getenv("KALSHI_ENV", "demo")` straight through with no
   normalization or validation (main.py:486-488, 1037), and `config.py:272`
   likewise stores the raw string unchecked — `BotConfig.validate()` never
   whitelists `kalshi_env` to `{"demo","prod"}`.
   Consequence chain: `main.py:4528` derives `_is_live = client.base_url !=
   DEMO_BASE`, so any KALSHI_ENV typo/case/whitespace variant makes the bot
   consider itself live. `trading_gates.LiveTradingGate.check()` (called with
   `client`) then trusts `client.base_url == PROD_BASE` as its sole "are we
   really in prod" signal (trading_gates.py:51-56) — deliberately, per its own
   docstring, to avoid a second `import main` reading a diverged env value —
   and does NOT independently cross-check the raw `KALSHI_ENV` string against
   `"prod"` when a client is passed (that literal-match check only runs in the
   `client is None` fallback branch, trading_gates.py:57-64). So this one
   fail-open comparison is the *entire* prod-detection ground truth for every
   real call site (`build_client()` always passes a client). The remaining
   interlocks (`LIVE_TRADING_ENABLED=="true"` exact-match, drawdown/streak/
   daily-loss/accuracy/graduation checks) are unaffected by this bug and would
   still need to independently pass for an actual live order to fire — this
   is a fail-open *classification* bug (demo intent silently becomes prod
   classification), not a bypass of the other interlocks.
   This is old code (`git blame`: kalshi_client.py:217 dates to `d7b2ad7e`,
   2026-04-09 — well before the audit's 2026-08-02 window) untouched by any
   of the 53 scoped commits, but it is the exact `base_url` value that
   Cluster D's `e5331a8d` (2026-08-17) newly made `_is_live`-determinative for
   `cmd_order`'s live-fill routing, and that `trading_gates.py`'s own docstring
   (updated 2026-07-09 per its comment) explicitly chose to trust as sole
   ground truth. Every other `env == "prod"`/`_kalshi_env() == "prod"` string
   comparison found elsewhere in the repo (main.py:493, 9424, 9562;
   trading_gates.py:63) correctly requires an *exact* `"prod"` match and thus
   fails closed (toward demo) on any typo — `kalshi_client.py:217` is the one
   comparison in the whole codebase that inverts this and fails open (toward
   prod) instead.

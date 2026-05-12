// static/signals.js
(function () {
  'use strict';

  var _log = [];
  var _liveSignals = [];

  // ── Live signals ────────────────────────────────────────────────────────────

  function loadLiveSignals() {
    fetch('/api/live_signals')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        _liveSignals = (d.signals || []).sort(function (a, b) {
          return Math.min(Math.abs(b.edge_pct), 500) - Math.min(Math.abs(a.edge_pct), 500);
        });
        renderSummary(d.summary || {}, d.generated_at || '');
        populateCityFilter(_liveSignals);
        renderLiveSignals(_liveSignals);
      })
      .catch(function (err) { console.error('live_signals fetch failed:', err); });
  }

  function renderSummary(s, ts) {
    setText('sum-scanned', s.scanned != null ? s.scanned : '—');
    setText('sum-edge',    s.with_edge != null ? s.with_edge : '—');
    setText('sum-strong',  s.strong != null ? s.strong : '—');
    setText('sum-lowrisk', s.low_risk != null ? s.low_risk : '—');
    var tsEl = document.getElementById('sum-ts');
    if (tsEl && ts) {
      var scanTime = new Date(ts + 'Z');
      var ageMs = Date.now() - scanTime.getTime();
      var ageMin = Math.round(ageMs / 60000);
      var timeStr = ts.slice(11, 19) + ' UTC';
      tsEl.textContent = timeStr;
      if (ageMs > 2 * 3600 * 1000) {
        tsEl.style.color = 'var(--neg)';
        tsEl.title = 'Stale — ' + ageMin + ' min ago. Run a scan to refresh.';
      } else if (ageMs > 3600 * 1000) {
        tsEl.style.color = 'var(--warn)';
        tsEl.title = ageMin + ' min ago';
      } else {
        tsEl.title = ageMin + ' min ago';
      }
    } else if (tsEl) {
      tsEl.textContent = '—';
    }
  }

  function setText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function populateCityFilter(signals) {
    var cities = Array.from(new Set(signals.map(function (s) { return s.city; }).filter(Boolean))).sort();
    var sel = document.getElementById('ls-filter-city');
    if (!sel) return;
    cities.forEach(function (c) {
      var o = document.createElement('option'); o.value = c; o.textContent = c;
      sel.appendChild(o);
    });
    sel.addEventListener('change', applyLiveFilters);
    document.getElementById('ls-filter-risk').addEventListener('change', applyLiveFilters);
    document.getElementById('ls-filter-strength').addEventListener('change', applyLiveFilters);
  }

  function applyLiveFilters() {
    var city = (document.getElementById('ls-filter-city') || {}).value || '';
    var risk = (document.getElementById('ls-filter-risk') || {}).value || '';
    var strength = (document.getElementById('ls-filter-strength') || {}).value || '';
    var filtered = _liveSignals.filter(function (s) {
      return (!city || s.city === city)
        && (!risk || s.time_risk === risk)
        && (!strength || s.signal.indexOf(strength) !== -1);
    });
    // Re-sort by capped edge so inflated low-price markets don't dominate
    filtered.sort(function (a, b) {
      return Math.min(Math.abs(b.edge_pct), 500) - Math.min(Math.abs(a.edge_pct), 500);
    });
    renderLiveSignals(filtered);
  }

  function renderLiveSignals(signals) {
    var el = document.getElementById('live-signals-table');
    if (!el) return;
    if (!signals.length) {
      el.innerHTML = '<p class="neu">No signals match filter.</p>';
      return;
    }

    var table = document.createElement('table');
    var thead = table.createTHead();
    thead.innerHTML = '<tr>'
      + '<th>Rating</th>'
      + '<th>City</th>'
      + '<th>Ticker</th>'
      + '<th>Side</th>'
      + '<th>Edge</th>'
      + '<th>We Think</th>'
      + '<th>Mkt Says</th>'
      + '<th>Risk</th>'
      + '<th>Flags</th>'
      + '<th>Kelly $</th>'
      + '</tr>';

    var tbody = table.createTBody();
    signals.forEach(function (s) {
      var row = tbody.insertRow();
      if (s.already_held) row.style.opacity = '0.5';

      // Rating stars
      var tdStars = row.insertCell();
      tdStars.textContent = s.stars || '—';
      tdStars.style.color = s.stars === '★★★' ? 'var(--pos)' : s.stars === '★★' ? 'var(--warn)' : 'var(--text-muted)';
      tdStars.style.letterSpacing = '2px';

      row.insertCell().textContent = s.city;

      var tdTicker = row.insertCell();
      tdTicker.textContent = s.ticker;
      tdTicker.style.fontSize = '0.8em';
      tdTicker.style.color = 'var(--text-muted)';

      // Side badge
      var tdSide = row.insertCell();
      var badge = document.createElement('span');
      badge.textContent = s.side;
      badge.className = s.side === 'YES' ? 'pos' : 'neg';
      badge.style.fontWeight = 'bold';
      tdSide.appendChild(badge);

      // Edge — cap display at ±500% to avoid misleading huge numbers from penny markets
      var tdEdge = row.insertCell();
      var displayEdge = Math.abs(s.edge_pct) > 500
        ? (s.edge_pct > 0 ? '>+500%' : '>-500%')
        : (s.edge_pct > 0 ? '+' : '') + s.edge_pct.toFixed(1) + '%';
      tdEdge.textContent = displayEdge;
      tdEdge.className = s.edge_pct > 0 ? 'pos' : 'neg';
      tdEdge.style.fontWeight = 'bold';
      if (Math.abs(s.edge_pct) > 500) tdEdge.title = 'Raw: ' + s.edge_pct.toFixed(0) + '%';

      row.insertCell().textContent = s.forecast_prob.toFixed(0) + '%';
      row.insertCell().textContent = s.market_prob.toFixed(0) + '%';

      // Time risk
      var tdRisk = row.insertCell();
      tdRisk.textContent = s.time_risk;
      tdRisk.className = s.time_risk === 'LOW' ? 'pos' : s.time_risk === 'MEDIUM' ? 'warn' : 'neg';

      // Flags: near_threshold and hedge indicators
      var tdFlags = row.insertCell();
      var flags = [];
      if (s.near_threshold) flags.push('<span title="Forecast within ±3°F of threshold — high flip risk, Kelly reduced 25%" style="color:var(--warn);cursor:default">⚠ threshold</span>');
      if (s.is_hedge) flags.push('<span title="This trade hedges an existing open position" style="color:var(--text-muted);cursor:default">↔ hedge</span>');
      tdFlags.innerHTML = flags.length ? flags.join(' ') : '<span style="color:var(--text-muted)">—</span>';

      // Kelly $
      var tdKelly = row.insertCell();
      tdKelly.textContent = s.kelly_dollars > 0 ? '$' + s.kelly_dollars.toFixed(2) : '—';
      tdKelly.style.color = 'var(--text-muted)';
    });

    el.innerHTML = '';
    el.appendChild(table);
  }

  // ── Cron log & alerts ───────────────────────────────────────────────────────

  function loadSignals() {
    fetch('/api/signals')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        renderAlerts(d.alerts || []);
        _log = d.log || [];
        populateFilters(_log);
        renderLog(_log);
      })
      .catch(function (err) { console.error('signals fetch failed:', err); });
  }

  function renderAlerts(alerts) {
    var el = document.getElementById('alert-feed');
    if (!el) return;
    if (!alerts.length) { el.innerHTML = '<p class="neu">No alerts.</p>'; return; }
    var table = document.createElement('table');
    var thead = table.createTHead();
    thead.innerHTML = '<tr><th>Time</th><th>Level</th><th>Message</th></tr>';
    var tbody = table.createTBody();
    alerts.slice().reverse().forEach(function (a) {
      var lvl = a.level || a.signal || '—';
      var lvlCls = lvl === 'ERROR' ? 'neg' : lvl === 'WARNING' ? 'warn' : 'neu';
      var row = tbody.insertRow();
      row.insertCell().textContent = (a.ts || '—').slice(0, 19);
      var td2 = row.insertCell(); td2.className = lvlCls; td2.textContent = lvl;
      row.insertCell().textContent = a.message || a.signal || '';
    });
    el.innerHTML = '';
    el.appendChild(table);
  }

  function populateFilters(log) {
    var signals = Array.from(new Set(log.map(function (e) { return e.signal || ''; }).filter(Boolean))).sort();
    var cities = Array.from(new Set(log.map(function (e) { return e.city || ''; }).filter(Boolean))).sort();

    var sigSel = document.getElementById('filter-signal');
    if (sigSel) {
      signals.forEach(function (s) {
        var o = document.createElement('option'); o.value = s; o.textContent = s;
        sigSel.appendChild(o);
      });
      sigSel.addEventListener('change', applyFilters);
    }
    var citySel = document.getElementById('filter-sig-city');
    if (citySel) {
      cities.forEach(function (c) {
        var o = document.createElement('option'); o.value = c; o.textContent = c;
        citySel.appendChild(o);
      });
      citySel.addEventListener('change', applyFilters);
    }
  }

  function applyFilters() {
    var sig = (document.getElementById('filter-signal') || {}).value || '';
    var city = (document.getElementById('filter-sig-city') || {}).value || '';
    var filtered = _log.filter(function (e) {
      return (!sig || e.signal === sig) && (!city || e.city === city);
    });
    renderLog(filtered);
  }

  function renderLog(entries) {
    var el = document.getElementById('cron-log-table');
    if (!el) return;
    if (!entries.length) { el.innerHTML = '<p class="neu">No entries match filter.</p>'; return; }
    var table = document.createElement('table');
    var thead = table.createTHead();
    thead.innerHTML = '<tr><th>Time</th><th>Ticker</th><th>City</th><th>Signal</th><th>Net Edge</th><th>Outcome</th></tr>';
    var tbody = table.createTBody();
    entries.slice().reverse().forEach(function (e) {
      var edge = e.net_edge;
      var edgeCls = edge > 0 ? 'pos' : edge < 0 ? 'neg' : 'neu';
      var row = tbody.insertRow();
      row.insertCell().textContent = (e.ts || '—').slice(0, 19);
      row.insertCell().textContent = e.ticker || '—';
      row.insertCell().textContent = e.city || '—';
      row.insertCell().textContent = e.signal || '—';
      var td5 = row.insertCell(); td5.className = edgeCls;
      td5.textContent = edge !== undefined ? (edge * 100).toFixed(1) + '%' : '—';
      row.insertCell().textContent = e.outcome !== undefined ? String(e.outcome) : '—';
    });
    el.innerHTML = '';
    el.appendChild(table);
  }

  // Expose runScan globally for the button onclick
  window.runScan = function () {
    var btn = document.getElementById('run-scan-btn');
    if (btn) { btn.textContent = '⏳ Scanning…'; btn.disabled = true; }
    fetch('/api/run_cron', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (resp) {
        if (resp && resp.error) {
          if (btn) { btn.textContent = '▶ Run Scan Now'; btn.disabled = false; }
          alert(resp.error);
          return;
        }
        if (btn) btn.textContent = '⏳ Running (0s)…';
        // Poll /api/cron-status every 5s until the subprocess exits,
        // then reload signals.  Hard cap at 8 min (matches watchdog).
        var elapsed = 0;
        var pollMs = 5000;
        var maxMs  = 480000;
        var poller = setInterval(function () {
          elapsed += pollMs;
          fetch('/api/cron-status')
            .then(function (r) { return r.json(); })
            .then(function (s) {
              if (!s.running || elapsed >= maxMs) {
                clearInterval(poller);
                loadLiveSignals();
                loadSignals();
                if (btn) { btn.textContent = '▶ Run Scan Now'; btn.disabled = false; }
              } else if (btn) {
                btn.textContent = '⏳ Running (' + Math.round(elapsed / 1000) + 's)…';
              }
            })
            .catch(function () {
              clearInterval(poller);
              if (btn) { btn.textContent = '▶ Run Scan Now'; btn.disabled = false; }
            });
        }, pollMs);
      })
      .catch(function () {
        if (btn) { btn.textContent = '▶ Run Scan Now'; btn.disabled = false; }
      });
  };

  loadLiveSignals();
  loadSignals();
}());

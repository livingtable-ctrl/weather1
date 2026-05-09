// static/dashboard.js
(function () {
  'use strict';

  // --- SSE: live data for stat cards and markets strip ---
  var _lastSseTs = null;
  var dashDot = document.getElementById('dash-dot');
  var dashUpdated = document.getElementById('dash-updated');
  var dashTs = document.getElementById('dash-ts');

  setInterval(function () {
    if (_lastSseTs === null) return;
    var secs = Math.round((Date.now() - _lastSseTs) / 1000);
    if (dashTs) dashTs.textContent = secs < 5 ? 'just now' : secs + 's ago';
    if (dashDot) dashDot.classList.toggle('stale', secs > 30);
  }, 1000);

  var es = new EventSource('/api/stream');
  es.onerror = function () {
    if (dashUpdated) dashUpdated.textContent = 'Offline';
    if (dashDot) dashDot.classList.add('stale');
  };
  es.onmessage = function (e) {
    try {
      _lastSseTs = Date.now();
      var d = JSON.parse(e.data);
      if (dashUpdated) dashUpdated.textContent = 'Live';
      var el;
      if (d.balance !== undefined) {
        el = document.getElementById('stat-balance');
        if (el) el.textContent = '$' + d.balance.toFixed(2);
      }
      if (d.open_count !== undefined) {
        el = document.getElementById('stat-open');
        if (el) el.textContent = d.open_count;
      }
      if (d.brier !== null && d.brier !== undefined) {
        el = document.getElementById('stat-brier');
        if (el) el.textContent = d.brier.toFixed(4);
      }
      if (d.markets) renderMarketsStrip(d.markets);
    } catch (err) { console.error('SSE parse error:', err); }
  };

  function renderMarketsStrip(markets) {
    var el = document.getElementById('markets-strip');
    if (!el) return;
    if (!markets.length) {
      el.innerHTML = '<p class="neu">No opportunities right now.</p>';
      return;
    }
    var table = document.createElement('table');
    var thead = table.createTHead();
    thead.innerHTML = '<tr><th>Ticker</th><th>Yes Ask</th><th>Edge</th></tr>';
    var tbody = table.createTBody();
    markets.forEach(function (m) {
      var edgeCls = m.edge >= 0 ? 'pos' : 'neg';
      var edgeStr = (m.edge >= 0 ? '+' : '') + (m.edge * 100).toFixed(1) + '%';
      var row = tbody.insertRow();
      var td1 = row.insertCell(); td1.textContent = m.ticker;
      var td2 = row.insertCell(); td2.textContent = m.yes_ask || '—';
      var td3 = row.insertCell(); td3.textContent = edgeStr; td3.className = edgeCls;
    });
    el.innerHTML = '';
    el.appendChild(table);
  }

  // --- Graduation bars + Fear/Greed gauge ---
  function loadGraduation() {
    fetch('/api/graduation').then(function (r) { return r.json(); }).then(function (d) {
      // Win rate stat card
      var wr = document.getElementById('stat-winrate');
      if (wr) {
        wr.textContent = (d.win_rate !== null && d.win_rate !== undefined)
          ? (d.win_rate * 100).toFixed(1) + '%' : '—';
      }

      // Trades progress bar
      var done = d.trades_done || 0;
      var tradesLabel = document.getElementById('grad-trades-label');
      var tradesBar = document.getElementById('grad-trades-bar');
      if (tradesLabel) tradesLabel.textContent = done + '/30';
      if (tradesBar) {
        tradesBar.style.width = Math.min(100, (done / 30) * 100) + '%';
        tradesBar.classList.toggle('complete', done >= 30);
      }

      // P&L progress bar (target: $50)
      var pnl = d.total_pnl || 0;
      var pnlLabel = document.getElementById('grad-pnl-label');
      var pnlBar = document.getElementById('grad-pnl-bar');
      if (pnlLabel) pnlLabel.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2) + '/$50';
      if (pnlBar) {
        pnlBar.style.width = Math.min(100, Math.max(0, (pnl / 50) * 100)) + '%';
        pnlBar.classList.toggle('complete', pnl >= 50);
      }

      // Brier score progress bar (target: ≤0.20; lower is better so invert)
      var brier = d.brier;
      var brierLabel = document.getElementById('grad-brier-label');
      var brierBar = document.getElementById('grad-brier-bar');
      if (brierLabel) brierLabel.textContent = brier !== null && brier !== undefined ? brier.toFixed(4) + '/<0.20' : '—/<0.20';
      if (brierBar) {
        // bar fills as brier improves: 0.25 (random) = 0%, 0.0 (perfect) = 100%
        var brierPct = brier !== null && brier !== undefined ? Math.min(100, Math.max(0, (1 - brier / 0.25) * 100)) : 0;
        brierBar.style.width = brierPct + '%';
        brierBar.classList.toggle('complete', brier !== null && brier !== undefined && brier <= 0.20);
      }

      // Status message
      var gradStatus = document.getElementById('grad-status');
      if (gradStatus) {
        gradStatus.textContent = d.ready ? '✓ Ready to go live' : 'Keep building track record…';
        gradStatus.style.color = d.ready ? 'var(--pos)' : 'var(--text-muted)';
      }

      // Fear/Greed gauge
      renderFearGreed(d.fear_greed_score || 0, d.fear_greed_label || '');
    }).catch(function (err) { console.error('graduation fetch failed:', err); });
  }

  function renderFearGreed(score, label) {
    var el = document.getElementById('fear-greed-chart');
    if (!el || typeof Plotly === 'undefined') return;
    Plotly.newPlot(el, [{
      type: 'indicator',
      mode: 'gauge+number',
      value: score,
      title: { text: label, font: { color: 'var(--text-muted)', size: 13 } },
      gauge: {
        axis: { range: [0, 100], tickcolor: 'var(--text-muted)' },
        bar: { color: score < 40 ? '#f85149' : score < 65 ? '#e3b341' : '#3fb950' },
        bgcolor: 'var(--surface)',
        bordercolor: 'var(--border)',
        steps: [
          { range: [0, 40], color: '#3a1a1a' },
          { range: [40, 65], color: '#3a3a1a' },
          { range: [65, 100], color: '#1a3a1f' }
        ]
      }
    }], {
      paper_bgcolor: 'transparent',
      font: { color: 'var(--text)', family: 'Consolas' },
      margin: { t: 30, b: 10, l: 20, r: 20 }
    }, { responsive: true });
  }

  // --- Balance history chart (Plotly replaces Chart.js) ---
  function loadBalanceChart(range) {
    var url = '/api/balance_history' + (range ? '?range=' + range : '');
    fetch(url).then(function (r) { return r.json(); }).then(function (data) {
      var el = document.getElementById('balance-chart');
      if (!el || typeof Plotly === 'undefined') return;
      Plotly.newPlot(el, [{
        x: data.labels,
        y: data.values,
        type: 'scatter',
        mode: 'lines',
        line: { color: 'var(--accent)', width: 2 },
        fill: 'tozeroy',
        fillcolor: 'rgba(88,166,255,0.08)'
      }], {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: 'var(--text)', family: 'Consolas' },
        xaxis: { showticklabels: false, showgrid: false, zeroline: false },
        yaxis: { tickprefix: '$', gridcolor: 'var(--border)', zeroline: false },
        margin: { t: 10, b: 20, l: 55, r: 10 },
        showlegend: false
      }, { responsive: true });

      document.querySelectorAll('.range-btn').forEach(function (b) {
        b.style.opacity = b.dataset.range === range ? '1' : '0.5';
      });
    }).catch(function (err) { console.error('balance history fetch failed:', err); });
  }

  // Fetch and render Live P&L card
  function loadLivePnl() {
    fetch('/api/live-pnl').then(function (r) { return r.json(); }).then(function (d) {
      var card = document.getElementById('live-pnl-card');
      var el = document.getElementById('stat-live-pnl');
      var openEl = document.getElementById('stat-live-open');
      if (!card || !el) return;
      if (d.settled_count === 0 && d.open_count === 0) return;
      card.style.display = '';
      var pnl = d.today_pnl || 0;
      el.textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2);
      el.className = 'stat-value ' + (pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : '');
      if (openEl) openEl.textContent = d.open_count > 0 ? d.open_count + ' open' : '';
    }).catch(function (err) { console.error('live-pnl fetch failed:', err); });
  }

  // --- Open positions widget ---
  function loadOpenPositions() {
    fetch('/api/trades').then(function (r) { return r.json(); }).then(function (d) {
      var open = d.open || [];
      var el = document.getElementById('open-positions-widget');
      if (!el) return;
      if (!open.length) {
        el.innerHTML = '<p class="neu">No open positions.</p>';
        return;
      }
      var table = document.createElement('table');
      var thead = table.createTHead();
      thead.innerHTML = '<tr><th>Ticker</th><th>City</th><th>Side</th><th>Cost</th><th>Expiry</th></tr>';
      var tbody = table.createTBody();
      open.forEach(function (t) {
        var row = tbody.insertRow();
        row.insertCell().textContent = t.ticker || '—';
        row.insertCell().textContent = t.city || '—';
        var tdSide = row.insertCell();
        var badge = document.createElement('span');
        badge.className = t.side === 'yes' ? 'badge badge-green' : 'badge badge-red';
        badge.textContent = (t.side || '').toUpperCase();
        tdSide.appendChild(badge);
        row.insertCell().textContent = '$' + (t.cost || 0).toFixed(2);
        row.insertCell().textContent = t.target_date || '—';
      });
      el.innerHTML = '';
      el.appendChild(table);
    }).catch(function (err) { console.error('open positions fetch failed:', err); });
  }

  // --- Circuit breaker status card ---
  var _CB_LABELS = {
    'open_meteo_forecast': 'Open-Meteo Forecast',
    'open_meteo_ensemble': 'Open-Meteo Ensemble',
    'weatherapi': 'WeatherAPI',
    'pirate_weather': 'Pirate Weather'
  };

  function loadCircuitStatus() {
    fetch('/api/circuit-status').then(function (r) { return r.json(); }).then(function (d) {
      var grid = document.getElementById('circuit-status-grid');
      if (!grid) return;
      if (d.error) {
        grid.innerHTML = '<p class="neg" style="grid-column:1/-1">' + d.error + '</p>';
        return;
      }
      grid.innerHTML = '';
      Object.keys(d).forEach(function (key) {
        var cb = d[key];
        var isOpen = cb.state === 'open';
        var card = document.createElement('div');
        card.style.cssText = 'border:1px solid ' + (isOpen ? 'var(--neg)' : 'var(--border)') + ';border-radius:6px;padding:10px 14px;background:var(--surface)';
        var dot = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + (isOpen ? 'var(--neg)' : 'var(--pos)') + ';margin-right:6px"></span>';
        var label = _CB_LABELS[key] || key;
        var stateLabel = isOpen ? 'OPEN' : 'Closed';
        var detail = isOpen
          ? (cb.retry_in_s > 0 ? 'retry in ' + cb.retry_in_s + 's' : 'probing…')
          : (cb.failures > 0 ? cb.failures + ' recent failure(s)' : 'OK');
        card.innerHTML = '<div style="font-size:0.88em;font-weight:600;margin-bottom:4px">' + dot + label + '</div>'
          + '<div style="font-size:0.82em;color:' + (isOpen ? 'var(--neg)' : 'var(--pos)') + '">' + stateLabel + '</div>'
          + '<div style="font-size:0.78em;color:var(--text-muted);margin-top:2px">' + detail + '</div>';
        grid.appendChild(card);
      });
    }).catch(function (err) { console.error('circuit-status fetch failed:', err); });
  }

  // Init
  loadGraduation();
  loadBalanceChart('');
  loadLivePnl();
  loadOpenPositions();
  loadCircuitStatus();
  setInterval(loadCircuitStatus, 60000);
}());

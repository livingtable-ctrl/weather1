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

      // Win rate progress bar
      var winRate = d.win_rate || 0;
      var wrLabel = document.getElementById('grad-wr-label');
      var wrBar = document.getElementById('grad-wr-bar');
      if (wrLabel) wrLabel.textContent = (winRate * 100).toFixed(1) + '%/55%';
      if (wrBar) {
        wrBar.style.width = Math.min(100, (winRate / 0.55) * 100) + '%';
        wrBar.classList.toggle('complete', winRate >= 0.55);
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

  // Init
  loadGraduation();
  loadBalanceChart('');
}());

// static/analytics.js
(function () {
  'use strict';

  // Resolve CSS custom properties once at load time (CSS is render-blocking so this is safe).
  // Fallbacks are the dark-theme hex values in case getPropertyValue returns empty.
  var _cs = getComputedStyle(document.documentElement);
  var C = {
    text:   (_cs.getPropertyValue('--text').trim()       || '#c9d1d9'),
    border: (_cs.getPropertyValue('--border').trim()     || '#30363d'),
    accent: (_cs.getPropertyValue('--accent').trim()     || '#58a6ff'),
    muted:  (_cs.getPropertyValue('--text-muted').trim() || '#8b949e'),
    bg:     (_cs.getPropertyValue('--surface').trim()    || '#161b22'),
  };

  var LAYOUT = {
    paper_bgcolor: C.bg,
    plot_bgcolor:  C.bg,
    font: { color: C.text, family: 'Consolas', size: 12 },
    margin: { t: 20, b: 40, l: 55, r: 20 }
  };

  function makeLayout(extra) {
    return Object.assign({}, LAYOUT, extra || {});
  }

  function loadAnalytics() {
    fetch('/api/analytics').then(function (r) { return r.json(); }).then(function (d) {
      // Brier stat card
      var brierEl = document.getElementById('an-brier');
      if (brierEl && d.brier !== null && d.brier !== undefined) {
        brierEl.textContent = d.brier.toFixed(4);
      }

      // Calibration curve: predicted prob buckets vs actual outcome rate
      // API returns {buckets:[...]} — unwrap first so .map() doesn't throw TypeError
      var calBuckets = d.model_calibration_buckets && d.model_calibration_buckets.buckets;
      if (calBuckets && calBuckets.length) {
        var xCal = calBuckets.map(function (b) { return b.our_prob_avg; });
        var yCal = calBuckets.map(function (b) { return b.actual_rate; });
        var calEl = document.getElementById('calibration-chart');
        if (calEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(calEl, [
            { x: [0, 1], y: [0, 1], type: 'scatter', mode: 'lines', name: 'Perfect',
              line: { color: C.muted, dash: 'dash', width: 1 } },
            { x: xCal, y: yCal, type: 'scatter', mode: 'markers+lines', name: 'Model',
              marker: { color: C.accent, size: 7 }, line: { color: C.accent } }
          ], makeLayout({
            xaxis: { title: 'Predicted Prob', gridcolor: C.border, zeroline: false, range: [0, 1] },
            yaxis: { title: 'Actual Rate',    gridcolor: C.border, zeroline: false, range: [0, 1] }
          }), { responsive: true });
        }
      }

      // ROC curve with AUC in legend
      // API returns roc.points:[{fpr,tpr}] — not flat roc.fpr/roc.tpr arrays
      var roc = d.roc_auc;
      if (roc && roc.points && roc.points.length) {
        var rocFpr = roc.points.map(function (p) { return p.fpr; });
        var rocTpr = roc.points.map(function (p) { return p.tpr; });
        var rocEl = document.getElementById('roc-chart');
        if (rocEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(rocEl, [
            { x: [0, 1], y: [0, 1], type: 'scatter', mode: 'lines', name: 'Random',
              line: { color: C.muted, dash: 'dash', width: 1 } },
            { x: rocFpr, y: rocTpr, type: 'scatter', mode: 'lines',
              name: 'Model (AUC=' + (roc.auc || 0).toFixed(3) + ')',
              line: { color: C.accent, width: 2 } }
          ], makeLayout({
            xaxis: { title: 'FPR', gridcolor: C.border, zeroline: false, range: [0, 1] },
            yaxis: { title: 'TPR', gridcolor: C.border, zeroline: false, range: [0, 1] }
          }), { responsive: true });
        }
      }

      // P&L attribution: horizontal bar per source by Brier score
      var attr = d.component_attribution;
      if (attr) {
        var sources = Object.keys(attr);
        var brierVals = sources.map(function (s) { return (attr[s] || {}).brier || 0; });
        var attrEl = document.getElementById('attribution-chart');
        if (attrEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(attrEl, [{
            type: 'bar', orientation: 'h',
            x: brierVals, y: sources,
            marker: { color: C.accent }
          }], makeLayout({
            xaxis: { title: 'Brier Score', gridcolor: C.border, zeroline: false },
            yaxis: { gridcolor: C.border }
          }), { responsive: true });
        }
      }

      // Brier by days out: bar chart colored by quality
      var bd = d.brier_by_days;
      if (bd) {
        var dKeys = Object.keys(bd).sort(function (a, b) { return +a - +b; });
        var dVals = dKeys.map(function (k) { return bd[k]; });
        var bdEl = document.getElementById('brier-days-chart');
        if (bdEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(bdEl, [{
            type: 'bar',
            x: dKeys.map(function (k) { return k + ' days'; }),
            y: dVals,
            marker: { color: dVals.map(function (v) {
              return v < 0.25 ? '#3fb950' : v < 0.35 ? '#e3b341' : '#f85149';
            })}
          }], makeLayout({
            xaxis: { gridcolor: C.border },
            yaxis: { title: 'Brier', gridcolor: C.border, zeroline: false }
          }), { responsive: true });
        }
      }

      // City calibration table
      var cities = d.city_calibration;
      if (cities) {
        var cityNames = Object.keys(cities).sort();
        var table = document.createElement('table');
        var thead = table.createTHead();
        thead.innerHTML = '<tr><th>City</th><th>N</th><th>Brier</th><th>Bias</th></tr>';
        var tbody = table.createTBody();
        cityNames.forEach(function (city) {
          var c = cities[city] || {};
          var row = tbody.insertRow();
          var td1 = row.insertCell(); td1.textContent = city;
          var td2 = row.insertCell(); td2.textContent = c.n || 0;
          var td3 = row.insertCell(); td3.textContent = c.brier !== undefined ? c.brier.toFixed(4) : '—';
          var td4 = row.insertCell(); td4.textContent = c.bias !== undefined ? c.bias.toFixed(4) : '—';
        });
        var tblEl = document.getElementById('city-cal-table');
        if (tblEl) { tblEl.innerHTML = ''; tblEl.appendChild(table); }
      }
    }).catch(function (err) { console.error('analytics fetch failed:', err); });
  }

  function loadBrierHistory() {
    fetch('/api/brier_history').then(function (r) { return r.json(); }).then(function (data) {
      var el = document.getElementById('brier-history-chart');
      if (!el || typeof Plotly === 'undefined' || !data.length) return;
      Plotly.newPlot(el, [{
        x: data.map(function (d) { return d.week; }),
        y: data.map(function (d) { return d.brier; }),
        type: 'scatter', mode: 'lines+markers',
        line: { color: C.accent, width: 2 },
        marker: { color: C.accent, size: 6 }
      }], makeLayout({
        xaxis: { gridcolor: C.border, zeroline: false },
        yaxis: { title: 'Brier', gridcolor: C.border, zeroline: false }
      }), { responsive: true });
    }).catch(function (err) { console.error('brier history fetch failed:', err); });
  }

  function loadModelAccuracy() {
    fetch('/api/ensemble-accuracy').then(function (r) { return r.json(); }).then(function (d) {
      var el = document.getElementById('model-accuracy-table');
      if (!el) return;
      var models = Object.keys(d);
      if (!models.length) { el.innerHTML = '<p class="neu">Accumulates after ~5 settled trades.</p>'; return; }
      var table = document.createElement('table');
      table.createTHead().innerHTML = '<tr><th>Model</th><th>MAE (°F)</th><th>N</th></tr>';
      var tbody = table.createTBody();
      models.sort(function (a, b) { return (d[a].mae || 99) - (d[b].mae || 99); }).forEach(function (m) {
        var row = tbody.insertRow();
        row.insertCell().textContent = m.replace('_seamless', '').toUpperCase();
        var tdMae = row.insertCell();
        tdMae.textContent = d[m].mae !== undefined ? d[m].mae.toFixed(2) : '—';
        tdMae.className = d[m].mae < 3 ? 'pos' : d[m].mae < 5 ? 'warn' : 'neg';
        row.insertCell().textContent = d[m].count || 0;
      });
      el.innerHTML = '';
      el.appendChild(table);
    }).catch(function () {});
  }

  function loadModelAttribution() {
    fetch('/api/model-attribution').then(function (r) { return r.json(); }).then(function (d) {
      var el = document.getElementById('model-attribution-table');
      if (!el) return;
      var cities = Object.keys(d);
      if (!cities.length) { el.innerHTML = '<p class="neu">No data yet.</p>'; return; }
      var allSources = Array.from(new Set(cities.flatMap(function (c) { return Object.keys(d[c]); }))).sort();
      var table = document.createElement('table');
      var hdr = '<tr><th>City</th>' + allSources.map(function (s) { return '<th>' + s + '</th>'; }).join('') + '</tr>';
      table.createTHead().innerHTML = hdr;
      var tbody = table.createTBody();
      cities.sort().forEach(function (city) {
        var row = tbody.insertRow();
        row.insertCell().textContent = city;
        allSources.forEach(function (s) {
          var v = d[city][s];
          var td = row.insertCell();
          td.textContent = v !== undefined ? (v * 100).toFixed(0) + '%' : '—';
          td.style.color = C.muted;
        });
      });
      el.innerHTML = '';
      el.appendChild(table);
    }).catch(function () {});
  }

  function loadPriceImprovement() {
    fetch('/api/price-improvement').then(function (r) { return r.json(); }).then(function (d) {
      var el = document.getElementById('price-improvement-table');
      if (!el) return;
      if (!d.total_trades) { el.innerHTML = '<p class="neu">No data yet (needs 5+ trades).</p>'; return; }
      var table = document.createElement('table');
      table.createTHead().innerHTML = '<tr><th>Metric</th><th>Value</th></tr>';
      var tbody = table.createTBody();
      var rows = [
        ['Avg Improvement', (d.avg_improvement_cents > 0 ? '+' : '') + d.avg_improvement_cents.toFixed(2) + '¢'],
        ['Median Improvement', (d.median_improvement_cents > 0 ? '+' : '') + (d.median_improvement_cents || 0).toFixed(2) + '¢'],
        ['% Positive Fills', (d.positive_pct || 0).toFixed(1) + '%'],
        ['Trades', d.total_trades],
      ];
      rows.forEach(function (r) {
        var row = tbody.insertRow();
        row.insertCell().textContent = r[0];
        var td = row.insertCell();
        td.textContent = r[1];
        if (r[0] === 'Avg Improvement') td.className = d.avg_improvement_cents >= 0 ? 'pos' : 'neg';
      });
      el.innerHTML = '';
      el.appendChild(table);
    }).catch(function () {});
  }

  function loadSourceReliability() {
    fetch('/api/source-reliability').then(function (r) { return r.json(); }).then(function (d) {
      var el = document.getElementById('source-reliability-table');
      if (!el) return;
      var agg = {};
      Object.values(d).forEach(function (cityData) {
        Object.keys(cityData).forEach(function (src) {
          if (!agg[src]) agg[src] = { successes: 0, total: 0 };
          agg[src].successes += cityData[src].successes || 0;
          agg[src].total += cityData[src].total || 0;
        });
      });
      var sources = Object.keys(agg);
      if (!sources.length) { el.innerHTML = '<p class="neu">No data yet.</p>'; return; }
      var table = document.createElement('table');
      table.createTHead().innerHTML = '<tr><th>Source</th><th>Success Rate</th><th>Attempts</th></tr>';
      var tbody = table.createTBody();
      sources.sort().forEach(function (src) {
        var s = agg[src];
        var rate = s.total ? s.successes / s.total : 0;
        var row = tbody.insertRow();
        row.insertCell().textContent = src;
        var tdRate = row.insertCell();
        tdRate.textContent = (rate * 100).toFixed(1) + '%';
        tdRate.className = rate >= 0.95 ? 'pos' : rate >= 0.8 ? 'warn' : 'neg';
        row.insertCell().textContent = s.total;
      });
      el.innerHTML = '';
      el.appendChild(table);
    }).catch(function () {});
  }

  loadAnalytics();
  loadBrierHistory();
  loadModelAccuracy();
  loadModelAttribution();
  loadPriceImprovement();
  loadSourceReliability();
}());

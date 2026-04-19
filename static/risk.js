// static/risk.js
(function () {
  'use strict';

  var LAYOUT = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: 'var(--text)', family: 'Consolas', size: 12 },
    margin: { t: 20, b: 40, l: 80, r: 20 }
  };

  function loadRisk() {
    fetch('/api/risk').then(function (r) { return r.json(); }).then(function (d) {
      // Risk stat cards
      var tExp = document.getElementById('risk-total-exp');
      if (tExp) tExp.textContent = (d.total_exposure * 100).toFixed(1) + '%';
      var aged = document.getElementById('risk-aged');
      if (aged) aged.textContent = (d.aged_positions || []).length;
      var corr = document.getElementById('risk-corr');
      if (corr) corr.textContent = (d.correlated_events || []).length;

      // City exposure horizontal bar chart (sorted descending by spec)
      var ce = d.city_exposure || [];
      var ceEl = document.getElementById('city-exposure-chart');
      if (ceEl && ce.length && typeof Plotly !== 'undefined') {
        Plotly.newPlot(ceEl, [{
          type: 'bar', orientation: 'h',
          x: ce.map(function (c) { return c.exposure; }),
          y: ce.map(function (c) { return c.city; }),
          marker: { color: 'var(--accent)' }
        }], Object.assign({}, LAYOUT, {
          xaxis: { title: '$', gridcolor: 'var(--border)', zeroline: false },
          yaxis: { gridcolor: 'var(--border)', automargin: true }
        }), { responsive: true });
      } else if (ceEl && !ce.length) {
        ceEl.innerHTML = '<p class="neu" style="padding:20px">No open positions.</p>';
      }

      // Directional bias donut
      var dir = d.directional || {};
      var dirEl = document.getElementById('directional-chart');
      if (dirEl && typeof Plotly !== 'undefined') {
        Plotly.newPlot(dirEl, [{
          type: 'pie', hole: 0.5,
          labels: ['YES', 'NO'],
          values: [dir.yes || 0, dir.no || 0],
          marker: { colors: ['#3fb950', '#f85149'] },
          textinfo: 'label+percent'
        }], Object.assign({}, LAYOUT, { margin: { t: 20, b: 20, l: 20, r: 20 } }), { responsive: true });
      }

      // Expiry clustering bar chart — each bar = a date with 2+ positions
      var ec = d.expiry_clustering || [];
      var ecEl = document.getElementById('expiry-chart');
      if (ecEl && ec.length && typeof Plotly !== 'undefined') {
        Plotly.newPlot(ecEl, [{
          type: 'bar',
          x: ec.map(function (e) { return e.date; }),
          y: ec.map(function (e) { return e.count; }),
          text: ec.map(function (e) { return '$' + e.total_cost.toFixed(2); }),
          marker: { color: ec.map(function (e) {
            return e.count >= 4 ? '#f85149' : e.count >= 3 ? '#e3b341' : '#58a6ff';
          })}
        }], Object.assign({}, LAYOUT, {
          xaxis: { gridcolor: 'var(--border)' },
          yaxis: { title: 'Position Count', gridcolor: 'var(--border)', zeroline: false, dtick: 1 }
        }), { responsive: true });
      } else if (ecEl && !ec.length) {
        ecEl.innerHTML = '<p class="neu" style="padding:20px">No expiry concentration risk.</p>';
      }
    }).catch(function (err) { console.error('risk fetch failed:', err); });
  }

  loadRisk();
}());

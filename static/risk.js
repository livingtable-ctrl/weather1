// static/risk.js
(function () {
  'use strict';

  // Resolve CSS custom properties once at load time.
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
    margin: { t: 20, b: 40, l: 80, r: 20 }
  };

  function makeLayout(extra) {
    return Object.assign({}, LAYOUT, extra || {});
  }

  function loadRisk() {
    fetch('/api/risk').then(function (r) { return r.json(); }).then(function (d) {
      // Risk stat cards
      var tExp = document.getElementById('risk-total-exp');
      if (tExp) tExp.textContent = (d.total_exposure * 100).toFixed(1) + '%';
      var aged = document.getElementById('risk-aged');
      if (aged) aged.textContent = (d.aged_positions || []).length;
      var corr = document.getElementById('risk-corr');
      if (corr) corr.textContent = (d.correlated_events || []).length;

      // City exposure horizontal bar chart
      var ce = d.city_exposure || [];
      var ceEl = document.getElementById('city-exposure-chart');
      if (ceEl && ce.length && typeof Plotly !== 'undefined') {
        Plotly.newPlot(ceEl, [{
          type: 'bar', orientation: 'h',
          x: ce.map(function (c) { return c.exposure; }),
          y: ce.map(function (c) { return c.city; }),
          marker: { color: C.accent }
        }], makeLayout({
          xaxis: { title: '$', gridcolor: C.border, zeroline: false },
          yaxis: { gridcolor: C.border, automargin: true }
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
        }], makeLayout({ margin: { t: 20, b: 20, l: 20, r: 20 } }), { responsive: true });
      }

      // Expiry clustering bar chart
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
        }], makeLayout({
          xaxis: { gridcolor: C.border },
          yaxis: { title: 'Position Count', gridcolor: C.border, zeroline: false, dtick: 1 }
        }), { responsive: true });
      } else if (ecEl && !ec.length) {
        ecEl.innerHTML = '<p class="neu" style="padding:20px">No expiry concentration risk.</p>';
      }
    }).catch(function (err) { console.error('risk fetch failed:', err); });
  }

  loadRisk();
}());

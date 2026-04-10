// static/analytics.js
(function () {
  'use strict';

  var LAYOUT_BASE = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: 'var(--text)', family: 'Consolas', size: 12 },
    margin: { t: 20, b: 40, l: 55, r: 20 }
  };

  function loadAnalytics() {
    fetch('/api/analytics').then(function (r) { return r.json(); }).then(function (d) {
      // Brier stat card
      var brierEl = document.getElementById('an-brier');
      if (brierEl && d.brier !== null && d.brier !== undefined) {
        brierEl.textContent = d.brier.toFixed(4);
      }

      // Calibration curve: predicted prob buckets vs actual outcome rate
      var calBuckets = d.model_calibration_buckets;
      if (calBuckets) {
        var xCal = calBuckets.map(function (b) { return b.predicted_prob; });
        var yCal = calBuckets.map(function (b) { return b.actual_rate; });
        var calEl = document.getElementById('calibration-chart');
        if (calEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(calEl, [
            { x: [0, 1], y: [0, 1], type: 'scatter', mode: 'lines', name: 'Perfect',
              line: { color: 'var(--text-muted)', dash: 'dash', width: 1 } },
            { x: xCal, y: yCal, type: 'scatter', mode: 'markers+lines', name: 'Model',
              marker: { color: 'var(--accent)', size: 7 }, line: { color: 'var(--accent)' } }
          ], Object.assign({}, LAYOUT_BASE, {
            xaxis: { title: 'Predicted Prob', gridcolor: 'var(--border)', zeroline: false, range: [0, 1] },
            yaxis: { title: 'Actual Rate', gridcolor: 'var(--border)', zeroline: false, range: [0, 1] }
          }), { responsive: true });
        }
      }

      // ROC curve with AUC in legend
      var roc = d.roc_auc;
      if (roc && roc.fpr && roc.tpr) {
        var rocEl = document.getElementById('roc-chart');
        if (rocEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(rocEl, [
            { x: [0, 1], y: [0, 1], type: 'scatter', mode: 'lines', name: 'Random',
              line: { color: 'var(--text-muted)', dash: 'dash', width: 1 } },
            { x: roc.fpr, y: roc.tpr, type: 'scatter', mode: 'lines',
              name: 'Model (AUC=' + (roc.auc || 0).toFixed(3) + ')',
              line: { color: 'var(--accent)', width: 2 } }
          ], Object.assign({}, LAYOUT_BASE, {
            xaxis: { title: 'FPR', gridcolor: 'var(--border)', zeroline: false, range: [0, 1] },
            yaxis: { title: 'TPR', gridcolor: 'var(--border)', zeroline: false, range: [0, 1] }
          }), { responsive: true });
        }
      }

      // P&L attribution: horizontal bar per source by Brier score
      var attr = d.component_attribution;
      if (attr) {
        var sources = Object.keys(attr);
        var brierVals = sources.map(function (s) { return (attr[s] || {}).brier_score || 0; });
        var attrEl = document.getElementById('attribution-chart');
        if (attrEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(attrEl, [{
            type: 'bar', orientation: 'h',
            x: brierVals, y: sources,
            marker: { color: 'var(--accent)' }
          }], Object.assign({}, LAYOUT_BASE, {
            xaxis: { title: 'Brier Score', gridcolor: 'var(--border)', zeroline: false },
            yaxis: { gridcolor: 'var(--border)' }
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
              return v < 0.25 ? 'var(--pos)' : v < 0.35 ? 'var(--warn)' : 'var(--neg)';
            })}
          }], Object.assign({}, LAYOUT_BASE, {
            xaxis: { gridcolor: 'var(--border)' },
            yaxis: { title: 'Brier', gridcolor: 'var(--border)', zeroline: false }
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
        line: { color: 'var(--accent)', width: 2 },
        marker: { color: 'var(--accent)', size: 6 }
      }], Object.assign({}, LAYOUT_BASE, {
        xaxis: { gridcolor: 'var(--border)', zeroline: false },
        yaxis: { title: 'Brier', gridcolor: 'var(--border)', zeroline: false }
      }), { responsive: true });
    }).catch(function (err) { console.error('brier history fetch failed:', err); });
  }

  loadAnalytics();
  loadBrierHistory();
}());

// static/forecast.js
(function () {
  'use strict';

  var LAYOUT = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: 'var(--text)', family: 'Consolas', size: 12 },
    margin: { t: 20, b: 60, l: 100, r: 20 }
  };

  function loadForecast() {
    fetch('/api/forecast_quality').then(function (r) { return r.json(); }).then(function (d) {
      renderCityHeatmap(d.city_heatmap || {});
      renderSourceReliability(d.source_reliability || {});
    }).catch(function (err) { console.error('forecast fetch failed:', err); });
  }

  function renderCityHeatmap(cityHeatmap) {
    var el = document.getElementById('city-heatmap');
    if (!el || typeof Plotly === 'undefined') return;
    var cities = Object.keys(cityHeatmap).sort();
    if (!cities.length) {
      el.innerHTML = '<p class="neu" style="padding:20px">No calibration data yet.</p>';
      return;
    }
    var brierVals = cities.map(function (c) { return (cityHeatmap[c] || {}).brier || 0; });
    Plotly.newPlot(el, [{
      type: 'bar', orientation: 'h',
      x: brierVals,
      y: cities,
      text: brierVals.map(function (v) { return v.toFixed(3); }),
      textposition: 'outside',
      marker: { color: brierVals.map(function (v) {
        return v < 0.25 ? 'var(--pos)' : v < 0.35 ? 'var(--warn)' : 'var(--neg)';
      })}
    }], Object.assign({}, LAYOUT, {
      xaxis: { title: 'Brier Score', gridcolor: 'var(--border)', zeroline: false },
      yaxis: { gridcolor: 'var(--border)', automargin: true }
    }), { responsive: true });
  }

  function renderSourceReliability(acc) {
    var el = document.getElementById('source-reliability-table');
    if (!el) return;
    var cities = Object.keys(acc).sort();
    if (!cities.length) {
      el.innerHTML = '<p class="neu">No ensemble member data yet.</p>';
      renderEnsembleChart({});
      return;
    }
    var table = document.createElement('table');
    var thead = table.createTHead();
    thead.innerHTML = '<tr><th>City</th><th>Model</th><th>MAE (°F)</th><th>N</th></tr>';
    var tbody = table.createTBody();
    cities.forEach(function (city) {
      var models = acc[city] || {};
      Object.keys(models).sort().forEach(function (model) {
        var stats = models[model] || {};
        var row = tbody.insertRow();
        var td1 = row.insertCell(); td1.textContent = city;
        var td2 = row.insertCell(); td2.textContent = model;
        var td3 = row.insertCell();
        td3.textContent = stats.mae !== undefined ? stats.mae.toFixed(2) : '—';
        var td4 = row.insertCell(); td4.textContent = stats.n || 0;
      });
    });
    el.innerHTML = '';
    el.appendChild(table);
    renderEnsembleChart(acc);
  }

  function renderEnsembleChart(acc) {
    var ensembleEl = document.getElementById('ensemble-chart');
    if (!ensembleEl || typeof Plotly === 'undefined') return;
    var cityNames = [];
    var stdVals = [];
    Object.keys(acc).sort().forEach(function (city) {
      var models = acc[city] || {};
      var maes = Object.values(models).map(function (s) { return s.mae || 0; });
      if (maes.length > 1) {
        var mean = maes.reduce(function (a, b) { return a + b; }, 0) / maes.length;
        var variance = maes.reduce(function (a, v) {
          return a + (v - mean) * (v - mean);
        }, 0) / maes.length;
        cityNames.push(city);
        stdVals.push(Math.round(Math.sqrt(variance) * 100) / 100);
      }
    });
    if (!cityNames.length) {
      ensembleEl.innerHTML = '<p class="neu" style="padding:20px">Need 2+ ensemble members per city.</p>';
      return;
    }
    Plotly.newPlot(ensembleEl, [{
      type: 'bar',
      x: cityNames,
      y: stdVals,
      marker: { color: stdVals.map(function (v) {
        return v < 1.0 ? 'var(--pos)' : v < 2.0 ? 'var(--warn)' : 'var(--neg)';
      })}
    }], Object.assign({}, LAYOUT, {
      margin: { t: 20, b: 40, l: 55, r: 20 },
      xaxis: { gridcolor: 'var(--border)' },
      yaxis: { title: 'Std Dev (MAE °F)', gridcolor: 'var(--border)', zeroline: false }
    }), { responsive: true });
  }

  loadForecast();
}());

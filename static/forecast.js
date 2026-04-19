// static/forecast.js
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

  function makeLayout(extra) {
    return Object.assign({
      paper_bgcolor: C.bg,
      plot_bgcolor:  C.bg,
      font: { color: C.text, family: 'Consolas', size: 12 },
      margin: { t: 20, b: 60, l: 100, r: 20 }
    }, extra || {});
  }

  // ── Live forecast tables ────────────────────────────────────────────────────

  function loadTodayForecasts() {
    fetch('/api/today_forecasts')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var now = new Date();
        var opts = { weekday: 'short', month: 'short', day: 'numeric' };
        var todayStr = now.toLocaleDateString(undefined, opts);
        var tomorrowDate = new Date(now); tomorrowDate.setDate(now.getDate() + 1);
        var tomorrowStr = tomorrowDate.toLocaleDateString(undefined, opts);
        document.getElementById('today-date').textContent = '— ' + todayStr;
        document.getElementById('tomorrow-date').textContent = '— ' + tomorrowStr;
        renderForecastTable('today-table', d.today || {});
        renderForecastTable('tomorrow-table', d.tomorrow || {});
      })
      .catch(function (err) { console.error('today_forecasts fetch failed:', err); });
  }

  function renderForecastTable(elId, data) {
    var el = document.getElementById(elId);
    if (!el) return;
    var cities = Object.keys(data).sort();
    if (!cities.length) {
      el.innerHTML = '<p class="neu">No forecast data available.</p>';
      return;
    }

    var table = document.createElement('table');
    var thead = table.createTHead();
    thead.innerHTML = '<tr>' +
      '<th>City</th>' +
      '<th>High</th>' +
      '<th>Low</th>' +
      '<th>Range</th>' +
      '<th>Precip</th>' +
      '<th>Models</th>' +
      '</tr>';

    var tbody = table.createTBody();
    cities.forEach(function (city) {
      var f = data[city];
      var row = tbody.insertRow();

      var tdCity = row.insertCell();
      tdCity.textContent = city;

      var tdHigh = row.insertCell();
      tdHigh.textContent = f.high_f.toFixed(1) + '°F';
      tdHigh.style.fontWeight = 'bold';

      var tdLow = row.insertCell();
      tdLow.textContent = f.low_f !== null ? f.low_f.toFixed(1) + '°F' : '—';
      tdLow.style.color = C.muted;

      var tdRange = row.insertCell();
      var lo = f.high_range[0], hi = f.high_range[1];
      var spread = hi - lo;
      tdRange.textContent = lo.toFixed(0) + '–' + hi.toFixed(0) + '°';
      tdRange.style.color = spread <= 2 ? '#3fb950' : spread <= 5 ? '#e3b341' : '#f85149';
      tdRange.title = 'Model spread: ' + spread.toFixed(1) + '°F';

      var tdPrecip = row.insertCell();
      if (f.precip_in > 0.01) {
        tdPrecip.textContent = f.precip_in.toFixed(2) + '"';
        tdPrecip.style.color = '#e3b341';
      } else {
        tdPrecip.textContent = 'Dry';
        tdPrecip.style.color = C.muted;
      }

      var tdModels = row.insertCell();
      tdModels.textContent = f.models_used + ' model' + (f.models_used !== 1 ? 's' : '');
      tdModels.style.color = f.models_used >= 3 ? '#3fb950' : f.models_used === 2 ? '#e3b341' : '#f85149';
    });

    el.innerHTML = '';
    el.appendChild(table);
  }

  // ── Calibration charts ──────────────────────────────────────────────────────

  function loadForecast() {
    fetch('/api/forecast_quality')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        renderCityHeatmap(d.city_heatmap || {});
        renderSourceReliability(d.source_reliability || {});
      })
      .catch(function (err) { console.error('forecast fetch failed:', err); });
  }

  function renderCityHeatmap(cityHeatmap) {
    var el = document.getElementById('city-heatmap');
    if (!el || typeof Plotly === 'undefined') return;
    var cities = Object.keys(cityHeatmap).sort();
    if (!cities.length) {
      el.innerHTML = '<p class="neu" style="padding:20px">No calibration data yet — accumulates after 10+ settled trades.</p>';
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
        return v < 0.25 ? '#3fb950' : v < 0.35 ? '#e3b341' : '#f85149';
      })}
    }], makeLayout({
      xaxis: { title: 'Brier Score', gridcolor: C.border, zeroline: false },
      yaxis: { gridcolor: C.border, automargin: true }
    }), { responsive: true });
  }

  function renderSourceReliability(acc) {
    var el = document.getElementById('source-reliability-table');
    if (!el) return;
    var cities = Object.keys(acc).sort();
    if (!cities.length) {
      el.innerHTML = '<p class="neu">No ensemble member data yet — accumulates after settled trades.</p>';
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
        row.insertCell().textContent = city;
        row.insertCell().textContent = model;
        var tdMae = row.insertCell();
        tdMae.textContent = stats.mae !== undefined ? stats.mae.toFixed(2) : '—';
        row.insertCell().textContent = stats.n || 0;
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
        return v < 1.0 ? '#3fb950' : v < 2.0 ? '#e3b341' : '#f85149';
      })}
    }], makeLayout({
      margin: { t: 20, b: 40, l: 55, r: 20 },
      xaxis: { gridcolor: C.border },
      yaxis: { title: 'Std Dev (MAE °F)', gridcolor: C.border, zeroline: false }
    }), { responsive: true });
  }

  loadTodayForecasts();
  loadForecast();
}());

// static/signals.js
(function () {
  'use strict';

  var _log = [];

  function loadSignals() {
    fetch('/api/signals').then(function (r) { return r.json(); }).then(function (d) {
      renderAlerts(d.alerts || []);
      _log = d.log || [];
      populateFilters(_log);
      renderLog(_log);
    }).catch(function (err) { console.error('signals fetch failed:', err); });
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
      var td1 = row.insertCell(); td1.textContent = (a.ts || '—').slice(0, 19);
      var td2 = row.insertCell(); td2.className = lvlCls; td2.textContent = lvl;
      var td3 = row.insertCell(); td3.textContent = a.message || a.signal || '';
    });
    el.innerHTML = '';
    el.appendChild(table);
  }

  function populateFilters(log) {
    var signals = Array.from(new Set(
      log.map(function (e) { return e.signal || ''; }).filter(Boolean)
    )).sort();
    var cities = Array.from(new Set(
      log.map(function (e) { return e.city || ''; }).filter(Boolean)
    )).sort();

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
    thead.innerHTML = '<tr><th>Time</th><th>Ticker</th><th>City</th>'
      + '<th>Signal</th><th>Net Edge</th><th>Outcome</th></tr>';
    var tbody = table.createTBody();
    entries.slice().reverse().forEach(function (e) {
      var edge = e.net_edge;
      var edgeCls = edge > 0 ? 'pos' : edge < 0 ? 'neg' : 'neu';
      var row = tbody.insertRow();
      var td1 = row.insertCell(); td1.textContent = (e.ts || '—').slice(0, 19);
      var td2 = row.insertCell(); td2.textContent = e.ticker || '—';
      var td3 = row.insertCell(); td3.textContent = e.city || '—';
      var td4 = row.insertCell(); td4.textContent = e.signal || '—';
      var td5 = row.insertCell(); td5.className = edgeCls;
      td5.textContent = edge !== undefined ? (edge * 100).toFixed(1) + '%' : '—';
      var td6 = row.insertCell(); td6.textContent = e.outcome !== undefined ? String(e.outcome) : '—';
    });
    el.innerHTML = '';
    el.appendChild(table);
  }

  loadSignals();
}());

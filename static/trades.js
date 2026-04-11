// static/trades.js
(function () {
  'use strict';

  var PAGE_SIZE = 25;
  var _closed = [];
  var _page = 0;

  function loadTrades() {
    fetch('/api/trades').then(function (r) { return r.json(); }).then(function (d) {
      renderSummary(d.open || [], d.closed || []);
      renderOpen(d.open || []);
      _closed = d.closed || [];
      populateCityFilter(_closed);
      renderClosed();
    }).catch(function (err) { console.error('trades fetch failed:', err); });
  }

  function renderSummary(open, closed) {
    var settled = closed.filter(function (t) { return t.pnl !== null && t.pnl !== undefined; });
    var totalPnl = settled.reduce(function (s, t) { return s + (t.pnl || 0); }, 0);
    var wins = settled.filter(function (t) { return (t.pnl || 0) > 0; }).length;
    var winRate = settled.length ? (wins / settled.length * 100) : null;
    var openCost = open.reduce(function (s, t) { return s + (t.cost || 0); }, 0);
    var tradesLeft = Math.max(0, 30 - settled.length);
    var pnlLeft = Math.max(0, 50 - totalPnl);
    var gradReady = tradesLeft === 0 && pnlLeft === 0; // brier checked server-side

    var pnlEl = document.getElementById('ps-total-pnl');
    if (pnlEl) {
      pnlEl.textContent = (totalPnl >= 0 ? '+$' : '-$') + Math.abs(totalPnl).toFixed(2);
      pnlEl.className = 'stat-value ' + (totalPnl >= 0 ? 'pos' : 'neg');
    }
    var wrEl = document.getElementById('ps-winrate');
    if (wrEl) wrEl.textContent = winRate !== null ? winRate.toFixed(1) + '%' : '—';
    var tEl = document.getElementById('ps-trades');
    if (tEl) tEl.textContent = settled.length;
    var ocEl = document.getElementById('ps-open-cost');
    if (ocEl) ocEl.textContent = '$' + openCost.toFixed(2);
    var gEl = document.getElementById('ps-grad');
    if (gEl) {
      if (gradReady) {
        gEl.textContent = '✓ Ready';
        gEl.className = 'stat-value pos';
      } else {
        var parts = [];
        if (tradesLeft > 0) parts.push(tradesLeft + ' trades');
        if (pnlLeft > 0) parts.push('+$' + pnlLeft.toFixed(0) + ' P&L');
        gEl.textContent = parts.join(', ');
        gEl.className = 'stat-value';
      }
    }
  }

  function renderOpen(trades) {
    var el = document.getElementById('open-trades-table');
    if (!el) return;
    if (!trades.length) { el.innerHTML = '<p class="neu">No open positions.</p>'; return; }
    var table = document.createElement('table');
    var thead = table.createTHead();
    thead.innerHTML = '<tr><th>Ticker</th><th>City</th><th>Side</th><th>Entry</th>'
      + '<th>Current</th><th>Cost</th><th>Expiry</th></tr>';
    var tbody = table.createTBody();
    trades.forEach(function (t) {
      var row = tbody.insertRow();
      var td1 = row.insertCell(); td1.textContent = t.ticker || '—';
      var td2 = row.insertCell(); td2.textContent = t.city || '—';
      var td3 = row.insertCell();
      var badge = document.createElement('span');
      badge.className = t.side === 'yes' ? 'badge badge-green' : 'badge badge-red';
      badge.textContent = (t.side || '').toUpperCase();
      td3.appendChild(badge);
      var td4 = row.insertCell();
      td4.textContent = t.entry_price !== undefined ? (t.entry_price * 100).toFixed(0) + '¢' : '—';
      var td5 = row.insertCell();
      td5.textContent = (t.current_yes_ask !== undefined && t.current_yes_ask !== null)
        ? t.current_yes_ask + '¢' : '—';
      var td6 = row.insertCell(); td6.textContent = '$' + (t.cost || 0).toFixed(2);
      var td7 = row.insertCell(); td7.textContent = t.target_date || '—';
    });
    el.innerHTML = '';
    el.appendChild(table);
  }

  function populateCityFilter(trades) {
    var cities = Array.from(new Set(
      trades.map(function (t) { return t.city || ''; }).filter(Boolean)
    )).sort();
    var sel = document.getElementById('filter-city');
    if (sel) {
      cities.forEach(function (c) {
        var opt = document.createElement('option');
        opt.value = c; opt.textContent = c;
        sel.appendChild(opt);
      });
      sel.addEventListener('change', function () { _page = 0; renderClosed(); });
    }
    var sideSel = document.getElementById('filter-side');
    if (sideSel) sideSel.addEventListener('change', function () { _page = 0; renderClosed(); });
  }

  function renderClosed() {
    var cityFilter = (document.getElementById('filter-city') || {}).value || '';
    var sideFilter = (document.getElementById('filter-side') || {}).value || '';
    var filtered = _closed.filter(function (t) {
      return (!cityFilter || t.city === cityFilter) && (!sideFilter || t.side === sideFilter);
    });
    var page = filtered.slice(_page * PAGE_SIZE, (_page + 1) * PAGE_SIZE);
    var el = document.getElementById('closed-trades-table');
    if (!el) return;
    if (!page.length) { el.innerHTML = '<p class="neu">No closed trades match filter.</p>'; renderPagination(0); return; }
    var table = document.createElement('table');
    var thead = table.createTHead();
    thead.innerHTML = '<tr><th>Ticker</th><th>City</th><th>Side</th><th>Outcome</th><th>P&L</th></tr>';
    var tbody = table.createTBody();
    page.forEach(function (t) {
      var p = t.pnl || 0;
      var pCls = p >= 0 ? 'pos' : 'neg';
      var pStr = (p >= 0 ? '+$' : '-$') + Math.abs(p).toFixed(2);
      var row = tbody.insertRow();
      var td1 = row.insertCell(); td1.textContent = t.ticker || '—';
      var td2 = row.insertCell(); td2.textContent = t.city || '—';
      var td3 = row.insertCell(); td3.textContent = (t.side || '').toUpperCase();
      var td4 = row.insertCell();
      var badge = document.createElement('span');
      badge.className = t.outcome === 'yes' ? 'badge badge-green' : 'badge badge-red';
      badge.textContent = (t.outcome || '—').toUpperCase();
      td4.appendChild(badge);
      var td5 = row.insertCell(); td5.className = pCls; td5.textContent = pStr;
    });
    el.innerHTML = '';
    el.appendChild(table);
    renderPagination(Math.ceil(filtered.length / PAGE_SIZE));
  }

  function renderPagination(pages) {
    var el = document.getElementById('trades-pagination');
    if (!el) return;
    if (pages <= 1) { el.innerHTML = ''; return; }
    el.innerHTML = '';
    for (var i = 0; i < pages; i++) {
      var btn = document.createElement('button');
      if (i === _page) btn.className = 'active';
      btn.textContent = i + 1;
      (function (pageIndex) {
        btn.addEventListener('click', function () { _page = pageIndex; renderClosed(); });
      }(i));
      el.appendChild(btn);
    }
  }

  loadTrades();
}());

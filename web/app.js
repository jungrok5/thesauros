// AI Quant v2 — frontend.

const $ = (id) => document.getElementById(id);

const fmt = {
  num: (v, d = 2) => (v == null || isNaN(v)) ? '—' : Number(v).toFixed(d),
  pct: (v, d = 2) => (v == null || isNaN(v)) ? '—' : (Number(v) * 100).toFixed(d) + '%',
  usd: (v, d = 2) => (v == null || isNaN(v)) ? '—' : '$' + Number(v).toFixed(d),
  cap: (v) => {
    if (v == null || isNaN(v)) return '—';
    const num = Number(v);
    if (num >= 1e12) return '$' + (num / 1e12).toFixed(2) + 'T';
    if (num >= 1e9) return '$' + (num / 1e9).toFixed(2) + 'B';
    return '$' + (num / 1e6).toFixed(0) + 'M';
  },
  scoreColor: (v) => v == null ? 'score-neu' : (v > 0 ? 'score-pos' : v < 0 ? 'score-neg' : 'score-neu'),
};

function startTimer(elId, msg) {
  const t0 = Date.now();
  const el = $(elId);
  const id = setInterval(() => {
    const sec = ((Date.now() - t0) / 1000).toFixed(0);
    el.textContent = `⏳ ${msg} (${sec}초 경과)`;
  }, 250);
  return () => clearInterval(id);
}

async function fetchJSON(url, opts = {}) {
  const ctl = new AbortController();
  const tid = setTimeout(() => ctl.abort(), opts.timeoutMs || 1800000);
  try {
    const r = await fetch(url, { ...opts, signal: ctl.signal });
    if (!r.ok) {
      const t = await r.text().catch(() => '');
      throw new Error(`HTTP ${r.status}: ${t.slice(0, 200)}`);
    }
    return await r.json();
  } finally { clearTimeout(tid); }
}

// Tabs
const tabs = ['rec', 'detail', 'bt', 'model', 'data'];
function showTab(t) {
  for (const k of tabs) {
    $('tab-' + k).classList.toggle('tab-active', k === t);
    $('view-' + k).classList.toggle('hidden', k !== t);
  }
  if (t === 'model') loadModelInfo();
  if (t === 'data') loadDataStats();
}
tabs.forEach(t => $('tab-' + t).onclick = () => showTab(t));

// On load — show DB badge
(async () => {
  try {
    const s = await fetchJSON('/api/data/stats');
    $('data-badge').textContent =
      `DB: ${s.universe ?? 0} 종목 · 가격 ${(s.prices_rows/1000).toFixed(0)}k 행 · 펀더 ${(s.fundamentals_rows/1000).toFixed(0)}k 행`;
  } catch (e) {
    $('data-badge').textContent = 'DB: 미초기화';
  }
})();

// === Recommend ===
$('btn-recommend').onclick = async () => {
  const k = $('topK').value || 20;
  $('rec-body').innerHTML = `<tr><td colspan="12" class="text-center text-slate-400 py-8">예측 계산 중...</td></tr>`;
  const stop = startTimer('rec-status', '예측 계산 중');
  $('btn-recommend').disabled = true;
  try {
    const data = await fetchJSON(`/api/recommend?top_k=${k}`);
    renderRecommendations(data);
    $('rec-status').textContent = `✅ ${data.items.length}개 — 기준일 ${data.as_of_date}`;
  } catch (e) {
    $('rec-status').textContent = '❌ ' + e.message;
    $('rec-body').innerHTML = `<tr><td colspan="12" class="text-center text-red-400 py-6">에러: ${e.message}</td></tr>`;
  } finally { stop(); $('btn-recommend').disabled = false; }
};

function renderRecommendations(data) {
  const tb = $('rec-body');
  tb.innerHTML = '';
  data.items.forEach((it, i) => {
    const tr = document.createElement('tr');
    tr.className = 'row-link';
    tr.innerHTML = `
      <td class="px-3 py-2 text-slate-500">${i+1}</td>
      <td class="px-3 py-2 font-mono">${it.ticker}</td>
      <td class="px-3 py-2">${it.name || ''}</td>
      <td class="px-3 py-2 text-slate-400 text-xs">${it.sector || '—'}</td>
      <td class="px-3 py-2 text-right">${fmt.usd(it.close)}</td>
      <td class="px-3 py-2 text-right ${fmt.scoreColor(it.pred_21d_return)} font-semibold">${fmt.pct(it.pred_21d_return, 2)}</td>
      <td class="px-3 py-2 text-right">${fmt.num(it.pe, 1)}</td>
      <td class="px-3 py-2 text-right">${fmt.num(it.pb, 2)}</td>
      <td class="px-3 py-2 text-right">${fmt.pct(it.roe_ttm, 1)}</td>
      <td class="px-3 py-2 text-right">${fmt.pct(it.mom_12_1, 1)}</td>
      <td class="px-3 py-2 text-right">${fmt.pct(it.vol_60, 1)}</td>
      <td class="px-3 py-2 text-right"><button class="text-sky-400 hover:underline text-xs">상세</button></td>
    `;
    tr.onclick = () => {
      $('detail-ticker').value = it.ticker;
      showTab('detail');
      $('btn-analyze').click();
    };
    tb.appendChild(tr);
  });
}

// === Detail ===
$('btn-analyze').onclick = async () => {
  const t = $('detail-ticker').value.trim().toUpperCase();
  if (!t) return;
  const stop = startTimer('detail-status', '분석 중');
  $('detail-content').classList.add('hidden');
  $('btn-analyze').disabled = true;
  try {
    const [a, p] = await Promise.all([
      fetchJSON(`/api/analyze?ticker=${encodeURIComponent(t)}`),
      fetchJSON(`/api/prices?ticker=${encodeURIComponent(t)}&start=${oneYearAgo()}`),
    ]);
    renderDetail(a, p);
    $('detail-status').textContent = '✅ 완료';
    $('detail-content').classList.remove('hidden');
  } catch (e) {
    $('detail-status').textContent = '❌ ' + e.message;
  } finally { stop(); $('btn-analyze').disabled = false; }
};

function oneYearAgo() {
  const d = new Date(); d.setFullYear(d.getFullYear() - 1);
  return d.toISOString().slice(0, 10);
}

function renderDetail(a, p) {
  $('d-name').textContent = `${a.name || a.ticker} (${a.ticker})`;
  $('d-meta').textContent = `${a.sector || '—'} · 시가총액 (log): ${fmt.num(a.fundamentals.log_market_cap, 2)}`;
  $('d-pred').textContent = fmt.pct(a.prediction.expected_return, 2);
  $('d-pred').className = 'text-2xl font-semibold ' + fmt.scoreColor(a.prediction.expected_return);
  $('d-asof').textContent = a.as_of_date;

  const tp = a.trade_plan || {};
  $('trade-plan').innerHTML = `
    <div><div class="text-[10px] text-slate-500">방향</div><div class="text-lg font-semibold">${tp.direction || '—'}</div></div>
    <div><div class="text-[10px] text-slate-500">진입가</div><div class="text-lg">${fmt.usd(tp.entry)}</div></div>
    <div><div class="text-[10px] text-slate-500">손절가</div><div class="text-lg score-neg">${fmt.usd(tp.stop_loss)}</div></div>
    <div><div class="text-[10px] text-slate-500">익절가</div><div class="text-lg score-pos">${fmt.usd(tp.take_profit)}</div></div>
    <div><div class="text-[10px] text-slate-500">ATR(14)</div><div>${fmt.usd(tp.atr14)}</div></div>
    <div><div class="text-[10px] text-slate-500">포지션</div><div>${fmt.pct(tp.position_size_pct)}</div></div>
    <div><div class="text-[10px] text-slate-500">손익비</div><div>1:${fmt.num(tp.rr_ratio,1)}</div></div>
    <div><div class="text-[10px] text-slate-500">리스크</div><div>${fmt.pct(tp.risk_per_trade_pct)}</div></div>
  `;

  const fundLabels = {
    pe: 'PER', pb: 'PBR', ps: 'PSR', ev_to_revenue: 'EV/매출', fcf_yield: 'FCF 수익률',
    roa_ttm: 'ROA', roe_ttm: 'ROE', op_margin: '영업이익률', gross_margin: '매출총이익률',
    debt_to_equity: '부채/자본', current_ratio: '유동비율',
    revenue_growth_yoy: '매출 성장 YoY', earnings_growth_yoy: '이익 성장 YoY',
    log_market_cap: 'log 시가총액',
  };
  const techLabels = {
    mom_1m: '1M 수익률', mom_3m: '3M', mom_6m: '6M',
    mom_12_1: '12-1 모멘텀', mom_12m: '12M',
    vol_20: '20D 변동성', vol_60: '60D 변동성',
    rsi_14: 'RSI(14)', macd_hist: 'MACD Hist',
    px_to_sma50: 'P/SMA50-1', px_to_sma200: 'P/SMA200-1', dd_252: 'DD 252',
  };
  function fillTable(el, obj, labels, isPct = (k) => k.startsWith('mom_') || k.includes('growth') || k.includes('margin') || k.includes('vol_') || k.includes('roe') || k.includes('roa') || k.includes('yield') || k === 'dd_252') {
    el.innerHTML = '';
    for (const [k, v] of Object.entries(obj || {})) {
      const lbl = labels[k] || k;
      let val;
      if (v == null || isNaN(v)) val = '<span class="text-slate-600">—</span>';
      else if (isPct(k)) val = fmt.pct(v, 2);
      else if (k === 'rsi_14') val = fmt.num(v, 1);
      else val = fmt.num(v, 3);
      el.insertAdjacentHTML('beforeend', `<tr><td class="py-1.5 text-slate-400">${lbl}</td><td class="py-1.5 text-right">${val}</td></tr>`);
    }
  }
  fillTable($('fund-table'), a.fundamentals, fundLabels);
  fillTable($('tech-table'), a.technical, techLabels);

  const c = (p.candles || []);
  const x = c.map(d => d.date), o = c.map(d => d.open),
        h = c.map(d => d.high), l = c.map(d => d.low),
        cl = c.map(d => d.close);
  Plotly.newPlot('chart', [
    { x, open: o, high: h, low: l, close: cl, type: 'candlestick', name: 'Price',
      increasing: { line: { color: '#22c55e' } }, decreasing: { line: { color: '#ef4444' } } },
  ], {
    margin: { t: 20, l: 50, r: 20, b: 30 },
    paper_bgcolor: '#0f172a', plot_bgcolor: '#0f172a',
    font: { color: '#e2e8f0' },
    xaxis: { rangeslider: { visible: false }, gridcolor: '#1e293b' },
    yaxis: { gridcolor: '#1e293b' },
    shapes: [
      { type: 'line', x0: x[0], x1: x[x.length-1], y0: tp.entry, y1: tp.entry, line: { color: '#38bdf8', dash: 'dash', width: 1 } },
      { type: 'line', x0: x[0], x1: x[x.length-1], y0: tp.stop_loss, y1: tp.stop_loss, line: { color: '#ef4444', dash: 'dot', width: 1 } },
      { type: 'line', x0: x[0], x1: x[x.length-1], y0: tp.take_profit, y1: tp.take_profit, line: { color: '#22c55e', dash: 'dot', width: 1 } },
    ],
  }, { displayModeBar: false, responsive: true });
}

// === Backtest ===
$('btn-backtest').onclick = async () => {
  const version = (document.querySelector('input[name="bt-version"]:checked')?.value) || 'v2';
  const baseBody = {
    start: $('bt-start').value, end: $('bt-end').value || null,
    train_start: $('bt-train-start').value,
    rebalance_n: parseInt($('bt-reb').value, 10) || 21,
    top_k: parseInt($('bt-topk').value, 10) || 20,
    cost_bps: parseFloat($('bt-cost').value) || 10,
    slippage_bps: parseFloat($('bt-slip').value) || 5,
  };
  const body = version === 'v3' ? {
    ...baseBody,
    sector_cap: parseFloat($('bt-sec-cap').value) || 0.30,
    drawdown_brake: parseFloat($('bt-dd').value) || -0.10,
    use_rank_target: true,
    feature_suffix: '_sn',
  } : baseBody;
  const url = version === 'v3' ? '/api/backtest_v3' : '/api/backtest';
  const stop = startTimer('bt-status', `백테스트 (${version}) 실행 중`);
  $('bt-result').classList.add('hidden');
  $('btn-backtest').disabled = true;
  try {
    const data = await fetchJSON(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    renderBacktest(data);
    $('bt-result').classList.remove('hidden');
    $('bt-status').textContent = `✅ 완료 (${version})`;
  } catch (e) {
    $('bt-status').textContent = '❌ ' + e.message;
  } finally { stop(); $('btn-backtest').disabled = false; }
};

function renderBacktest(data) {
  const m = data.metrics || {};
  const cards = [
    ['CAGR (전략)', fmt.pct(m.cagr), fmt.scoreColor(m.cagr)],
    ['CAGR (벤치)', fmt.pct(m.bench_cagr), 'score-neu'],
    ['알파', fmt.pct(m.alpha), fmt.scoreColor(m.alpha)],
    ['샤프', fmt.num(m.sharpe, 2), fmt.scoreColor(m.sharpe)],
    ['IR', fmt.num(m.info_ratio, 2), fmt.scoreColor(m.info_ratio)],
    ['MDD', fmt.pct(m.max_drawdown), 'score-neg'],
    ['연환산 변동성', fmt.pct(m.vol_annual), 'score-neu'],
    ['총수익(전략)', fmt.pct(m.total_return), fmt.scoreColor(m.total_return)],
    ['총수익(벤치)', fmt.pct(m.bench_total_return), 'score-neu'],
    ['거래일', fmt.num(m.n_days, 0), 'score-neu'],
  ];
  $('bt-metrics').innerHTML = cards.map(([k, v, c]) =>
    `<div><div class="text-[10px] text-slate-500">${k}</div><div class="text-lg ${c}">${v}</div></div>`
  ).join('');

  const eq = data.equity_curve || [];
  const x = eq.map(d => d.date), y1 = eq.map(d => d.equity), y2 = eq.map(d => d.benchmark);
  Plotly.newPlot('bt-chart', [
    { x, y: y1, mode: 'lines', name: '전략', line: { color: '#22c55e', width: 2 } },
    { x, y: y2, mode: 'lines', name: '벤치 (동일가중)', line: { color: '#94a3b8', width: 1.5, dash: 'dot' } },
  ], plotLayout({ y: '에쿼티 (1.0 시작)' }), { displayModeBar: false, responsive: true });

  const ic = data.ic_history || [];
  const xi = ic.map(d => d.date), yi = ic.map(d => d.ic);
  Plotly.newPlot('bt-ic-chart', [
    { x: xi, y: yi, type: 'bar', marker: { color: yi.map(v => v >= 0 ? '#22c55e' : '#ef4444') } },
  ], plotLayout({ y: 'Spearman IC' }), { displayModeBar: false, responsive: true });

  const h = data.holdings || [];
  $('bt-holdings').innerHTML = h.map(snap =>
    `<div><span class="text-slate-500">${snap.date}</span> — ${snap.tickers.join(', ')}</div>`
  ).join('');
}

// === Model info ===
async function loadModelInfo() {
  try {
    const m = await fetchJSON('/api/model/info');
    if (m.feature_importance) {
      const fi = m.feature_importance.slice(0, 20).reverse();
      Plotly.newPlot('fi-chart', [{
        type: 'bar', orientation: 'h',
        x: fi.map(f => f.gain), y: fi.map(f => f.feature),
        marker: { color: '#38bdf8' },
      }], plotLayout({ x: 'Gain' }), { displayModeBar: false, responsive: true });
    }
    if (m.ic_by_date) {
      const x = m.ic_by_date.map(r => r.date), y = m.ic_by_date.map(r => r.ic);
      Plotly.newPlot('ic-chart', [{
        type: 'bar', x, y, marker: { color: y.map(v => v >= 0 ? '#22c55e' : '#ef4444') },
      }], plotLayout({ y: 'IC' }), { displayModeBar: false, responsive: true });
    }
    if (m.fold_metrics) {
      $('fold-table').innerHTML = m.fold_metrics.map(f =>
        `<tr><td class="py-1">${f.fold}</td><td class="py-1 text-right">${f.n_train.toLocaleString()}</td><td class="py-1 text-right">${f.n_test.toLocaleString()}</td><td class="py-1 text-right ${fmt.scoreColor(f.ic_mean)}">${fmt.num(f.ic_mean, 4)}</td></tr>`
      ).join('');
    }
  } catch (e) {
    $('fi-chart').innerHTML = `<div class="text-slate-500 text-xs">모델 미학습 — '모델 재학습' 버튼을 눌러주세요.</div>`;
  }
}

$('btn-train').onclick = async () => {
  const r = await fetchJSON('/api/train', { method: 'POST' });
  $('train-status').textContent = '학습 시작됨 — 진행 상황을 30초마다 확인합니다...';
  pollTrain();
};

async function pollTrain() {
  const stop = startTimer('train-status', '학습 중');
  const id = setInterval(async () => {
    try {
      const s = await fetchJSON('/api/train/status');
      if (!s.running) {
        clearInterval(id); stop();
        if (s.error) {
          $('train-status').textContent = '❌ ' + s.error;
        } else if (s.result) {
          $('train-status').textContent = `✅ 완료 — OOF IC ${fmt.num(s.result.oof_ic_mean, 4)} (n=${s.result.n_rows.toLocaleString()})`;
          loadModelInfo();
        } else {
          $('train-status').textContent = '대기 중';
        }
      }
    } catch (e) {}
  }, 5000);
}

// === Data stats ===
async function loadDataStats() {
  const s = await fetchJSON('/api/data/stats');
  $('data-stats').textContent = JSON.stringify(s, null, 2);
}

function plotLayout(extra = {}) {
  return {
    margin: { t: 20, l: 50, r: 20, b: 30 },
    paper_bgcolor: '#0f172a', plot_bgcolor: '#0f172a',
    font: { color: '#e2e8f0' },
    xaxis: { gridcolor: '#1e293b', title: extra.x || '' },
    yaxis: { gridcolor: '#1e293b', title: extra.y || '' },
    legend: { orientation: 'h', y: 1.05 },
  };
}

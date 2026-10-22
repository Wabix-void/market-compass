/* 商情罗盘 MarketCompass — 前端逻辑（原生 JS，无第三方依赖） */

const state = {
  cat: '',
  days: 56,
  loaded: { overview: false, ranking: false, audit: false },
  trend: [],
  bands: [],
  lastAdvice: null,
  marketCategoryId: null,
};

const $ = (sel) => document.querySelector(sel);

/* ---------------- 工具 ---------------- */
const esc = (value) => String(value ?? '').replace(/[&<>"]/g,
  (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));

const num = (value, digits = 0) => (value === null || value === undefined || isNaN(value))
  ? '--' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });

const money = (value) => (value === null || value === undefined || isNaN(value))
  ? '--' : '¥' + Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 });

const pct = (value, digits = 1) => (value === null || value === undefined || isNaN(value))
  ? '--' : (Number(value) * 100).toFixed(digits) + '%';

const signedPct = (value) => {
  if (value === null || value === undefined || isNaN(value)) return '--';
  const cls = value >= 0 ? 'pos' : 'neg';
  return `<span class="${cls}">${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%</span>`;
};

const status = (text) => { $('#footerStatus').textContent = text; };

async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch { throw new Error('返回内容不是 JSON：' + text.slice(0, 120)); }
  if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
  return data;
}

/* ---------------- 图表（Canvas） ---------------- */
function prepare(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width < 10) return null;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  return { ctx, w: rect.width, h: rect.height };
}

function drawTrend(canvas, rows) {
  const env = prepare(canvas);
  if (!env || !rows.length) return;
  const { ctx, w, h } = env;
  const pad = { l: 56, r: 12, t: 14, b: 26 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;

  const highs = rows.map((r) => Number(r.sps_high || r.sps || 0));
  const lows = rows.map((r) => Number(r.sps_low || r.sps || 0));
  const mids = rows.map((r) => Number(r.sps || 0));
  const max = Math.max(...highs, 1) * 1.08;
  const min = 0;
  const x = (i) => pad.l + (rows.length === 1 ? innerW / 2 : (innerW * i) / (rows.length - 1));
  const y = (v) => pad.t + innerH - ((v - min) / (max - min)) * innerH;

  // 网格与 Y 轴
  ctx.strokeStyle = '#eef1f6';
  ctx.fillStyle = '#8b95a7';
  ctx.font = '11px system-ui, sans-serif';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 4; i++) {
    const value = min + ((max - min) * i) / 4;
    const py = y(value);
    ctx.beginPath(); ctx.moveTo(pad.l, py); ctx.lineTo(w - pad.r, py); ctx.stroke();
    ctx.fillText(num(value), pad.l - 8, py + 4);
  }

  // 不确定区间
  ctx.beginPath();
  rows.forEach((r, i) => { const px = x(i), py = y(Number(r.sps_high || r.sps || 0)); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
  for (let i = rows.length - 1; i >= 0; i--) { ctx.lineTo(x(i), y(Number(rows[i].sps_low || rows[i].sps || 0))); }
  ctx.closePath();
  ctx.fillStyle = 'rgba(47, 111, 235, .13)';
  ctx.fill();

  // 折线
  ctx.beginPath();
  mids.forEach((v, i) => { const px = x(i), py = y(v); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
  ctx.strokeStyle = '#2f6feb';
  ctx.lineWidth = 2;
  ctx.stroke();

  // X 轴标签
  ctx.fillStyle = '#8b95a7';
  ctx.textAlign = 'center';
  const ticks = [0, Math.floor(rows.length / 2), rows.length - 1];
  ticks.forEach((i) => {
    if (rows[i]) ctx.fillText(String(rows[i].stat_date).slice(5), x(i), h - 8);
  });
}

function drawBars(canvas, items) {
  const env = prepare(canvas);
  if (!env || !items.length) return;
  const { ctx, w, h } = env;
  const pad = { l: 14, r: 14, t: 18, b: 46 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const max = Math.max(...items.map((i) => i.value), 1);
  const slot = innerW / items.length;
  const barW = Math.min(slot * 0.56, 54);

  items.forEach((item, index) => {
    const cx = pad.l + slot * index + slot / 2;
    const height = (item.value / max) * innerH;
    const top = pad.t + innerH - height;

    const gradient = ctx.createLinearGradient(0, top, 0, pad.t + innerH);
    gradient.addColorStop(0, item.value > 0 ? '#2f6feb' : '#d5dbe6');
    gradient.addColorStop(1, item.value > 0 ? '#8fb4f8' : '#e6eaf2');
    ctx.fillStyle = gradient;
    ctx.beginPath();
    const r = Math.min(6, barW / 2);
    ctx.moveTo(cx - barW / 2, pad.t + innerH);
    ctx.lineTo(cx - barW / 2, top + r);
    ctx.quadraticCurveTo(cx - barW / 2, top, cx - barW / 2 + r, top);
    ctx.lineTo(cx + barW / 2 - r, top);
    ctx.quadraticCurveTo(cx + barW / 2, top, cx + barW / 2, top + r);
    ctx.lineTo(cx + barW / 2, pad.t + innerH);
    ctx.closePath();
    ctx.fill();

    ctx.fillStyle = '#4a5568';
    ctx.font = '11px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(item.label, cx, pad.t + innerH + 16);
    ctx.fillStyle = '#8b95a7';
    ctx.fillText(item.shareLabel, cx, pad.t + innerH + 32);
    ctx.fillStyle = '#2f6feb';
    ctx.fillText(num(item.value), cx, Math.max(top - 6, 12));
  });
}

/* ---------------- 顶部元信息 ---------------- */
async function loadMeta() {
  const meta = await api('/api/meta');
  const targets = [$('#catSelect'), $('#advCategory')];
  const subs = meta.categories.filter((c) => c.level === 2);
  targets.forEach((select) => {
    subs.forEach((cat) => {
      const option = document.createElement('option');
      option.value = cat.category_id;
      option.textContent = cat.name;
      select.appendChild(option);
    });
  });
  const aiOnline = Boolean(meta.llm_provider) && !String(meta.llm_provider).includes('offline');
  const badge = $('#llmBadge');
  badge.textContent = aiOnline
    ? '● AI 在线 · ' + String(meta.llm_provider).replace('openai-compat:', '') + ' ▾'
    : '○ AI 离线 · 模板模式 ▾';
  badge.className = 'badge ' + (aiOnline ? 'ai-on' : 'ghost');
  badge.title = aiOnline
    ? String(meta.llm_provider)
    : '未配置大模型（行情分析、证据链校验照常工作）';
  $('#periodBadge').textContent = '数据窗口 ' + meta.period[0] + ' ~ ' + meta.period[1];
  $('#metricNote').textContent = meta.metric_note;
}

/* ---------------- 品类大盘 ---------------- */
function renderKpis(overview) {
  const cards = [
    { label: '销量代理总量', value: num(overview.total_sps), sub: '件当量 · SPS', accent: true },
    { label: '销售额估计', value: money(overview.total_gms), sub: 'SPS × 期间均价' },
    { label: '在售商品数', value: num(overview.listing_count), sub: '去重后商品条目' },
    { label: '环比变化', value: `${overview.growth >= 0 ? '+' : ''}${pct(overview.growth)}`, sub: '后半窗口 vs 前半窗口', cls: overview.growth >= 0 ? 'pos' : 'neg' },
    { label: 'CR5 集中度', value: overview.cr5.toFixed(3), sub: 'Top5 销量代理占比' },
    { label: 'HHI', value: overview.hhi.toFixed(4), sub: '>0.15 视为高度集中' },
    { label: '平均置信度', value: overview.avg_confidence.toFixed(3), sub: '信号完整度加权' },
  ];
  $('#kpiGrid').innerHTML = cards.map((card) => `
    <div class="kpi ${card.accent ? 'accent' : ''}">
      <div class="label">${esc(card.label)}</div>
      <div class="value ${card.cls || ''}">${esc(card.value)}</div>
      <div class="sub">${esc(card.sub)}</div>
    </div>`).join('');
}

function renderSubcategories(items) {
  $('#subcatTable').innerHTML = items.map((item) => `
    <tr>
      <td><strong>${esc(item.name)}</strong></td>
      <td class="num">${num(item.total_sps)}</td>
      <td class="num">${money(item.total_gms)}</td>
      <td class="num">${num(item.listing_count)}</td>
      <td class="num">${item.cr5.toFixed(3)}</td>
      <td class="num">${item.hhi.toFixed(4)}</td>
      <td class="num">${num(item.heat_index)}</td>
      <td class="num">
        <span class="bar" style="width:${Math.max(item.gap_index * 0.6, 3)}px"></span>
        ${item.gap_index.toFixed(1)}
      </td>
      <td class="num">${item.avg_confidence.toFixed(2)}</td>
    </tr>`).join('');
}

async function loadOverview() {
  status('加载品类大盘…');
  const query = `category_id=${encodeURIComponent(state.cat)}&days=${state.days}`;
  const [overview, trend, bands, subcats] = await Promise.all([
    api('/api/overview?' + query),
    api('/api/trend?' + query),
    api('/api/price-bands?' + query),
    api('/api/subcategories?days=' + state.days),
  ]);
  state.trend = trend;
  state.bands = bands;
  renderKpis(overview);
  const scoped = state.cat ? subcats.filter((s) => s.category_id === state.cat) : subcats;
  renderSubcategories(scoped.length ? scoped : subcats);
  drawTrend($('#chartTrend'), trend);
  drawBars($('#chartBands'), bands.map((b) => ({
    label: b.high ? `${b.low}-${b.high}` : `${b.low}+`,
    value: b.sps,
    shareLabel: pct(b.sps_share, 0) + ' · ' + b.listing_count + '款',
  })));
  state.loaded.overview = true;
  status('就绪');
}

/* ---------------- 商品排行 ---------------- */
async function loadRanking() {
  status('加载商品排行…');
  const params = new URLSearchParams({
    category_id: state.cat,
    days: String(state.days),
    sort: $('#rankSort').value,
    limit: '40',
  });
  const keyword = $('#rankQuery').value.trim();
  if (keyword) params.set('q', keyword);
  const rows = await api('/api/products?' + params.toString());
  $('#rankTable').innerHTML = rows.map((row, index) => `
    <tr class="clickable" data-id="${esc(row.product_id)}">
      <td>${index + 1}</td>
      <td>${esc(row.title)}<div class="note">${esc(row.brand || '')} · ${esc(row.category_id)}</div></td>
      <td><span class="tag grey">${esc(row.platform_name)}</span></td>
      <td class="num">${money(row.price)}</td>
      <td class="num">${num(row.sps)}</td>
      <td class="num">${money(row.gms)}</td>
      <td class="num">${signedPct(row.growth)}</td>
      <td class="num">${row.confidence.toFixed(2)}</td>
      <td><button class="btn small" type="button">档案</button></td>
    </tr>`).join('');

  $('#rankTable').querySelectorAll('tr').forEach((tr) => {
    tr.addEventListener('click', () => {
      switchTab('detail');
      loadDetail(tr.dataset.id);
    });
  });
  state.loaded.ranking = true;
  status('就绪');
}

/* ---------------- 单品档案 ---------------- */
async function searchProducts() {
  const keyword = $('#detailQuery').value.trim();
  const params = new URLSearchParams({ limit: '12' });
  if (keyword) params.set('q', keyword);
  if (state.cat) params.set('category_id', state.cat);
  const rows = await api('/api/products?' + params.toString());
  $('#detailResults').innerHTML = rows.map((row) => `
    <div class="resultitem" data-id="${esc(row.product_id)}">
      <strong>${esc(row.title)}</strong>
      <span class="tag grey">${esc(row.platform_name)}</span>
      <span class="note">销量代理 ${num(row.sps)} · ${money(row.price)} · 置信度 ${row.confidence.toFixed(2)}</span>
    </div>`).join('');
  $('#detailResults').querySelectorAll('.resultitem').forEach((item) => {
    item.addEventListener('click', () => loadDetail(item.dataset.id));
  });
}

async function loadDetail(productId) {
  if (!productId) return;
  status('加载单品档案…');
  const data = await api('/api/products/' + encodeURIComponent(productId));
  const last = data.series.length ? data.series[data.series.length - 1] : null;

  const competitorRows = (data.competitors || []).map((item) => `
    <tr>
      <td>${esc(item.title)}</td>
      <td><span class="tag grey">${esc(item.platform_name)}</span></td>
      <td class="num">${money(item.price)}</td>
      <td class="num">${num(item.sps)}</td>
      <td class="num">${Number(item.match_score).toFixed(2)}</td>
      <td class="note">${esc(item.match_reason || '')}</td>
    </tr>`).join('');

  const review = data.review ? `
    <div class="kv">
      <div><div class="k">评价总数</div><div class="v">${num(data.review.review_cnt)}</div></div>
      <div><div class="k">正面情感</div><div class="v pos">${pct(data.review.sentiment_pos)}</div></div>
      <div><div class="k">负面情感</div><div class="v neg">${pct(data.review.sentiment_neg)}</div></div>
    </div>
    <div class="badge-line">${data.review.keywords.map((k) => `<span class="chip">${esc(k)}</span>`).join('')}</div>`
    : '<p class="note">暂无评价聚合数据</p>';

  $('#detailBody').innerHTML = `
    <div class="card">
      <h3>${esc(data.title)}</h3>
      <div class="badge-line">
        <span class="chip">${esc(data.platform_name)}</span>
        <span class="chip">${esc(data.brand || '未知品牌')}</span>
        <span class="chip">${esc(data.category_id)}</span>
        ${Object.entries(data.attrs || {}).map(([k, v]) => `<span class="chip">${esc(k)}:${esc(v)}</span>`).join('')}
      </div>
      <div class="kv">
        <div><div class="k">最新价格</div><div class="v">${money(data.evidence && data.evidence.signals ? data.evidence.signals.price : null)}</div></div>
        <div><div class="k">销量代理（窗口合计）</div><div class="v">${num(data.series.reduce((sum, s) => sum + s.sps_mid, 0))}</div></div>
        <div><div class="k">销售额估计</div><div class="v">${money(data.series.reduce((sum, s) => sum + s.gms_mid, 0))}</div></div>
        <div><div class="k">数据置信度</div><div class="v">${last ? last.confidence.toFixed(3) : '--'}</div></div>
      </div>
      <canvas id="chartDetail"></canvas>
    </div>

    <div class="card">
      <h3>跨平台同款对比 <small>同款识别：品牌 + 规格 + 材质 + 标题相似度</small></h3>
      <div class="tablewrap">
        <table>
          <thead><tr><th>商品</th><th>平台</th><th class="num">价格</th><th class="num">销量代理</th><th class="num">匹配分</th><th>匹配依据</th></tr></thead>
          <tbody>${competitorRows || '<tr><td colspan="6" class="note">未找到跨平台同款</td></tr>'}</tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h3>评价聚合（仅统计，不留存个人信息）</h3>
      ${review}
    </div>

    <div class="card">
      <h3>指标证据链 <small>最近一日，可追溯到原始公开信号</small></h3>
      <pre class="evidence">${esc(JSON.stringify(data.evidence, null, 2))}</pre>
    </div>`;

  drawTrend($('#chartDetail'), data.series.map((s) => ({
    stat_date: s.stat_date, sps: s.sps_mid, sps_low: s.sps_low, sps_high: s.sps_high,
  })));
  status('就绪');
}

/* ---------------- AI 选品参谋 ---------------- */
function renderReport(report, selector = '#advResult') {
  const verification = report.verification || { checked: [], failed: [], passed: false };
  const chips = [
    `<span class="chip">生成方式：${esc(report.generated_by)}</span>`,
    `<span class="chip">整体置信度：${Number(report.confidence).toFixed(3)}</span>`,
    `<span class="chip ${verification.passed ? 'ok' : 'bad'}">证据链校验：${verification.passed ? '通过（' + verification.checked.length + ' 条全部复现）' : '未通过'}</span>`,
    `<span class="chip">窗口：${esc((report.period || []).join(' ~ '))}</span>`,
  ].join('');

  const evidenceRows = report.evidence.map((item) => `
    <tr>
      <td><code>${esc(item.metric)}</code><div class="note">${esc(item.note || '')}</div></td>
      <td class="num">${typeof item.value === 'number' ? num(item.value, item.value < 1 ? 3 : 1) : esc(item.value)}</td>
      <td class="num">${esc(item.period)}</td>
      <td>${esc(item.source)}</td>
      <td class="num">${Number(item.confidence).toFixed(2)}</td>
    </tr>`).join('');

  const actionItems = report.actions.map((action) => `
    <li><strong>${esc(action.step)}</strong>
      <span class="why">${esc(action.reason)}　引用指标：<code>${esc(action.evidence_metric)}</code></span>
    </li>`).join('');

  const knowledge = (report.knowledge || []).map((entry) =>
    `<li><strong>${esc(entry.title)}</strong>：${esc(entry.text)}<span class="why">来源：${esc(entry.source)}</span></li>`).join('');

  const failed = verification.failed.length
    ? `<div class="card"><h3>未通过的引用</h3><pre class="evidence">${esc(JSON.stringify(verification.failed, null, 2))}</pre></div>` : '';

  document.querySelector(selector).innerHTML = `
    <div class="card">
      <div class="summary">${esc(report.summary)}</div>
      <div class="badge-line">${chips}</div>
      <p>${esc(report.conclusion)}</p>
    </div>

    <div class="card">
      <h3>建议动作 <small>每条动作绑定一个可复现的指标</small></h3>
      <ul class="actions">${actionItems || '<li>无</li>'}</ul>
    </div>

    <div class="card">
      <h3>证据链</h3>
      <div class="tablewrap">
        <table>
          <thead><tr><th>指标</th><th class="num">数值</th><th class="num">周期</th><th>来源</th><th class="num">置信度</th></tr></thead>
          <tbody>${evidenceRows}</tbody>
        </table>
      </div>
    </div>

    <div class="grid2">
      <div class="card">
        <h3>风险提示</h3>
        <ul class="plain">${report.risks.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>
      </div>
      <div class="card">
        <h3>局限性声明</h3>
        <ul class="plain">${report.limitations.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>
      </div>
    </div>

    <div class="card">
      <h3>检索到的知识条目</h3>
      <ul class="plain">${knowledge || '<li>无</li>'}</ul>
    </div>
    ${failed}`;
}

async function runAdvisor() {
  status('生成建议并校验证据链…');
  $('#advResult').innerHTML = '<div class="card"><p class="note">正在计算指标、检索知识并校验证据链…</p></div>';
  try {
    const report = await api('/api/advice', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        category_id: $('#advCategory').value || null,
        budget: Number($('#advBudget').value || 150),
        risk: $('#advRisk').value,
        goal: $('#advGoal').value,
      }),
    });
    state.lastAdvice = report;
    renderReport(report, '#advResult');
    showAdvAskCard();
    status('就绪');
  } catch (error) {
    $('#advResult').innerHTML = `<div class="card"><p class="neg">生成失败：${esc(error.message)}</p></div>`;
    status('生成失败');
  }
}

function showAdvAskCard() {
  $('#advAskCard').style.display = 'block';
  $('#advAskResult').innerHTML = '';
  $('#advAskInput').value = '';
}

async function runAdviceAsk() {
  const question = $('#advAskInput').value.trim();
  if (!question) {
    $('#advAskResult').innerHTML = '<p class="note">请先输入你的问题</p>';
    return;
  }
  status('模型作答并校验数字溯源…');
  $('#advAskResult').innerHTML = `
    <div class="ai-steps">
      <span class="ai-step done">① 读取建议报告</span>
      <span class="ai-step active">② 模型作答中…</span>
      <span class="ai-step">③ 数字溯源校验</span>
    </div>
    <p class="note">依据上方建议报告作答；完成后会逐个核对回答中的数字。</p>`;

  const startedAt = performance.now();
  try {
    const data = await api('/api/advice/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        category_id: $('#advCategory').value || null,
        budget: Number($('#advBudget').value || 150),
        risk: $('#advRisk').value,
        goal: $('#advGoal').value,
      }),
    });
    const elapsed = Math.round(performance.now() - startedAt);
    $('#advAskResult').innerHTML = renderAsk(data) + renderAskTrace(data, elapsed);
    status('就绪');
  } catch (error) {
    $('#advAskResult').innerHTML = `<p class="note">追问失败：${esc(error.message)}</p>`;
    status('追问失败');
  }
}

/* ---------------- 商品行情分析（自由输入） ---------------- */
const MARKET_EXAMPLES = ['保温杯', '露营折叠椅', '猫爬架', '收纳箱', '保鲜盒', '宠物窝'];

function bindChips(container) {
  container.querySelectorAll('.chip.link').forEach((el) => {
    el.addEventListener('click', () => {
      $('#mktQuery').value = el.dataset.word;
      // data-cat 存在时直接锁定标的，避免同名类目（演示数据 vs 真实数据）再次歧义
      state.marketCategoryId = el.dataset.cat || null;
      switchTab('market');
      runMarketAnalysis();
    });
  });
}

function renderMarketExamples() {
  $('#mktExamples').innerHTML = '<span class="note">试试：</span>' + MARKET_EXAMPLES
    .map((word) => `<span class="chip link" data-word="${esc(word)}">${esc(word)}</span>`).join('');
  bindChips($('#mktExamples'));
}

function renderMarketData(snapshot) {
  const confidence = snapshot.confidence_dist;
  const bandRows = snapshot.price_bands.map((band) => `
    <tr>
      <td>${esc(band.band)} 元</td>
      <td class="num">${num(band.listing_count)}</td>
      <td class="num">${num(band.sps)}</td>
      <td class="num">${pct(band.sps_share)}</td>
    </tr>`).join('');

  const brandRows = snapshot.brand_shares.slice(0, 8).map((item) => `
    <tr>
      <td>${esc(item.brand)}</td>
      <td class="num">${num(item.sps)}</td>
      <td class="num">${item.listing_count}</td>
      <td class="num">${pct(item.share)}</td>
    </tr>`).join('');

  const subRows = snapshot.subcategories.map((item) => `
    <tr>
      <td>${esc(item.name)}</td>
      <td class="num">${num(item.total_sps)}</td>
      <td class="num">${item.listing_count}</td>
      <td class="num">${pct(item.share)}</td>
    </tr>`).join('');

  const productRows = snapshot.top_products.map((item, index) => `
    <tr class="clickable" data-id="${esc(item.product_id)}">
      <td>${index + 1}</td>
      <td>${esc(item.title)}<div class="note">${esc(item.brand || '')}</div></td>
      <td><span class="tag grey">${esc(item.platform_name)}</span></td>
      <td class="num">${money(item.price)}</td>
      <td class="num">${num(item.sps)}</td>
      <td class="num">${money(item.gms)}</td>
      <td class="num">${signedPct(item.growth)}</td>
      <td class="num">${item.confidence.toFixed(2)}</td>
    </tr>`).join('');

  const moverRows = (items) => items.map((item) => `
    <tr>
      <td>${esc(item.title.slice(0, 26))}<div class="note">${esc(item.platform_name)} · ${money(item.price)}</div></td>
      <td class="num">${signedPct(item.growth)}</td>
      <td class="num">${num(item.sps)}</td>
    </tr>`).join('');

  const keywordChips = (items, cls) => items.length
    ? items.map((k) => `<span class="chip ${cls}">${esc(k.keyword)} ×${k.count}</span>`).join('')
    : '<span class="note">无</span>';

  const kpis = [
    { label: '销量代理总量', value: num(snapshot.total_sps), sub: '件当量', accent: true },
    { label: '销售额估计', value: money(snapshot.total_gms), sub: 'SPS × 均价' },
    { label: '在售条目', value: num(snapshot.listing_count), sub: '去重商品数' },
    { label: '环比变化', value: `${snapshot.growth >= 0 ? '+' : ''}${pct(snapshot.growth)}`, sub: '后半 vs 前半窗口', cls: snapshot.growth >= 0 ? 'pos' : 'neg' },
    { label: 'CR5', value: snapshot.cr5.toFixed(3), sub: 'Top5 销量代理占比' },
    { label: 'HHI', value: snapshot.hhi.toFixed(4), sub: '>0.15 高度集中' },
    { label: '品牌 CR3', value: snapshot.brand_cr3.toFixed(3), sub: 'Top3 品牌份额' },
    { label: '平均价格', value: money(snapshot.avg_price), sub: '在售均价' },
    { label: '负面词占比', value: pct(snapshot.negative_keyword_share), sub: '评价痛点集中度' },
    { label: '供需缺口', value: num(snapshot.gap_index, 1), sub: '0-100，越高越缺供给' },
    { label: '需求热度', value: num(snapshot.heat_index), sub: '公开搜索指数均值' },
    { label: '平均置信度', value: snapshot.avg_confidence.toFixed(3), sub: '信号完整度加权' },
  ];

  return `
    <div class="kpis">${kpis.map((k) => `
      <div class="kpi ${k.accent ? 'accent' : ''}">
        <div class="label">${esc(k.label)}</div>
        <div class="value ${k.cls || ''}">${esc(k.value)}</div>
        <div class="sub">${esc(k.sub)}</div>
      </div>`).join('')}</div>

    <div class="grid2">
      <div class="card">
        <h3>价格带分布</h3>
        <div class="tablewrap"><table>
          <thead><tr><th>价格带</th><th class="num">商品数</th><th class="num">销量代理</th><th class="num">占比</th></tr></thead>
          <tbody>${bandRows}</tbody>
        </table></div>
      </div>
      <div class="card">
        <h3>品牌份额</h3>
        <div class="tablewrap"><table>
          <thead><tr><th>品牌</th><th class="num">销量代理</th><th class="num">商品数</th><th class="num">份额</th></tr></thead>
          <tbody>${brandRows}</tbody>
        </table></div>
      </div>
    </div>

    ${snapshot.subcategories.length > 1 ? `
    <div class="card">
      <h3>细分结构</h3>
      <div class="tablewrap"><table>
        <thead><tr><th>细分</th><th class="num">销量代理</th><th class="num">商品数</th><th class="num">占比</th></tr></thead>
        <tbody>${subRows}</tbody>
      </table></div>
    </div>` : ''}

    <div class="card">
      <h3>销量代理 Top 商品 <small>点击行可查看单品档案与证据链</small></h3>
      <div class="tablewrap"><table>
        <thead><tr><th>#</th><th>商品</th><th>平台</th><th class="num">价格</th>
        <th class="num">销量代理</th><th class="num">销售额估计</th><th class="num">环比</th><th class="num">置信度</th></tr></thead>
        <tbody>${productRows}</tbody>
      </table></div>
    </div>

    <div class="grid2">
      <div class="card">
        <h3>增长最快</h3>
        <div class="tablewrap"><table>
          <thead><tr><th>商品</th><th class="num">环比</th><th class="num">销量代理</th></tr></thead>
          <tbody>${moverRows(snapshot.top_growth)}</tbody>
        </table></div>
      </div>
      <div class="card">
        <h3>下滑明显</h3>
        <div class="tablewrap"><table>
          <thead><tr><th>商品</th><th class="num">环比</th><th class="num">销量代理</th></tr></thead>
          <tbody>${moverRows(snapshot.top_decline)}</tbody>
        </table></div>
      </div>
    </div>

    <div class="card">
      <h3>评价关键词 <small>痛点即为差异化机会</small></h3>
      <p class="note">负面/痛点词（占 ${pct(snapshot.negative_keyword_share)}）</p>
      <div class="badge-line">${keywordChips(snapshot.keywords.negative, 'warn')}</div>
      <p class="note">正面/卖点词</p>
      <div class="badge-line">${keywordChips(snapshot.keywords.positive, 'ok')}</div>
    </div>

    <div class="card">
      <h3>数据置信度分布</h3>
      <div class="badge-line">
        <span class="chip ok">高（≥0.80）：${confidence.high} 个</span>
        <span class="chip">中（0.55-0.80）：${confidence.mid} 个</span>
        <span class="chip warn">低（&lt;0.55）：${confidence.low} 个（不纳入候选）</span>
      </div>
    </div>`;
}

function renderMarketResult(data) {
  if (!data.matched) {
    const candidates = (data.candidates || []).map((item) =>
      `<span class="chip link" data-word="${esc(item.label)}" data-cat="${esc(item.category_id || '')}">`
      + `${esc(item.label)} · ${esc(item.source_label || '')} · ${item.products || 0} 款 (${item.score})</span>`).join('');
    $('#mktResult').innerHTML = `
      <div class="card">
        <h3>当前数据未覆盖「${esc(data.query)}」</h3>
        <p>${esc(data.message)}</p>
        <div class="badge-line">${candidates || '<span class="note">暂无相近标的</span>'}</div>
      </div>`;
    bindChips($('#mktResult'));
    return;
  }

  const snapshot = data.snapshot;
  const report = data.report;
  const best = data.resolution.best;
  const kindLabel = { subcategory: '细分类目', parent: '一级类目', brand: '品牌' }[best.kind] || best.kind;

  // 同名类目可能来自不同数据源，把其它候选也列出来让用户显式切换
  const others = (data.resolution.candidates || [])
    .filter((item) => item.category_id && item.category_id !== snapshot.category.category_id
      && item.kind !== 'brand')
    .map((item) =>
      `<span class="chip link" data-word="${esc(item.label)}" data-cat="${esc(item.category_id)}">`
      + `换用：${esc(item.label)} · ${esc(item.source_label || '')} · ${item.products || 0} 款</span>`).join('');

  $('#mktResult').innerHTML = `
    <div class="card">
      <h3>解析结果</h3>
      <div class="badge-line">
        <span class="chip ok">命中「${esc(best.label)}」（${esc(kindLabel)}${best.source_label ? ' · ' + esc(best.source_label) : ''}）</span>
        <span class="chip">匹配方式：${esc(best.reason)}</span>
        <span class="chip">匹配度：${best.score}</span>
        <span class="chip">分析范围：${esc(snapshot.category.name)}（${snapshot.listing_count} 个条目）</span>
        <span class="chip">窗口：${esc(snapshot.period.join(' ~ '))}</span>
      </div>
      ${others ? `<div class="badge-line">${others}</div>` : ''}
      <p class="note">${esc(data.resolution.message)}</p>
    </div>
    ${renderMarketData(snapshot)}
    <div id="mktReport"></div>`;

  $('#mktResult').querySelectorAll('tr.clickable').forEach((tr) => {
    tr.addEventListener('click', () => { switchTab('detail'); loadDetail(tr.dataset.id); });
  });
  bindChips($('#mktResult'));
  renderReport(report, '#mktReport');
  showAskCard();
}

async function runMarketAnalysis() {
  const query = $('#mktQuery').value.trim();
  if (!query) {
    $('#mktResult').innerHTML = '<div class="card"><p class="neg">请先输入要投资的商品名</p></div>';
    return;
  }
  status('解析商品、计算行情并校验证据链…');
  $('#mktResult').innerHTML = '<div class="card"><p class="note">正在解析标的、计算行情指标并校验证据链…</p></div>';
  try {
    const data = await api('/api/market-analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        category_id: state.marketCategoryId || null,
        budget: Number($('#mktBudget').value || 150),
        risk: $('#mktRisk').value,
        goal: '行情分析',
      }),
    });
    renderMarketResult(data);
    status('就绪');
  } catch (error) {
    $('#mktResult').innerHTML = `<div class="card"><p class="neg">分析失败：${esc(error.message)}</p></div>`;
    status('分析失败');
  }
}

/* ---------------- AI 追问（模型作答 + 数字溯源校验） ---------------- */
function showAskCard() {
  $('#mktAskCard').style.display = 'block';
  $('#askResult').innerHTML = '';
  $('#askInput').value = '';
}

function renderAsk(data) {
  if (!data.matched) {
    return `<p class="note">${esc(data.message || '标的未覆盖，无法追问')}</p>`;
  }
  if (!data.answer) {
    return `<p class="note">${esc(data.note || '模型暂时不可用')}</p>`;
  }
  // 正常情况下只留一个轻量标记；只有真的出现无法溯源的数字时才展开说明
  const badge = data.verified
    ? `<span class="chip ok">数字已核对（${(data.citations || []).length} 个）</span>`
    : `<span class="chip bad">${data.unverified.length} 个数字无法溯源</span>`;
  const detail = data.verified ? '' : `
    <div class="note" style="color:#c0392b">
      指标层找不到出处：${data.unverified.map((n) => `<code>${esc(n)}</code>`).join(' ')}
    </div>`;

  return `<p>${esc(data.answer)}</p><div class="badge-line">${badge}</div>${detail}`;
}

async function runAsk() {
  const question = $('#askInput').value.trim();
  const query = $('#mktQuery').value.trim();
  if (!question) {
    $('#askResult').innerHTML = '<p class="note">请先输入你的问题</p>';
    return;
  }
  if (!query) {
    $('#askResult').innerHTML = '<p class="note">请先在上方完成一次行情分析</p>';
    return;
  }
  status('模型作答并校验数字溯源…');
  // 把「AI 在做什么」显式摊开：取数 → 作答 → 校验，而不是一个黑盒转圈
  $('#askResult').innerHTML = `
    <div class="ai-steps">
      <span class="ai-step done">① 从指标层取快照</span>
      <span class="ai-step active">② 模型作答中…</span>
      <span class="ai-step">③ 数字溯源校验</span>
    </div>
    <p class="note">模型只组织语言，数值全部来自指标层；作答完成后会逐个核对回答中的数字。</p>`;

  const startedAt = performance.now();
  try {
    const data = await api('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        question,
        category_id: state.marketCategoryId || null,
      }),
    });
    const elapsed = Math.round(performance.now() - startedAt);
    $('#askResult').innerHTML = renderAsk(data) + renderAskTrace(data, elapsed);
    status('就绪');
  } catch (error) {
    $('#askResult').innerHTML = `<p class="note">追问失败：${esc(error.message)}</p>`;
    status('追问失败');
  }
}

/** 渲染「取数 → 作答 → 校验」三步轨迹，把 AI 的工作量变成可观察的数字。 */
function renderAskTrace(data, elapsed) {
  if (!data || !data.answer) return '';
  const pool = data.metric_pool_size || 0;
  const checked = (data.citations || []).length + (data.unverified || []).length;
  const bad = (data.unverified || []).length;
  const step3 = bad
    ? `<span class="ai-step done">③ 溯源校验 ${checked} 个数字 · ${bad} 个可疑</span>`
    : `<span class="ai-step done">③ 溯源校验 ${checked} 个数字 · 全部可追溯</span>`;
  return `
    <div class="ai-steps">
      <span class="ai-step done">① 指标快照 ${pool} 个数值</span>
      <span class="ai-step done">② 模型作答</span>
      ${step3}
      <span class="ai-step done">端到端 ${elapsed} ms</span>
    </div>`;
}

/* ---------------- AI 接入设置（BYOK：用户自带密钥） ---------------- */
const AI_PROTOCOL_PRESET = {
  openai: {
    url: 'https://api.deepseek.com/v1',
    hint: '请填写兼容 OpenAI Chat Completions 协议的地址，通常以 /v1 结尾。',
  },
  anthropic: {
    url: 'https://api.deepseek.com/anthropic',
    hint: '请填写兼容 Anthropic Messages 协议的 API 地址。',
  },
};

const aiState = { protocol: 'openai', dirty: false, hasKey: false };

function toast(message) {
  let node = document.getElementById('appToast');
  if (!node) {
    node = document.createElement('div');
    node.id = 'appToast';
    node.className = 'toast';
    document.body.appendChild(node);
  }
  node.textContent = message;
  node.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => node.classList.remove('show'), 2200);
}

function setAiError(message) {
  const node = $('#aiFormError');
  node.textContent = message || '';
  node.hidden = !message;
}

function updateModelStatus() {
  const count = $('#aiModelList').querySelectorAll('.model-row').length;
  $('#aiModelStatus').textContent = count
    ? `已配置 ${count} 个模型`
    : '正在使用适配器默认模型';
}

function buildModelRow(id, display) {
  const row = document.createElement('div');
  row.className = 'model-row';

  const idInput = document.createElement('input');
  idInput.type = 'text';
  idInput.className = 'model-id';
  idInput.placeholder = 'deepseek-flash';
  idInput.spellcheck = false;
  idInput.value = id || '';

  const displayInput = document.createElement('input');
  displayInput.type = 'text';
  displayInput.className = 'model-display';
  displayInput.placeholder = 'DeepSeek-V4.1-Flash';
  displayInput.spellcheck = false;
  displayInput.value = display || '';

  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'icon-btn';
  remove.setAttribute('aria-label', '删除该模型');
  remove.title = '删除';
  remove.textContent = '🗑';
  remove.addEventListener('click', () => {
    row.remove();
    updateModelStatus();
    aiState.dirty = true;
  });

  [idInput, displayInput].forEach((input) => {
    input.addEventListener('input', () => { aiState.dirty = true; });
  });

  row.append(idInput, displayInput, remove);
  return row;
}

function renderModelRows(models) {
  const list = $('#aiModelList');
  list.innerHTML = '';
  (models || []).forEach((model) => list.appendChild(buildModelRow(model.id, model.display)));
  updateModelStatus();
}

function readModelRows() {
  return Array.from($('#aiModelList').querySelectorAll('.model-row')).map((row) => ({
    id: row.querySelector('.model-id').value.trim(),
    display: row.querySelector('.model-display').value.trim(),
  })).filter((model) => model.id);
}

function setAiProtocol(protocol) {
  aiState.protocol = protocol;
  document.querySelectorAll('.seg-btn').forEach((button) => {
    button.classList.toggle('active', button.dataset.proto === protocol);
  });
  const preset = AI_PROTOCOL_PRESET[protocol] || AI_PROTOCOL_PRESET.openai;
  $('#aiBaseUrl').placeholder = preset.url;
  $('#aiBaseHint').textContent = preset.hint;
}

function fillAiForm(config) {
  setAiProtocol(config.protocol || 'openai');
  $('#aiBaseUrl').value = config.base_url || '';
  $('#aiKey').value = '';
  aiState.hasKey = Boolean(config.has_key);
  $('#aiKey').placeholder = config.has_key ? config.key_masked : '留空使用已保存凭证';
  $('#aiClearKey').hidden = !config.has_key;
  // 未填界面配置时说明「为什么现在也能用」——否则用户会以为没接入
  $('#aiNotice').hidden = Boolean(config.has_key);
  renderModelRows(config.models || []);
  aiState.dirty = false;
  setAiError('');
  const result = $('#aiTestResult');
  result.textContent = '';
  result.className = 'ai-test-result';
}

async function openAiSettings() {
  $('#aiMenu').hidden = true;
  $('#aiModal').hidden = false;
  setAiError('');
  try {
    fillAiForm(await api('/api/ai/config'));
  } catch (error) {
    setAiError('读取配置失败：' + error.message);
  }
}

function closeAiSettings(force) {
  if (!force && aiState.dirty && !window.confirm('放弃未保存的修改？')) return;
  $('#aiModal').hidden = true;
  aiState.dirty = false;
}

async function testAiConnection() {
  const button = $('#aiTest');
  const result = $('#aiTestResult');
  button.disabled = true;
  button.textContent = '测试中…';
  result.className = 'ai-test-result';
  result.textContent = '';
  try {
    const models = readModelRows();
    const data = await api('/api/ai/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        protocol: aiState.protocol,
        base_url: $('#aiBaseUrl').value.trim(),
        api_key: $('#aiKey').value.trim(),
        model: models[0] ? models[0].id : '',
      }),
    });
    if (data.ok) {
      result.className = 'ai-test-result ok';
      result.textContent = '连接成功 · ' + data.latency_ms + ' ms';
    } else {
      result.className = 'ai-test-result bad';
      result.textContent = data.error || '连接失败';
      if (data.detail) result.title = data.detail;
    }
  } catch (error) {
    result.className = 'ai-test-result bad';
    result.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = '测试连接';
  }
}

async function saveAiSettings() {
  const baseUrl = $('#aiBaseUrl').value.trim();
  const key = $('#aiKey').value.trim();

  if (baseUrl && !/^https?:\/\//i.test(baseUrl)) {
    setAiError('请输入以 http:// 或 https:// 开头的合法地址');
    return;
  }
  if (key && key.length < 8) {
    setAiError('密钥长度至少 8 个字符');
    return;
  }
  if (key && /\s/.test(key)) {
    setAiError('密钥不能包含空格');
    return;
  }
  const models = readModelRows();
  const ids = models.map((model) => model.id);
  if (new Set(ids).size !== ids.length) {
    setAiError('模型 ID 不能重复');
    return;
  }

  setAiError('');
  const button = $('#aiSave');
  button.disabled = true;
  try {
    const config = await api('/api/ai/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        protocol: aiState.protocol,
        base_url: baseUrl,
        api_key: key,
        models,
      }),
    });
    fillAiForm(config);
    closeAiSettings(true);
    toast('配置已保存');
    await loadMeta();
  } catch (error) {
    setAiError('保存失败：' + error.message);
  } finally {
    button.disabled = false;
  }
}

async function clearAiCredentials() {
  if (!window.confirm('确定清除已保存的凭证吗？清除后需重新填写密钥。')) return;
  try {
    fillAiForm(await api('/api/ai/credentials', { method: 'DELETE' }));
    toast('已清除保存的凭证');
    await loadMeta();
  } catch (error) {
    setAiError('清除失败：' + error.message);
  }
}

async function quickTestConnection() {
  $('#aiMenu').hidden = true;
  toast('正在测试连接…');
  try {
    const data = await api('/api/ai/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    toast(data.ok ? '连接正常 · ' + data.latency_ms + ' ms'
                  : '连接失败：' + (data.error || '未知错误'));
  } catch (error) {
    toast('连接失败：' + error.message);
  }
}

/* ---------------- 合规审计 ---------------- */
async function loadAudit() {
  const [logs, clusters] = await Promise.all([api('/api/audit'), api('/api/clusters')]);
  $('#auditTable').innerHTML = logs.map((log) => `
    <tr>
      <td>${log.log_id}</td>
      <td>${esc(log.source)}</td>
      <td class="note">${esc(log.url)}</td>
      <td class="note">${esc(log.fetched_at)}</td>
      <td>${log.robots_allowed ? '<span class="tag">允许</span>' : '<span class="tag warn">跳过</span>'}</td>
      <td class="note">${esc(log.fields)}</td>
      <td class="num">${num(log.records)}</td>
      <td class="note">${esc(log.batch_id)}</td>
    </tr>`).join('');
  $('#clusterTable').innerHTML = clusters.map((item) => `
    <tr>
      <td><code>${esc(item.cluster_id)}</code></td>
      <td>${esc(item.canonical_title)}</td>
      <td>${esc(item.category_id)}</td>
      <td class="num">${item.listing_count}</td>
    </tr>`).join('');
  state.loaded.audit = true;
}

/* ---------------- 页签切换 ---------------- */
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach((btn) => btn.classList.toggle('active', btn.dataset.tab === tab));
  document.querySelectorAll('.panel').forEach((panel) => panel.classList.toggle('active', panel.id === 'sec-' + tab));
  if (tab === 'overview') {
    if (!state.loaded.overview) { loadOverview().catch(reportError); } else {
      drawTrend($('#chartTrend'), state.trend);
      drawBars($('#chartBands'), state.bands.map((b) => ({
        label: b.high ? `${b.low}-${b.high}` : `${b.low}+`,
        value: b.sps, shareLabel: pct(b.sps_share, 0) + ' · ' + b.listing_count + '款',
      })));
    }
  }
  if (tab === 'ranking' && !state.loaded.ranking) loadRanking().catch(reportError);
  if (tab === 'detail' && !$('#detailResults').children.length) searchProducts().catch(reportError);
  if (tab === 'audit' && !state.loaded.audit) loadAudit().catch(reportError);
}

function reportError(error) {
  status('出错了');
  console.error(error);
}

/* ---------------- 初始化 ---------------- */
async function boot() {
  try {
    await loadMeta();
    await loadOverview();
    await searchProducts();
    renderMarketExamples();
  } catch (error) {
    reportError(error);
    $('#kpiGrid').innerHTML = `<div class="kpi"><div class="label">加载失败</div><div class="value neg">!</div><div class="sub">${esc(error.message)}</div></div>`;
  }
}

document.querySelectorAll('.tab').forEach((btn) => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
$('#refreshBtn').addEventListener('click', () => {
  state.cat = $('#catSelect').value;
  state.days = Number($('#daysSelect').value);
  state.loaded.overview = false;
  state.loaded.ranking = false;
  const tab = document.querySelector('.tab.active').dataset.tab;
  if (tab === 'overview') loadOverview().catch(reportError);
  else if (tab === 'ranking') loadRanking().catch(reportError);
  else { loadOverview().catch(reportError); loadRanking().catch(reportError); }
});
$('#rankSearchBtn').addEventListener('click', () => { state.loaded.ranking = false; loadRanking().catch(reportError); });
$('#rankQuery').addEventListener('keydown', (event) => { if (event.key === 'Enter') $('#rankSearchBtn').click(); });
$('#detailSearchBtn').addEventListener('click', () => searchProducts().catch(reportError));
$('#detailQuery').addEventListener('keydown', (event) => { if (event.key === 'Enter') searchProducts().catch(reportError); });
$('#advRun').addEventListener('click', runAdvisor);
$('#advAskRun').addEventListener('click', runAdviceAsk);
$('#advAskInput').addEventListener('keydown', (event) => { if (event.key === 'Enter') runAdviceAsk(); });

// ---- AI 接入（顶栏下拉 + BYOK 面板）----
$('#llmBadge').addEventListener('click', (event) => {
  event.stopPropagation();
  const menu = $('#aiMenu');
  menu.hidden = !menu.hidden;
  $('#llmBadge').setAttribute('aria-expanded', String(!menu.hidden));
  if (!menu.hidden) {
    $('#aiMenuTitle').textContent = $('#llmBadge').textContent || 'AI 状态';
    $('#aiMenuSub').textContent = $('#llmBadge').title || '';
  }
});
document.addEventListener('click', (event) => {
  const menu = $('#aiMenu');
  if (menu.hidden) return;
  if (event.target.closest('.ai-menu-wrap')) return;
  menu.hidden = true;
  $('#llmBadge').setAttribute('aria-expanded', 'false');
});
$('#aiOpenSettings').addEventListener('click', openAiSettings);
$('#aiQuickTest').addEventListener('click', quickTestConnection);
$('#aiTest').addEventListener('click', testAiConnection);
$('#aiSave').addEventListener('click', saveAiSettings);
$('#aiCancel').addEventListener('click', () => closeAiSettings(false));
$('#aiClearKey').addEventListener('click', clearAiCredentials);
$('#aiAddModel').addEventListener('click', () => {
  const row = buildModelRow('', '');
  $('#aiModelList').appendChild(row);
  updateModelStatus();
  row.querySelector('.model-id').focus();
  aiState.dirty = true;
});
document.querySelectorAll('.seg-btn').forEach((button) => {
  button.addEventListener('click', () => {
    setAiProtocol(button.dataset.proto);
    aiState.dirty = true;
  });
});
$('#aiBaseUrl').addEventListener('input', () => { aiState.dirty = true; });
$('#aiKey').addEventListener('input', () => { aiState.dirty = true; });
$('#aiModal').addEventListener('click', (event) => {
  if (event.target.id === 'aiModal') closeAiSettings(false);
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !$('#aiModal').hidden) closeAiSettings(false);
});
$('#mktRun').addEventListener('click', runMarketAnalysis);
$('#mktQuery').addEventListener('keydown', (event) => { if (event.key === 'Enter') runMarketAnalysis(); });
// 用户手动改动输入内容时，解除之前锁定的标的，重新走文本解析
$('#mktQuery').addEventListener('input', () => { state.marketCategoryId = null; });
$('#askRun').addEventListener('click', runAsk);
$('#askInput').addEventListener('keydown', (event) => { if (event.key === 'Enter') runAsk(); });
window.addEventListener('resize', () => {
  if (document.querySelector('.tab.active').dataset.tab === 'overview') {
    drawTrend($('#chartTrend'), state.trend);
    drawBars($('#chartBands'), state.bands.map((b) => ({
      label: b.high ? `${b.low}-${b.high}` : `${b.low}+`,
      value: b.sps, shareLabel: pct(b.sps_share, 0) + ' · ' + b.listing_count + '款',
    })));
  }
});

boot();

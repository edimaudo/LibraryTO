const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const numberFormat = new Intl.NumberFormat('en-CA', { maximumFractionDigits: 0 });
const decimalFormat = new Intl.NumberFormat('en-CA', { maximumFractionDigits: 2 });
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]));
const fmt = (value) => value === null || value === undefined || value === '' ? '—' : numberFormat.format(value);
const fmtDecimal = (value) => value === null || value === undefined || value === '' ? '—' : decimalFormat.format(value);
const page = $('#main').dataset.page;
const pageContent = $('#page-content');
let chartSequence = 0;
const chartRegistry = new Map();
const mapInstances = new Map();
const responseCache = new Map();
const CACHE_VERSION = $('#main').dataset.cacheVersion || 'local';
const CACHE_TTL_MS = 5 * 60 * 1000;
const CACHE_STALE_MS = 30 * 60 * 1000;
const scriptPromises = new Map();
let chartObserver = null;
const TIER_COLORS = { DL: '#176b87', NL: '#4e8468', RR: '#94639a', Other: '#7b858b' };

function pruneOldSessionCache() {
  try {
    const currentPrefix = `libraryto-cache:${CACHE_VERSION}:`;
    const obsoleteKeys = [];
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith('libraryto-cache:') && !key.startsWith(currentPrefix)) obsoleteKeys.push(key);
    }
    obsoleteKeys.forEach((key) => sessionStorage.removeItem(key));
  } catch (_) { /* Session storage can be disabled by browser policy. */ }
}
pruneOldSessionCache();

function loadScriptOnce(key, src) {
  if (window[key]) return Promise.resolve(window[key]);
  if (scriptPromises.has(key)) return scriptPromises.get(key);
  const promise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.onload = () => window[key] ? resolve(window[key]) : reject(new Error(`${key} did not initialise`));
    script.onerror = () => reject(new Error(`Unable to load ${key}`));
    document.head.appendChild(script);
  });
  scriptPromises.set(key, promise);
  return promise;
}
const ensurePlotly = () => loadScriptOnce('Plotly', 'https://cdn.plot.ly/plotly-2.35.2.min.js');
const ensureLeaflet = () => loadScriptOnce('L', 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js');
function ensureLeafletStyles() {
  if (document.querySelector('link[data-leaflet-style]')) return Promise.resolve();
  return new Promise((resolve) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet'; link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    link.dataset.leafletStyle = 'true'; link.onload = resolve; link.onerror = resolve;
    document.head.appendChild(link);
  });
}
function ensureInterFont() {
  if (document.querySelector('link[data-inter-font]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet'; link.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;450;500;550;600;650;700&display=swap';
  link.dataset.interFont = 'true';
  document.head.appendChild(link);
}
ensureInterFont();

const descriptions = {
  overview: 'Explore library activity, branch information and service patterns.',
  branches: 'Select a branch to view its services, activity and programs.',
  comparisons: 'Choose branches to compare their reported services and annual activity.',
  events: 'Find upcoming library programs by interest, audience, language, branch and time.'
};
$('#page-description').textContent = descriptions[page] || '';

function safeReadSetting(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}
function safeWriteSetting(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* Preference remains available for this page view. */ }
}
const themeToggle = $('#theme-toggle');
const scaleSelect = $('#font-scale');
function setTheme(theme) {
  const value = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = value;
  themeToggle.textContent = value === 'dark' ? 'Light mode' : 'Dark mode';
  themeToggle.setAttribute('aria-label', `Switch to ${value === 'dark' ? 'light' : 'dark'} mode`);
  safeWriteSetting('libraryto-theme', value);
  document.dispatchEvent(new CustomEvent('libraryto:themechange'));
}
function setScale(scale) {
  const value = ['small', 'medium', 'large'].includes(scale) ? scale : 'medium';
  document.documentElement.dataset.scale = value;
  scaleSelect.value = value;
  safeWriteSetting('libraryto-scale', value);
}
const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
setTheme(safeReadSetting('libraryto-theme') || (prefersDark ? 'dark' : 'light'));
setScale(safeReadSetting('libraryto-scale') || 'medium');
themeToggle.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'));
scaleSelect.addEventListener('change', (event) => setScale(event.target.value));

function readSessionCache(cacheKey) {
  try {
    const raw = sessionStorage.getItem(`libraryto-cache:${CACHE_VERSION}:${cacheKey}`);
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}
function writeSessionCache(cacheKey, entry) {
  try { sessionStorage.setItem(`libraryto-cache:${CACHE_VERSION}:${cacheKey}`, JSON.stringify(entry)); } catch (_) { /* Keep the in-memory cache when storage is full or unavailable. */ }
}
async function fetchJson(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { Accept: 'application/json', ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.error || payload.message || `Request failed (${response.status})`);
  return payload;
}
async function getJson(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  if (method !== 'GET') return fetchJson(url, options);
  const cacheKey = `${method}:${url}`;
  const now = Date.now();
  let cached = responseCache.get(cacheKey);
  if (!cached) {
    cached = readSessionCache(cacheKey);
    if (cached) responseCache.set(cacheKey, cached);
  }
  if (cached && now - cached.time < CACHE_TTL_MS) return cached.value;
  if (cached && now - cached.time < CACHE_STALE_MS) {
    fetchJson(url, options).then((value) => {
      const entry = { time: Date.now(), value };
      responseCache.set(cacheKey, entry);
      writeSessionCache(cacheKey, entry);
    }).catch(() => {});
    return cached.value;
  }
  const payload = await fetchJson(url, options);
  const entry = { time: Date.now(), value: payload };
  responseCache.set(cacheKey, entry);
  writeSessionCache(cacheKey, entry);
  return payload;
}
function empty(message) { return `<div class="empty-state">${esc(message)}</div>`; }
function notice(message, type = '') { return `<div class="notice ${type}" role="status">${esc(message)}</div>`; }
function csvExportButton(url, label = 'Download CSV') {
  return `<a class="button secondary export-button" href="${esc(url)}">${esc(label)}</a>`;
}
function safeHttpUrl(value) {
  const raw = String(value || '').trim();
  try {
    const parsed = new URL(raw);
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : '';
  } catch (_) { return ''; }
}
function humanTier(value) { return value || 'Not specified'; }
function renderTable(headers, rows, options = {}) {
  if (!rows.length) return empty(options.emptyMessage || 'No matching information is available.');
  const headerHtml = headers.map((header) => `<th scope="col">${esc(header)}</th>`).join('');
  const rowHtml = rows.map((row) => `<tr>${row.map((cell) => {
    const value = cell && typeof cell === 'object' && Object.hasOwn(cell, 'html') ? cell.html : esc(cell);
    const className = cell && typeof cell === 'object' ? (cell.className || '') : '';
    return `<td class="${esc(className)}">${value}</td>`;
  }).join('')}</tr>`).join('');
  return `<div class="table-wrap" tabindex="0" role="region" aria-label="Scrollable data table"><table><thead><tr>${headerHtml}</tr></thead><tbody>${rowHtml}</tbody></table></div>`;
}
function tableDetails(label, headers, rows) {
  return `<details class="data-details"><summary>View ${esc(label.toLowerCase())} data</summary>${renderTable(headers, rows)}</details>`;
}

function makeChartId(spec) {
  const id = `plot-${++chartSequence}`;
  chartRegistry.set(id, spec);
  return id;
}
function lineChart(points, label) {
  if (!points || !points.length) return empty(`No ${label.toLowerCase()} history is available.`);
  const id = makeChartId({
    traces: [{
      type: 'scatter', mode: 'lines+markers', name: label,
      x: points.map((point) => String(point.year)), y: points.map((point) => Number(point.value)),
      line: { width: 3 }, marker: { size: 7 },
      hovertemplate: `%{x}<br>${esc(label)}: %{y:,.0f}<extra></extra>`
    }],
    title: `${label} by year`,
    rows: points.map((point) => [point.year, fmtDecimal(point.value)]),
    headers: ['Year', 'Value']
  });
  return `<div class="chart-block"><div class="chart-tools"><button type="button" class="chart-download" data-download-chart="${id}">Download chart</button></div><div id="${id}" class="plotly-chart" role="img" aria-label="Interactive chart: ${esc(label)} by year"></div>${tableDetails(`${label} history`, chartRegistry.get(id).headers, chartRegistry.get(id).rows)}</div>`;
}
function multiLineChart(yearRows, branches, metricLabel) {
  const rows = yearRows || [];
  if (!rows.length || !branches.length) return empty(`No ${metricLabel.toLowerCase()} comparisons are available.`);
  const traces = branches.map((branch) => ({
    type: 'scatter', mode: 'lines+markers', name: branch.name,
    x: rows.map((row) => String(row.year)),
    y: rows.map((row) => row.values[branch.code] == null ? null : Number(row.values[branch.code])),
    connectgaps: false, line: { width: 2.5 }, marker: { size: 6 },
    hovertemplate: `%{x}<br>${esc(branch.name)}: %{y:,.0f}<extra></extra>`
  }));
  const headers = ['Year', ...branches.map((branch) => branch.name)];
  const tableRows = rows.map((row) => [row.year, ...branches.map((branch) => fmt(row.values[branch.code]))]);
  const id = makeChartId({ traces, title: `${metricLabel} by branch`, headers, rows: tableRows });
  return `<div class="chart-block"><div class="chart-tools"><button type="button" class="chart-download" data-download-chart="${id}">Download chart</button></div><div id="${id}" class="plotly-chart" role="img" aria-label="Interactive ${esc(metricLabel)} comparison by branch"></div></div>`;
}
function forecastChart(history, forecast, label) {
  const historical = history || [];
  const estimates = forecast?.forecasts || [];
  if (!historical.length && !estimates.length) return empty(`No ${label.toLowerCase()} forecast is available.`);
  const last = historical[historical.length - 1];
  const traces = [];
  if (historical.length) traces.push({
    type: 'scatter', mode: 'lines+markers', name: 'Reported',
    x: historical.map((point) => String(point.year)), y: historical.map((point) => Number(point.value)),
    line: { width: 2.5 }, marker: { size: 6 }, hovertemplate: '%{x}<br>Reported: %{y:,.0f}<extra></extra>'
  });
  if (estimates.length) traces.push({
    type: 'scatter', mode: 'lines+markers', name: 'Estimate',
    x: [...(last ? [String(last.year)] : []), ...estimates.map((point) => String(point.year))],
    y: [...(last ? [Number(last.value)] : []), ...estimates.map((point) => Number(point.value))],
    line: { width: 3, dash: 'dash' }, marker: { size: 7 }, hovertemplate: '%{x}<br>Estimate: %{y:,.0f}<extra></extra>'
  });
  const tableRows = [
    ...historical.map((point) => [point.year, 'Reported', fmtDecimal(point.value)]),
    ...estimates.map((point) => [point.year, 'Estimate', fmtDecimal(point.value)])
  ];
  const headers = ['Year', 'Type', 'Value'];
  const id = makeChartId({ traces, title: `${label} reported values and estimates`, headers, rows: tableRows });
  return `<div class="chart-block"><div class="chart-tools"><button type="button" class="chart-download" data-download-chart="${id}">Download chart</button></div><div id="${id}" class="plotly-chart" role="img" aria-label="Interactive chart showing reported ${esc(label)} and 2025 and 2026 estimates"></div>${tableDetails(`${label} forecast`, headers, tableRows)}</div>`;
}

function plotLayout(spec) {
  const css = getComputedStyle(document.documentElement);
  const text = css.getPropertyValue('--text').trim() || '#17232b';
  const muted = css.getPropertyValue('--muted').trim() || '#52616a';
  const line = css.getPropertyValue('--line').trim() || '#d2dce1';
  const base = {
    title: { text: spec.title, x: 0.02, xanchor: 'left', font: { size: 14, color: text } },
    autosize: true, height: 310, margin: { l: 66, r: 22, t: 48, b: 55 },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Inter, sans-serif', color: text, size: 12 },
    xaxis: { title: '', gridcolor: line, linecolor: line, tickfont: { color: muted }, automargin: true, showspikes: false },
    yaxis: { title: '', gridcolor: line, linecolor: line, tickfont: { color: muted }, tickformat: ',.0f', rangemode: 'tozero', automargin: true, showspikes: false },
    legend: { orientation: 'h', y: -0.23, font: { color: muted } },
    hovermode: 'closest', dragmode: 'pan', showlegend: spec.traces.length > 1,
    uirevision: `${page}-${spec.title}`
  };
  const overrides = spec.layout || {};
  return { ...base, ...overrides,
    xaxis: { ...base.xaxis, ...(overrides.xaxis || {}) },
    yaxis: { ...base.yaxis, ...(overrides.yaxis || {}) },
    title: { ...base.title, ...(overrides.title || {}) },
    legend: { ...base.legend, ...(overrides.legend || {}) }
  };
}
function renderPlotlyCharts(root = document) {
  const elements = $$('.plotly-chart', root).filter((element) =>
    element.dataset.rendered !== 'true' && element.dataset.observed !== 'true'
  );
  if (!elements.length) return;

  const draw = (element) => {
    if (!element || element.dataset.rendered === 'true' || !window.Plotly) return;
    const spec = chartRegistry.get(element.id);
    if (!spec) return;
    const plotly = window.Plotly;
    element.dataset.loading = 'false';
    element.dataset.rendered = 'true';
    element.setAttribute('aria-busy', 'false');
    try {
      Promise.resolve(plotly.newPlot(element, spec.traces, plotLayout(spec), {
        responsive: true, displaylogo: false, scrollZoom: false,
        modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d']
      })).catch(() => {
        element.dataset.rendered = 'false';
        element.textContent = 'The chart could not be displayed.';
      });
    } catch (_) {
      element.dataset.rendered = 'false';
      element.textContent = 'The chart could not be displayed.';
    }
  };

  const loadAndDraw = (element) => {
    if (window.Plotly) { draw(element); return; }
    element.dataset.loading = 'true';
    element.setAttribute('aria-busy', 'true');
    element.textContent = 'Loading chart…';
    ensurePlotly().then(() => draw(element)).catch(() => {
      element.dataset.loading = 'false';
      element.setAttribute('aria-busy', 'false');
      element.textContent = 'Chart library unavailable.';
    });
  };

  if ('IntersectionObserver' in window) {
    if (!chartObserver) chartObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        chartObserver.unobserve(entry.target);
        loadAndDraw(entry.target);
      });
    }, { rootMargin: '160px 0px' });
    elements.forEach((element) => {
      element.dataset.observed = 'true';
      chartObserver.observe(element);
    });
  } else {
    elements.forEach(loadAndDraw);
  }
}
function resizePlotlyCharts(root) {
  if (!window.Plotly?.Plots?.resize) return;
  $$('.plotly-chart[data-rendered="true"]', root).forEach((element) => window.Plotly.Plots.resize(element));
}

document.addEventListener('libraryto:themechange', () => {
  if (!window.Plotly) return;
  $$('.plotly-chart[data-rendered="true"]').forEach((element) => {
    const spec = chartRegistry.get(element.id);
    if (spec) window.Plotly.relayout(element, plotLayout(spec));
  });
});
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-download-chart]');
  if (!button || !window.Plotly) return;
  const chart = document.getElementById(button.dataset.downloadChart);
  if (chart) window.Plotly.downloadImage(chart, { format: 'png', filename: 'libraryto-chart', width: 1200, height: 700, scale: 2 });
});

function parseDateTime(value) {
  if (!value) return null;
  const raw = String(value).trim();
  const dateOnly = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnly) return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]));
  let parsed = new Date(raw);
  if (!Number.isNaN(parsed.getTime())) return parsed;
  const match = raw.match(/^(\d{4}-\d{2}-\d{2})[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)$/i);
  if (match) {
    let hour = Number(match[2]) % 12;
    if (match[5].toUpperCase() === 'PM') hour += 12;
    parsed = new Date(`${match[1]}T${String(hour).padStart(2, '0')}:${match[3]}:${match[4] || '00'}`);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  return null;
}
function formatDateTime(value, includeDate = true) {
  if (!value) return 'Time not supplied';
  const parsed = parseDateTime(value);
  if (!parsed) return String(value);
  const datePart = new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: 'short', day: 'numeric' }).format(parsed);
  const timePart = new Intl.DateTimeFormat('en-CA', { hour: 'numeric', minute: '2-digit' }).format(parsed);
  return includeDate ? `${datePart} · ${timePart}` : timePart;
}
function humanizeKey(value) {
  return String(value).replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/^./, (c) => c.toUpperCase());
}
function friendlyGraphValue(key, value) {
  if (value == null || value === '') return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  const keyText = String(key).toLowerCase();
  if (/(date|time|created|updated|timestamp)/.test(keyText)) {
    if (typeof value === 'number' || /^\d{10,13}$/.test(String(value))) {
      const numeric = Number(value);
      const parsed = new Date(numeric > 1e12 ? numeric : numeric * 1000);
      if (!Number.isNaN(parsed.getTime())) return formatDateTime(parsed.toISOString());
    }
    return formatDateTime(value);
  }
  return String(value);
}
function renderEvidence(evidence) {
  if (!evidence || !evidence.length) return '';
  const details = evidence.map((item, index) => {
    const props = Object.entries(item.properties || {}).slice(0, 8);
    const connectionItems = (item.connections || []).slice(0, 5).map((connection) => {
      const related = Object.entries(connection.related_properties || {}).slice(0, 5);
      const relatedSummary = related.map(([key, value]) => `${humanizeKey(key)}: ${friendlyGraphValue(key, value)}`).join(' · ');
      return `<li>${esc((connection.related_labels || []).join(', ') || 'Related information')}${relatedSummary ? ` — ${esc(relatedSummary)}` : ''}</li>`;
    }).join('');
    const propsHtml = props.map(([key, value]) => `<div class="fact-row"><dt>${esc(humanizeKey(key))}</dt><dd>${esc(friendlyGraphValue(key, value))}</dd></div>`).join('');
    return `<article class="evidence-item"><h4>${esc((item.labels || []).join(' · ') || `Related item ${index + 1}`)}</h4><dl>${propsHtml}</dl>${connectionItems ? `<div class="connected-facts"><strong>Connected to</strong><ul>${connectionItems}</ul></div>` : ''}</article>`;
  }).join('');
  return `<details class="supporting-details"><summary>Supporting details (${evidence.length})</summary><div class="evidence-list">${details}</div></details>`;
}
function formatTabState(tabList, target) {
  $$('.branch-tab', tabList).forEach((tab) => {
    const selected = tab.dataset.tab === target;
    tab.setAttribute('aria-selected', selected ? 'true' : 'false');
    tab.tabIndex = selected ? 0 : -1;
  });
  $$('.branch-tabpanel').forEach((panel) => { panel.hidden = panel.id !== `tab-${target}`; });
  const panel = $(`#tab-${target}`);
  if (panel) renderPlotlyCharts(panel);
}

function enableTabKeyboard(tabList, tabSelector) {
  tabList.addEventListener('keydown', (event) => {
    const current = event.target.closest(tabSelector);
    if (!current) return;
    const tabs = $$(tabSelector, tabList);
    let index = tabs.indexOf(current);
    if (event.key === 'ArrowRight') index = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') index = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') index = 0;
    else if (event.key === 'End') index = tabs.length - 1;
    else return;
    event.preventDefault();
    tabs[index].focus();
    tabs[index].click();
  });
}

function chartMarkup(title, traces, layout = {}, ariaLabel = title) {
  const id = makeChartId({ traces, title, layout });
  return `<div class="chart-block"><div class="chart-tools"><button type="button" class="chart-download" data-download-chart="${id}">Download chart</button></div><div id="${id}" class="plotly-chart" role="img" aria-label="${esc(ariaLabel)}"></div></div>`;
}
function yearOptions(years, selected) {
  return (years || []).map((year) => `<option value="${esc(year)}" ${String(year) === String(selected) ? 'selected' : ''}>${esc(year)}</option>`).join('');
}
function metricRows(data, metric, year) {
  const record = (data.annual_values?.[metric] || []).find((item) => String(item.year) === String(year));
  if (!record) return [];
  return data.branches.map((branch) => ({ branch, value: record.values?.[branch.code] }))
    .filter((item) => item.value !== null && item.value !== undefined && Number.isFinite(Number(item.value)));
}
function metricName(metric) {
  return ({ circulation: 'Circulation', visits: 'Visitation', workstations: 'Workstation Usage', registrations: 'Card Registrations' })[metric] || metric;
}
function tierCode(branch) { return branch.service_tier_code || 'Other'; }
function tierName(code) {
  return ({ DL: 'District Library', NL: 'Neighbourhood Library', RR: 'Research & Reference Library', Other: 'Other' })[code] || code;
}
function renderRankCharts(data, year) {
  return Object.keys(data.metrics).map((metric) => {
    const rows = metricRows(data, metric, year).sort((a, b) => Number(a.value) - Number(b.value));
    const bottom = rows.slice(0, 10);
    const top = rows.slice(-10).reverse();
    const make = (title, list) => {
      if (!list.length) return empty(`No ${metricName(metric).toLowerCase()} values are available for ${year}.`);
      const trace = [{
        type: 'bar', orientation: 'h',
        x: list.map((item) => Number(item.value)),
        y: list.map((item) => item.branch.name),
        marker: { color: '#28758c' },
        customdata: list.map((item) => [item.branch.code, tierName(tierCode(item.branch))]),
        hovertemplate: '%{y}<br>%{x:,.0f}<br>Branch: %{customdata[0]}<br>%{customdata[1]}<extra></extra>'
      }];
      return chartMarkup(title, trace, {
        height: 340,
        margin: { l: 145, r: 20, t: 42, b: 40 },
        xaxis: { title: '', rangemode: 'tozero', tickformat: ',.0f' },
        yaxis: { title: '', autorange: 'reversed', automargin: true, tickfont: { size: 10 } },
        showlegend: false
      }, `${title}, ${year}`);
    };
    const label = metricName(metric);
    return `<article class="panel"><h3 class="subheading">${esc(label)}</h3><div class="grid grid-2 rank-pair"><div><h4>Top 10</h4>${make(`Top 10 Annual ${label}`, top)}</div><div><h4>Bottom 10</h4>${make(`Bottom 10 Annual ${label}`, bottom)}</div></div></article>`;
  }).join('');
}
function renderDistributionCharts(data, year) {
  return Object.keys(data.metrics).map((metric) => {
    const rows = metricRows(data, metric, year);
    const tiers = ['DL', 'NL', 'RR', 'Other'];
    const traces = tiers.map((tier) => ({
      type: 'box', name: tierName(tier),
      y: rows.filter((item) => tierCode(item.branch) === tier).map((item) => Number(item.value)),
      marker: { color: TIER_COLORS[tier] }, line: { color: TIER_COLORS[tier] },
      boxpoints: 'outliers', hovertemplate: `${tierName(tier)}<br>%{y:,.0f}<extra></extra>`
    })).filter((trace) => trace.y.length);
    const title = `Annual ${metricName(metric)} distribution`;
    return `<article class="panel">${traces.length ? chartMarkup(title, traces, { height: 300, yaxis: { title: '', tickformat: ',.0f', rangemode: 'tozero' } }, `${title} by service tier`) : empty(`No values are available for ${year}.`)}</article>`;
  }).join('');
}
function renderFootprintCharts(data, year) {
  const metrics = Object.keys(data.metrics);
  return metrics.map((metric) => {
    const rows = metricRows(data, metric, year).filter((item) => item.branch.square_footage !== null && item.branch.square_footage !== undefined);
    const traces = ['DL', 'NL', 'RR', 'Other'].map((tier) => {
      const items = rows.filter((item) => tierCode(item.branch) === tier);
      return {
        type: 'scatter', mode: 'markers', name: tierName(tier),
        x: items.map((item) => Number(item.branch.square_footage)),
        y: items.map((item) => Number(item.value)),
        customdata: items.map((item) => [item.branch.name, tierName(tier), fmt(item.branch.square_footage), fmt(item.branch.workstations)]),
        marker: {
          color: TIER_COLORS[tier],
          size: items.map((item) => Math.max(5, Number(item.branch.workstations) || 5)),
          sizemode: 'area',
          sizeref: Math.max(1, (Math.max(1, ...items.map((item) => Number(item.branch.workstations) || 1)) * 2) / (24 ** 2)),
          sizemin: 5, opacity: 0.82, line: { width: 1, color: 'rgba(255,255,255,.65)' }
        },
        hovertemplate: '%{customdata[0]}<br>%{customdata[1]}<br>Area: %{customdata[2]} sq ft<br>Workstations: %{customdata[3]}<br>Value: %{y:,.0f}<extra></extra>'
      };
    }).filter((trace) => trace.x.length);
    const title = `Annual ${metricName(metric)} vs. Square Footage`;
    return `<article class="panel">${traces.length ? chartMarkup(title, traces, {
      height: 330,
      xaxis: { title: 'Square footage', tickformat: ',.0f', rangemode: 'tozero' },
      yaxis: { title: metricName(metric), tickformat: ',.0f', rangemode: 'tozero' }
    }, `${title}, coloured by service tier`) : empty(`No matched area and metric values are available for ${year}.`)}</article>`;
  }).join('');
}
function pearson(valuesA, valuesB) {
  const count = valuesA.length;
  if (count < 2) return null;
  const avgA = valuesA.reduce((sum, value) => sum + value, 0) / count;
  const avgB = valuesB.reduce((sum, value) => sum + value, 0) / count;
  let numerator = 0, denomA = 0, denomB = 0;
  for (let i = 0; i < count; i += 1) {
    const a = valuesA[i] - avgA, b = valuesB[i] - avgB;
    numerator += a * b; denomA += a * a; denomB += b * b;
  }
  const denominator = Math.sqrt(denomA * denomB);
  return denominator ? numerator / denominator : null;
}
function correlationData(data) {
  const metrics = Object.keys(data.metrics);
  const series = {};
  for (const metric of metrics) {
    const byKey = new Map();
    for (const yearRow of data.annual_values?.[metric] || []) {
      for (const branch of data.branches) {
        const value = yearRow.values?.[branch.code];
        if (value !== null && value !== undefined && Number.isFinite(Number(value))) {
          byKey.set(`${branch.code}::${yearRow.year}`, Number(value));
        }
      }
    }
    series[metric] = byKey;
  }
  const z = [], sampleN = [];
  for (const metricA of metrics) {
    const row = [], nRow = [];
    for (const metricB of metrics) {
      const valuesA = [], valuesB = [];
      for (const [key, valueA] of series[metricA]) {
        if (series[metricB].has(key)) {
          valuesA.push(valueA); valuesB.push(series[metricB].get(key));
        }
      }
      row.push(pearson(valuesA, valuesB)); nRow.push(valuesA.length);
    }
    z.push(row); sampleN.push(nRow);
  }
  return { metrics, z, sampleN };
}
function renderCorrelationChart(data) {
  const matrix = correlationData(data);
  const labels = matrix.metrics.map((metric) => metricName(metric));
  const trace = [{
    type: 'heatmap', x: labels, y: labels, z: matrix.z,
    zmin: -1, zmax: 1, zmid: 0, colorscale: 'RdBu', reversescale: true,
    customdata: matrix.sampleN,
    hovertemplate: '%{y} × %{x}<br>Correlation: %{z:.2f}<br>Matched branch-years: %{customdata}<extra></extra>',
    colorbar: { title: 'r' }
  }];
  return chartMarkup('Annual metric correlation', trace, {
    height: 410,
    margin: { l: 170, r: 70, t: 44, b: 110 },
    xaxis: { title: '', tickangle: -25, automargin: true },
    yaxis: { title: '', autorange: 'reversed', automargin: true },
    showlegend: false
  }, 'Correlation matrix using matched branch and reporting year observations');
}
function median(values) {
  const sorted = values.slice().sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
function renderQuadrant(data, year) {
  const rows = metricRows(data, 'visits', year).filter((item) => Number(item.branch.square_footage) > 0);
  if (!rows.length) return empty(`No matched visitation and square footage values are available for ${year}.`);
  const medianArea = median(rows.map((item) => Number(item.branch.square_footage)));
  const medianVisits = median(rows.map((item) => Number(item.value)));
  const groups = [
    { key: 'over', name: 'Overachievers', test: (item) => Number(item.branch.square_footage) <= medianArea && Number(item.value) >= medianVisits, color: '#27765b' },
    { key: 'large-high', name: 'Higher visitation, larger footprint', test: (item) => Number(item.branch.square_footage) > medianArea && Number(item.value) >= medianVisits, color: '#276c91' },
    { key: 'small-low', name: 'Lower visitation, smaller footprint', test: (item) => Number(item.branch.square_footage) <= medianArea && Number(item.value) < medianVisits, color: '#8a7846' },
    { key: 'under', name: 'Underutilized', test: (item) => Number(item.branch.square_footage) > medianArea && Number(item.value) < medianVisits, color: '#975d5a' }
  ];
  const traces = groups.map((group) => {
    const items = rows.filter(group.test);
    return {
      type: 'scatter', mode: 'markers', name: group.name,
      x: items.map((item) => Number(item.branch.square_footage)),
      y: items.map((item) => Number(item.value)),
      customdata: items.map((item) => [item.branch.name, item.branch.code, tierName(tierCode(item.branch))]),
      marker: { size: 10, color: group.color, opacity: 0.85 },
      hovertemplate: '%{customdata[0]}<br>%{customdata[1]}<br>%{customdata[2]}<br>Area: %{x:,.0f} sq ft<br>Annual visitation: %{y:,.0f}<extra></extra>'
    };
  });
  const lists = groups.map((group) => {
    const items = rows.filter(group.test).sort((a, b) => a.branch.name.localeCompare(b.branch.name));
    return `<article class="quadrant-group"><h4>${esc(group.name)} <span>${items.length}</span></h4>${items.length ? `<ul>${items.map((item) => `<li><a href="/branch-insights?branch=${encodeURIComponent(item.branch.code)}">${esc(item.branch.name)}</a><small>${fmt(item.value)} visits · ${fmt(item.branch.square_footage)} sq ft</small></li>`).join('')}</ul>` : '<p class="small-text">No branches in this group.</p>'}</article>`;
  }).join('');
  const title = `Annual Visitation vs. Square Footage · ${year}`;
  return `${chartMarkup(title, traces, {
    height: 420,
    xaxis: { title: 'Square footage', tickformat: ',.0f', rangemode: 'tozero' },
    yaxis: { title: 'Annual visitation', tickformat: ',.0f', rangemode: 'tozero' },
    shapes: [
      { type: 'rect', xref: 'x', yref: 'y', x0: 0, x1: medianArea, y0: 0, y1: medianVisits, fillcolor: 'rgba(138,120,70,.08)', line: { width: 0 }, layer: 'below' },
      { type: 'rect', xref: 'x', yref: 'y', x0: 0, x1: medianArea, y0: medianVisits, y1: Math.max(...rows.map((item) => Number(item.value))) * 1.05, fillcolor: 'rgba(39,118,91,.08)', line: { width: 0 }, layer: 'below' },
      { type: 'rect', xref: 'x', yref: 'y', x0: medianArea, x1: Math.max(...rows.map((item) => Number(item.branch.square_footage))) * 1.05, y0: 0, y1: medianVisits, fillcolor: 'rgba(151,93,90,.08)', line: { width: 0 }, layer: 'below' },
      { type: 'rect', xref: 'x', yref: 'y', x0: medianArea, x1: Math.max(...rows.map((item) => Number(item.branch.square_footage))) * 1.05, y0: medianVisits, y1: Math.max(...rows.map((item) => Number(item.value))) * 1.05, fillcolor: 'rgba(39,108,145,.08)', line: { width: 0 }, layer: 'below' }
    ]
  }, title)}<div class="quadrant-grid">${lists}</div><p class="small-text">Groups use the selected year's medians for square footage and visitation. This is a relative size-and-visitation comparison, not an overall branch quality rating.</p>`;
}
function renderTierTrendCharts(data) {
  return Object.keys(data.metrics).map((metric) => {
    const rows = data.tier_trends?.[metric] || [];
    const traces = [{
      type: 'scatter', mode: 'lines+markers', name: 'Network',
      x: rows.map((row) => String(row.year)), y: rows.map((row) => Number(row.network)),
      line: { width: 3, color: '#384f5a' }, marker: { size: 6 },
      hovertemplate: '%{x}<br>Network: %{y:,.0f}<extra></extra>'
    }];
    ['DL', 'NL', 'RR'].forEach((tier) => {
      traces.push({
        type: 'scatter', mode: 'lines+markers', name: tier,
        x: rows.map((row) => String(row.year)),
        y: rows.map((row) => row.tiers?.[tier]?.value ?? null),
        customdata: rows.map((row) => row.tiers?.[tier]?.n ?? 0),
        line: { width: 2, color: TIER_COLORS[tier] }, marker: { size: 5 }, connectgaps: false,
        hovertemplate: `%{x}<br>${tier}: %{y:,.0f}<br>Branches with values: %{customdata}<extra></extra>`
      });
    });
    const title = `Network vs. Service-Tier ${metricName(metric)}`;
    return `<article class="panel">${rows.length ? chartMarkup(title, traces, { height: 310 }, title) : empty('No annual service-tier observations are available.')}</article>`;
  }).join('');
}
function branchPopup(branch) {
  const services = (branch.services || []).length
    ? `<ul>${branch.services.map((service) => `<li>${esc(service)}</li>`).join('')}</ul>`
    : 'Not listed';
  const website = safeHttpUrl(branch.website);
  const phone = String(branch.telephone || '').trim();
  const phoneLink = phone ? `<a href="tel:${esc(phone.replace(/[^+\d]/g, ''))}">${esc(phone)}</a>` : 'Not listed';
  return `<div class="map-popup"><strong>${esc(branch.name)}</strong>
    <div><b>Type of Library:</b> ${esc(branch.type_of_library || humanTier(branch.service_tier))}</div>
    <div><b>Year Opened:</b> ${esc(branch.year_opened || 'Not listed')}</div>
    <div><b>Location:</b> ${esc(branch.address || 'Not listed')}${branch.postal_code ? `, ${esc(branch.postal_code)}` : ''}</div>
    <div><b># of Workstations:</b> ${fmt(branch.workstations)}</div>
    <div><b>Area:</b> ${fmt(branch.square_footage)} sq ft</div>
    <div><b>Services:</b>${services}</div>
    <div><b>Phone #:</b> ${phoneLink}</div>
    <div><b>Website:</b> ${website ? `<a href="${esc(website)}" target="_blank" rel="noopener noreferrer">${esc(website)}</a>` : 'Not listed'}</div></div>`;
}
function renderMapDirectory(branches, selector) {
  const host = $(selector);
  if (!host) return;
  host.innerHTML = renderTable(
    ['Branch', 'Address', 'Type of library'],
    branches.map((branch) => [
      { html: `<button type="button" class="map-branch-select" data-map-branch="${esc(branch.code)}">${esc(branch.name)}</button>` },
      branch.address || '—', branch.type_of_library || humanTier(branch.service_tier)
    ])
  );
}
function createBranchMap(elementId, branches, directorySelector, annualValues = {}, years = []) {
  const element = $(`#${elementId}`);
  if (!element) return;
  renderMapDirectory(branches, directorySelector);
  const located = branches.filter((branch) =>
    branch.lat !== null && branch.lat !== undefined && branch.lat !== '' &&
    branch.lon !== null && branch.lon !== undefined && branch.lon !== '' &&
    Number.isFinite(Number(branch.lat)) && Number.isFinite(Number(branch.lon)) &&
    Math.abs(Number(branch.lat)) <= 90 && Math.abs(Number(branch.lon)) <= 180
  );
  if (!located.length) {
    element.textContent = 'No branch coordinates are available.';
    return;
  }

  const initialise = async () => {
    if (element.dataset.mapReady === 'true') return;
    element.textContent = 'Loading branch map…';
    try {
      if (!window.L) await Promise.all([ensureLeaflet(), ensureLeafletStyles()]);
      else await ensureLeafletStyles();
    } catch (_) {
      element.textContent = 'Map unavailable. Branch coordinates could not be displayed.';
      return;
    }
    if (!window.L) {
      element.textContent = 'Map unavailable. Branch coordinates could not be displayed.';
      return;
    }
    element.dataset.mapReady = 'true';
    const map = L.map(element, { scrollWheelZoom: false, keyboard: true }).setView([43.70, -79.40], 10);
    mapInstances.set(elementId, map);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors', maxZoom: 19
    }).addTo(map);
    const markers = new Map();
    located.forEach((branch) => {
      const marker = L.circleMarker([Number(branch.lat), Number(branch.lon)], {
        radius: 7, color: '#17495e', weight: 1.5, fillColor: '#28758c', fillOpacity: 0.82
      }).addTo(map).bindPopup(branchPopup(branch), { maxWidth: 360 });
      markers.set(branch.code, marker);
    });
    if (markers.size > 1) map.fitBounds(L.featureGroup(Array.from(markers.values())).getBounds().pad(0.06));
    else map.setView([Number(located[0].lat), Number(located[0].lon)], 14);

    const metricSelect = $('#map-metric-select');
    const yearSelect = $('#map-year-select');
    function recolor() {
      const metric = metricSelect?.value || '';
      const year = yearSelect?.value || '';
      const values = (annualValues[metric] || []).find((row) => String(row.year) === String(year))?.values || {};
      const numeric = Object.values(values).filter((value) => value !== null && value !== undefined && Number.isFinite(Number(value))).map(Number).sort((a, b) => a - b);
      const thresholds = numeric.length ? [0.2, 0.4, 0.6, 0.8].map((fraction) => numeric[Math.min(numeric.length - 1, Math.floor((numeric.length - 1) * fraction))]) : [];
      const palette = ['#e7f0f3', '#a8c8d3', '#5d9aaf', '#276f87', '#17465b'];
      markers.forEach((marker, code) => {
        const branch = branches.find((item) => item.code === code);
        const value = values[code];
        let fillColor = metric ? '#aeb9bd' : '#28758c';
        if (metric && value !== null && value !== undefined && thresholds.length) {
          const band = thresholds.findIndex((limit) => Number(value) <= limit);
          fillColor = palette[band < 0 ? 4 : band];
        }
        const area = Number(branch?.square_footage) || 0;
        const size = area > 0 ? Math.max(6, Math.min(13, 5 + Math.sqrt(area) / 35)) : 7;
        marker.setStyle({ fillColor, radius: size });
      });
    }
    if (metricSelect) metricSelect.addEventListener('change', recolor);
    if (yearSelect) yearSelect.addEventListener('change', recolor);
    const directory = $(directorySelector);
    if (directory) directory.addEventListener('click', (event) => {
      const button = event.target.closest('[data-map-branch]');
      if (!button) return;
      const marker = markers.get(button.dataset.mapBranch);
      if (marker) { map.flyTo(marker.getLatLng(), Math.max(map.getZoom(), 14)); marker.openPopup(); }
    });
    recolor();
    requestAnimationFrame(() => map.invalidateSize());
  };

  if ('IntersectionObserver' in window) {
    const mapObserver = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      mapObserver.disconnect();
      initialise();
    }, { rootMargin: '200px 0px' });
    mapObserver.observe(element);
  } else {
    initialise();
  }
}

function renderYearDependentAnalysis(data, year) {
  const rankings = renderRankCharts(data, year);
  const distributions = renderDistributionCharts(data, year);
  const footprint = renderFootprintCharts(data, year);
  const quadrant = renderQuadrant(data, year);
  const host = $('#year-dependent-analysis');
  if (!host) return;
  host.innerHTML = `
    <section class="section"><h2 class="section-heading">Top 10 and Bottom 10 by Annual Metric</h2><div class="grid grid-2">${rankings}</div></section>
    <section class="section"><h2 class="section-heading">Metric Distribution</h2><div class="grid grid-2">${distributions}</div></section>
    <section class="section"><h2 class="section-heading">Annual Metrics vs. Square Footage</h2><div class="grid grid-2">${footprint}</div></section>
    <section class="section"><h2 class="section-heading">Visitation vs. Library Size</h2>${quadrant}</section>`;
  renderPlotlyCharts(host);
}

async function renderOverview() {
  const data = await getJson('/overview');
  const metrics = Object.keys(data.metrics || {});
  const statItems = metrics.map((metric) => [data.metrics[metric], data.totals?.[metric], data.latest_years?.[metric]]);
  const statHtml = statItems.map(([label, value, year]) => `
    <div class="stat"><span class="stat-label">${esc(label)}</span><strong class="stat-value">${fmt(value)}</strong>
      <span class="stat-note">${year ? `Latest reported year: ${esc(year)}` : 'No annual value available'}</span></div>`).join('') + `
    <div class="stat"><span class="stat-label">Physical Branches</span><strong class="stat-value">${fmt(data.branch_count)}</strong><span class="stat-note">Branch locations</span></div>`;
  const years = data.years || [];
  const selectedYear = years[years.length - 1] || '';
  const trendCharts = metrics.map((metric) => {
    const label = data.metrics[metric];
    const points = data.trend?.[metric] || [];
    const trace = [{ type: 'scatter', mode: 'lines+markers', name: label,
      x: points.map((item) => String(item.year)), y: points.map((item) => Number(item.value)),
      line: { width: 2.5, color: '#28758c' }, marker: { size: 6 },
      hovertemplate: '%{x}<br>%{y:,.0f}<extra></extra>' }];
    return `<article class="panel">${points.length ? chartMarkup(label, trace, { height: 300 }, `${label} by year`) : empty(`No ${label.toLowerCase()} history is available.`)}</article>`;
  }).join('');
  const tierCharts = renderTierTrendCharts(data);
  pageContent.innerHTML = `
    <section class="stat-grid" aria-label="Annual network summary">${statHtml}</section>
    <section class="section"><h2 class="section-heading">Network Activity</h2><div class="grid grid-2">${trendCharts}</div></section>
    <section class="section"><h2 class="section-heading">Network vs. Service-Tier Trends</h2><div class="grid grid-2">${tierCharts}</div></section>
    <section class="section"><h2 class="section-heading">Annual Metric Correlations</h2><p class="small-text">Each correlation uses only matching branch and reporting-year observations. Missing values are excluded, not treated as zero.</p>${renderCorrelationChart(data)}</section>
    <section class="section"><div class="toolbar toolbar-spread"><h2 class="section-heading">Branch-Level Analysis</h2><label class="analysis-year-label" for="overview-analysis-year">Reporting year <select id="overview-analysis-year" class="select-control">${yearOptions(years, selectedYear)}</select></label></div><div id="year-dependent-analysis"></div></section>
    <section class="section"><h2 class="section-heading">Branch Locations</h2>
      <div class="map-analysis-controls"><label for="map-metric-select">Metric map <select id="map-metric-select" class="select-control"><option value="">Branch locations</option>${metrics.map((metric) => `<option value="${esc(metric)}">${esc(data.metrics[metric])}</option>`).join('')}</select></label>
      <label for="map-year-select">Reporting year <select id="map-year-select" class="select-control">${yearOptions(years, selectedYear)}</select></label></div>
      <div id="branch-map" role="region" aria-label="Map of Toronto Public Library physical branches"></div>
      <details class="map-directory"><summary>View branch locations as a table</summary><div id="branch-map-directory"></div></details>
    </section>`;
  renderPlotlyCharts();
  renderYearDependentAnalysis(data, selectedYear);
  $('#overview-analysis-year').addEventListener('change', (event) => renderYearDependentAnalysis(data, event.target.value));
  // Branch records are included in this cached response, avoiding a second initial data request.
  createBranchMap('branch-map', data.branches || [], '#branch-map-directory', data.annual_values || {}, years);
}
function searchableBranchPicker(branches, initialCode = '') {
  pageContent.innerHTML = `<section class="branch-picker-section">
    <label for="branch-select">Branch</label>
    <select id="branch-select" class="select-control" aria-label="Select a library branch">
      <option value="">Select a branch</option>
      ${branches.map((branch) => `<option value="${esc(branch.code)}" ${branch.code === initialCode ? 'selected' : ''}>${esc(branch.name)} (${esc(branch.code)})</option>`).join('')}
    </select>
  </section><div id="branch-profile" class="branch-profile-host">${empty('Select a branch to view its information.')}</div>`;
  const selector = $('#branch-select');
  selector.addEventListener('change', async () => {
    const code = selector.value;
    if (!code) {
      $('#branch-profile').innerHTML = empty('Select a branch to view its information.');
      const url = new URL(location.href); url.searchParams.delete('branch'); history.replaceState({}, '', url);
      return;
    }
    const branch = branches.find((item) => item.code === code);
    const url = new URL(location.href);
    url.searchParams.set('branch', code);
    history.replaceState({}, '', url);
    await loadBranchProfile(code);
  });
  if (initialCode && branches.some((branch) => branch.code === initialCode)) loadBranchProfile(initialCode);
}

async function loadBranchProfile(code) {
  const host = $('#branch-profile');
  host.innerHTML = '<p class="loading-line">Loading branch information…</p>';
  try {
    const [data, forecasts] = await Promise.all([
      getJson(`/branches/${encodeURIComponent(code)}`),
      getJson(`/branches/${encodeURIComponent(code)}/forecasts`)
    ]);
    const branch = data.branch;
    const serviceHtml = branch.services?.length
      ? `<ul class="service-list">${branch.services.map((service) => `<li>${esc(service)}</li>`).join('')}</ul>`
      : '<p class="small-text">No additional service information is listed for this branch.</p>';
    const contactRows = [
      ['Address', branch.address || '—'], ['Postal code', branch.postal_code || '—'],
      ['Type of library', branch.type_of_library || humanTier(branch.service_tier)], ['Year opened', branch.year_opened || '—'],
      ['Service tier', humanTier(branch.service_tier)], ['Square footage', `${fmt(branch.square_footage)} sq ft`],
      ['Workstations', fmt(branch.workstations)], ['Telephone', branch.telephone || '—']
    ];
    const website = safeHttpUrl(branch.website);
    const eventsHtml = data.events.length ? `<div class="event-cards">${data.events.slice(0, 16).map((event) => branchEventCard(event)).join('')}</div>` : empty('No upcoming programs are listed for this branch.');
    host.innerHTML = `
      <header class="branch-profile-header"><div><h2>${esc(branch.name)}</h2><p class="profile-meta">${esc(branch.code)} · ${esc(humanTier(branch.service_tier))}</p></div>
        ${website ? `<a class="button secondary" href="${esc(website)}" target="_blank" rel="noopener noreferrer">Branch website</a>` : ''}</header>
      <div class="branch-tabs" role="tablist" aria-label="Branch information">
        <button type="button" class="branch-tab" role="tab" id="branch-tab-overview" aria-controls="tab-overview" aria-selected="true" data-tab="overview">Overview</button>
        <button type="button" class="branch-tab" role="tab" id="branch-tab-activity" aria-controls="tab-activity" aria-selected="false" data-tab="activity" tabindex="-1">Activity</button>
        <button type="button" class="branch-tab" role="tab" id="branch-tab-forecast" aria-controls="tab-forecast" aria-selected="false" data-tab="forecast" tabindex="-1">Forecasts</button>
        <button type="button" class="branch-tab" role="tab" id="branch-tab-services" aria-controls="tab-services" aria-selected="false" data-tab="services" tabindex="-1">Services</button>
        <button type="button" class="branch-tab" role="tab" id="branch-tab-ask" aria-controls="tab-ask" aria-selected="false" data-tab="ask" tabindex="-1">Ask a question</button>
        <button type="button" class="branch-tab" role="tab" id="branch-tab-events" aria-controls="tab-events" aria-selected="false" data-tab="events" tabindex="-1">Programs</button>
      </div>
      <section id="tab-overview" class="branch-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="branch-tab-overview">
        <section class="profile-section"><h3 class="section-heading">Branch information</h3>${renderTable(['Detail', 'Information'], contactRows)}</section>
      </section>
      <section id="tab-activity" class="branch-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="branch-tab-activity" hidden>
        <div class="grid grid-2">${renderBranchHistory(data.history)}</div>
      </section>
      <section id="tab-forecast" class="branch-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="branch-tab-forecast" hidden>
        <div class="grid grid-2">${renderForecasts(data.history, forecasts)}</div>
      </section>
      <section id="tab-services" class="branch-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="branch-tab-services" hidden>
        <section class="profile-section"><h3 class="section-heading">Reported services</h3>${serviceHtml}</section>
      </section>
      <section id="tab-ask" class="branch-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="branch-tab-ask" hidden>
        <form id="question-form" class="question-form"><label class="visually-hidden" for="branch-question">Your question</label>
          <input id="branch-question" class="control" type="text" maxlength="500" placeholder="Ask about this branch, its services or related programs" required>
          <button class="button" type="submit">Ask</button></form>
        <div id="answer-area" aria-live="polite" aria-atomic="true"></div>
      </section>
      <section id="tab-events" class="branch-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="branch-tab-events" hidden>
        <div class="toolbar toolbar-spread"><h3 class="section-heading">Upcoming programs at this branch</h3><a href="/programs-events?branch=${encodeURIComponent(branch.code)}">Find more programs</a></div>
        ${eventsHtml}
      </section>`;

    const tabs = $('.branch-tabs', host);
    tabs.addEventListener('click', (event) => {
      const tab = event.target.closest('[role="tab"]');
      if (!tab) return;
      formatTabState(tabs, tab.dataset.tab);
      if (tab.dataset.tab === 'ask') {
        const answerArea = $('#answer-area');
        answerArea.innerHTML = '<p class="small-text">Checking branch question availability…</p>';
        getJson('/status').then((status) => {
          if (!status.relate?.ready) answerArea.innerHTML = notice('Branch questions are not available right now.', 'warning');
          else answerArea.innerHTML = '';
        }).catch(() => { answerArea.innerHTML = notice('Branch questions are not available right now.', 'warning'); });
      }
    });
    tabs.addEventListener('keydown', (event) => {
      const current = event.target.closest('[role="tab"]');
      if (!current) return;
      const tabButtons = $$('.branch-tab', tabs);
      let index = tabButtons.indexOf(current);
      if (event.key === 'ArrowRight') index = (index + 1) % tabButtons.length;
      else if (event.key === 'ArrowLeft') index = (index - 1 + tabButtons.length) % tabButtons.length;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = tabButtons.length - 1;
      else return;
      event.preventDefault(); tabButtons[index].focus(); tabButtons[index].click();
    });

    $('#question-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const input = $('#branch-question');
      const answerArea = $('#answer-area');
      const button = $('button[type="submit"]', event.currentTarget);
      if (!input.value.trim()) return;
      button.disabled = true;
      answerArea.innerHTML = '<p class="small-text">Looking for related branch information…</p>';
      try {
        const answer = await getJson('/ask', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: input.value.trim(), branch_code: code })
        });
        const highlights = (answer.highlights || []).map((item) => `<li class="answer-highlight"><div class="answer-highlight-heading"><strong>${esc(item.title)}</strong><span>${esc(item.category)}</span></div>${item.details?.length ? `<dl>${item.details.map((detail) => `<div class="answer-highlight-detail"><dt>${esc(detail.label)}</dt><dd>${esc(detail.value)}</dd></div>`).join('')}</dl>` : ''}</li>`).join('');
        answerArea.innerHTML = `<div class="answer-panel"><h3>What I found</h3><p>${esc(answer.answer)}</p>${highlights ? `<ul class="answer-highlights">${highlights}</ul>` : ''}${renderEvidence(answer.evidence)}</div>`;
      } catch (_) { answerArea.innerHTML = notice('Branch questions are not available right now. Please try again later.', 'warning'); }
      finally { button.disabled = false; }
    });
  } catch (_) { host.innerHTML = notice('Branch information could not be loaded. Please try again.', 'error'); }
}
function renderBranchHistory(history) {
  const labels = { circulation: 'Circulation', visits: 'Visits', workstations: 'Workstation sessions', registrations: 'Card registrations' };
  return Object.entries(history).map(([metric, points]) => `<article class="panel"><h3 class="section-heading">${esc(labels[metric] || metric)}</h3>${lineChart(points, labels[metric] || metric)}</article>`).join('');
}
function renderForecasts(history, forecasts) {
  const labels = { circulation: 'Circulation', visits: 'Visits', workstations: 'Workstation sessions', registrations: 'Card registrations' };
  return Object.entries(forecasts).map(([metric, result]) => {
    const label = labels[metric] || metric;
    if (!result.available) return `<article class="panel"><h3 class="section-heading">${esc(label)}</h3>${empty(result.reason || 'A forecast is not available for this measure.')}</article>`;
    const values = result.forecasts.map((item) => `${item.year}: ${fmtDecimal(item.value)}`).join(' · ');
    return `<article class="panel"><h3 class="section-heading">${esc(label)}</h3><p class="forecast-values">${esc(values)}</p>${forecastChart(history[metric] || [], result, label)}</article>`;
  }).join('');
}
function branchEventCard(event) {
  const url = safeHttpUrl(event.event_url);
  const registrationUrl = safeHttpUrl(event.registration_url);
  return `<article class="event-item"><div class="event-card-main"><h4>${esc(event.title)}</h4><p class="event-meta">${esc(formatDateTime(event.start))}${event.end ? ` – ${esc(formatDateTime(event.end, false))}` : ''}</p>
    <p class="event-description">${esc(event.description || event.types || 'Library program')}</p><p class="event-meta">${esc(event.audiences || 'All audiences')} · ${esc(event.languages || 'Language not specified')}</p></div>
    <div class="event-card-actions">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Program details</a>` : ''}${registrationUrl ? `<a href="${esc(registrationUrl)}" target="_blank" rel="noopener noreferrer">Registration</a>` : ''}</div></article>`;
}
async function renderBranches() {
  const branches = await getJson('/branches');
  if (!branches.length) { pageContent.innerHTML = empty('Branch information is not available right now.'); return; }
  const selected = new URLSearchParams(location.search).get('branch') || '';
  await searchableBranchPicker(branches, selected);
}

async function renderComparisons() {
  const branches = await getJson('/branches');
  if (branches.length < 2) { pageContent.innerHTML = empty('At least two physical branches are needed for a comparison.'); return; }
  const params = new URLSearchParams(location.search);
  const initial = (params.get('branches') || '').split(',').filter((code) => branches.some((branch) => branch.code === code)).slice(0, 5);
  pageContent.innerHTML = `<section class="panel compare-selector">
    <div class="compare-select-header"><div><h2 class="section-heading">Choose branches</h2><p class="section-intro">Select up to five branches.</p></div><p id="compare-count" class="selection-count" aria-live="polite">${initial.length} of 5 selected</p></div>
    <label for="compare-search">Search branches</label><input id="compare-search" class="control" type="search" placeholder="Filter by branch name or code" autocomplete="off">
    <div id="compare-branch-list" class="compare-branch-list" aria-describedby="compare-count">${branches.map((branch) => `
      <label class="compare-branch-option" data-search="${esc(`${branch.name} ${branch.code} ${branch.service_tier}`.toLowerCase())}">
        <input type="checkbox" value="${esc(branch.code)}" ${initial.includes(branch.code) ? 'checked' : ''}>
        <span><strong>${esc(branch.name)}</strong><small>${esc(branch.code)} · ${esc(humanTier(branch.service_tier))}</small></span></label>`).join('')}</div>
    <div class="selected-branches" id="selected-branches" aria-label="Selected branches"></div>
    <div class="filter-actions"><button id="compare-submit" class="button" type="button" ${initial.length < 2 ? 'disabled' : ''}>Compare selected branches</button><button class="button secondary" type="button" id="clear-compare">Clear selection</button></div>
  </section><div id="comparison-results" class="section" aria-live="polite">${empty('Select at least two branches to compare.')}</div>`;

  const list = $('#compare-branch-list');
  const checkboxes = $$('input[type="checkbox"]', list);
  function selectedBranches() { return checkboxes.filter((input) => input.checked).map((input) => branches.find((branch) => branch.code === input.value)).filter(Boolean); }
  function updateSelection() {
    const selected = selectedBranches();
    $('#compare-count').textContent = `${selected.length} of 5 selected`;
    $('#compare-submit').disabled = selected.length < 2 || selected.length > 5;
    checkboxes.forEach((input) => { input.disabled = !input.checked && selected.length >= 5; });
    $('#selected-branches').innerHTML = selected.map((branch) => `<span class="selected-branch-chip">${esc(branch.name)}<button type="button" aria-label="Remove ${esc(branch.name)}" data-remove="${esc(branch.code)}">×</button></span>`).join('');
  }
  $('#compare-search').addEventListener('input', (event) => {
    const term = event.target.value.trim().toLowerCase();
    $$('.compare-branch-option', list).forEach((label) => { label.hidden = !label.dataset.search.includes(term); });
  });
  list.addEventListener('change', () => updateSelection());
  $('#selected-branches').addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove]');
    if (!button) return;
    const checkbox = checkboxes.find((input) => input.value === button.dataset.remove);
    if (checkbox) checkbox.checked = false;
    updateSelection();
  });
  $('#clear-compare').addEventListener('click', () => {
    checkboxes.forEach((input) => { input.checked = false; });
    $('#comparison-results').innerHTML = empty('Select at least two branches to compare.');
    updateSelection();
    const url = new URL(location.href); url.searchParams.delete('branches'); history.replaceState({}, '', url);
  });
  $('#compare-submit').addEventListener('click', async () => {
    const selected = selectedBranches();
    const codes = selected.map((branch) => branch.code).slice(0, 5);
    const host = $('#comparison-results');
    if (codes.length < 2) { host.innerHTML = notice('Choose at least two branches.', 'warning'); return; }
    const url = new URL(location.href); url.searchParams.set('branches', codes.join(',')); history.replaceState({}, '', url);
    host.innerHTML = '<p class="loading-line">Preparing your comparison…</p>';
    try {
      const data = await getJson(`/comparisons/data?branches=${encodeURIComponent(codes.join(','))}`);
      const branchRows = data.branches.map((branch) => [
        branch.name, branch.code, humanTier(branch.service_tier), branch.address || '—', branch.postal_code || '—',
        fmt(branch.square_footage), fmt(branch.workstations), branch.year_opened || '—',
        (branch.services || []).join(', ') || '—'
      ]);
      const metricKeys = Object.keys(data.metrics);
      const metricTabs = metricKeys.map((metric, index) => `<button type="button" id="metric-tab-${esc(metric)}" class="branch-tab metric-tab" role="tab" aria-controls="metric-panel-${esc(metric)}" aria-selected="${index === 0 ? 'true' : 'false'}" tabindex="${index === 0 ? 0 : -1}" data-metric-tab="${esc(metric)}">${esc(metricName(metric))}</button>`).join('');
      const metricPanels = metricKeys.map((metric, index) => {
        const years = data.metrics[metric];
        const label = data.metric_labels[metric];
        const rows = years.map((row) => [row.year, ...data.branches.map((branch) => fmt(row.values[branch.code]))]);
        return `<section id="metric-panel-${esc(metric)}" class="metric-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="metric-tab-${esc(metric)}" ${index ? 'hidden' : ''}>${multiLineChart(years, data.branches, label)}${tableDetails(`${label} by year`, ['Year', ...data.branches.map((branch) => branch.name)], rows)}</section>`;
      }).join('');
      const allServices = Array.from(new Set(data.branches.flatMap((branch) => branch.services || []))).sort((a, b) => a.localeCompare(b));
      const serviceRows = allServices.map((service) => [service, ...data.branches.map((branch) => (branch.services || []).includes(service) ? 'Reported' : 'Not listed')]);
      host.innerHTML = `
        <div class="comparison-tabs" role="tablist" aria-label="Comparison views">
          <button type="button" id="comparison-tab-annual" class="branch-tab comparison-tab" role="tab" aria-controls="comparison-view-annual" aria-selected="true" tabindex="0" data-view-tab="annual">Annual metrics</button>
          <button type="button" id="comparison-tab-information" class="branch-tab comparison-tab" role="tab" aria-controls="comparison-view-information" aria-selected="false" tabindex="-1" data-view-tab="information">Branch information</button>
          <button type="button" id="comparison-tab-services" class="branch-tab comparison-tab" role="tab" aria-controls="comparison-view-services" aria-selected="false" tabindex="-1" data-view-tab="services">Services</button>
          <button type="button" id="comparison-tab-locations" class="branch-tab comparison-tab" role="tab" aria-controls="comparison-view-locations" aria-selected="false" tabindex="-1" data-view-tab="locations">Locations</button>
        </div>
        <section id="comparison-view-annual" class="comparison-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="comparison-tab-annual">
          <div class="comparison-metric-tabs" role="tablist" aria-label="Annual metric">${metricTabs}</div>
          ${metricPanels}
        </section>
        <section id="comparison-view-information" class="comparison-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="comparison-tab-information" hidden>
          ${renderTable(['Branch', 'Code', 'Service tier', 'Address', 'Postal code', 'Area (sq ft)', 'Workstations', 'Year opened', 'Reported services'], branchRows)}
        </section>
        <section id="comparison-view-services" class="comparison-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="comparison-tab-services" hidden>
          ${serviceRows.length ? renderTable(['Service offering', ...data.branches.map((branch) => branch.name)], serviceRows) : empty('No service offerings are recorded for these branches.')}
        </section>
        <section id="comparison-view-locations" class="comparison-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="comparison-tab-locations" hidden>
          <div id="comparison-map" role="region" aria-label="Map of selected branches"></div>
          <details class="map-directory"><summary>View selected locations as a table</summary><div id="comparison-map-directory"></div></details>
        </section>`;
      const comparisonTabs = $('.comparison-tabs', host);
      enableTabKeyboard(comparisonTabs, '.comparison-tab');
      comparisonTabs.addEventListener('click', (event) => {
        const tab = event.target.closest('[data-view-tab]');
        if (!tab) return;
        $$('.comparison-tab', comparisonTabs).forEach((item) => {
          const active = item === tab;
          item.setAttribute('aria-selected', active ? 'true' : 'false');
          item.tabIndex = active ? 0 : -1;
        });
        $$('.comparison-tabpanel', host).forEach((panel) => { panel.hidden = panel.id !== `comparison-view-${tab.dataset.viewTab}`; });
        if (tab.dataset.viewTab === 'locations') requestAnimationFrame(() => mapInstances.get('comparison-map')?.invalidateSize());
        if (tab.dataset.viewTab === 'annual') { renderPlotlyCharts($('#comparison-view-annual', host)); requestAnimationFrame(() => resizePlotlyCharts($('#comparison-view-annual', host))); }
      });
      const metricTabList = $('.comparison-metric-tabs', host);
      enableTabKeyboard(metricTabList, '.metric-tab');
      metricTabList.addEventListener('click', (event) => {
        const tab = event.target.closest('[data-metric-tab]');
        if (!tab) return;
        $$('.metric-tab', metricTabList).forEach((item) => {
          const active = item === tab;
          item.setAttribute('aria-selected', active ? 'true' : 'false');
          item.tabIndex = active ? 0 : -1;
        });
        $$('.metric-tabpanel', host).forEach((panel) => { panel.hidden = panel.id !== `metric-panel-${tab.dataset.metricTab}`; });
        const activePanel = $(`#metric-panel-${tab.dataset.metricTab}`, host); renderPlotlyCharts(activePanel); requestAnimationFrame(() => resizePlotlyCharts(activePanel));
      });
      renderPlotlyCharts($('#comparison-view-annual', host));
      createBranchMap('comparison-map', data.branches, '#comparison-map-directory');
    } catch (_) { host.innerHTML = notice('The comparison could not be loaded. Please try again.', 'error'); }
  });
  updateSelection();
  if (initial.length >= 2) $('#compare-submit').click();
}

function distinctOption(values, selected, label) {
  return `<option value="">${esc(label)}</option>${values.map((value) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(value)}</option>`).join('')}`;
}
function renderEventDiscovery(analysis) {
  if (!analysis) return empty('Event analysis is unavailable.');
  const dimensions = [
    ['types', 'Events by type'], ['audiences', 'Events by audience'],
    ['languages', 'Events by language'], ['branches', 'Events by branch']
  ];
  const charts = dimensions.map(([key, title]) => {
    const rows = (analysis[key] || []).slice(0, 12);
    if (!rows.length) return `<article class="panel"><h3 class="subheading">${esc(title)}</h3>${empty('No matching event records.')}</article>`;
    const trace = [{
      type: 'bar', orientation: 'h',
      x: rows.map((item) => item.count), y: rows.map((item) => item.label),
      marker: { color: '#28758c' },
      hovertemplate: '%{y}<br>%{x:,.0f} events<extra></extra>'
    }];
    return `<article class="panel">${chartMarkup(title, trace, {
      height: Math.max(260, 44 + rows.length * 28),
      margin: { l: 150, r: 20, t: 42, b: 35 },
      xaxis: { title: '', rangemode: 'tozero', tickformat: ',.0f' },
      yaxis: { title: '', autorange: 'reversed', automargin: true, tickfont: { size: 10 } },
      showlegend: false
    }, title)}</article>`;
  }).join('');
  return `<p class="small-text">${fmt(analysis.total_upcoming)} matching upcoming event records</p><div class="grid grid-2">${charts}</div>`;
}
function eventItem(event) {
  const url = safeHttpUrl(event.event_url);
  const registrationUrl = safeHttpUrl(event.registration_url);
  const statusClass = ['Full', 'Closed'].includes(event.registration_status) ? 'closed' : event.registration_status === 'Registration open' ? 'open' : '';
  return `<article class="event-card">
    <div class="event-date"><strong>${esc(new Intl.DateTimeFormat('en-CA', { month: 'short', day: 'numeric' }).format(new Date(event.start_iso)))}</strong><span>${esc(new Intl.DateTimeFormat('en-CA', { year: 'numeric' }).format(new Date(event.start_iso)))}</span><span>${esc(formatDateTime(event.start_iso, false))}${event.end_iso ? ` – ${esc(formatDateTime(event.end_iso, false))}` : ''}</span></div>
    <div class="event-card-main"><h3>${esc(event.title)}</h3><p class="event-meta">${esc(event.location || 'Library location')} · ${esc(event.audiences || 'All audiences')} · ${esc(event.languages || 'Language not specified')}</p>
      ${event.description ? `<p class="event-description">${esc(event.description)}</p>` : ''}
      ${event.match_reasons?.length ? `<p class="event-reasons">Matched: ${esc(event.match_reasons.join(', '))}</p>` : ''}</div>
    <div class="event-card-actions"><span class="event-status ${statusClass}">${esc(event.registration_status === 'Availability not supplied' ? 'Availability not listed' : event.registration_status)}</span>
      ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Program details</a>` : ''}${registrationUrl ? `<a href="${esc(registrationUrl)}" target="_blank" rel="noopener noreferrer">Register</a>` : ''}</div>
  </article>`;
}
async function renderEvents() {
  const [options] = await Promise.all([getJson('/events/options')]);
  const params = new URLSearchParams(location.search);
  const branchOptions = options.branches.map((branch) => `<option value="${esc(branch.code)}" ${params.get('branch') === branch.code ? 'selected' : ''}>${esc(branch.name)}</option>`).join('');
  pageContent.innerHTML = `
    <section class="panel event-filters-panel">
      <form id="event-filters" class="event-filter-grid">
        <div class="form-field interest-field"><label for="interest">Interest</label><input class="control" id="interest" name="interest" placeholder="e.g. coding, reading, music" value="${esc(params.get('interest') || '')}"></div>
        <div class="form-field"><label for="audience">Audience</label><select class="select-control" id="audience" name="audience">${distinctOption(options.audiences, params.get('audience'), 'Any audience')}</select></div>
        <div class="form-field"><label for="language">Language</label><select class="select-control" id="language" name="language">${distinctOption(options.languages, params.get('language'), 'Any language')}</select></div>
        <div class="form-field"><label for="event_type">Program type</label><select class="select-control" id="event_type" name="event_type">${distinctOption(options.event_types, params.get('event_type'), 'Any type')}</select></div>
        <div class="form-field"><label for="event_branch">Branch</label><select class="select-control" id="event_branch" name="branch"><option value="">All branches</option>${branchOptions}</select></div>
        <div class="form-field"><label for="event_date">Date</label><input class="control" id="event_date" name="date" type="date" value="${esc(params.get('date') || '')}"></div>
        <div class="form-field"><label for="start_time">Start time</label><input class="control" id="start_time" name="start_time" type="time" value="${esc(params.get('start_time') || '')}"></div>
        <div class="form-field"><label for="end_time">End time</label><input class="control" id="end_time" name="end_time" type="time" value="${esc(params.get('end_time') || '')}"></div>
        <div class="form-field"><label for="registration">Registration</label><select class="select-control" id="registration" name="registration"><option value="">Any status</option><option value="available" ${params.get('registration') === 'available' ? 'selected' : ''}>Open registration</option></select></div>
        <div class="filter-actions event-filter-actions"><button class="button" type="submit">Find programs</button><button class="button secondary" id="reset-events" type="button">Reset</button></div>
      </form>
    </section>
    <section class="section"><h2 class="section-heading">Event Discovery</h2><div id="event-analysis" aria-live="polite"></div></section>
    <section class="section"><div class="toolbar toolbar-spread"><h2 class="section-heading">Matching Programs</h2><div id="event-export"></div></div>
      <p id="event-summary" class="small-text" aria-live="polite">Loading programs…</p><div id="event-results" class="event-results" aria-live="polite"></div></section>`;
  const form = $('#event-filters');
  async function searchEvents(updateUrl = true) {
    const query = new URLSearchParams(new FormData(form));
    const queryString = query.toString();
    if (updateUrl) { const nextUrl = new URL(location.href); nextUrl.search = queryString; history.replaceState({}, '', nextUrl); }
    $('#event-results').innerHTML = '<p class="loading-line">Finding matching programs…</p>';
    try {
      const data = await getJson(`/events/recommendations?${queryString}`);
      $('#event-summary').textContent = `${fmt(data.total)} upcoming program${data.total === 1 ? '' : 's'} found.`;
      $('#event-results').innerHTML = data.events.length ? data.events.map(eventItem).join('') : empty('No upcoming programs match those preferences. Try changing a filter.');
      $('#event-analysis').innerHTML = renderEventDiscovery(data.analysis);
      renderPlotlyCharts($('#event-analysis'));
      $('#event-export').innerHTML = csvExportButton(`/exports/events.csv?${queryString}`, 'Download matching events CSV');
    } catch (_) {
      $('#event-results').innerHTML = notice('Programs could not be loaded right now. Please try again.', 'error');
      $('#event-summary').textContent = 'Programs could not be loaded.';
      $('#event-export').innerHTML = '';
      $('#event-analysis').innerHTML = '';
    }
  }
  form.addEventListener('submit', (event) => { event.preventDefault(); searchEvents(true); });
  $('#reset-events').addEventListener('click', () => { form.reset(); searchEvents(true); });
  await searchEvents(false);
}

const renderers = { overview: renderOverview, branches: renderBranches, comparisons: renderComparisons, events: renderEvents };
(async () => {
  try { await (renderers[page] || renderOverview)(); }
  catch (_) { pageContent.innerHTML = notice('This section could not be loaded right now. Please try again.', 'error'); }
  finally { pageContent.setAttribute('aria-busy', 'false'); }
})();

const searchInput = $('#global-search');
const searchResults = $('#search-results');
let searchTimer;
let activeSearchIndex = -1;
function updateSearchOption() {
  const options = $$('.search-result[role="option"]', searchResults);
  options.forEach((option, index) => {
    option.setAttribute('aria-selected', index === activeSearchIndex ? 'true' : 'false');
    if (index === activeSearchIndex) option.scrollIntoView({ block: 'nearest' });
  });
  if (activeSearchIndex >= 0 && options[activeSearchIndex]) searchInput.setAttribute('aria-activedescendant', options[activeSearchIndex].id);
  else searchInput.removeAttribute('aria-activedescendant');
}
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  const query = searchInput.value.trim();
  activeSearchIndex = -1;
  searchInput.removeAttribute('aria-activedescendant');
  if (query.length < 2) { searchResults.hidden = true; searchInput.setAttribute('aria-expanded', 'false'); return; }
  searchTimer = setTimeout(async () => {
    try {
      const data = await getJson(`/search?q=${encodeURIComponent(query)}`);
      const items = [
        ...data.branches.map((branch) => ({ label: branch.name, sub: `Branch · ${branch.code}`, url: `/branch-insights?branch=${encodeURIComponent(branch.code)}` })),
        ...data.events.map((event) => ({ label: event.title, sub: `Program · ${event.location || 'Library location'}`, url: `/programs-events?interest=${encodeURIComponent(query)}` }))
      ];
      searchResults.innerHTML = items.length ? items.map((item, index) => `<a id="search-option-${index}" class="search-result" role="option" aria-selected="false" tabindex="-1" href="${item.url}">${esc(item.label)}<small>${esc(item.sub)}</small></a>`).join('') : '<p class="search-empty">No results found.</p>';
      searchResults.hidden = false; searchInput.setAttribute('aria-expanded', 'true');
    } catch (_) { searchResults.hidden = true; searchInput.setAttribute('aria-expanded', 'false'); }
  }, 180);
});
document.addEventListener('click', (event) => {
  if (!event.target.closest('.global-search')) {
    searchResults.hidden = true;
    searchInput.setAttribute('aria-expanded', 'false');
    searchInput.removeAttribute('aria-activedescendant');
    activeSearchIndex = -1;
  }
});
searchInput.addEventListener('keydown', (event) => {
  const options = $$('.search-result[role="option"]', searchResults);
  if (event.key === 'Escape') {
    searchResults.hidden = true;
    searchInput.setAttribute('aria-expanded', 'false');
    searchInput.removeAttribute('aria-activedescendant');
    activeSearchIndex = -1;
  } else if (event.key === 'ArrowDown' && options.length) {
    event.preventDefault();
    activeSearchIndex = Math.min(activeSearchIndex + 1, options.length - 1);
    updateSearchOption();
  } else if (event.key === 'ArrowUp' && options.length) {
    event.preventDefault();
    activeSearchIndex = Math.max(activeSearchIndex - 1, 0);
    updateSearchOption();
  } else if (event.key === 'Enter' && activeSearchIndex >= 0 && options[activeSearchIndex]) {
    event.preventDefault();
    location.href = options[activeSearchIndex].href;
  }
});

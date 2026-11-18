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
const responseCache = new Map();
const CACHE_TTL_MS = 5 * 60 * 1000;

const descriptions = {
  overview: 'Explore library activity, branch information and service patterns.',
  branches: 'Find a branch to view its services, activity, programs and related information.',
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

async function getJson(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const cacheKey = `${method}:${url}`;
  if (method === 'GET') {
    const cached = responseCache.get(cacheKey);
    if (cached && Date.now() - cached.time < CACHE_TTL_MS) return cached.value;
  }
  const response = await fetch(url, { ...options, headers: { Accept: 'application/json', ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.error || `Request failed (${response.status})`);
  if (method === 'GET') responseCache.set(cacheKey, { time: Date.now(), value: payload });
  return payload;
}
function empty(message) { return `<div class="empty-state">${esc(message)}</div>`; }
function notice(message, type = '') { return `<div class="notice ${type}" role="status">${esc(message)}</div>`; }
function csvExportButton(url, label = 'Export CSV') {
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
  return `<div class="chart-block"><div class="chart-tools"><button type="button" class="chart-download" data-download-chart="${id}">Download chart</button></div><div id="${id}" class="plotly-chart" role="img" aria-label="Interactive ${esc(metricLabel)} comparison by branch"></div>${tableDetails(`${metricLabel} comparison`, headers, tableRows)}</div>`;
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
  return {
    title: { text: spec.title, x: 0.02, xanchor: 'left', font: { size: 14, color: text } },
    autosize: true, height: 310, margin: { l: 66, r: 22, t: 48, b: 55 },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Inter, sans-serif', color: text, size: 12 },
    xaxis: { title: '', gridcolor: line, linecolor: line, tickfont: { color: muted }, automargin: true },
    yaxis: { title: '', gridcolor: line, linecolor: line, tickfont: { color: muted }, tickformat: ',.0f', rangemode: 'tozero', automargin: true },
    legend: { orientation: 'h', y: -0.23, font: { color: muted } },
    hovermode: 'x unified', dragmode: 'pan', showlegend: spec.traces.length > 1,
    uirevision: `${page}-${spec.title}`
  };
}
function renderPlotlyCharts(root = document) {
  const plotly = window.Plotly;
  const elements = $$('.plotly-chart', root).filter((element) => element.dataset.rendered !== 'true');
  if (!plotly) {
    elements.forEach((element) => { element.textContent = 'The chart could not be loaded. The underlying values are available in the table below.'; });
    return;
  }
  elements.forEach((element) => {
    const spec = chartRegistry.get(element.id);
    if (!spec) return;
    element.dataset.rendered = 'true';
    plotly.newPlot(element, spec.traces, plotLayout(spec), {
      responsive: true, displaylogo: false, scrollZoom: false,
      modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d']
    }).catch(() => {
      element.dataset.rendered = 'false';
      element.textContent = 'The chart could not be displayed. View the data table below.';
    });
  });
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

async function renderOverview() {
  const data = await getJson('/overview');
  const statItems = [
    ['Circulation', data.totals.circulation, data.latest_years.circulation],
    ['Visits', data.totals.visits, data.latest_years.visits],
    ['Workstation sessions', data.totals.workstations, data.latest_years.workstations],
    ['Card registrations', data.totals.registrations, data.latest_years.registrations],
    ['Physical branches', data.branch_count, null]
  ];
  const statHtml = statItems.map(([label, value, year]) => `
    <div class="stat"><span class="stat-label">${esc(label)}</span><strong class="stat-value">${fmt(value)}</strong>
      <span class="stat-note">${year ? `Latest reported year: ${esc(year)}` : 'Branch directory'}</span></div>`).join('');
  const chartPanels = Object.entries(data.metrics).map(([key, label]) => `
    <article class="panel"><div class="panel-heading"><h3>${esc(label)}</h3><span>Annual trend</span></div>${lineChart(data.trend[key], label)}</article>`).join('');
  pageContent.innerHTML = `
    <section class="stat-grid" aria-label="Network summary">${statHtml}</section>
    <section class="section"><div class="toolbar toolbar-spread"><h2 class="section-heading">Library activity over time</h2>${csvExportButton('/exports/observations.csv')}</div>
      <div class="grid grid-2">${chartPanels}</div>
    </section>
    <section class="section grid grid-2">
      <article><h2 class="section-heading">Branches by service tier</h2>${renderTable(['Service tier', 'Branches'], Object.entries(data.tiers).map(([tier, count]) => [tier, fmt(count)]))}</article>
      <article><h2 class="section-heading">Branch locations</h2><p class="small-text">Select a map marker to view branch details and services.</p><a href="/branch-insights">Find a branch</a></article>
    </section>
    <section class="section"><div id="branch-map" role="region" aria-label="Map of Toronto Public Library physical branches"></div>
      <details class="map-directory"><summary>View branch locations as a table</summary><div id="branch-map-directory"></div></details>
    </section>`;
  renderPlotlyCharts();
  await initBranchMap();
}

function branchPopup(branch) {
  const services = (branch.services || []).map(esc).join(', ') || 'No service details listed';
  const website = safeHttpUrl(branch.website);
  return `<div class="map-popup"><strong>${esc(branch.name)}</strong><div>${esc(branch.code)} · ${esc(humanTier(branch.service_tier))}</div>
    ${branch.address ? `<div>${esc(branch.address)}</div>` : ''}${branch.postal_code ? `<div>${esc(branch.postal_code)}</div>` : ''}
    <div>Workstations: ${fmt(branch.workstations)} · Area: ${fmt(branch.square_footage)} sq ft</div>
    <div>Services: ${services}</div>${branch.telephone ? `<div>${esc(branch.telephone)}</div>` : ''}
    <a href="/branch-insights?branch=${encodeURIComponent(branch.code)}">View branch details</a>${website ? ` · <a href="${esc(website)}" target="_blank" rel="noopener noreferrer">Website</a>` : ''}</div>`;
}
function renderMapDirectory(branches, selector) {
  const host = $(selector);
  if (!host) return;
  host.innerHTML = renderTable(
    ['Branch', 'Address', 'Service tier', 'Services'],
    branches.map((branch) => [
      { html: `<a href="/branch-insights?branch=${encodeURIComponent(branch.code)}">${esc(branch.name)}</a>` },
      branch.address || '—', humanTier(branch.service_tier), (branch.services || []).join(', ') || '—'
    ])
  );
}
async function createBranchMap(elementId, branches, directorySelector) {
  const element = $(`#${elementId}`);
  if (!element) return;
  const located = branches.filter((branch) => Number.isFinite(Number(branch.lat)) && Number.isFinite(Number(branch.lon)));
  renderMapDirectory(branches, directorySelector);
  if (!window.L) { element.textContent = 'Map unavailable. Use the branch table for branch locations.'; return; }
  if (!located.length) { element.textContent = 'No branch coordinates are available.'; return; }
  const map = L.map(element, { scrollWheelZoom: false, keyboard: true }).setView([43.70, -79.40], 10);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors', maxZoom: 19
  }).addTo(map);
  const markers = located.map((branch) => L.marker([Number(branch.lat), Number(branch.lon)], { keyboard: true, title: branch.name })
    .addTo(map).bindPopup(branchPopup(branch), { maxWidth: 330 }));
  if (markers.length > 1) map.fitBounds(L.featureGroup(markers).getBounds().pad(0.06));
  else map.setView([Number(located[0].lat), Number(located[0].lon)], 14);
  requestAnimationFrame(() => map.invalidateSize());
}
async function initBranchMap() {
  const branches = await getJson('/branches');
  await createBranchMap('branch-map', branches, '#branch-map-directory');
}

function searchableBranchPicker(branches, initialCode = '') {
  pageContent.innerHTML = `<section class="branch-picker-section">
    <label for="branch-search">Find a branch</label>
    <div class="branch-combobox"><input id="branch-search" class="control" type="search" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="branch-suggestions" placeholder="Start typing a branch name or code" autocomplete="off">
      <div id="branch-suggestions" class="combo-options" role="listbox" aria-label="Matching branches" hidden></div></div>
    <p id="branch-selection-note" class="small-text" aria-live="polite">Choose a branch to view its information.</p>
  </section><div id="branch-profile" class="branch-profile-host"></div>`;
  const input = $('#branch-search');
  const suggestions = $('#branch-suggestions');
  let activeIndex = -1;
  let filtered = [];
  function drawSuggestions(term) {
    const normalized = term.trim().toLocaleLowerCase();
    filtered = branches.filter((branch) => !normalized || `${branch.name} ${branch.code} ${branch.address}`.toLocaleLowerCase().includes(normalized)).slice(0, 12);
    suggestions.innerHTML = filtered.length ? filtered.map((branch, index) => `
      <button type="button" role="option" tabindex="-1" aria-selected="false" id="branch-option-${index}" class="combo-option" data-code="${esc(branch.code)}">
        <strong>${esc(branch.name)}</strong><span>${esc(branch.code)} · ${esc(humanTier(branch.service_tier))}</span></button>`).join('') : '<p class="combo-empty">No matching branches.</p>';
    suggestions.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    activeIndex = -1;
  }
  async function selectBranch(code) {
    const branch = branches.find((item) => item.code === code);
    if (!branch) return;
    input.value = `${branch.name} (${branch.code})`;
    suggestions.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    $('#branch-selection-note').textContent = `${branch.name} selected`;
    const url = new URL(location.href);
    url.searchParams.set('branch', branch.code);
    history.replaceState({}, '', url);
    await loadBranchProfile(branch.code);
  }
  input.addEventListener('focus', () => drawSuggestions(input.value.replace(/\s*\([^)]*\)$/, '')));
  input.addEventListener('input', () => drawSuggestions(input.value));
  suggestions.addEventListener('click', (event) => {
    const option = event.target.closest('[data-code]');
    if (option) selectBranch(option.dataset.code);
  });
  input.addEventListener('keydown', (event) => {
    if (suggestions.hidden && ['ArrowDown', 'Enter'].includes(event.key)) drawSuggestions(input.value);
    if (event.key === 'ArrowDown' && filtered.length) { event.preventDefault(); activeIndex = Math.min(activeIndex + 1, filtered.length - 1); }
    else if (event.key === 'ArrowUp' && filtered.length) { event.preventDefault(); activeIndex = Math.max(activeIndex - 1, 0); }
    else if (event.key === 'Enter' && filtered.length) { event.preventDefault(); const item = filtered[Math.max(activeIndex, 0)]; selectBranch(item.code); }
    else if (event.key === 'Escape') { suggestions.hidden = true; input.setAttribute('aria-expanded', 'false'); }
    $$('.combo-option', suggestions).forEach((option, index) => {
      option.setAttribute('aria-selected', index === activeIndex ? 'true' : 'false');
      if (index === activeIndex) option.scrollIntoView({ block: 'nearest' });
    });
    if (activeIndex >= 0) input.setAttribute('aria-activedescendant', `branch-option-${activeIndex}`);
    else input.removeAttribute('aria-activedescendant');
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.branch-combobox')) { suggestions.hidden = true; input.setAttribute('aria-expanded', 'false'); }
  });
  if (initialCode && branches.some((branch) => branch.code === initialCode)) selectBranch(initialCode);
}

async function loadBranchProfile(code) {
  const host = $('#branch-profile');
  host.innerHTML = '<p class="loading-line">Loading branch information…</p>';
  try {
    const [data, forecasts, status] = await Promise.all([
      getJson(`/branches/${encodeURIComponent(code)}`),
      getJson(`/branches/${encodeURIComponent(code)}/forecasts`),
      getJson('/status')
    ]);
    const branch = data.branch;
    const serviceHtml = branch.services?.length
      ? `<ul class="service-list">${branch.services.map((service) => `<li>${esc(service)}</li>`).join('')}</ul>`
      : '<p class="small-text">No additional service information is listed for this branch.</p>';
    const contactRows = [
      ['Address', branch.address || '—'], ['Postal code', branch.postal_code || '—'],
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
        <button type="button" class="branch-tab" role="tab" id="branch-tab-ask" aria-controls="tab-ask" aria-selected="false" data-tab="ask" tabindex="-1">Ask a question</button>
        <button type="button" class="branch-tab" role="tab" id="branch-tab-events" aria-controls="tab-events" aria-selected="false" data-tab="events" tabindex="-1">Programs</button>
      </div>
      <section id="tab-overview" class="branch-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="branch-tab-overview">
        <section class="profile-section"><h3 class="section-heading">Branch information</h3>${renderTable(['Detail', 'Information'], contactRows)}</section>
        <section class="profile-section"><h3 class="section-heading">Reported services</h3>${serviceHtml}</section>
      </section>
      <section id="tab-activity" class="branch-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="branch-tab-activity" hidden>
        <div class="grid grid-2">${renderBranchHistory(data.history)}</div>
      </section>
      <section id="tab-forecast" class="branch-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="branch-tab-forecast" hidden>
        <div class="grid grid-2">${renderForecasts(data.history, forecasts)}</div>
      </section>
      <section id="tab-ask" class="branch-tabpanel" role="tabpanel" tabindex="0" aria-labelledby="branch-tab-ask" hidden>
        ${status.relate.ready ? '' : notice('Branch questions are not available right now.', 'warning')}
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
  const initial = (params.get('branches') || '').split(',').filter((code) => branches.some((branch) => branch.code === code)).slice(0, 6);
  pageContent.innerHTML = `<section class="panel compare-selector">
    <div class="compare-select-header"><div><h2 class="section-heading">Choose branches</h2><p class="section-intro">Choose branches to view their services and activity side by side.</p></div><p id="compare-count" class="selection-count" aria-live="polite">${initial.length} selected</p></div>
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
    $('#compare-count').textContent = `${selected.length} of 6 selected`;
    $('#compare-submit').disabled = selected.length < 2 || selected.length > 6;
    checkboxes.forEach((input) => { input.disabled = !input.checked && selected.length >= 6; });
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
    const codes = selected.map((branch) => branch.code);
    const host = $('#comparison-results');
    if (selected.length < 2) { host.innerHTML = notice('Choose at least two branches.', 'warning'); return; }
    const url = new URL(location.href); url.searchParams.set('branches', codes.join(',')); history.replaceState({}, '', url);
    host.innerHTML = '<p class="loading-line">Preparing your comparison…</p>';
    try {
      const data = await getJson(`/comparisons/data?branches=${encodeURIComponent(codes.join(','))}`);
      const branchRows = data.branches.map((branch) => [
        branch.name, branch.code, humanTier(branch.service_tier), branch.address || '—', branch.postal_code || '—',
        fmt(branch.square_footage), fmt(branch.workstations), (branch.services || []).join(', ') || '—'
      ]);
      const metricSections = Object.entries(data.metrics).map(([metric, years]) => {
        const rows = years.map((row) => [row.year, ...data.branches.map((branch) => fmt(row.values[branch.code]))]);
        return `<section class="section"><h3 class="section-heading">${esc(data.metric_labels[metric])}</h3>${multiLineChart(years, data.branches, data.metric_labels[metric])}${tableDetails(`${data.metric_labels[metric]} by year`, ['Year', ...data.branches.map((branch) => branch.name)], rows)}</section>`;
      }).join('');
      host.innerHTML = `
        <section class="section"><div class="toolbar toolbar-spread"><h2 class="section-heading">Branch details</h2>${csvExportButton(`/exports/comparisons.csv?branches=${encodeURIComponent(codes.join(','))}`)}</div>
          ${renderTable(['Branch', 'Code', 'Service tier', 'Address', 'Postal code', 'Area (sq ft)', 'Workstations', 'Reported services'], branchRows)}</section>
        <section class="section"><h2 class="section-heading">Selected branch locations</h2><div id="comparison-map" role="region" aria-label="Map of selected branches"></div>
          <details class="map-directory"><summary>View selected locations as a table</summary><div id="comparison-map-directory"></div></details></section>
        ${metricSections}`;
      renderPlotlyCharts(host);
      await createBranchMap('comparison-map', data.branches, '#comparison-map-directory');
    } catch (_) { host.innerHTML = notice('The comparison could not be loaded. Please try again.', 'error'); }
  });
  updateSelection();
  if (initial.length >= 2) $('#compare-submit').click();
}

function distinctOption(values, selected, label) {
  return `<option value="">${esc(label)}</option>${values.map((value) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(value)}</option>`).join('')}`;
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
    <section class="section"><div class="toolbar toolbar-spread"><h2 class="section-heading">Upcoming programs</h2><div id="event-export"></div></div>
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
      $('#event-export').innerHTML = csvExportButton(`/exports/events.csv?${queryString}`);
    } catch (_) {
      $('#event-results').innerHTML = notice('Programs could not be loaded right now. Please try again.', 'error');
      $('#event-summary').textContent = 'Programs could not be loaded.';
      $('#event-export').innerHTML = '';
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

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

const descriptions = {
  overview: 'Explore annual network activity, branch characteristics, service tiers and program data.',
  branches: 'Review branch information, historical activity, forecasts and connected graph evidence.',
  comparisons: 'Compare selected branches side by side across available reporting years and characteristics.',
  events: 'Discover upcoming programs using audience, interest, language, location and date preferences.',
  methodology: 'Review source datasets, reporting coverage, definitions, calculations and known limitations.'
};
$('#page-description').textContent = descriptions[page] || '';

function safeReadSetting(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}
function safeWriteSetting(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* Preferences remain usable for this page view. */ }
}
const themeToggle = $('#theme-toggle');
const scaleSelect = $('#font-scale');
function setTheme(theme) {
  const value = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = value;
  themeToggle.textContent = value === 'dark' ? 'Light mode' : 'Dark mode';
  themeToggle.setAttribute('aria-label', `Switch to ${value === 'dark' ? 'light' : 'dark'} mode`);
  safeWriteSetting('libraryto-theme', value);
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
  const response = await fetch(url, { ...options, headers: { Accept: 'application/json', ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || payload.error || `Request failed (${response.status})`);
  return payload;
}
function empty(message) { return `<div class="empty-state">${esc(message)}</div>`; }
function notice(message, type = '') { return `<div class="notice ${type}">${esc(message)}</div>`; }
function downloadFile(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
function csvExportButton(url, label = 'Export CSV') {
  return `<a class="button secondary" href="${esc(url)}">${esc(label)}</a>`;
}
function safeHttpUrl(value) {
  const raw = String(value || '').trim();
  try {
    const parsed = new URL(raw);
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : '';
  } catch (_) { return ''; }
}
function humanTier(value) {
  return value || 'Not specified';
}

function renderTable(headers, rows, options = {}) {
  if (!rows.length) return empty(options.emptyMessage || 'No matching records are available.');
  const headerHtml = headers.map((header) => `<th scope="col">${esc(header)}</th>`).join('');
  const rowHtml = rows.map((row) => `<tr>${row.map((cell) => {
    const value = cell && typeof cell === 'object' && Object.hasOwn(cell, 'html') ? cell.html : esc(cell);
    const className = cell && typeof cell === 'object' ? (cell.className || '') : '';
    return `<td class="${esc(className)}">${value}</td>`;
  }).join('')}</tr>`).join('');
  return `<div class="table-wrap"><table><thead><tr>${headerHtml}</tr></thead><tbody>${rowHtml}</tbody></table></div>`;
}

function chartDataTable(points, label) {
  return `<details class="chart-data"><summary>View ${esc(label.toLowerCase())} data</summary>${renderTable(
    ['Year', 'Value', 'Branches covered'],
    points.map((point) => [point.year, fmtDecimal(point.value), point.branches_covered ?? '—'])
  )}</details>`;
}
function lineChart(points, label) {
  if (!points || !points.length) return empty(`No observations are available for ${label.toLowerCase()}.`);
  const width = 680, height = 230, pad = { left: 58, right: 18, top: 20, bottom: 34 };
  const values = points.map((point) => Number(point.value));
  const min = Math.min(0, ...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const xy = points.map((point, index) => ({
    x: pad.left + index * plotWidth / Math.max(points.length - 1, 1),
    y: pad.top + (max - Number(point.value)) / range * plotHeight
  }));
  const path = xy.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ');
  const grid = [0, 1, 2, 3].map((index) => {
    const y = pad.top + index * plotHeight / 3;
    const value = max - index * range / 3;
    return `<line class="gridline" x1="${pad.left}" x2="${width - pad.right}" y1="${y}" y2="${y}"/><text x="${pad.left - 9}" y="${y + 4}" text-anchor="end">${esc(fmt(value))}</text>`;
  }).join('');
  const yearLabels = points.map((point, index) => {
    if (index !== 0 && index !== points.length - 1 && index !== Math.floor(points.length / 2)) return '';
    return `<text x="${xy[index].x}" y="${height - 8}" text-anchor="middle">${esc(point.year)}</text>`;
  }).join('');
  const dots = xy.map((point) => `<circle class="point" cx="${point.x}" cy="${point.y}" r="4"/>`).join('');
  const chartId = `chart-${++chartSequence}`;
  const svg = `<svg class="chart" id="${chartId}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)} by year"><title>${esc(label)} by year</title>${grid}<path class="series" d="${path}"/>${dots}${yearLabels}</svg>`;
  return `<div class="chart-block"><div class="chart-tools"><button type="button" class="chart-download" data-download-chart="${chartId}">Download chart (SVG)</button></div>${svg}${chartDataTable(points, label)}</div>`;
}
function multiLineChart(yearRows, branches, metricLabel) {
  const rows = yearRows || [];
  if (!rows.length || !branches.length) return empty(`No comparable ${metricLabel.toLowerCase()} observations are available.`);
  const years = rows.map((row) => row.year);
  const series = branches.map((branch, index) => ({
    name: branch.name,
    code: branch.code,
    colorClass: index % 5,
    values: rows.map((row) => row.values[branch.code] == null ? null : Number(row.values[branch.code]))
  }));
  const allValues = series.flatMap((item) => item.values.filter((value) => value !== null));
  if (!allValues.length) return empty(`No comparable ${metricLabel.toLowerCase()} observations are available.`);
  const width = 700, height = 250, pad = { left: 60, right: 15, top: 20, bottom: 36 };
  const min = Math.min(0, ...allValues), max = Math.max(...allValues), range = max - min || 1;
  const plotWidth = width - pad.left - pad.right, plotHeight = height - pad.top - pad.bottom;
  const grid = [0, 1, 2, 3].map((index) => {
    const y = pad.top + index * plotHeight / 3;
    const value = max - index * range / 3;
    return `<line class="gridline" x1="${pad.left}" x2="${width - pad.right}" y1="${y}" y2="${y}"/><text x="${pad.left - 9}" y="${y + 4}" text-anchor="end">${esc(fmt(value))}</text>`;
  }).join('');
  const x = (index) => pad.left + index * plotWidth / Math.max(years.length - 1, 1);
  const y = (value) => pad.top + (max - value) / range * plotHeight;
  const paths = series.map((item, index) => {
    const segments = [];
    let active = false;
    item.values.forEach((value, pointIndex) => {
      if (value === null) { active = false; return; }
      segments.push(`${active ? 'L' : 'M'}${x(pointIndex).toFixed(1)},${y(value).toFixed(1)}`);
      active = true;
    });
    const points = item.values.map((value, pointIndex) => value === null ? '' : `<circle class="point point-${index % 5}" cx="${x(pointIndex)}" cy="${y(value)}" r="3.5"/>`).join('');
    return `<path class="series series-${index % 5}" d="${segments.join(' ')}"/>${points}`;
  }).join('');
  const labels = years.map((year, index) => {
    if (index !== 0 && index !== years.length - 1 && index !== Math.floor(years.length / 2)) return '';
    return `<text x="${x(index)}" y="${height - 8}" text-anchor="middle">${esc(year)}</text>`;
  }).join('');
  const legend = series.map((item, index) => `<span class="legend-item"><span class="legend-line ${index ? `c${index}` : ''}"></span>${esc(item.name)}</span>`).join('');
  const chartId = `chart-${++chartSequence}`;
  const svg = `<svg class="chart" id="${chartId}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(metricLabel)} comparison across selected branches"><title>${esc(metricLabel)} comparison across selected branches</title>${grid}${paths}${labels}</svg>`;
  const rowsForTable = years.map((year, index) => [year, ...series.map((item) => fmt(item.values[index]))]);
  return `<div class="chart-block"><div class="legend">${legend}</div><div class="chart-tools"><button type="button" class="chart-download" data-download-chart="${chartId}">Download chart (SVG)</button></div>${svg}<details class="chart-data"><summary>View ${esc(metricLabel.toLowerCase())} data</summary>${renderTable(['Year', ...series.map((item) => item.name)], rowsForTable)}</details></div>`;
}

document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-download-chart]');
  if (!button) return;
  const chart = document.getElementById(button.dataset.downloadChart);
  if (!chart) return;
  const clone = chart.cloneNode(true);
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue('--accent').trim() || '#155b75';
  const line = css.getPropertyValue('--line').trim() || '#d2dce1';
  const text = css.getPropertyValue('--muted').trim() || '#52616a';
  clone.querySelectorAll('.series').forEach((path) => {
    const seriesMatch = path.getAttribute('class').match(/series-(\d+)/);
    const palette = [accent, '#ad6b34', '#4b8c78', '#8974b2', '#b15a76'];
    path.setAttribute('stroke', palette[seriesMatch ? Number(seriesMatch[1]) % palette.length : 0]);
    path.setAttribute('fill', 'none'); path.setAttribute('stroke-width', '2.5');
  });
  clone.querySelectorAll('.point').forEach((point) => point.setAttribute('fill', accent));
  clone.querySelectorAll('.gridline').forEach((gridline) => { gridline.setAttribute('stroke', line); gridline.setAttribute('stroke-width', '1'); });
  clone.querySelectorAll('text').forEach((label) => { label.setAttribute('fill', text); label.setAttribute('font-family', 'Arial, sans-serif'); label.setAttribute('font-size', '11'); });
  downloadFile(`${button.dataset.downloadChart}.svg`, new XMLSerializer().serializeToString(clone), 'image/svg+xml;charset=utf-8');
});

async function loadDataStatus() {
  const status = await getJson('/status');
  const loaded = Object.values(status.datasets).filter((dataset) => dataset.loaded).length;
  $('#data-status').textContent = `${loaded} of 6 datasets loaded`;
  return status;
}

async function renderOverview() {
  const [data, status] = await Promise.all([getJson('/overview'), loadDataStatus()]);
  const stats = [
    ['Circulation', data.totals.circulation, data.latest_years.circulation, data.coverage.circulation],
    ['Visits', data.totals.visits, data.latest_years.visits, data.coverage.visits],
    ['Workstation sessions', data.totals.workstations, data.latest_years.workstations, data.coverage.workstations],
    ['Card registrations', data.totals.registrations, data.latest_years.registrations, data.coverage.registrations],
    ['TPL branches', data.branch_count, null, null],
    ['Event records', data.event_count, null, null]
  ];
  const statHtml = stats.map(([label, value, year, coverage]) => `
    <div class="stat"><span class="stat-label">${esc(label)}</span>
      <strong class="stat-value">${fmt(value)}</strong>
      <span class="stat-note">${year ? `${esc(year)} reporting year · ${fmt(coverage)} branches represented` : label === 'TPL branches' ? 'Branch directory records' : 'Rows in the supplied event feed'}</span>
    </div>`).join('');
  const metricPanels = Object.entries(data.metrics).map(([key, label]) => `
    <article class="panel"><div class="panel-heading"><h3>${esc(label)}</h3><span>Annual totals</span></div>
      ${lineChart(data.trend[key], label)}
    </article>`).join('');
  const loadedMissing = Object.entries(status.datasets).filter(([, item]) => !item.loaded);
  const dataNotice = loadedMissing.length
    ? notice(`${loadedMissing.length} source dataset(s) are not loaded or do not contain the expected fields. Add the agreed CSV files under data/ and review Data & Methodology.`, 'warning')
    : '';
  const eventNotice = data.event_count && !data.event_feed_has_upcoming
    ? notice('The event feed contains no events dated today or later. Update tpl-events-feed.csv to show upcoming programs.', 'warning')
    : '';

  pageContent.innerHTML = `${dataNotice}${eventNotice}
    <section class="stat-grid" aria-label="Network summary">${statHtml}</section>
    <section class="section"><div class="toolbar toolbar-spread"><h2 class="section-heading">Network activity over time</h2>${csvExportButton('/exports/observations.csv')}</div>
      <div class="grid grid-2">${metricPanels}</div>
      <p class="small-text">Each headline total uses that metric’s latest available reporting year. Coverage counts show how many branch codes have an observation for that year. Reporting periods can differ by metric.</p>
    </section>
    <section class="section grid grid-2">
      <article><h2 class="section-heading">Branches by service tier</h2>${renderTable(['Service tier', 'Branch count'], Object.entries(data.tiers).map(([tier, count]) => [tier, fmt(count)]))}
        <p class="small-text">DL = District Library · NL = Neighbourhood Library · RR = Research &amp; Reference Library.</p>
      </article>
      <article><h2 class="section-heading">Source coverage</h2>${renderTable(['Dataset', 'Rows', 'Reporting years'], Object.entries(status.datasets).map(([key, item]) => [item.label, fmt(item.rows), item.first_year ? `${item.first_year}–${item.last_year}` : '—']))}
        <p class="small-text">Dataset definitions, source-file names and coverage diagnostics are available in <a href="/data-methodology">Data &amp; Methodology</a>.</p>
      </article>
    </section>
    <section class="section"><h2 class="section-heading">TPL branch locations</h2>
      <div id="branch-map" role="region" aria-label="Map of Toronto Public Library branches"></div>
      <p class="map-alt">Map pins use coordinates in the branch dataset. The linked branch directory below provides an accessible alternative to the map.</p>
      <div id="branch-map-list" class="branch-map-list"></div>
    </section>`;
  await initMap();
}

async function initMap() {
  const element = $('#branch-map');
  if (!element) return;
  try {
    const branches = await getJson('/branches');
    const points = branches.filter((branch) => Number.isFinite(branch.lat) && Number.isFinite(branch.lon));
    $('#branch-map-list').innerHTML = branches.map((branch) => `<a href="/branch-insights?branch=${encodeURIComponent(branch.code)}">${esc(branch.name)}</a>`).join('');
    if (!window.L) {
      element.textContent = 'The map library did not load. Use the branch directory links below.';
      return;
    }
    if (!points.length) {
      element.textContent = 'No branch coordinates are available in the supplied branch dataset.';
      return;
    }
    const map = L.map(element, { scrollWheelZoom: false }).setView([43.70, -79.40], 10);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors', maxZoom: 19
    }).addTo(map);
    const markers = points.map((branch) => L.marker([branch.lat, branch.lon]).addTo(map)
      .bindPopup(`<strong>${esc(branch.name)}</strong><br>${esc(branch.code)} · ${esc(branch.service_tier)}<br><a href="/branch-insights?branch=${encodeURIComponent(branch.code)}">Open branch profile</a>`));
    if (markers.length > 1) map.fitBounds(L.featureGroup(markers).getBounds().pad(0.06));
    else map.setView([points[0].lat, points[0].lon], 14);
    setTimeout(() => map.invalidateSize(), 100);
  } catch (_) {
    element.textContent = 'Branch locations could not be loaded. Use the Branch Insights directory.';
  }
}

function renderBranchHistory(history) {
  return Object.entries(history).map(([metric, points]) => `
    <article class="panel"><div class="panel-heading"><h3>${esc(({circulation: 'Circulation', visits: 'Visits', workstations: 'Workstation sessions', registrations: 'Card registrations'})[metric])}</h3><span>Annual history</span></div>
      ${lineChart(points, metric)}
    </article>`).join('');
}
function renderForecasts(forecasts) {
  return Object.entries(forecasts).map(([metric, result]) => {
    const label = ({circulation: 'Circulation', visits: 'Visits', workstations: 'Workstation sessions', registrations: 'Card registrations'})[metric] || metric;
    if (!result.available) return `<article class="panel"><div class="panel-heading"><h3>${esc(label)}</h3></div>${empty(result.reason)}</article>`;
    const forecastRows = result.forecasts.map((forecast) => [forecast.year, fmtDecimal(forecast.value)]);
    return `<article class="panel"><div class="panel-heading"><h3>${esc(label)}</h3><span>${esc(result.method)}</span></div>
      <p class="forecast-label">${esc(result.direction)} trend · ${result.observations} annual observations · ${result.historical_start}–${result.historical_end}</p>
      ${renderTable(['Forecast year', 'Point estimate'], forecastRows)}
      <p class="small-text">Expanding-window backtest MAE: ${fmtDecimal(result.backtest_mae)}. Naive last-value MAE: ${fmtDecimal(result.naive_baseline_mae)}.</p>
      <p class="small-text">${esc(result.uncertainty_note)}</p>
    </article>`;
  }).join('');
}
function renderEvidence(evidence) {
  if (!evidence || !evidence.length) return '';
  return `<div class="evidence-list">${evidence.map((item, index) => {
    const properties = Object.entries(item.properties || {}).slice(0, 12);
    const propertyHtml = properties.map(([key, value]) => `<dt>${esc(key)}</dt><dd>${esc(typeof value === 'object' ? JSON.stringify(value) : value)}</dd>`).join('');
    const connectionHtml = (item.connections || []).map((connection) => {
      const related = Object.entries(connection.related_properties || {}).slice(0, 8);
      const relatedHtml = related.map(([key, value]) => `<dt>${esc(key)}</dt><dd>${esc(typeof value === 'object' ? JSON.stringify(value) : value)}</dd>`).join('');
      return `<div class="evidence-connection"><p class="small-text">Connected through <strong>${esc(connection.relationship_type)}</strong>${connection.related_labels?.length ? ` to ${esc(connection.related_labels.join(', '))}` : ''}</p><dl>${relatedHtml}</dl></div>`;
    }).join('');
    return `<article class="evidence-item"><h4>Evidence ${index + 1}: ${esc((item.labels || []).join(', '))}</h4>
      <dl>${propertyHtml}</dl>${connectionHtml}
    </article>`;
  }).join('')}</div>`;
}

async function renderBranches() {
  const branches = await getJson('/branches');
  if (!branches.length) {
    pageContent.innerHTML = empty('The branch directory is not loaded. Add tpl-branch-general-information.csv to data/ and redeploy.');
    return;
  }
  const params = new URLSearchParams(location.search);
  let selected = params.get('branch') || branches[0].code;
  const valid = branches.some((branch) => branch.code === selected);
  if (!valid) selected = branches[0].code;
  pageContent.innerHTML = `<div class="branch-layout">
    <aside class="branch-browser" aria-label="Branch directory">
      <h2>Branch directory <span class="muted">(${branches.length})</span></h2>
      <label class="visually-hidden" for="branch-filter">Filter branches by name or code</label>
      <input id="branch-filter" class="text-control" type="search" placeholder="Filter branches">
      <div id="branch-list" class="branch-list" role="listbox" aria-label="Select a branch">
        ${branches.map((branch) => `<button type="button" class="branch-option" data-code="${esc(branch.code)}" aria-pressed="${branch.code === selected ? 'true' : 'false'}"><strong>${esc(branch.name)}</strong><small>${esc(branch.code)} · ${esc(humanTier(branch.service_tier))}</small></button>`).join('')}
      </div>
    </aside>
    <div id="branch-detail" class="branch-profile" aria-live="polite">${empty('Select a branch to view its information.')}</div>
  </div>`;

  const branchList = $('#branch-list');
  $('#branch-filter').addEventListener('input', (event) => {
    const term = event.target.value.trim().toLowerCase();
    $$('.branch-option', branchList).forEach((button) => {
      const branch = branches.find((item) => item.code === button.dataset.code);
      button.hidden = !`${branch.name} ${branch.code} ${branch.service_tier}`.toLowerCase().includes(term);
    });
  });
  branchList.addEventListener('click', (event) => {
    const button = event.target.closest('[data-code]');
    if (button) chooseBranch(button.dataset.code);
  });
  await chooseBranch(selected);

  async function chooseBranch(code) {
    selected = code;
    $$('.branch-option', branchList).forEach((button) => button.setAttribute('aria-pressed', button.dataset.code === code ? 'true' : 'false'));
    const nextUrl = new URL(location.href);
    nextUrl.searchParams.set('branch', code);
    history.replaceState({}, '', nextUrl);
    const detail = $('#branch-detail');
    detail.innerHTML = '<p class="loading-line">Loading branch information…</p>';
    try {
      const [data, forecasts, status] = await Promise.all([
        getJson(`/branches/${encodeURIComponent(code)}`),
        getJson(`/branches/${encodeURIComponent(code)}/forecasts`),
        getJson('/status')
      ]);
      const branch = data.branch;
      const services = branch.services?.length
        ? `<ul class="service-list">${branch.services.map((service) => `<li>${esc(service)}</li>`).join('')}</ul>`
        : '<p class="small-text">No designated service flags were identified in the source row.</p>';
      const eventHtml = data.events.length ? `<div class="event-list">${data.events.slice(0, 12).map((event) => {
        const url = safeHttpUrl(event.event_url);
        return `<article class="event-item"><h3>${esc(event.title)}</h3><div class="event-meta"><span>${esc(event.start || 'Date not supplied')}</span><span>${esc(event.location)}</span><span>${esc(event.audiences)}</span></div><p class="event-description">${esc(event.description)}</p>${url ? `<div class="event-actions"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Event details</a></div>` : ''}</article>`;
      }).join('')}</div>` : empty('No events were linked to this branch using the event feed location or branch code.');
      const graphReady = status.relate.ready;
      detail.innerHTML = `
        <header><h2>${esc(branch.name)}</h2><p class="profile-meta">${esc(branch.code)} · ${esc(humanTier(branch.service_tier))}${branch.address ? ` · ${esc(branch.address)}` : ''}</p></header>
        <section class="profile-section"><h3 class="section-heading">Branch characteristics</h3>
          ${renderTable(['Square footage', 'Workstations', 'Postal code', 'Telephone'], [[fmt(branch.square_footage), fmt(branch.workstations), branch.postal_code || '—', branch.telephone || '—']])}
          <div class="profile-section"><h4 class="subheading">Reported services</h4>${services}</div>
          ${branch.website && safeHttpUrl(branch.website) ? `<p class="small-text"><a href="${esc(safeHttpUrl(branch.website))}" target="_blank" rel="noopener noreferrer">Branch website</a></p>` : ''}
        </section>
        <section class="profile-section"><h3 class="section-heading">Historical activity</h3><div class="grid grid-2">${renderBranchHistory(data.history)}</div></section>
        <section class="profile-section"><h3 class="section-heading">Predictive insights</h3>
          <p class="section-intro">A linear trend baseline is shown only when the branch has at least six annual observations. Forecasts are point estimates, not guaranteed outcomes.</p>
          <div class="grid grid-2">${renderForecasts(forecasts)}</div>
        </section>
        <section class="profile-section"><h3 class="section-heading">Branch graph Q&amp;A</h3>
          <p class="section-intro">Ask a question about graph entities and their connections. Results are retrieved from the supplied Relate graph and include supporting properties.</p>
          ${graphReady ? '' : notice(status.relate.message, 'warning')}
          <form id="question-form" class="question-form"><label class="visually-hidden" for="branch-question">Question</label><input id="branch-question" class="text-control" type="text" maxlength="500" placeholder="e.g. What services are connected to this branch?" required><button class="button" type="submit">Search graph</button></form>
          <div id="answer-area" aria-live="polite"></div>
        </section>
        <section class="profile-section"><h3 class="section-heading">Events associated with this branch</h3>${eventHtml}</section>`;
      $('#question-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const input = $('#branch-question');
        const answerArea = $('#answer-area');
        const button = $('button[type="submit"]', event.currentTarget);
        if (!input.value.trim()) return;
        button.disabled = true;
        answerArea.innerHTML = '<p class="small-text">Searching the Relate graph…</p>';
        try {
          const answer = await getJson('/ask', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: input.value.trim(), branch_code: code })
          });
          answerArea.innerHTML = `<div class="answer-panel"><p>${esc(answer.answer)}</p>${answer.notice ? `<p class="small-text">${esc(answer.notice)}</p>` : ''}${renderEvidence(answer.evidence)}</div>`;
        } catch (error) {
          answerArea.innerHTML = notice(error.message, 'warning');
        } finally { button.disabled = false; }
      });
    } catch (error) {
      detail.innerHTML = notice(`Branch information could not be loaded: ${error.message}`, 'error');
    }
  }
}

async function renderComparisons() {
  const branches = await getJson('/branches');
  if (branches.length < 2) {
    pageContent.innerHTML = empty('At least two branch records are required for a branch comparison.');
    return;
  }
  const params = new URLSearchParams(location.search);
  const initial = (params.get('branches') || '').split(',').filter(Boolean);
  pageContent.innerHTML = `<section class="panel">
    <h2 class="section-heading">Select branches</h2>
    <p class="section-intro">Select up to six branches. Comparisons are descriptive and do not assign branch rankings or performance scores.</p>
    <form id="compare-form">
      <div class="grid grid-2">
        <div class="form-field"><label for="compare-branches">Branches</label><select id="compare-branches" class="select-control" multiple size="9">${branches.map((branch) => `<option value="${esc(branch.code)}" ${initial.includes(branch.code) ? 'selected' : ''}>${esc(branch.name)} (${esc(branch.code)})</option>`).join('')}</select><span class="hint">Use Ctrl (Windows) or Command (Mac) to select multiple branches.</span></div>
        <div><div class="form-field"><label for="year-from">First reporting year</label><input class="control" id="year-from" type="number" inputmode="numeric" placeholder="Any year"></div><div class="form-field" style="margin-top:.7rem"><label for="year-to">Last reporting year</label><input class="control" id="year-to" type="number" inputmode="numeric" placeholder="Any year"></div><div class="filter-actions" style="margin-top:1rem"><button class="button" type="submit">Compare branches</button><button class="button secondary" type="button" id="clear-compare">Clear</button></div></div>
      </div>
    </form>
  </section>
  <div id="comparison-results" class="section">${empty('Choose two or more branches to view a comparison.')}</div>`;
  const select = $('#compare-branches');
  $('#clear-compare').addEventListener('click', () => { Array.from(select.options).forEach((option) => { option.selected = false; }); $('#comparison-results').innerHTML = empty('Choose two or more branches to view a comparison.'); });
  $('#compare-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const codes = Array.from(select.selectedOptions).map((option) => option.value);
    const resultHost = $('#comparison-results');
    if (codes.length < 2) { resultHost.innerHTML = notice('Select at least two branches.', 'warning'); return; }
    if (codes.length > 6) { resultHost.innerHTML = notice('Select no more than six branches.', 'warning'); return; }
    const nextUrl = new URL(location.href);
    nextUrl.searchParams.set('branches', codes.join(','));
    history.replaceState({}, '', nextUrl);
    resultHost.innerHTML = '<p class="loading-line">Preparing comparison…</p>';
    try {
      const data = await getJson(`/comparisons/data?branches=${encodeURIComponent(codes.join(','))}`);
      if (data.branches.length < 2) { resultHost.innerHTML = empty('Two or more valid branch records are required.'); return; }
      const yearFrom = Number($('#year-from').value) || -Infinity;
      const yearTo = Number($('#year-to').value) || Infinity;
      const characteristics = data.branches.map((branch) => [branch.name, branch.code, humanTier(branch.service_tier), fmt(branch.square_footage), fmt(branch.workstations)]);
      const metricSections = Object.entries(data.metrics).map(([metric, years]) => {
        const filtered = years.filter((row) => Number(row.year) >= yearFrom && Number(row.year) <= yearTo);
        const rows = filtered.map((row) => [row.year, ...data.branches.map((branch) => fmt(row.values[branch.code]))]);
        return `<section class="section"><h3 class="section-heading">${esc(data.metric_labels[metric])}</h3>${multiLineChart(filtered, data.branches, data.metric_labels[metric])}${renderTable(['Year', ...data.branches.map((branch) => branch.name)], rows)}</section>`;
      }).join('');
      resultHost.innerHTML = `
        <div class="toolbar toolbar-spread"><h2 class="section-heading">Branch characteristics</h2>${csvExportButton(`/exports/comparisons.csv?branches=${encodeURIComponent(codes.join(','))}`)}</div>
        ${renderTable(['Branch', 'Code', 'Service tier', 'Square footage', 'Workstations'], characteristics)}
        <p class="small-text">Branch attributes are shown as supplied in the directory. Square footage is not a measure of full service capacity. No population or neighbourhood coverage assumptions are used.</p>
        ${metricSections}
        <p class="small-text">Only reported branch-year observations are shown. Blank cells mean that the selected branch does not have an observation for that metric and year.</p>`;
    } catch (error) { resultHost.innerHTML = notice(error.message, 'error'); }
  });
  if (initial.length >= 2) $('#compare-form').requestSubmit();
}

function eventItem(event) {
  const url = safeHttpUrl(event.event_url);
  const registrationUrl = safeHttpUrl(event.registration_url);
  const statusClass = ['Full', 'Closed'].includes(event.registration_status) ? 'closed' : event.registration_status === 'Registration open' ? 'open' : '';
  const statusLabel = event.registration_status === 'Status not supplied' ? 'Availability not supplied' : event.registration_status;
  return `<article class="event-item">
    <div class="panel-heading"><h3>${esc(event.title)}</h3><span class="event-status ${statusClass}">${esc(statusLabel)}</span></div>
    <div class="event-meta"><span>${esc(event.start || 'Date not supplied')}</span><span>${esc(event.location || 'Location not supplied')}</span><span>${esc(event.audiences || 'Audience not specified')}</span><span>${esc(event.languages || 'Language not specified')}</span></div>
    ${event.description ? `<p class="event-description">${esc(event.description)}</p>` : ''}
    <p class="event-reasons">Why it appears: ${esc((event.match_reasons || []).join(' · '))}${event.recurring ? ' · Recurring program' : ''}</p>
    ${(url || registrationUrl) ? `<div class="event-actions">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Event information</a>` : ''}${registrationUrl ? `<a href="${esc(registrationUrl)}" target="_blank" rel="noopener noreferrer">Registration details</a>` : ''}</div>` : ''}
  </article>`;
}
async function renderEvents() {
  const branches = await getJson('/branches');
  const params = new URLSearchParams(location.search);
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  pageContent.innerHTML = `<section class="panel">
    <h2 class="section-heading">Program and event finder</h2>
    <p class="section-intro">Recommendations use information supplied in the event feed. They do not predict attendance, popularity or program effectiveness. Registration status is only shown when the feed supplies it.</p>
    <form id="event-filters" class="filter-grid">
      <div class="form-field"><label for="interest">Interest or keyword</label><input class="control" id="interest" name="interest" placeholder="e.g. coding, reading" value="${esc(params.get('interest') || '')}"></div>
      <div class="form-field"><label for="audience">Audience</label><input class="control" id="audience" name="audience" placeholder="e.g. Adults, Children" value="${esc(params.get('audience') || '')}"></div>
      <div class="form-field"><label for="language">Language</label><input class="control" id="language" name="language" placeholder="e.g. English, French" value="${esc(params.get('language') || '')}"></div>
      <div class="form-field"><label for="event_type">Event type</label><input class="control" id="event_type" name="event_type" placeholder="e.g. Workshop" value="${esc(params.get('event_type') || '')}"></div>
      <div class="form-field"><label for="event_branch">Branch or location</label><input class="control" id="event_branch" name="branch" list="branch-options" placeholder="Branch name or code" value="${esc(params.get('branch') || '')}"><datalist id="branch-options">${branches.map((branch) => `<option value="${esc(branch.name)}"></option><option value="${esc(branch.code)}"></option>`).join('')}</datalist></div>
      <div class="form-field"><label for="start_date">From date</label><input class="control" id="start_date" name="start_date" type="date" value="${esc(params.get('start_date') || today)}"></div>
      <div class="form-field"><label for="end_date">To date</label><input class="control" id="end_date" name="end_date" type="date" value="${esc(params.get('end_date') || '')}"></div>
      <div class="form-field"><label for="time_from">Start time from</label><input class="control" id="time_from" name="time_from" type="time" value="${esc(params.get('time_from') || '')}"></div>
      <div class="form-field"><label for="time_to">Start time to</label><input class="control" id="time_to" name="time_to" type="time" value="${esc(params.get('time_to') || '')}"></div>
      <div class="form-field"><label for="registration">Registration</label><select class="select-control" id="registration" name="registration"><option value="">Any status</option><option value="available" ${params.get('registration') === 'available' ? 'selected' : ''}>Confirmed open only</option></select><span class="hint">Events without a supplied status are not treated as open.</span></div>
      <div class="filter-actions"><button class="button" type="submit">Find events</button><button class="button secondary" id="reset-events" type="button">Reset</button></div>
    </form>
  </section>
  <section class="section"><div class="toolbar toolbar-spread"><h2 class="section-heading">Matching programs and events</h2><div id="event-export"></div></div><p id="event-summary" class="small-text" aria-live="polite">Loading upcoming events…</p><div id="event-results" class="event-list"></div></section>`;
  const form = $('#event-filters');
  async function searchEvents(updateUrl = true) {
    const query = new URLSearchParams(new FormData(form));
    const queryString = query.toString();
    if (updateUrl) {
      const nextUrl = new URL(location.href);
      nextUrl.search = queryString;
      history.replaceState({}, '', nextUrl);
    }
    $('#event-results').innerHTML = '<p class="loading-line">Searching the event feed…</p>';
    try {
      const data = await getJson(`/events/recommendations?${queryString}`);
      $('#event-summary').textContent = `${fmt(data.total)} event record(s) match the selected period. Events are ordered by preference matches, then start date.`;
      $('#event-results').innerHTML = data.events.length ? data.events.map(eventItem).join('') : empty('No upcoming events match those filters. Try a wider date range or broader preferences.');
      $('#event-export').innerHTML = csvExportButton(`/exports/events.csv?${queryString}`);
    } catch (error) {
      $('#event-results').innerHTML = notice(error.message, 'error');
      $('#event-summary').textContent = 'The event feed could not be searched.';
      $('#event-export').innerHTML = '';
    }
  }
  form.addEventListener('submit', (event) => { event.preventDefault(); searchEvents(true); });
  $('#reset-events').addEventListener('click', () => {
    form.reset();
    $('#start_date').value = today;
    searchEvents(true);
  });
  await searchEvents(false);
}

async function renderMethodology() {
  const status = await loadDataStatus();
  const datasetRows = Object.entries(status.datasets).map(([key, dataset]) => {
    const label = dataset.loaded ? 'Loaded' : dataset.exists ? 'Check fields' : 'Missing';
    const coverage = dataset.first_year ? `${dataset.first_year}–${dataset.last_year}` : '—';
    return [dataset.label, `<span class="code-name">${esc(dataset.filename)}</span>`, fmt(dataset.rows), coverage, `<span class="${dataset.loaded ? 'status-loaded' : 'status-missing'}">${label}</span>`];
  });
  const graph = status.relate;
  const graphInfo = graph.ready
    ? `Read-only graph available. Labels: ${(graph.labels || []).join(', ') || 'none reported'}. Relationships: ${(graph.relationship_types || []).join(', ') || 'none reported'}.`
    : graph.message;
  pageContent.innerHTML = `
    <section><h2 class="section-heading">Source files</h2>
      ${renderTable(['Dataset', 'Expected filename', 'Rows', 'Reporting years', 'Status'], datasetRows)}
      <p class="method-copy">The six CSV files and the Relate database are stored together in the project’s single <span class="code-name">data/</span> directory. Dataset rows are read as a deployment snapshot and cached in memory by each application process.</p>
    </section>
    <section class="section grid grid-2">
      <article><h2 class="section-heading">Relate graph</h2>
        <div class="method-list"><div class="method-row"><strong>Database file</strong><span class="code-name">${esc(graph.filename)}</span></div><div class="method-row"><strong>File present</strong><span class="${graph.file_present ? 'status-loaded' : 'status-missing'}">${graph.file_present ? 'Yes' : 'No'}</span></div><div class="method-row"><strong>Python client</strong><span>${graph.client_available ? 'Available' : 'Not available'}</span></div><div class="method-row"><strong>Connection mode</strong><span>Embedded · read only</span></div></div>
        <p class="method-copy">${esc(graphInfo)}</p>
        <p class="method-copy">Branch graph Q&amp;A uses schema-aware, parameterized Cypher retrieval and displays returned node properties and connected evidence. It does not execute user-written Cypher or claim to generate facts with a language model.</p>
      </article>
      <article><h2 class="section-heading">Metric definitions</h2>
        <div class="method-list"><div class="method-row"><strong>Circulation</strong><span>Annual circulation values as reported in the source dataset.</span></div><div class="method-row"><strong>Visits</strong><span>Annual visit counts as reported. They are not interpreted as unique people.</span></div><div class="method-row"><strong>Workstation sessions</strong><span>Annual workstation-use session values as reported.</span></div><div class="method-row"><strong>Card registrations</strong><span>Annual registration values as reported. They are not treated as active-card counts.</span></div></div>
      </article>
    </section>
    <section class="section grid grid-2">
      <article><h2 class="section-heading">Analysis rules</h2>
        <div class="method-list"><div class="method-row"><strong>Network totals</strong><span>Sum branch observations for each metric’s latest available reporting year. Coverage is shown beside each total.</span></div><div class="method-row"><strong>Branch comparisons</strong><span>Show observed values by reporting year. Missing branch-year observations remain blank.</span></div><div class="method-row"><strong>Forecasts</strong><span>Linear trend baseline with an expanding-window comparison against the last-observation baseline. Six or more observations required.</span></div><div class="method-row"><strong>Program matching</strong><span>Preference matching uses audience, language, type, branch/location, date/time and event text supplied in the feed.</span></div></div>
      </article>
      <article><h2 class="section-heading">Interpretation limits</h2>
        <div class="method-list"><div class="method-row"><strong>No branch rankings</strong><span>LibraryTO does not rate branches or label them as underperforming or overperforming.</span></div><div class="method-row"><strong>Branch size</strong><span>Square footage is descriptive and does not represent staffing, hours, maintenance or full service capacity.</span></div><div class="method-row"><strong>Events</strong><span>Event metadata does not provide attendance, demand, satisfaction or effectiveness.</span></div><div class="method-row"><strong>Coverage</strong><span>Metrics may cover different years and branch sets. Comparisons must account for that variation.</span></div><div class="method-row"><strong>Forecasts</strong><span>Baseline projections are not causal explanations or guaranteed future outcomes.</span></div></div>
      </article>
    </section>
    <section class="section"><h2 class="section-heading">Refreshing the data</h2>
      <p class="method-copy">Replace the source snapshots in <span class="code-name">data/</span> and redeploy the application. Vercel deployments use bundled read-only source files; runtime writes are not used as persistent storage. The Relate file must be named <span class="code-name">tpl_library_graph.rl</span>.</p>
      <p class="method-copy">Neighbourhood polygons, population data and neighbourhood service-coverage analysis are not used in this application.</p>
    </section>`;
}

const renderers = {
  overview: renderOverview,
  branches: renderBranches,
  comparisons: renderComparisons,
  events: renderEvents,
  methodology: renderMethodology
};
(async () => {
  try {
    await (renderers[page] || renderOverview)();
  } catch (error) {
    pageContent.innerHTML = notice(`Unable to load this section: ${error.message}`, 'error');
  } finally {
    pageContent.setAttribute('aria-busy', 'false');
  }
})();

const searchInput = $('#global-search');
const searchResults = $('#search-results');
let searchTimer;
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  const query = searchInput.value.trim();
  if (query.length < 2) {
    searchResults.hidden = true;
    searchInput.setAttribute('aria-expanded', 'false');
    return;
  }
  searchTimer = setTimeout(async () => {
    try {
      const data = await getJson(`/search?q=${encodeURIComponent(query)}`);
      const items = [
        ...data.branches.map((branch) => ({ label: branch.name, sub: `Branch · ${branch.code}`, url: `/branch-insights?branch=${encodeURIComponent(branch.code)}` })),
        ...data.events.map((event) => ({ label: event.title, sub: `Event · ${event.location || 'Location not supplied'}`, url: `/programs-events?interest=${encodeURIComponent(query)}` }))
      ];
      searchResults.innerHTML = items.length
        ? items.map((item) => `<a class="search-result" role="option" href="${item.url}">${esc(item.label)}<small>${esc(item.sub)}</small></a>`).join('')
        : '<p class="search-empty">No results found.</p>';
      searchResults.hidden = false;
      searchInput.setAttribute('aria-expanded', 'true');
    } catch (_) {
      searchResults.hidden = true;
      searchInput.setAttribute('aria-expanded', 'false');
    }
  }, 180);
});
document.addEventListener('click', (event) => {
  if (!event.target.closest('.global-search')) {
    searchResults.hidden = true;
    searchInput.setAttribute('aria-expanded', 'false');
  }
});
searchInput.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    searchResults.hidden = true;
    searchInput.setAttribute('aria-expanded', 'false');
  }
});

/* Read-only Branch Explorer and activity-intensity panels.
   All derived values use the repository's existing CSV snapshots. */
(() => {
  'use strict';

  const page = document.querySelector('#main')?.dataset.page || '';
  const root = document.querySelector('#page-content');
  if (!root) return;

  const metricLabels = {
    circulation: 'Annual circulation',
    visits: 'Annual visits',
    workstations: 'Workstation sessions',
    registrations: 'Card registrations'
  };
  let branchListPromise;
  const number = value => value == null || !Number.isFinite(Number(value)) ? '—' : new Intl.NumberFormat('en-CA', {maximumFractionDigits: 2}).format(Number(value));
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  async function getJSON(url) {
    const response = await fetch(url, {headers:{'Accept':'application/json'}, cache:'no-store'});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
    return payload;
  }
  function branchList() {
    if (!branchListPromise) branchListPromise = getJSON('/branches');
    return branchListPromise;
  }
  function createSection(id, title, description) {
    const section = document.createElement('section');
    section.className = 'analysis-section libraryto-enhancement';
    section.id = id;
    section.innerHTML = `<div class="enhancement-heading"><div><h2>${escapeHtml(title)}</h2><p class="small-note">${escapeHtml(description)}</p></div></div>`;
    return section;
  }
  function intensityMarkup(metric, result, mode, codes) {
    const data = result.metrics?.[metric];
    if (!data) return '<p class="small-note">No matching annual observations are available.</p>';
    const years = data.years || [];
    if (!years.length) return '<p class="small-note">No annual observations are available for this selection.</p>';
    if (mode === 'overview') {
      const rows = years.map(item => `<tr><th scope="row">${escapeHtml(item.year)}</th><td>${number(item.network_per_1000_sq_ft)}</td><td>${number(item.branches_with_values)}</td></tr>`).join('');
      const latest = years[years.length - 1];
      const top = (latest.branch_values || []).slice(0, 10).map(item => `<tr><th scope="row">${escapeHtml(item.name)}</th><td>${number(item.per_1000_sq_ft)}</td><td>${number(item.activity)}</td><td>${number(item.square_footage)}</td></tr>`).join('');
      return `<div class="intensity-summary"><p><strong>Network intensity</strong> is total reported activity divided by the square footage of branches with a reported value for that year.</p><div class="table-scroll"><table class="data-table" aria-label="Network activity intensity by year"><caption class="visually-hidden">Network activity intensity by year</caption><thead><tr><th scope="col">Year</th><th scope="col">Activity per 1,000 sq ft</th><th scope="col">Branches included</th></tr></thead><tbody>${rows}</tbody></table></div><h3>Highest branch intensity · ${escapeHtml(latest.year)}</h3><div class="table-scroll"><table class="data-table" aria-label="Branches with highest activity intensity"><caption class="visually-hidden">Branches with highest activity intensity in ${escapeHtml(latest.year)}</caption><thead><tr><th scope="col">Branch</th><th scope="col">Per 1,000 sq ft</th><th scope="col">Annual activity</th><th scope="col">Area (sq ft)</th></tr></thead><tbody>${top || '<tr><td colspan="4">No branch values available.</td></tr>'}</tbody></table></div></div>`;
    }
    const selected = new Set(codes || []);
    const rows = [];
    for (const year of years) {
      const values = year.branch_values || [];
      if (mode === 'branch') {
        const match = values.find(item => selected.has(item.code));
        if (match) rows.push(`<tr><th scope="row">${escapeHtml(year.year)}</th><td>${number(match.per_1000_sq_ft)}</td><td>${number(match.activity)}</td><td>${number(match.square_footage)}</td></tr>`);
      } else {
        const matches = values.filter(item => selected.has(item.code));
        if (matches.length) rows.push(`<tr><th scope="row">${escapeHtml(year.year)}</th>${codes.map(code => {const m=matches.find(item=>item.code===code);return `<td>${number(m?.per_1000_sq_ft)}</td>`;}).join('')}</tr>`);
      }
    }
    const headers = mode === 'branch' ? '<th scope="col">Year</th><th scope="col">Per 1,000 sq ft</th><th scope="col">Annual activity</th><th scope="col">Area (sq ft)</th>' : `<th scope="col">Year</th>${codes.map(code => `<th scope="col">${escapeHtml(code)}</th>`).join('')}`;
    const caption = mode === 'branch' ? 'Selected branch activity intensity by year' : 'Selected branch activity intensity comparison by year';
    return `<div class="table-scroll"><table class="data-table" aria-label="${caption}"><caption class="visually-hidden">${caption}</caption><thead><tr>${headers}</tr></thead><tbody>${rows.join('') || `<tr><td colspan="${mode === 'branch' ? 4 : codes.length+1}">No branch values available.</td></tr>`}</tbody></table></div>`;
  }

  async function installIntensity(target, mode, codes, forcedMetric = null) {
    if (!target) return;
    const selectionKey = `${(codes || []).join(',')}:${forcedMetric || ''}`;
    const sectionId = `intensity-${mode}${forcedMetric ? `-${forcedMetric}` : ''}`;
    const existing = target.querySelector(`:scope > #${sectionId}`);
    if (existing && existing.dataset.selection === selectionKey) return;
    existing?.remove();
    const section = createSection(sectionId, 'Activity Intensity', 'Annual activity per 1,000 square feet, calculated from the supplied branch area and annual records. This is a size-normalized measure, not a measure of efficiency.');
    section.dataset.selection = selectionKey;
    const controlMarkup = forcedMetric ? '' : `<div class="intensity-controls"><label for="${mode}-intensity-metric">Annual metric</label><select class="control" id="${mode}-intensity-metric">${Object.entries(metricLabels).map(([key,label]) => `<option value="${key}">${escapeHtml(label)}</option>`).join('')}</select></div>`;
    section.innerHTML += `${controlMarkup}<div class="intensity-result" aria-live="polite" aria-atomic="true"><p class="small-note" role="status">Loading activity intensity…</p></div>`;
    target.append(section);
    const resultHost = section.querySelector('.intensity-result');
    const select = forcedMetric ? null : section.querySelector('select');
    try {
      const payload = await getJSON(`/activity-intensity${codes.length ? `?branch_codes=${encodeURIComponent(codes.join(','))}` : ''}`);
      const draw = () => { resultHost.innerHTML = intensityMarkup(forcedMetric || select.value, payload, mode, codes); };
      select?.addEventListener('change', draw);
      draw();
    } catch (error) {
      resultHost.innerHTML = `<p class="notice error" role="alert">${escapeHtml(error.message || 'Activity intensity is unavailable.')}</p>`;
    }
  }

  const nodeLabels = {
    BranchGeneralInformation: 'Branch directory',
    Neighbourhoods: 'Neighbourhood geography',
    LibraryNeighbourhood: 'Neighbourhood',
    LibraryWard: 'Ward',
    LibraryService: 'Service',
    LibraryFacility: 'Facility'
  };
  const relationshipLabels = {
    IN_NEIGHBOURHOOD: 'Located in neighbourhood',
    IN_WARD: 'Located in ward',
    OFFERS_SERVICE: 'Offers service',
    HAS_FACILITY: 'Has facility'
  };
  const explorerNodeTypes = new Set([
    'BranchGeneralInformation', 'LibraryNeighbourhood', 'LibraryWard', 'LibraryService', 'LibraryFacility'
  ]);
  const explorerRelationshipTypes = new Set([
    'IN_NEIGHBOURHOOD', 'IN_WARD', 'OFFERS_SERVICE', 'HAS_FACILITY'
  ]);
  function humanizeIdentifier(value) {
    return String(value || '')
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .replace(/[_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/\b\w/g, char => char.toUpperCase());
  }
  function niceNodeLabel(value) {
    return nodeLabels[value] || humanizeIdentifier(value);
  }
  function niceRelationshipLabel(value, fallback = '') {
    return relationshipLabels[value] || fallback || humanizeIdentifier(value);
  }
  function propertyTable(properties) {
    const entries = Object.entries(properties || {}).filter(([key,value]) => value !== null && value !== '');
    if (!entries.length) return '<p class="small-note">No additional details are available.</p>';
    return `<div class="table-scroll"><table class="data-table graph-property-table" aria-label="Connected record details"><caption class="visually-hidden">Connected record details</caption><tbody>${entries.map(([key,value])=>`<tr><th scope="row">${escapeHtml(humanizeIdentifier(key))}</th><td>${escapeHtml(typeof value === 'object' ? JSON.stringify(value) : value)}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function explorerSummary(graph) {
    const nodeRows = (graph.node_counts || []).filter(item => explorerNodeTypes.has(item.label)).map(item => `<tr><th scope="row">${escapeHtml(niceNodeLabel(item.label))}</th><td>${number(item.count)}</td></tr>`).join('');
    const relationshipRows = (graph.relationship_counts || []).filter(item => explorerRelationshipTypes.has(item.type)).map(item => `<tr><th scope="row">${escapeHtml(niceRelationshipLabel(item.type, item.label))}</th><td>${number(item.count)}</td></tr>`).join('');
    return `<div class="graph-stat-line"><span><strong>${number(graph.node_count)}</strong><small>Nodes</small></span><span><strong>${number(graph.relationship_count)}</strong><small>Relationships</small></span></div><div class="graph-summary-tables"><div class="table-scroll"><h3>Node Labels</h3><table class="data-table" aria-label="Node label counts"><caption class="visually-hidden">Node label counts</caption><thead><tr><th scope="col">Label</th><th scope="col">Nodes</th></tr></thead><tbody>${nodeRows || '<tr><td colspan="2">No node labels available.</td></tr>'}</tbody></table></div><div class="table-scroll"><h3>Relationship Types</h3><table class="data-table" aria-label="Relationship type counts"><caption class="visually-hidden">Relationship type counts</caption><thead><tr><th scope="col">Relationship</th><th scope="col">Connections</th></tr></thead><tbody>${relationshipRows || '<tr><td colspan="2">No relationship types available.</td></tr>'}</tbody></table></div></div>`;
  }
  function visibleConnections(branch) {
    return (branch?.connections || []).filter(edge => explorerRelationshipTypes.has(edge.relationship_type));
  }
  function connectionGroups(edges) {
    const groups = new Map();
    for (const edge of edges) {
      const key = edge.relationship_type;
      if (!groups.has(key)) groups.set(key, {label:niceRelationshipLabel(key, edge.relationship_label), edges:[]});
      groups.get(key).edges.push(edge);
    }
    return [...groups.values()].map(group => {
      const rows = group.edges.map(edge => `<details class="graph-node-details"><summary><strong>${escapeHtml(edge.target_title || 'Connected record')}</strong></summary><div class="graph-node-inspection">${propertyTable(edge.properties)}</div></details>`).join('');
      return `<section class="graph-relationship-group"><h3>${escapeHtml(group.label)} <span>${number(group.edges.length)}</span></h3><div class="graph-node-list">${rows}</div></section>`;
    }).join('');
  }
  function connectionIdentity(edge) {
    const props = edge.properties || {};
    const preferred = {
      IN_NEIGHBOURHOOD: ['area_key', 'neighbourhood_no', 'name'],
      IN_WARD: ['area_key', 'ward_no', 'name'],
      OFFERS_SERVICE: ['service_key', 'service_name', 'name'],
      HAS_FACILITY: ['facility_key', 'facility_name', 'name']
    }[edge.relationship_type] || [];
    const lookup = new Map(Object.entries(props).map(([key,value]) => [key.toLowerCase().replace(/[^a-z0-9]/g,''), value]));
    const identity = preferred.map(key => lookup.get(key.toLowerCase().replace(/[^a-z0-9]/g,''))).find(value => value !== undefined && value !== null && value !== '');
    return `${edge.relationship_type}:${String(identity ?? edge.target_title ?? '').trim().toLowerCase()}`;
  }
  function comparisonConnections(branches) {
    const shared = new Map();
    const uniqueByBranch = new Map();
    for (const branch of branches) {
      const seen = new Set();
      for (const edge of visibleConnections(branch)) {
        const key = connectionIdentity(edge);
        if (!key || seen.has(key)) continue;
        seen.add(key);
        if (!shared.has(key)) shared.set(key, {edge, branches:[]});
        shared.get(key).branches.push(branch.branch_name);
      }
    }
    const common = [...shared.values()].filter(item => item.branches.length > 1);
    for (const branch of branches) {
      const rows = [];
      const seen = new Set();
      for (const edge of visibleConnections(branch)) {
        const key = connectionIdentity(edge);
        if (seen.has(key)) continue;
        seen.add(key);
        const item = shared.get(key);
        if (item?.branches.length === 1) rows.push(edge);
      }
      uniqueByBranch.set(branch.branch_code, rows);
    }
    const commonRows = common.map(item => `<tr><th scope="row">${escapeHtml(niceRelationshipLabel(item.edge.relationship_type, item.edge.relationship_label))}</th><td>${escapeHtml(item.edge.target_title || 'Connected record')}</td><td>${escapeHtml(item.branches.join(', '))}</td></tr>`).join('');
    const sharedMarkup = common.length
      ? `<div class="table-scroll"><table class="data-table" aria-label="Connections shared by selected branches"><caption class="visually-hidden">Connections shared by selected branches</caption><thead><tr><th scope="col">Relationship</th><th scope="col">Shared connection</th><th scope="col">Branches</th></tr></thead><tbody>${commonRows}</tbody></table></div>`
      : '<p class="small-note">The selected branches do not share a neighbourhood, ward, service or facility connection in the graph.</p>';
    const uniqueMarkup = branches.map(branch => {
      const edges = uniqueByBranch.get(branch.branch_code) || [];
      return `<details class="branch-connection-details"><summary><strong>${escapeHtml(branch.branch_name)}</strong><span>${number(edges.length)} branch-specific connections</span></summary>${edges.length ? connectionGroups(edges) : '<p class="small-note">No branch-specific connections in the selected categories.</p>'}</details>`;
    }).join('');
    return `<section class="branch-explorer-block"><h3>Shared connections</h3>${sharedMarkup}</section><section class="branch-explorer-block"><h3>Branch-specific connections</h3>${uniqueMarkup}</section>`;
  }
  async function installExplorer(target, mode, selectedCodes) {
    if (!target || !selectedCodes.length) return;
    const currentKey = selectedCodes.join(',');
    const existing = target.querySelector(':scope > #branch-explorer');
    if (existing && existing.dataset.mode === mode && existing.dataset.selection === currentKey) return;
    existing?.remove();
    const section = createSection('branch-explorer', 'Branch Explorer', mode === 'comparison'
      ? 'Explore shared and branch-specific neighbourhood, ward, service and facility connections for the selected branches.'
      : 'Explore the selected branch’s neighbourhood, ward, service and facility connections.');
    section.dataset.mode = mode;
    section.dataset.selection = currentKey;
    section.innerHTML += '<div class="branch-explorer-summary" aria-live="polite" aria-atomic="true"><p class="small-note" role="status">Loading branch connections…</p></div><div class="branch-explorer-connections" aria-live="polite" aria-atomic="true"></div>';
    target.append(section);
    const summary = section.querySelector('.branch-explorer-summary');
    const connections = section.querySelector('.branch-explorer-connections');
    try {
      const graph = await getJSON(`/relate/explorer?branch_codes=${encodeURIComponent(selectedCodes.join(','))}`);
      summary.innerHTML = explorerSummary(graph);
      const branches = (graph.selected || []).filter(branch => selectedCodes.includes(branch.branch_code));
      if (mode === 'comparison') {
        if (branches.length < 2) {
          connections.innerHTML = '<p class="small-note">Select at least two branches to explore their connected context.</p>';
          return;
        }
        connections.innerHTML = comparisonConnections(branches);
        return;
      }
      const branch = branches[0];
      if (!branch) {
        connections.innerHTML = '<p class="small-note">The selected branch could not be found in the graph.</p>';
        return;
      }
      const edges = visibleConnections(branch);
      connections.innerHTML = `<div class="graph-root-node"><strong>${escapeHtml(branch.branch_name)}</strong></div>${edges.length ? connectionGroups(edges) : '<p class="small-note">No neighbourhood, ward, service or facility connections were found for this branch.</p>'}`;
    } catch (error) {
      summary.innerHTML = `<p class="notice error" role="alert">${escapeHtml(error.message || 'The Branch Explorer could not be loaded.')}</p>`;
      connections.innerHTML = '';
    }
  }

  let enhancementTimer;
  let enhancing = false;
  let enhanceAgain = false;
  function enhance() {
    clearTimeout(enhancementTimer);
    enhancementTimer = setTimeout(async () => {
      if (enhancing) {
        enhanceAgain = true;
        return;
      }
      enhancing = true;
      try {
        if (page === 'overview') {
          // Activity intensity remains in the annual metric view. The graph explorer is not useful here.
          const panel = document.querySelector('#overview-panel-2 .ranking-metric-panel:not([hidden])');
          if (panel) await installIntensity(panel, 'overview', [], panel.dataset.metric || 'circulation');
        } else if (page === 'branches') {
          const profile = document.querySelector('#branch-profile');
          const content = profile?.querySelector('.profile-render-content');
          const code = profile?.dataset.branchCode || '';
          if (content && code && !profile.querySelector('.profile-loading-overlay')) {
            const activityPanel = content.querySelector('#branch-panel-1');
            if (activityPanel) await installIntensity(activityPanel, 'branch', [code]);
            const explorerHost = content.querySelector('#branch-explorer-host');
            if (explorerHost) await installExplorer(explorerHost, 'branch', [code]);
          }
        } else if (page === 'comparisons') {
          const result = document.querySelector('#comparison-results');
          if (result?.querySelector('.tabs[aria-label="comparison-main"]')) {
            const codes = [...document.querySelectorAll('#compare-list input[type="checkbox"]:checked')].map(item=>item.value);
            const metricPanel = result.querySelector('#comparison-main-panel-0 > .tab-panel:not([hidden])');
            if (metricPanel) await installIntensity(metricPanel, 'comparison', codes, metricPanel.dataset.metric || 'circulation');
            if (codes.length >= 2) await installExplorer(result, 'comparison', codes);
          }
        }
      } finally {
        enhancing = false;
        if (enhanceAgain) {
          enhanceAgain = false;
          enhance();
        }
      }
    }, 100);
  }

  const observer = new MutationObserver(() => { enhance(); });
  observer.observe(root, {childList:true, subtree:true});
  document.addEventListener('change', event => {
    if (event.target.matches('#compare-list input[type="checkbox"]')) enhance();
  });
  document.addEventListener('click', event => {
    if (event.target.closest('.tabs[aria-label="annual-metric"]') || event.target.closest('.tabs[aria-label="comparison-year"]')) enhance();
  });
  enhance();
})();

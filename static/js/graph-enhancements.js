/* LibraryTO judge-facing Relate Explorer and activity-intensity panels.
   Uses only the application's existing branch and annual metric records. */
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
      return `<div class="intensity-summary"><p><strong>Network intensity</strong> is total reported activity divided by the square footage of branches with a reported value for that year.</p><div class="table-scroll"><table class="data-table"><thead><tr><th>Year</th><th>Activity per 1,000 sq ft</th><th>Branches included</th></tr></thead><tbody>${rows}</tbody></table></div><h3>Highest branch intensity · ${escapeHtml(latest.year)}</h3><div class="table-scroll"><table class="data-table"><thead><tr><th>Branch</th><th>Per 1,000 sq ft</th><th>Annual activity</th><th>Area (sq ft)</th></tr></thead><tbody>${top || '<tr><td colspan="4">No branch values available.</td></tr>'}</tbody></table></div></div>`;
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
    const headers = mode === 'branch' ? '<th>Year</th><th>Per 1,000 sq ft</th><th>Annual activity</th><th>Area (sq ft)</th>' : `<th>Year</th>${codes.map(code => `<th>${escapeHtml(code)}</th>`).join('')}`;
    return `<div class="table-scroll"><table class="data-table"><thead><tr>${headers}</tr></thead><tbody>${rows.join('') || `<tr><td colspan="${mode === 'branch' ? 4 : codes.length+1}">No branch values available.</td></tr>`}</tbody></table></div>`;
  }

  async function installIntensity(target, mode, codes) {
    if (!target) return;
    const selectionKey = (codes || []).join(',');
    const existing = target.querySelector(`:scope > #intensity-${mode}`);
    if (existing && existing.dataset.selection === selectionKey) return;
    existing?.remove();
    const section = createSection(`intensity-${mode}`, 'Activity per 1,000 sq ft', 'Compare reported annual activity relative to branch floor area. This is a size-normalized measure, not a measure of efficiency.');
    section.dataset.selection = selectionKey;
    section.innerHTML += `<div class="intensity-controls"><label for="${mode}-intensity-metric">Measure</label><select class="control" id="${mode}-intensity-metric">${Object.entries(metricLabels).map(([key,label]) => `<option value="${key}">${escapeHtml(label)}</option>`).join('')}</select></div><div class="intensity-result" aria-live="polite"><p class="small-note">Loading activity intensity…</p></div>`;
    target.append(section);
    const resultHost = section.querySelector('.intensity-result');
    const select = section.querySelector('select');
    let payload;
    try {
      payload = await getJSON(`/activity-intensity${codes.length ? `?branch_codes=${encodeURIComponent(codes.join(','))}` : ''}`);
      const draw = () => { resultHost.innerHTML = intensityMarkup(select.value, payload, mode, codes); };
      select.addEventListener('change', draw);
      draw();
    } catch (error) {
      resultHost.innerHTML = `<p class="notice error">${escapeHtml(error.message || 'Activity intensity is unavailable.')}</p>`;
    }
  }

  function branchLabel(branches, code) {
    return branches.find(item => item.code === code)?.name || code;
  }

  async function installExplorer(target, mode, selectedCodes) {
    if (!target) return;
    const currentKey = selectedCodes.join(',');
    const existing = target.querySelector(':scope > #relate-explorer');
    if (existing && existing.dataset.mode === mode && existing.dataset.selection === currentKey) return;
    existing?.remove();
    const section = createSection('relate-explorer', 'Relate Explorer', 'Inspect the persisted graph: branch nodes, typed relationships and the records connected to a selected branch.');
    section.dataset.mode = mode;
    section.dataset.selection = currentKey;
    section.innerHTML += `<div class="relate-explorer-controls"><label for="relate-branch-select">Branch</label><select class="control" id="relate-branch-select"><option value="">Choose a branch</option></select><button class="button secondary" type="button" id="relate-refresh">Refresh graph</button></div><div class="relate-explorer-summary" aria-live="polite"><p class="small-note">Loading graph summary…</p></div><div class="relate-explorer-connections" aria-live="polite"></div>`;
    target.append(section);
    const select = section.querySelector('#relate-branch-select');
    const summary = section.querySelector('.relate-explorer-summary');
    const connections = section.querySelector('.relate-explorer-connections');
    try {
      const branches = await branchList();
      const allowed = (mode === 'comparison' || mode === 'branch') && selectedCodes.length ? selectedCodes : branches.map(item=>item.code);
      const options = allowed.map(code => `<option value="${escapeHtml(code)}">${escapeHtml(branchLabel(branches,code))}</option>`).join('');
      select.innerHTML = `<option value="">${mode === 'overview' ? 'Choose a branch to inspect' : 'Choose a selected branch'}</option>${options}`;
      if (selectedCodes.length) select.value = selectedCodes[0];
      if (!allowed.length) {
        summary.innerHTML = '<p class="small-note">Choose branches above before inspecting their connections.</p>';
      }
      async function load(code) {
        connections.innerHTML = '<p class="small-note">Loading connected records…</p>';
        try {
          const params = code ? `?branch_codes=${encodeURIComponent(code)}` : '';
          const graph = await getJSON(`/relate/explorer${params}`);
          summary.innerHTML = `<div class="graph-stat-line"><span><strong>${number(graph.node_count)}</strong><small>nodes</small></span><span><strong>${number(graph.relationship_count)}</strong><small>relationships</small></span><span><strong>${escapeHtml(graph.store)}</strong><small>persistent store · ${escapeHtml(graph.mode)}</small></span></div><div class="graph-summary-tables"><div class="table-scroll"><h3>Node labels</h3><table class="data-table"><thead><tr><th>Label</th><th>Nodes</th></tr></thead><tbody>${(graph.node_counts||[]).map(item=>`<tr><th>${escapeHtml(item.label)}</th><td>${number(item.count)}</td></tr>`).join('')}</tbody></table></div><div class="table-scroll"><h3>Relationship types</h3><table class="data-table"><thead><tr><th>Relationship</th><th>Edges</th></tr></thead><tbody>${(graph.relationship_counts||[]).map(item=>`<tr><th>${escapeHtml(item.label)}</th><td>${number(item.count)}</td></tr>`).join('') || '<tr><td colspan="2">No relationships have been created. Run the graph build script.</td></tr>'}</tbody></table></div></div>`;
          const branch = (graph.selected||[])[0];
          if (!code) {
            connections.innerHTML = '<p class="small-note">Select a branch to inspect the records connected to it.</p>';
            return;
          }
          if (!branch || !branch.connections?.length) {
            connections.innerHTML = '<p class="small-note">No connected records were found for this branch. Run <code>python scripts/build_relate_graph.py</code> after extracting the update to create the relationships.</p>';
            return;
          }
          const groups = new Map();
          for (const edge of branch.connections) {
            const key = edge.relationship_type;
            if (!groups.has(key)) groups.set(key, {label:edge.relationship_label, edges:[]});
            groups.get(key).edges.push(edge);
          }
          connections.innerHTML = `<div class="graph-root-node"><span>Selected branch node</span><strong>${escapeHtml(branch.branch_name)}</strong><small>BranchCode: ${escapeHtml(branch.branch_code)}</small></div>${[...groups.entries()].map(([type,group])=>`<section class="graph-relationship-group"><h4>${escapeHtml(group.label)} <span>${number(group.edges.length)}</span></h4><ul>${group.edges.map(edge=>`<li><span class="graph-edge-type">${escapeHtml(type)}</span><strong>${escapeHtml(edge.target_title)}</strong><small>${escapeHtml((edge.target_labels||[]).join(' · '))}</small></li>`).join('')}</ul></section>`).join('')}`;
        } catch (error) {
          connections.innerHTML = `<p class="notice error">${escapeHtml(error.message || 'The graph could not be explored.')}</p>`;
        }
      }
      select.addEventListener('change', () => load(select.value));
      section.querySelector('#relate-refresh').addEventListener('click', () => load(select.value));
      await load(select.value);
    } catch (error) {
      summary.innerHTML = `<p class="notice error">${escapeHtml(error.message || 'Branch list unavailable.')}</p>`;
    }
  }

  let enhancementTimer;
  async function enhance() {
    clearTimeout(enhancementTimer);
    enhancementTimer = setTimeout(async () => {
      if (page === 'overview') {
        const panel = document.querySelector('#overview-panel-0');
        if (panel) {
          await installIntensity(panel, 'overview', []);
          await installExplorer(root, 'overview', []);
        }
      } else if (page === 'branches') {
        const profile = document.querySelector('#branch-profile');
        const content = profile?.querySelector('.profile-render-content');
        const code = profile?.dataset.branchCode || '';
        if (content && code && !profile.querySelector('.profile-loading-overlay')) {
          const activityPanel = content.querySelector('#branch-panel-1');
          if (activityPanel) await installIntensity(activityPanel, 'branch', [code]);
          await installExplorer(profile, 'branch', [code]);
        } else if (profile && !content) {
          await installExplorer(profile, 'branch', []);
        }
      } else if (page === 'comparisons') {
        const result = document.querySelector('#comparison-results');
        if (result?.querySelector('.tabs[aria-label="comparison-main"]')) {
          const codes = [...document.querySelectorAll('#compare-list input[type="checkbox"]:checked')].map(item=>item.value);
          await installIntensity(result, 'comparison', codes);
          await installExplorer(result, 'comparison', codes);
        } else if (result && !result.querySelector('#relate-explorer')) {
          await installExplorer(result, 'comparison', []);
        }
      }
    }, 120);
  }

  const observer = new MutationObserver(enhance);
  observer.observe(root, {childList:true, subtree:true});
  document.addEventListener('change', event => {
    if (event.target.matches('#compare-list input[type="checkbox"]')) enhance();
  });
  enhance();
})();

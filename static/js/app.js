/* LibraryTO client. Vanilla JavaScript, accessible tabs, cached data, Plotly and Leaflet. */
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nf = new Intl.NumberFormat('en-CA', {maximumFractionDigits:0});
const df = new Intl.NumberFormat('en-CA', {maximumFractionDigits:2});
const fmt = value => value === null || value === undefined || value === '' ? '—' : nf.format(value);
const fmtD = value => value === null || value === undefined || value === '' ? '—' : df.format(value);
const root = $('#main');
const page = root.dataset.page;
const host = $('#page-content');
const version = root.dataset.cacheVersion || 'libraryto-v1';
const memoryCache = new Map();
const inflight = new Map();
const charts = new Map();
const maps = new Map();
let plotlyPromise;
let leafletPromise;
let chartCounter = 0;
const TTL = 300000;
const STALE = 1800000;
const METRICS = {circulation:'Annual Circulation', visits:'Annual Visitation', workstations:'Annual Workstation Usage', registrations:'Annual Card Registrations'};
const TIERS = {DL:'District Library', NL:'Neighbourhood Library', RR:'Research and Reference Library'};
const TIER_COLORS = {DL:'#0072B2', NL:'#D55E00', RR:'#009E73', Other:'#6C757D'};

function cacheGet(key) {
  try { return JSON.parse(sessionStorage.getItem(`libraryto:${version}:${key}`) || 'null'); } catch (_) { return null; }
}
function cacheSet(key, value) {
  const item = {time:Date.now(), value}; memoryCache.set(key,item);
  try { sessionStorage.setItem(`libraryto:${version}:${key}`,JSON.stringify(item)); } catch (_) {}
}
async function request(url, options={}) {
  const method = (options.method || 'GET').toUpperCase();
  if (method !== 'GET') {
    const response = await fetch(url, {...options,headers:{Accept:'application/json',...(options.headers||{})}});
    const body = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(body.detail || body.error || `Request failed (${response.status})`);
    return body;
  }
  const key = `${method}:${url}`;
  let item = memoryCache.get(key) || cacheGet(key);
  if (item) memoryCache.set(key,item);
  if (item && Date.now()-item.time < TTL) return item.value;
  if (inflight.has(key)) return inflight.get(key);
  const load = async () => {
    const response = await fetch(url,{headers:{Accept:'application/json'}});
    const body = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(body.detail || body.error || `Request failed (${response.status})`);
    cacheSet(key,body); return body;
  };
  const promise = load().finally(()=>inflight.delete(key));
  inflight.set(key,promise);
  if (item && Date.now()-item.time < STALE) { promise.catch(()=>{}); return item.value; }
  return promise;
}
function note(message, type='') { return `<p class="notice ${type}" role="status">${esc(message)}</p>`; }
function empty(message) { return `<p class="empty-state">${esc(message)}</p>`; }
function loadingMarkup(message, extraClass='') {
  return `<div class="loading-state ${esc(extraClass)}" role="status"><span class="loading-spinner" aria-hidden="true"></span><span>${esc(message)}</span></div>`;
}
function safeUrl(value) { try { const u=new URL(value); return ['https:','http:'].includes(u.protocol)?u.href:''; } catch(_){return '';} }
function metricName(key) { return METRICS[key] || key; }
function tierName(code) { return TIERS[code] || 'Other'; }

function setTheme(theme) {
  const value = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = value;
  const button = $('#theme-toggle');
  button.textContent = value === 'dark' ? 'Light mode' : 'Dark mode';
  button.setAttribute('aria-label', `Switch to ${value === 'dark' ? 'light' : 'dark'} mode`);
  try { localStorage.setItem('libraryto-theme',value); } catch (_) {}
  document.dispatchEvent(new Event('libraryto:themechange'));
}
function setScale(scale) {
  const value = ['small','medium','large'].includes(scale) ? scale : 'medium';
  document.documentElement.dataset.scale=value;
  $('#font-scale').value=value;
  try { localStorage.setItem('libraryto-scale',value); } catch (_) {}
}
try { setTheme(localStorage.getItem('libraryto-theme') || (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')); } catch (_) { setTheme('light'); }
try { setScale(localStorage.getItem('libraryto-scale') || 'medium'); } catch (_) { setScale('medium'); }
$('#theme-toggle').addEventListener('click',()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));
$('#font-scale').addEventListener('change',e=>setScale(e.target.value));

function loadScript(key, src) {
  if (window[key]) return Promise.resolve(window[key]);
  if (key==='Plotly' && plotlyPromise) return plotlyPromise;
  if (key==='L' && leafletPromise) return leafletPromise;
  const promise = new Promise((resolve,reject)=>{
    const script=document.createElement('script'); script.src=src; script.async=true;
    script.onload=()=>window[key]?resolve(window[key]):reject(new Error(`${key} did not load`));
    script.onerror=()=>reject(new Error(`${key} could not be loaded`)); document.head.append(script);
  });
  if (key==='Plotly') plotlyPromise=promise;
  if (key==='L') leafletPromise=promise;
  return promise;
}
const ensurePlotly=()=>loadScript('Plotly','https://cdn.plot.ly/plotly-2.35.2.min.js');
async function ensureLeaflet() {
  if (!document.querySelector('[data-leaflet-css]')) {
    const link=document.createElement('link'); link.rel='stylesheet'; link.href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'; link.dataset.leafletCss='1'; document.head.append(link);
  }
  return loadScript('L','https://unpkg.com/leaflet@1.9.4/dist/leaflet.js');
}

function chartId(spec) { const id=`libraryto-chart-${++chartCounter}`; charts.set(id,spec); return id; }
function chart(title, traces, layout={}, label=title) {
  const id=chartId({title,traces,layout});
  return `<div class="chart-wrap"><div id="${id}" class="plotly-chart" role="img" aria-label="Interactive chart: ${esc(label)}"></div></div>`;
}
function chartLayout(spec) {
  const css=getComputedStyle(document.documentElement);
  const text=css.getPropertyValue('--text').trim()||'#18252c';
  const muted=css.getPropertyValue('--muted').trim()||'#59666e';
  const line=css.getPropertyValue('--line').trim()||'#d7dfe3';
  return {
    title:{text:spec.title,x:.5,xanchor:'center',font:{family:'Inter, sans-serif',size:15,color:text}},
    autosize:true,height:350,margin:{l:65,r:25,t:62,b:70},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
    font:{family:'Inter, sans-serif',color:text,size:12},
    xaxis:{gridcolor:line,linecolor:line,tickfont:{color:muted},automargin:true},
    yaxis:{gridcolor:line,linecolor:line,tickfont:{color:muted},tickformat:',.0f',automargin:true},
    legend:{orientation:'h',y:-.24,font:{color:muted}},hovermode:'closest',showlegend:spec.traces.length>1,
    uirevision:`${page}-${spec.title}`,...spec.layout
  };
}
async function drawCharts(scope=document) {
  const elements=$$('.plotly-chart:not([data-drawn="1"])',scope).filter(el=>!el.closest('[hidden]'));
  if (!elements.length) return;
  try {
    const Plotly=await ensurePlotly();
    await Promise.all(elements.map(async element=>{
      const spec=charts.get(element.id); if (!spec || !element.isConnected) return;
      element.dataset.drawn='1';
      try {
        await Plotly.newPlot(element,spec.traces,chartLayout(spec),{responsive:true,displaylogo:false,scrollZoom:false,
          modeBarButtonsToRemove:['lasso2d','select2d','autoScale2d']});
      } catch (_) {
        element.dataset.drawn='0';element.textContent='Chart unavailable.';
      }
    }));
  } catch (_) { elements.forEach(el=>{el.textContent='Charts could not be loaded.';}); }
}
document.addEventListener('libraryto:themechange',()=>{
  if (!window.Plotly) return;
  $$('.plotly-chart[data-drawn="1"]').forEach(el=>{const spec=charts.get(el.id);if(spec)Plotly.relayout(el,chartLayout(spec));});
});
function titleCaseTabLabel(value) {
  return String(value ?? '').replace(/\b[a-z]/g, letter => letter.toUpperCase());
}
function tabsMarkup(items, group, active=0) {
  return `<div class="tabs" role="tablist" aria-label="${esc(group)}">${items.map((item,i)=>`<button type="button" class="tab" role="tab" id="${group.replace(/\W/g,'-')}-tab-${i}" aria-controls="${group.replace(/\W/g,'-')}-panel-${i}" aria-selected="${i===active?'true':'false'}" tabindex="${i===active?0:-1}" data-tab-group="${group}" data-tab-index="${i}">${esc(titleCaseTabLabel(item))}</button>`).join('')}</div>`;
}
function attachTabs(scope=document, afterChange=()=>{}) {
  $$('.tabs',scope).forEach(tablist=>{
    if(tablist.dataset.bound) return; tablist.dataset.bound='1';
    const group=tablist.getAttribute('aria-label');
    const activate=tab=>{
      const index=Number(tab.dataset.tabIndex);
      $$('.tab',tablist).forEach(t=>{const active=t===tab;t.setAttribute('aria-selected',active?'true':'false');t.tabIndex=active?0:-1;});
      const prefix=group.replace(/\W/g,'-');
      $$(`[id^="${prefix}-panel-"]`,scope).forEach(panel=>{panel.hidden=panel.id!==`${prefix}-panel-${index}`;});
      const panel=$(`#${prefix}-panel-${index}`,scope);
      if(panel){
        const followUp=afterChange(panel,index);
        if(followUp&&typeof followUp.then==='function')followUp.catch(()=>{});
        else drawCharts(panel);
      }
    };
    tablist.addEventListener('click',e=>{const tab=e.target.closest('.tab');if(tab)activate(tab);});
    tablist.addEventListener('keydown',e=>{
      const current=e.target.closest('.tab');if(!current)return;
      const list=$$('.tab',tablist);let i=list.indexOf(current);
      if(e.key==='ArrowRight')i=(i+1)%list.length;else if(e.key==='ArrowLeft')i=(i-1+list.length)%list.length;else if(e.key==='Home')i=0;else if(e.key==='End')i=list.length-1;else return;
      e.preventDefault();list[i].focus();activate(list[i]);
    });
  });
}
function table(headers,rows) {
  if(!rows.length)return empty('No reported values are available.');
  return `<div class="table-wrap" tabindex="0" role="region" aria-label="Data table"><table><thead><tr>${headers.map(h=>`<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${v&&typeof v==='object'&&Object.hasOwn(v,'html')?v.html:esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function details(label,headers,rows) { return `<details class="data-details"><summary>View ${esc(label)} by year</summary>${table(headers,rows)}</details>`; }
function lineTrace(points,label,color) {
  return {type:'scatter',mode:'lines+markers',name:label,x:points.map(p=>String(p.year)),y:points.map(p=>Number(p.value)),line:{width:2.8,color},marker:{size:6},hovertemplate:'%{x}<br>%{y:,.0f}<extra></extra>'};
}
function serviceTierCharts(data) {
  return Object.keys(METRICS).map(metric=>{
    const rows=data.tier_trends?.[metric]||[];
    const traces=['DL','NL','RR'].map(code=>({type:'scatter',mode:'lines+markers',name:tierName(code),x:rows.map(r=>String(r.year)),y:rows.map(r=>r.tiers?.[code]?.value??null),line:{width:2.5,color:TIER_COLORS[code]},marker:{size:5},connectgaps:false,hovertemplate:'%{x}<br>%{y:,.0f}<extra></extra>'}));
    return `<article class="panel">${chart(METRICS[metric],traces,{height:310},`${METRICS[metric]} by library type`)}</article>`;
  }).join('');
}
function branchTotals(data,metric,selectedYears=['all']) {
  const yearSet=new Set((selectedYears||['all']).map(String));
  const totals=new Map(),counts=new Map();
  (data.annual_values?.[metric]||[]).forEach(year=>{
    if(!yearSet.has('all')&&!yearSet.has(String(year.year)))return;
    data.branches.forEach(branch=>{
      const value=year.values?.[branch.code];
      if(value===null||value===undefined||!Number.isFinite(Number(value)))return;
      totals.set(branch.code,(totals.get(branch.code)||0)+Number(value));
      counts.set(branch.code,(counts.get(branch.code)||0)+1);
    });
  });
  return data.branches.map(branch=>({branch,value:totals.get(branch.code)??null,observations:counts.get(branch.code)||0}))
    .filter(row=>row.value!==null);
}
function branchOverviewResults(data,metric,yearSelection='all') {
  const selectedYears=yearSelection==='all'
    ? (data.annual_values?.[metric]||[]).map(row=>String(row.year))
    : [String(yearSelection)];
  const rows=branchTotals(data,metric,selectedYears).sort((a,b)=>a.value-b.value);
  const build=(items,label)=>{
    if(!items.length)return empty('No reported values are available for the selected reporting years.');
    const trace={type:'bar',orientation:'h',x:items.map(x=>x.value),y:items.map(x=>x.branch.name),marker:{color:'#286b83'},
      customdata:items.map(x=>[x.branch.code,tierName(x.branch.service_tier_code),x.observations]),
      hovertemplate:'%{y}<br>Total reported: %{x:,.0f}<br>Branch code: %{customdata[0]}<br>%{customdata[1]}<extra></extra>'};
    return chart('',[trace],{height:390,margin:{l:160,r:28,t:26,b:65},title:{text:''},
      xaxis:{rangemode:'tozero',title:{text:METRICS[metric]}},
      yaxis:{autorange:'reversed',automargin:true},showlegend:false},label);
  };
  const yearLabel=yearSelection==='all'?'All Years':String(yearSelection);
  const chartView=branchActivitySizeChart(data,metric,selectedYears);
  return `<div class="grid-2 ranking-charts">
      <section class="rank-chart-section"><h3>Top 10 Branches</h3>${build(rows.slice(-10).reverse(),`Top 10 branches by ${METRICS[metric]} · ${yearLabel}`)}</section>
      <section class="rank-chart-section"><h3>Bottom 10 Branches</h3>${build(rows.slice(0,10),`Bottom 10 branches by ${METRICS[metric]} · ${yearLabel}`)}</section>
    </div>
    <section class="rank-chart-section branch-size-section"><h3>Annual Activity And Branch Area</h3><div class="activity-size-chart">${chartView}</div></section>`;
}
function rankingMetricPanel(data,metric,index) {
  const years=(data.annual_values?.[metric]||[]).map(row=>String(row.year));
  const yearOptions=[`<option value="all" selected>All Years</option>`,...years.map(year=>`<option value="${esc(year)}">${esc(year)}</option>`)].join('');
  return `<section id="annual-metric-panel-${index}" data-metric="${esc(metric)}" class="tab-panel ranking-metric-panel" role="tabpanel" aria-labelledby="annual-metric-tab-${index}" ${index?'hidden':''}>
    <div class="branch-overview-filter"><label for="branch-overview-year-${index}">Reporting Year</label><select id="branch-overview-year-${index}" class="control branch-overview-year">${yearOptions}</select></div>
    <div class="branch-overview-results">${branchOverviewResults(data,metric,'all')}</div>
  </section>`;
}
function branchActivitySizeChart(data,metric,selectedYears=['all']) {
  const allRows=data.annual_values?.[metric]||[];
  const yearSet=new Set((selectedYears||['all']).map(String));
  const annualRows=yearSet.has('all')?allRows:allRows.filter(row=>yearSet.has(String(row.year)));
  if(!annualRows.length)return empty('No annual values are available for the selected reporting years.');

  // One point per branch. When All is selected, sum that branch's reported
  // observations across all available years instead of plotting one point per year.
  const totals=new Map();
  annualRows.forEach(annual=>{
    (data.branches||[]).forEach(branch=>{
      const rawValue=annual.values?.[branch.code];
      if(rawValue===null||rawValue===undefined||rawValue===''||!Number.isFinite(Number(rawValue)))return;
      const current=totals.get(branch.code)||{value:0,observations:0};
      current.value+=Number(rawValue);
      current.observations+=1;
      totals.set(branch.code,current);
    });
  });
  const aggregatedPoints=(data.branches||[])
    .filter(branch=>Number(branch.square_footage)>0&&totals.has(branch.code))
    .map(branch=>({branch,...totals.get(branch.code)}));

  const tiers=['DL','NL','RR','Other'];
  const traces=tiers.map(code=>{
    const points=aggregatedPoints.filter(point=>(point.branch.service_tier_code||'Other')===code);
    return {type:'scatter',mode:'markers',name:tierName(code),x:points.map(point=>Number(point.branch.square_footage)),y:points.map(point=>point.value),
      customdata:points.map(point=>[point.branch.name,point.branch.code,point.observations]),
      marker:{size:9,color:TIER_COLORS[code]||TIER_COLORS.Other,opacity:.78},
      hovertemplate:`%{customdata[0]}<br>Branch Area: %{x:,.0f} sq ft<br>${METRICS[metric]} total: %{y:,.0f}<br>Reporting years with data: %{customdata[2]}<extra></extra>`};
  }).filter(trace=>trace.x.length);
  const yearLabel=yearSet.has('all')?'All':[...yearSet].join(', ');
  if(!traces.length)return empty('No branches have both a reported annual value and floor area for these reporting years.');
  return chart(`${METRICS[metric]} And Branch Area - ${yearLabel}`,traces,{height:390,margin:{l:82,r:25,t:58,b:100},
    xaxis:{title:{text:'Branch Area (sq ft)',standoff:14},rangemode:'tozero'},
    yaxis:{title:METRICS[metric],rangemode:'tozero'},
    legend:{orientation:'h',y:-.3,yanchor:'top',x:.5,xanchor:'center'}});
}
function rankingTabs(data) {
  const keys=Object.keys(METRICS);
  return `${tabsMarkup(keys.map(metric=>METRICS[metric]),'annual-metric')}${keys.map((metric,index)=>rankingMetricPanel(data,metric,index)).join('')}`;
}

function popup(branch) {
  const services=(branch.services||[]).length?`<ul>${branch.services.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'Not listed';
  const phone=String(branch.telephone||'').trim();
  const website=safeUrl(branch.website);
  return `<div class="map-popup"><strong>${esc(branch.name)}</strong><p><b>Type of library:</b> ${esc(branch.type_of_library||branch.service_tier||'Not listed')}</p><p><b>Present site year:</b> ${esc(branch.year_opened||'Not listed')}</p><p><b>Location:</b> ${esc(branch.address||'Not listed')} ${esc(branch.postal_code||'')}</p><p><b>Workstations:</b> ${fmt(branch.workstations)}</p><p><b>Area:</b> ${fmt(branch.square_footage)} sq ft</p><p><b>Services:</b> ${services}</p><p><b>Phone:</b> ${phone?`<a href="tel:${esc(phone.replace(/[^+\d]/g,''))}">${esc(phone)}</a>`:'Not listed'}</p><p><b>Website:</b> ${website?`<a target="_blank" rel="noopener noreferrer" href="${esc(website)}">Open website</a>`:'Not listed'}</p></div>`;
}
async function createMap(id,branches,metricData=null,years=[]) {
  const el=$(`#${id}`);if(!el||el.dataset.ready==='1')return;
  el.dataset.ready='1';
  try {
    await ensureLeaflet();
    if(!el.isConnected)return;
    const L=window.L;const torontoBounds=L.latLngBounds([[43.50,-79.85],[43.90,-79.05]]);const map=L.map(el,{scrollWheelZoom:false,keyboard:true,minZoom:9,maxZoom:18,maxBounds:torontoBounds,maxBoundsViscosity:0.85}).setView([43.70,-79.40],10);maps.set(id,map);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
    const located=branches.filter(b=>b.lat!==null&&b.lat!==undefined&&b.lat!==''&&b.lon!==null&&b.lon!==undefined&&b.lon!==''&&Number.isFinite(Number(b.lat))&&Number.isFinite(Number(b.lon))&&Number(b.lat)>=43.50&&Number(b.lat)<=43.90&&Number(b.lon)>=-79.85&&Number(b.lon)<=-79.05);
    const markers=[];
    located.forEach(branch=>{
      const icon=L.divIcon({className:'branch-pin-wrap',html:'<span class="branch-pin" aria-hidden="true"></span>',iconSize:[24,32],iconAnchor:[12,30],popupAnchor:[0,-28]});
      const marker=L.marker([Number(branch.lat),Number(branch.lon)],{icon,keyboard:true,title:branch.name,alt:branch.name}).addTo(map).bindPopup(popup(branch),{minWidth:280,maxWidth:460,maxHeight:Math.round(window.innerHeight*.62),autoPan:true,autoPanPadding:[36,36],keepInView:true});
      marker._libraryBranch=branch;marker.bindTooltip(branch.name,{direction:'top'});markers.push(marker);
    });
    if(markers.length>1)map.fitBounds(L.featureGroup(markers).getBounds().pad(.08),{maxZoom:12});
    else if(markers.length)map.setView(markers[0].getLatLng(),12);
    map.setMaxBounds(torontoBounds);
    const metricSelect=$('#map-metric-select'),yearSelect=$('#map-year-select');
    const recolor=()=>{
      if(!metricData||!metricSelect)return;
      const metric=metricSelect.value,year=yearSelect?.value||'all';
      const rows=metricData[metric]||[];
      const branchValues={};
      if(year==='all'){
        rows.forEach(row=>Object.entries(row.values||{}).forEach(([code,value])=>{
          if(value===null||value===undefined||!Number.isFinite(Number(value)))return;
          branchValues[code]=(branchValues[code]||0)+Number(value);
        }));
      }else{
        const row=rows.find(item=>String(item.year)===String(year));
        Object.assign(branchValues,row?.values||{});
      }
      const values=Object.values(branchValues).filter(v=>v!==null&&Number.isFinite(Number(v))).map(Number).sort((a,b)=>a-b);
      markers.forEach(marker=>{
        const value=branchValues[marker._libraryBranch.code];
        const rank=values.indexOf(Number(value));
        const index=values.length?Math.min(4,Math.floor(Math.max(0,rank)/Math.max(1,values.length/5))):0;
        const colors=['#dceaf0','#a9cad8','#6fa6bc','#367c98','#174c66'];
        const pin=marker.getElement()?.querySelector('.branch-pin');
        if(pin)pin.style.background=metric?(value!==null&&value!==undefined?colors[index]:'#9aa6ab'):'#286b83';
      });
    };
    metricSelect?.addEventListener('change',recolor);yearSelect?.addEventListener('change',recolor);recolor();
    requestAnimationFrame(()=>map.invalidateSize());
  } catch (_) {el.textContent='The branch map is unavailable.';}
}
function renderYearOptions(years,selected) {return years.map(y=>`<option value="${esc(y)}" ${String(y)===String(selected)?'selected':''}>${esc(y)}</option>`).join('');}

async function renderOverview() {
  const data=await request('/overview');
  const years=data.years||[];const selected='all';
  const metrics=Object.keys(METRICS);
  const stats=metrics.map(key=>`<article class="stat"><span>${esc(METRICS[key])}</span><strong>${fmt(data.totals?.[key])}</strong><small>${data.latest_years?.[key]?`Latest report: ${esc(data.latest_years[key])}`:'No values reported'}</small></article>`).join('')+`<article class="stat"><span>Physical branches</span><strong>${fmt(data.branch_count)}</strong><small>Library locations</small></article>`;
  const activity=metrics.map(key=>`<article class="activity-chart">${chart(METRICS[key],[lineTrace(data.trend?.[key]||[],METRICS[key],'#286b83')],{height:300})}</article>`).join('');
  const tiers=serviceTierCharts(data);
  const locations=`<div class="map-toolbar"><label for="map-metric-select">Metrics</label><select class="control" id="map-metric-select">${metrics.map(k=>`<option value="${k}">${esc(METRICS[k])}</option>`).join('')}</select><label for="map-year-select">Reporting Year</label><select class="control" id="map-year-select"><option value="all" selected>All Years</option>${renderYearOptions(years,'')}</select></div><div id="branch-map" class="map" role="region" aria-label="Map of Toronto Public Library physical branches"></div><div class="map-legend" aria-label="Metric value legend"><span>Lower metric value</span><span class="map-legend-ramp" aria-hidden="true"></span><span>Higher metric value</span></div>`;
  const panels=[
    `<section id="overview-panel-0" class="tab-panel" role="tabpanel" aria-labelledby="overview-tab-0"><div class="grid-2">${activity}</div></section>`,
    `<section id="overview-panel-1" class="tab-panel" role="tabpanel" aria-labelledby="overview-tab-1" hidden><div class="grid-2">${tiers}</div></section>`,
    `<section id="overview-panel-2" class="tab-panel" role="tabpanel" aria-labelledby="overview-tab-2" hidden>
      <section class="analysis-section branch-analysis-section">${rankingTabs(data)}</section>
    </section>`,
    `<section id="overview-panel-3" class="tab-panel" role="tabpanel" aria-labelledby="overview-tab-3" hidden><section class="location-section">${locations}</section></section>`,
    `<section id="overview-panel-4" class="tab-panel" role="tabpanel" aria-labelledby="overview-tab-4" hidden><div id="overview-graph-explorer"></div></section>`
  ].join('');
  host.innerHTML=`
    <section class="overview-question analysis-section"><h2>Ask a question</h2><form id="overview-question-form" class="question-form"><label class="visually-hidden" for="overview-question">Your question</label><div class="question-controls"><input id="overview-question" class="control" type="text" maxlength="500" required placeholder="Ask about any branch, its details, services, facilities or activity"><button class="button" type="submit">Ask</button></div></form><div id="overview-answer" aria-live="polite"></div></section>
    <section class="stats-grid" aria-label="Annual network summary">${stats}</section>
    ${tabsMarkup(['Annual Activity','Service Tiers','Branch Overview','Location','Library Network Explorer'],'overview')}${panels}`;
  host.addEventListener('change',event=>{
    const select=event.target.closest('.branch-overview-year');
    if(!select)return;
    const panel=select.closest('.ranking-metric-panel');
    const results=panel?.querySelector('.branch-overview-results');
    if(!panel||!results)return;
    if(window.Plotly)$$('.plotly-chart',results).forEach(el=>{try{Plotly.purge(el);}catch(_){}});
    results.innerHTML=branchOverviewResults(data,panel.dataset.metric,select.value);
    drawCharts(results);
  });
  bindQuestionForm('#overview-question-form','#overview-question','#overview-answer',null);
  let graphExplorerLoaded=false;
  attachTabs(host,(panel,index)=>{
    if(index===3 && panel.id==='overview-panel-3'){const mapEl=$('#branch-map');if(mapEl&&!mapEl.dataset.ready)createMap('branch-map',data.branches,data.annual_values,years);else requestAnimationFrame(()=>maps.get('branch-map')?.invalidateSize());}
    if(index===4 && panel.id==='overview-panel-4'&&!graphExplorerLoaded){
      graphExplorerLoaded=true;
      return renderGraphExplorer($('#overview-graph-explorer'));
    }
  });
  await drawCharts($('#overview-panel-0'));
  if(!$('#overview-panel-3').hidden)createMap('branch-map',data.branches,data.annual_values,years);
}

function branchPicker(branches,initial) {
  host.innerHTML=`<section class="branch-picker"><label for="branch-search">Find a branch</label><input id="branch-search" class="control" type="search" list="branch-options" placeholder="Type a branch name" autocomplete="off" value="${esc(branches.find(b=>b.code===initial)?.name||'')}"><datalist id="branch-options">${branches.map(b=>`<option value="${esc(b.name)}"></option>`).join('')}</datalist></section><div id="branch-profile" class="profile-host"></div>`;
  const input=$('#branch-search');
  const load=()=>{const term=input.value.trim().toLocaleLowerCase();const match=branches.find(b=>b.name.toLocaleLowerCase()===term);if(match)loadProfile(match.code);};
  input.addEventListener('change',load);input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();load();}});
  if(initial){const branch=branches.find(b=>b.code===initial);if(branch)loadProfile(initial);}
}
let branchProfileSequence=0;
async function loadProfile(code) {
  const pane=$('#branch-profile');if(!pane)return;
  pane.dataset.branchCode=code;
  const sequence=++branchProfileSequence;
  pane.setAttribute('aria-busy','true');
  pane.innerHTML=loadingMarkup('Loading branch information…','profile-loading-state');
  try {
    const [detail,forecast]=await Promise.all([request(`/branches/${encodeURIComponent(code)}`),request(`/branches/${encodeURIComponent(code)}/forecasts`)]);
    if(sequence!==branchProfileSequence||!pane.isConnected)return;
    const b=detail.branch;
    const hoursMarkup=b.hours?{html:`<div class="branch-hours">${String(b.hours).split(/\s*;\s*/).filter(Boolean).map(item=>`<span>${esc(item)}</span>`).join('')}</div>`}:'—';
    const parkingRaw=String(b.public_parking??'').trim();
    const parkingValue=parkingRaw&&/^\d+(?:\.\d+)?$/.test(parkingRaw)?`${fmt(Number(parkingRaw))} spaces`:parkingRaw;
    const services=(b.services||[]);
    const servicesMarkup=services.length?`<ul class="service-list">${services.map(service=>`<li>${esc(service)}</li>`).join('')}</ul>`:'Not listed';
    const info=[['Address',b.address],['Postal code',b.postal_code],['Type of library',b.type_of_library||b.service_tier],['Present site year',b.year_opened],['Service tier',b.service_tier],['Area',`${fmt(b.square_footage)} sq ft`],['Workstations',fmt(b.workstations)],['Telephone',b.telephone],['Hours',hoursMarkup],['Public Parking',parkingValue],['Neighbourhood',b.neighbourhood],['Ward',b.ward],['Reported Services',{html:servicesMarkup}],['Website',b.website?safeUrl(b.website):'']].map(([label,value])=>label==='Website'&&value? [label,{html:`<a href="${esc(value)}" target="_blank" rel="noopener noreferrer">${esc(value)}</a>`}]:[label,value]);
    const activityForecast=Object.keys(METRICS).map(key=>{
      const f=forecast[key];const label=METRICS[key];
      const history=(detail.history?.[key]||[]).map(point=>({year:String(point.year),value:Number(point.value)}));
      const next=f?.available?(f.forecasts||[]):[];
      const traces=[];
      if(history.length)traces.push({type:'scatter',mode:'lines+markers',name:'Reported',x:history.map(point=>point.year),y:history.map(point=>point.value),line:{color:'#0072B2'}});
      if(next.length){
        const from=history.length?history[history.length-1]:null;
        traces.push({type:'scatter',mode:'lines+markers',name:'Forecast',x:[...(from?[from.year]:[]),...next.map(point=>String(point.year))],y:[...(from?[from.value]:[]),...next.map(point=>point.value)],line:{dash:'dash',color:'#D55E00'}});
      }
      const graph=traces.length?chart(label,traces):empty('No annual activity history is available for this measure.');
      const forecastNote=f?.available&&next.length?`<p class="forecast-value">Forecast For ${esc(next[0].year)}: ${fmtD(next[0].value)}</p>`:`<p class="small-note">${esc(f?.reason||'A forecast is not available for this measure.')}</p>`;
      return `<article class="panel">${graph}${forecastNote}</article>`;
    }).join('');
    const events=(detail.events||[]).slice(0,15).map(eventCard).join('')||empty('No future programs are listed for this branch.');
    pane.innerHTML=`<div class="profile-loading-overlay" role="status"><span class="loading-spinner" aria-hidden="true"></span><span>Preparing branch insights…</span></div><div class="profile-render-content"><header class="profile-heading"><h2>${esc(b.name)}</h2></header>${tabsMarkup(['Branch Information','Activity & Forecast','Branch Explorer','Ask A Question','Programs'],'branch')}
      <section id="branch-panel-0" class="tab-panel" role="tabpanel" aria-labelledby="branch-tab-0"><section class="branch-information"><h3>Branch Details</h3>${table(['Detail','Information'],info)}</section></section>
      <section id="branch-panel-1" class="tab-panel" role="tabpanel" aria-labelledby="branch-tab-1" hidden><div class="grid-2">${activityForecast}</div></section>
      <section id="branch-panel-2" class="tab-panel" role="tabpanel" aria-labelledby="branch-tab-2" hidden><div id="branch-explorer-host"></div></section>
      <section id="branch-panel-3" class="tab-panel" role="tabpanel" aria-labelledby="branch-tab-3" hidden><form id="branch-question-form" class="question-form"><label for="branch-question">Ask About ${esc(b.name)}</label><div class="question-controls"><input id="branch-question" class="control" maxlength="500" required placeholder="Ask any question about this branch"><button class="button" type="submit">Ask</button></div></form><div id="branch-answer" aria-live="polite"></div></section><section id="branch-panel-4" class="tab-panel" role="tabpanel" aria-labelledby="branch-tab-4" hidden><div class="event-list">${events}</div></section></div>`;
    const content=$('.profile-render-content',pane);
    attachTabs(content,async (panel)=>{
      const pendingCharts=$$('.plotly-chart:not([data-drawn="1"])',panel).some(el=>!el.closest('[hidden]'));
      if(!pendingCharts){await drawCharts(panel);return;}
      pane.setAttribute('aria-busy','true');
      const overlay=document.createElement('div');
      overlay.className='profile-loading-overlay';
      overlay.setAttribute('role','status');
      overlay.innerHTML='<span class="loading-spinner" aria-hidden="true"></span><span>Preparing branch insights…</span>';
      pane.prepend(overlay);
      try{await drawCharts(panel);}
      finally{overlay.remove();pane.setAttribute('aria-busy','false');}
    });
    bindQuestionForm('#branch-question-form','#branch-question','#branch-answer',code);
    await drawCharts($('#branch-panel-0'));
    if(sequence!==branchProfileSequence||!pane.isConnected)return;
    $('.profile-loading-overlay',pane)?.remove();
    pane.setAttribute('aria-busy','false');
  } catch(_){
    if(sequence!==branchProfileSequence||!pane.isConnected)return;
    pane.innerHTML=note('Branch information could not be loaded.','error');
    pane.setAttribute('aria-busy','false');
  }
}
function bindQuestionForm(formSelector,inputSelector,resultSelector,branchCode=null) {
  const form=$(formSelector);if(!form||form.dataset.bound==='1')return;form.dataset.bound='1';
  form.addEventListener('submit',async event=>{
    event.preventDefault();const input=$(inputSelector);const target=$(resultSelector);const button=$('button[type="submit"]',form);
    const question=input?.value?.trim();if(!question)return;
    button.disabled=true;target.innerHTML=note('Searching library information…');
    try {
      const answer=await request('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,branch_code:branchCode})});
      const highlights=(answer.highlights||[]).map(item=>`<li class="answer-highlight"><strong>${esc(item.title)}</strong><span>${esc(item.category)}</span>${item.details?.length?`<dl>${item.details.map(detail=>`<div><dt>${esc(detail.label)}</dt><dd>${esc(graphDetailValue(detail.label,detail.value))}</dd></div>`).join('')}</dl>`:''}</li>`).join('');
      target.innerHTML=`<article class="answer-panel"><h3>Summary</h3><p>${esc(answer.answer||'No clear match was found.')}</p>${highlights?`<ul class="answer-highlights">${highlights}</ul>`:''}</article>`;
    } catch(error) {target.innerHTML=note(error.message||'The library graph is unavailable right now.','error');}
    finally {button.disabled=false;}
  });
}

async function renderBranches() {
  host.innerHTML=loadingMarkup('Loading branch directory…','branch-directory-loading');
  const branches=await request('/branches');
  if(!branches.length){host.innerHTML=empty('Branch information is not available.');return;}
  const selected=new URLSearchParams(location.search).get('branch')||'';
  branchPicker(branches,selected);
}

async function renderComparisons() {
  const branches=await request('/branches');if(branches.length<2){host.innerHTML=empty('At least two branches are required.');return;}
  const initial=(new URLSearchParams(location.search).get('branches')||'').split(',').slice(0,5);
  host.innerHTML=`<section class="compare-picker"><div class="form-field"><label for="compare-search">Find branches</label><input id="compare-search" class="control" type="search" placeholder="Search by branch name or code"></div><div id="compare-list" class="compare-list">${branches.map(b=>`<label class="compare-option" data-key="${esc(`${b.name} ${b.code} ${b.service_tier}`.toLowerCase())}"><input type="checkbox" value="${esc(b.code)}" ${initial.includes(b.code)?'checked':''}><span><strong>${esc(b.name)}</strong><small>${esc(b.code)} · ${esc(b.service_tier)}</small></span></label>`).join('')}</div><p id="compare-count" aria-live="polite"></p><button id="compare-clear" class="button secondary" type="button">Clear selection</button></section><div id="comparison-results" class="section" aria-live="polite">${empty('Choose two to five branches. Results will update as you select branches.')}</div>`;
  const list=$('#compare-list');const boxes=$$('input[type="checkbox"]',list);let requestSequence=0;
  const selected=()=>boxes.filter(x=>x.checked).map(x=>branches.find(b=>b.code===x.value)).filter(Boolean);
  async function loadComparison() {
    const chosen=selected();const codes=chosen.map(x=>x.code);const result=$('#comparison-results');const sequence=++requestSequence;
    if(codes.length<2){result.innerHTML=empty('Choose at least two branches to compare.');return;}
    result.innerHTML=note('Updating comparison…');
    const url=new URL(location.href);url.searchParams.set('branches',codes.join(','));history.replaceState({},'',url);
    try {
      const data=await request(`/comparisons/data?branches=${encodeURIComponent(codes.join(','))}`);if(sequence!==requestSequence)return;
      const metrics=Object.keys(METRICS);
      const chartPanels=metrics.map((metric,i)=>{
        const rows=data.metrics[metric]||[];
        const palette=['#0072B2','#D55E00','#009E73','#CC79A7','#6C757D'];
        const traces=data.branches.map((branch,index)=>({type:'scatter',mode:'lines+markers',name:branch.name,x:rows.map(row=>String(row.year)),y:rows.map(row=>row.values?.[branch.code]??null),connectgaps:false,line:{width:2.6,color:palette[index]},marker:{size:6},hovertemplate:'%{x}<br>%{y:,.0f}<extra></extra>'}));
        const chartView=rows.length?chart(METRICS[metric],traces,{height:380,margin:{l:70,r:25,t:60,b:90},legend:{orientation:'h',y:-.25}}):empty(`No annual ${METRICS[metric].toLowerCase()} records are available for these branches.`);
        return `<section id="comparison-year-panel-${i}" data-metric="${metric}" class="tab-panel" role="tabpanel" aria-labelledby="comparison-year-tab-${i}" ${i?'hidden':''}>${chartView}${rows.length?details(METRICS[metric],['Year',...data.branches.map(x=>x.name)],rows.map(row=>[row.year,...data.branches.map(branch=>fmt(row.values?.[branch.code]))])):''}</section>`;
      }).join('');
      const infoRows=data.branches.map(b=>[b.name,b.code,b.type_of_library||b.service_tier,b.year_opened||'—',b.address||'—',b.postal_code||'—',fmt(b.square_footage),fmt(b.workstations),b.telephone||'—',b.website||'—']);
      const services=Array.from(new Set(data.branches.flatMap(b=>b.services||[]))).sort();
      const serviceRows=services.map(service=>[service,...data.branches.map(b=>(b.services||[]).includes(service)?'Reported':'Not listed')]);
      result.innerHTML=`${tabsMarkup(['Annual Metrics','Branch Information','Branch Explorer'],'comparison-main')}<section id="comparison-main-panel-0" class="tab-panel" role="tabpanel" aria-labelledby="comparison-main-tab-0">${tabsMarkup(metrics.map(metric=>METRICS[metric]),'comparison-year')}${chartPanels}</section><section id="comparison-main-panel-1" class="tab-panel" role="tabpanel" aria-labelledby="comparison-main-tab-1" hidden><section class="branch-information"><h3>Branch Details</h3>${table(['Branch','Code','Library Type','Year Opened','Address','Postal Code','Area (sq ft)','Workstations','Telephone','Website'],infoRows)}<h3 class="reported-services-heading">Reported Services</h3>${services.length?table(['Service',...data.branches.map(b=>b.name)],serviceRows):empty('No reported services are listed for these branches.')}<h3 class="reported-services-heading">Selected Branch Locations</h3><div id="comparison-map" class="map" role="region" aria-label="Map of selected Toronto Public Library branches"></div></section></section><section id="comparison-main-panel-2" class="tab-panel" role="tabpanel" aria-labelledby="comparison-main-tab-2" hidden><div id="comparison-explorer-host"></div></section>`;
      attachTabs(result,(panel,index)=>{if(index===1){if(!$('#comparison-map').dataset.ready)createMap('comparison-map',data.branches);else requestAnimationFrame(()=>maps.get('comparison-map')?.invalidateSize());}});
      const yearTabs=$('.tabs[aria-label="comparison-year"]',result);if(yearTabs){yearTabs.addEventListener('click',e=>{const tab=e.target.closest('[data-tab-index]');if(tab){const i=Number(tab.dataset.tabIndex);const active=$(`#comparison-year-panel-${i}`,result);drawCharts(active);}});}
      await drawCharts($('#comparison-main-panel-0'));
    } catch(_){if(sequence===requestSequence)result.innerHTML=note('The comparison could not be loaded.','error');}
  }
  const update=()=>{
    const chosen=selected();const n=chosen.length;$('#compare-count').textContent=`${n} of 5 selected`;
    boxes.forEach(box=>{box.disabled=!box.checked&&n>=5;});
    clearTimeout(update.timer);update.timer=setTimeout(loadComparison,180);
  };
  $('#compare-search').addEventListener('input',e=>{const q=e.target.value.trim().toLowerCase();$$('.compare-option',list).forEach(option=>{option.hidden=!option.dataset.key.includes(q);});});
  list.addEventListener('change',update);
  $('#compare-clear').addEventListener('click',()=>{boxes.forEach(box=>{box.checked=false;});const url=new URL(location.href);url.searchParams.delete('branches');history.replaceState({},'',url);update();});
  update();
}

function eventCard(event) {
  const start=String(event.start||event.start_iso||'');
  const end=String(event.end||event.end_iso||'');
  const normalized=value=>value?value.slice(0,16).replace('T',' '):'Time not supplied';
  const eventUrl=safeUrl(event.event_url),regUrl=safeUrl(event.registration_url);
  const status=event.registration_status||'Availability not supplied';
  return `<article class="event-card"><div class="event-datetime"><strong>${esc(normalized(start))}</strong>${end?`<span>to ${esc(normalized(end))}</span>`:''}</div><div><h3>${esc(event.title)}</h3><p class="event-meta">${esc(event.location||'Library location')} · ${esc(event.audiences||'All audiences')} · ${esc(event.languages||'Language not listed')}</p>${event.description?`<p>${esc(event.description)}</p>`:''}<p class="event-meta">${esc(event.types||'Program type not listed')} · ${esc(status)}</p>${eventUrl?`<a href="${esc(eventUrl)}" target="_blank" rel="noopener noreferrer">Program details</a>`:''} ${regUrl?`<a href="${esc(regUrl)}" target="_blank" rel="noopener noreferrer">Register</a>`:''}</div></article>`;
}
function options(values,selected,label) {return `<option value="">${esc(label)}</option>${values.map(v=>{const value=typeof v==='object'?v.value:v;const text=typeof v==='object'?v.label:v;return `<option value="${esc(value)}" ${String(value)===String(selected||'')?'selected':''}>${esc(text)}</option>`;}).join('')}`;}
function graphDetailValue(label,value) { const text=String(value??''); if(/date|time|timestamp|start|end/i.test(label)) { const match=text.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2})/); if(match)return `${match[1]} ${match[2]}`; } return text || '—'; }
function graphValue(value) {
  if(value===null||value===undefined||value==='')return '—';
  if(typeof value==='object')return JSON.stringify(value);
  return String(value);
}
function humanizeGraphKey(value) { return String(value||'').replace(/([a-z0-9])([A-Z])/g,'$1 $2').replace(/[_-]+/g,' ').replace(/\s+/g,' ').trim().replace(/\b\w/g,char=>char.toUpperCase()); }
function graphPropertiesMarkup(properties) {
  const entries=Object.entries(properties||{});
  if(!entries.length)return '<p class="small-note">No stored properties were returned.</p>';
  return `<dl class="graph-inspector-properties">${entries.map(([key,value])=>`<div><dt>${esc(humanizeGraphKey(key))}</dt><dd>${esc(graphValue(value))}</dd></div>`).join('')}</dl>`;
}
function graphRecordMarkup(record,index) {
  const title=record.summary||record.properties?.BranchName||record.properties?.BranchCode||`Node ${index+1}`;
  const subtitle=(record.labels||[]).map(humanizeGraphKey).join(' · ');
  return `<details class="graph-node-details"><summary><strong>${esc(title)}</strong><small>${esc(subtitle)}</small></summary><div class="graph-node-inspection">${graphPropertiesMarkup(record.properties)}</div></details>`;
}
async function renderGraphExplorer(target=host) {
  const graphHost=target||host;
  const $g=(selector)=>$(selector,graphHost);
  graphHost.innerHTML=loadingMarkup('Reading graph structure and physical branch relationships…','graph-inspector-loading');
  let graph;
  try { graph=await request('/relate/explorer'); }
  catch(error){graphHost.innerHTML=note(error.message||'The Relate graph is unavailable.','error');return;}
  if(!graph.available){graphHost.innerHTML=empty('The Relate graph is not available.');return;}

  const insights=graph.insights||{};
  const runtime=graph.runtime||{};
  const runtimeLine=runtime.connected
    ? `<p class="relate-runtime-status" role="status"><span class="relate-runtime-indicator" aria-hidden="true"></span><strong>Relate connected</strong><span>Persistent store: ${esc(runtime.store||'tpl_library_graph.rl')}</span></p>`
    : '';
  const nodeTypes=(graph.node_counts||[]).slice().sort((a,b)=>String(a.display_label||a.label).localeCompare(String(b.display_label||b.label)));
  const relationshipTypes=(graph.relationship_counts||[]).slice().sort((a,b)=>String(a.label||a.type).localeCompare(String(b.label||b.type)));
  const branchLabel='BranchGeneralInformation';
  const defaultLabel=(nodeTypes.find(item=>item.label===branchLabel)||nodeTypes[0]||{}).label||'';
  const labelOptions=nodeTypes.map(item=>`<option value="${esc(item.label)}" ${item.label===defaultLabel?'selected':''}>${esc(item.display_label||item.label)} (${fmt(item.count)})</option>`).join('');
  const totalNodes=(graph.node_counts||[]).reduce((sum,item)=>sum+Number(item.count||0),0);
  const totalEdges=(graph.relationship_counts||[]).reduce((sum,item)=>sum+Number(item.count||0),0);
  const physicalGraph=Number(insights.physical_branch_nodes||0);
  const topBranches=(insights.top_connected_branches||[]).slice(0,10).map((item,index)=>[String(index+1), item.name, fmt(item.connections)]);
  const areaTable=(items,heading)=>items?.length
    ? `<div class="table-scroll"><table class="data-table"><thead><tr><th scope="col">Rank</th><th scope="col">${esc(heading)}</th><th scope="col">Physical Branches</th></tr></thead><tbody>${items.slice(0,10).map((item,index)=>`<tr><td>${index+1}</td><th scope="row">${esc(item.name)}</th><td>${fmt(item.branches)}</td></tr>`).join('')}</tbody></table></div>`
    : empty(`No connected ${heading.toLowerCase()} were found.`);
  const structureNodeRows=nodeTypes.map(item=>`<tr><th scope="row">${esc(item.display_label||item.label)}</th><td>${fmt(item.count)}</td><td><details class="graph-schema-properties"><summary>${fmt((item.properties||[]).length)} fields</summary><p>${(item.properties||[]).map(humanizeGraphKey).map(esc).join(', ')||'No properties reported'}</p></details></td></tr>`).join('');
  const structureRelationshipRows=relationshipTypes.map(item=>`<tr><th scope="row">${esc(item.label||item.type)}</th><td>${fmt(item.count)}</td></tr>`).join('');

  graphHost.innerHTML=`<div class="graph-explorer-shell">
    ${runtimeLine}
    ${tabsMarkup(['Graph Insights','Graph Structure','Browse Nodes'],'graph-explorer-sections')}
    <section id="graph-explorer-sections-panel-0" class="tab-panel graph-inspector-panel" role="tabpanel" aria-labelledby="graph-explorer-sections-tab-0">
      <div class="graph-insight-grid">
        <section class="graph-insight-section"><div class="graph-section-heading"><h3>Top 10 Most Connected Branches</h3><p>Ranked by direct graph relationships.</p></div>${table(['Rank','Branch','Connections'],topBranches)}</section>
        <section class="graph-insight-section"><div class="graph-section-heading"><h3>Top 10 Neighbourhoods</h3><p>Ranked by the number of connected physical branches.</p></div>${areaTable(insights.area_hubs?.neighbourhoods,'Neighbourhood')}</section>
        <section class="graph-insight-section"><div class="graph-section-heading"><h3>Top 10 Wards</h3><p>Ranked by the number of connected physical branches.</p></div>${areaTable(insights.area_hubs?.wards,'Ward')}</section>
        <section class="graph-insight-section"><div class="graph-section-heading"><h3>Services With The Widest Branch Reach</h3><p>Services connected to the greatest number of physical branches.</p></div>${areaTable(insights.service_reach,'Service')}</section>
      </div>
    </section>
    <section id="graph-explorer-sections-panel-1" class="tab-panel graph-inspector-panel" role="tabpanel" aria-labelledby="graph-explorer-sections-tab-1" hidden>
      <div class="graph-structure-header"><div><h3>Node Labels</h3><p>Explore the node types and relationship types that make up the LibraryTO network.</p></div><span>${fmt(totalNodes)} nodes</span></div>
      <div class="graph-structure-grid"><section class="graph-insight-section"><h4>Node Types</h4><div class="table-scroll"><table class="data-table"><thead><tr><th scope="col">Node Type</th><th scope="col">Records</th><th scope="col">Properties</th></tr></thead><tbody>${structureNodeRows}</tbody></table></div></section>
      <section class="graph-insight-section"><h4>Relationship Types</h4><div class="table-scroll"><table class="data-table"><thead><tr><th scope="col">Relationship</th><th scope="col">Connections</th></tr></thead><tbody>${structureRelationshipRows}</tbody></table></div></section></div>
    </section>
    <section id="graph-explorer-sections-panel-2" class="tab-panel graph-inspector-panel" role="tabpanel" aria-labelledby="graph-explorer-sections-tab-2" hidden>
      <div class="graph-section-heading"><h3>Browse Nodes And Properties</h3><p>Use this record inspector to verify the source properties stored on individual graph nodes.</p></div>
      <form id="graph-node-search" class="graph-node-toolbar"><div class="form-field"><label for="graph-node-label">Node Type</label><select id="graph-node-label" class="control">${labelOptions}</select></div><div class="form-field graph-node-search-field"><label for="graph-node-term">Search Node Properties</label><input id="graph-node-term" class="control" type="search" maxlength="120" placeholder="Search names, years, codes or values"></div><button class="button" type="submit">Search</button></form>
      <p id="graph-node-count" class="small-note" aria-live="polite"></p><div id="graph-node-results" class="graph-node-list" aria-live="polite"></div><div class="graph-node-actions"><button id="graph-node-more" class="button secondary" type="button" hidden>Show More Nodes</button></div>
    </section>
  </div>`;

  const labelSelect=$g('#graph-node-label'),searchInput=$g('#graph-node-term'),nodeResults=$g('#graph-node-results'),nodeCount=$g('#graph-node-count'),moreButton=$g('#graph-node-more');
  let currentOffset=0,currentLabel=defaultLabel,currentTerm='';
  async function loadNodePage(reset=true){
    if(!labelSelect)return;
    if(reset){currentOffset=0;nodeResults.innerHTML=loadingMarkup('Loading graph nodes…');}
    else{moreButton.disabled=true;moreButton.textContent='Loading More Nodes…';}
    currentLabel=labelSelect.value;currentTerm=searchInput.value.trim();
    const params=new URLSearchParams({label:currentLabel,search:currentTerm,limit:'50',offset:String(currentOffset)});
    try{
      const result=await request(`/relate/inspect?${params}`);
      const records=result.records||[];
      nodeCount.textContent=`${fmt(result.total)} matching nodes · Showing ${fmt(Math.min(currentOffset+records.length,Number(result.total||0)))} of ${fmt(result.total)}`;
      if(reset)nodeResults.innerHTML='';
      nodeResults.insertAdjacentHTML('beforeend',records.map((record,index)=>graphRecordMarkup(record,currentOffset+index)).join(''));
      if(!records.length&&reset)nodeResults.innerHTML=empty('No nodes match this search.');
      currentOffset+=records.length;moreButton.hidden=!result.has_more;
    }catch(error){nodeCount.textContent='';if(reset)nodeResults.innerHTML=note(error.message||'Graph nodes could not be loaded.','error');else nodeResults.insertAdjacentHTML('beforeend',note(error.message||'More graph nodes could not be loaded.','error'));}
    finally{moreButton.disabled=false;moreButton.textContent='Show More Nodes';}
  }
  $('#graph-node-search',graphHost).addEventListener('submit',event=>{event.preventDefault();loadNodePage(true);});
  labelSelect.addEventListener('change',()=>loadNodePage(true));
  moreButton.addEventListener('click',()=>loadNodePage(false));
  attachTabs(graphHost,(_panel,index)=>{
    if(index===2&&!$g('#graph-node-results').dataset.loaded){$g('#graph-node-results').dataset.loaded='1';return loadNodePage(true);}
  });
}

async function renderEvents() {
  const filters=await request('/events/options');const params=new URLSearchParams(location.search);
  host.innerHTML=`<section class="panel"><form id="event-form" class="event-form">
    <div class="form-field"><label for="interest">Interest</label><input id="interest" name="interest" class="control" placeholder="e.g. coding, reading, music" value="${esc(params.get('interest')||'')}"></div>
    <div class="form-field"><label for="audience">Audience</label><select id="audience" name="audience" class="control">${options(filters.audiences,params.get('audience'),'Any audience')}</select></div>
    <div class="form-field"><label for="language">Language</label><select id="language" name="language" class="control">${options(filters.languages,params.get('language'),'Any language')}</select></div>
    <div class="form-field"><label for="event_type">Program type</label><select id="event_type" name="event_type" class="control">${options(filters.event_types,params.get('event_type'),'Any type')}</select></div>
    <div class="form-field"><label for="branch">Branch</label><select id="branch" name="branch" class="control">${options(filters.branches.map(b=>({value:b.code,label:b.name})),params.get('branch'),'All branches')}</select></div>
    <div class="form-field"><label for="date">Date</label><input id="date" name="date" type="date" class="control" value="${esc(params.get('date')||'')}"></div>
    <div class="form-field"><label for="start_time">Start time</label><input id="start_time" name="start_time" type="time" class="control" value="${esc(params.get('start_time')||'')}"></div>
    <div class="form-field"><label for="end_time">End time</label><input id="end_time" name="end_time" type="time" class="control" value="${esc(params.get('end_time')||'')}"></div>
    <div class="form-field"><label for="registration">Registration</label><select id="registration" name="registration" class="control"><option value="">Any status</option><option value="available" ${params.get('registration')==='available'?'selected':''}>Open registration</option></select></div>
    <div class="actions"><button class="button" type="submit">Find programs</button><button class="button secondary" id="event-reset" type="button">Reset</button></div></form></section>
    <section class="section"><h2>Programs</h2><p id="event-count" aria-live="polite"></p><div id="event-results" class="event-results" aria-live="polite"></div></section>`;
  const form=$('#event-form');
  async function search(updateUrl=true) {
    const data=new FormData(form);const branchCode=data.get('branch')||'';const query=new URLSearchParams();
    for(const key of ['interest','audience','language','event_type','date','start_time','end_time','registration'])if(data.get(key))query.set(key,data.get(key));
    if(branchCode)query.set('branch',branchCode);
    if(updateUrl){const url=new URL(location.href);url.search=query.toString();history.replaceState({},'',url);}
    try {const result=await request(`/events/recommendations?${query}`);$('#event-count').textContent=`Showing ${fmt(result.total)} upcoming programs`; $('#event-results').innerHTML=result.events.length?result.events.map(eventCard).join(''):empty('No future programs match those filters.');}
    catch(_){$('#event-results').innerHTML=note('Programs could not be loaded.','error');$('#event-count').textContent='';}
  }
  form.addEventListener('submit',e=>{e.preventDefault();search();});
  $('#event-reset').addEventListener('click',()=>{form.reset();search();});
  await search(false);
}

$('#page-description').textContent='';
const renderers={overview:renderOverview,branches:renderBranches,comparisons:renderComparisons,events:renderEvents};
(async()=>{try{await (renderers[page]||renderOverview)();}catch(_){host.innerHTML=note('This section could not be loaded.','error');}finally{host.setAttribute('aria-busy','false');}})();

// Global search is type-ahead and keyboard operable; server results use the same cached GET layer.
const searchInput=$('#global-search'),searchHost=$('#search-results');let searchTimer=0;
searchInput.addEventListener('input',()=>{
  clearTimeout(searchTimer);const query=searchInput.value.trim();
  if(query.length<2){searchHost.hidden=true;searchInput.setAttribute('aria-expanded','false');return;}
  searchTimer=setTimeout(async()=>{try{const data=await request(`/search?q=${encodeURIComponent(query)}`);const entries=[...(data.branches||[]).map(b=>({title:b.name,meta:`Branch · ${b.code}`,href:`/branch-insights?branch=${encodeURIComponent(b.code)}`})),...(data.events||[]).map(e=>({title:e.title,meta:`Program · ${e.location||''}`,href:`/programs-events?interest=${encodeURIComponent(query)}`}))];searchHost.innerHTML=entries.length?entries.map((x,i)=>`<a class="search-result" role="option" id="search-result-${i}" href="${x.href}"><strong>${esc(x.title)}</strong><small>${esc(x.meta)}</small></a>`).join(''):empty('No matching records.');searchHost.hidden=false;searchInput.setAttribute('aria-expanded','true');}catch(_){searchHost.hidden=true;}},180);
});
document.addEventListener('click',e=>{if(!e.target.closest('.global-search')){searchHost.hidden=true;searchInput.setAttribute('aria-expanded','false');}});

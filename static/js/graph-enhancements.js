/* Selection-driven Branch Explorer insights powered by the Relate graph. */
(() => {
  'use strict';

  const page = document.querySelector('#main')?.dataset.page || '';
  const root = document.querySelector('#page-content');
  if (!root) return;

  let branchListPromise;
  const number = value => value == null || !Number.isFinite(Number(value)) ? '0' : new Intl.NumberFormat('en-CA', {maximumFractionDigits: 0}).format(Number(value));
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const humanizeIdentifier = value => String(value || '').replace(/([a-z0-9])([A-Z])/g,'$1 $2').replace(/[_-]+/g,' ').replace(/\s+/g,' ').trim().replace(/\b\w/g,letter=>letter.toUpperCase());
  const labels = {
    IN_NEIGHBOURHOOD:'Neighbourhood',
    IN_WARD:'Ward',
    OFFERS_SERVICE:'Reported Service',
    HAS_FACILITY:'Facility'
  };
  const visibleTypes = new Set(Object.keys(labels));

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
  function visibleConnections(branch, type = null) {
    return (branch?.connections || []).filter(edge => visibleTypes.has(edge.relationship_type) && (!type || edge.relationship_type === type));
  }
  function edgeName(edge) {
    const props = edge?.properties || {};
    const normal = Object.fromEntries(Object.entries(props).map(([key,value])=>[key.toLowerCase().replace(/[^a-z0-9]/g,''),value]));
    if (edge.relationship_type === 'OFFERS_SERVICE') return String(normal.servicename || edge.target_title || 'Service');
    if (edge.relationship_type === 'HAS_FACILITY') return String(normal.facilityname || edge.target_title || 'Facility');
    return String(edge.target_title || normal.name || '');
  }
  function edgeIdentity(edge) {
    const props=edge?.properties||{};
    const normal=Object.fromEntries(Object.entries(props).map(([key,value])=>[key.toLowerCase().replace(/[^a-z0-9]/g,''),value]));
    const candidates={
      IN_NEIGHBOURHOOD:['areakey','neighbourhoodno','name'],
      IN_WARD:['areakey','wardno','name'],
      OFFERS_SERVICE:['servicekey','servicename','name'],
      HAS_FACILITY:['facilitykey','facilityname','name']
    }[edge.relationship_type]||[];
    const value=candidates.map(key=>normal[key]).find(item=>item!==undefined&&item!==null&&item!=='');
    return `${edge.relationship_type}:${String(value??edgeName(edge)).trim().toLowerCase()}`;
  }
  function edgeNames(branch,type) {
    return [...new Set(visibleConnections(branch,type).map(edgeName).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  }
  function peerContextLabel(context) {
    return `${context.context_type==='ward'?'Ward':'Neighbourhood'}: ${context.context_name}`;
  }
  function branchExplorerInsights(branch) {
    const peers=(branch.peer_branches||[]).filter(peer=>peer.branch_code!==branch.branch_code);
    const ownServices=edgeNames(branch,'OFFERS_SERVICE');
    const ownServiceSet=new Set(ownServices.map(name=>name.toLowerCase()));
    const peerRows=peers.map(peer=>{
      const peerServices=new Set((peer.services||[]).map(name=>String(name).toLowerCase()));
      const shared=ownServices.filter(name=>peerServices.has(name.toLowerCase()));
      const contexts=(peer.contexts||[]).map(peerContextLabel);
      return {...peer,sharedServices:shared,contextLabel:contexts.join('; ')||'Shared graph context'};
    }).sort((a,b)=>b.sharedServices.length-a.sharedServices.length||a.branch_name.localeCompare(b.branch_name));

    const peerMarkup=peerRows.length
      ? `<div class="table-scroll"><table class="data-table" aria-label="Other branches sharing this branch's ward or neighbourhood"><caption class="visually-hidden">Other branches sharing this branch's ward or neighbourhood</caption><thead><tr><th scope="col">Branch</th><th scope="col">Shared Context</th><th scope="col">Reported Services In Common</th></tr></thead><tbody>${peerRows.map(peer=>`<tr><th scope="row">${escapeHtml(peer.branch_name)}</th><td>${escapeHtml(peer.contextLabel)}</td><td>${peer.sharedServices.length?escapeHtml(peer.sharedServices.join(', ')):'No shared services reported'}</td></tr>`).join('')}</tbody></table></div>`
      : '<p class="small-note">No other branches are connected through this branch’s neighbourhood or ward in the current graph.</p>';

    const coverage=new Map();
    ownServices.forEach(name=>coverage.set(name.toLowerCase(),{name,selected:true,peers:[]}));
    peerRows.forEach(peer=>(peer.services||[]).forEach(name=>{
      const key=String(name).toLowerCase();
      if(!coverage.has(key))coverage.set(key,{name,selected:false,peers:[]});
      coverage.get(key).peers.push(peer.branch_name);
    }));
    const coverageRows=[...coverage.values()].sort((a,b)=>b.peers.length-a.peers.length||a.name.localeCompare(b.name));
    const coverageMarkup=coverageRows.length&&peerRows.length
      ? `<div class="table-scroll"><table class="data-table" aria-label="Reported service coverage across branches in the same area"><caption class="visually-hidden">Reported service coverage across branches in the same area</caption><thead><tr><th scope="col">Service</th><th scope="col">Selected Branch</th><th scope="col">Other Local Branches</th></tr></thead><tbody>${coverageRows.map(item=>`<tr><th scope="row">${escapeHtml(item.name)}</th><td>${item.selected?'Reported':'Not Reported'}</td><td>${item.peers.length?`${number(item.peers.length)}: ${escapeHtml(item.peers.join(', '))}`:'None in selected peer group'}</td></tr>`).join('')}</tbody></table></div>`
      : '<p class="small-note">Service coverage comparisons appear when other branches share the selected branch’s ward or neighbourhood.</p>';

    const sharedServiceCount=coverageRows.filter(item=>item.selected&&item.peers.length>0).length;
    const onlyElsewhere=coverageRows.filter(item=>!item.selected&&item.peers.length>0);
    const insights=[];
    if(peerRows.length)insights.push(`${peerRows.length} other ${peerRows.length===1?'branch shares':'branches share'} a ward or neighbourhood with ${branch.branch_name}.`);
    if(sharedServiceCount)insights.push(`${sharedServiceCount} reported ${sharedServiceCount===1?'service is':'services are'} also offered by at least one local peer.`);
    if(onlyElsewhere.length)insights.push(`${onlyElsewhere.length} ${onlyElsewhere.length===1?'service is':'services are'} reported by local peers but not listed for this branch.`);
    const insightMarkup=insights.length?`<ul class="branch-explorer-takeaways">${insights.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>`:'<p class="small-note">The available graph does not contain enough connected peer data to calculate local service comparisons.</p>';

    return `${insightMarkup}<section class="branch-explorer-block"><h3>Branches In The Same Area</h3>${peerMarkup}</section><section class="branch-explorer-block"><h3>Local Service Coverage</h3>${coverageMarkup}</section>`;
  }
  function pairwiseInsights(branches) {
    const pairs=[];
    for(let i=0;i<branches.length;i++)for(let j=i+1;j<branches.length;j++){
      const left=branches[i],right=branches[j];
      const shared=(type)=>{
        const rightSet=new Set(visibleConnections(right,type).map(edgeIdentity));
        return visibleConnections(left,type).filter(edge=>rightSet.has(edgeIdentity(edge))).map(edgeName).filter(Boolean);
      };
      pairs.push({
        left:left.branch_name,
        right:right.branch_name,
        neighbourhoods:shared('IN_NEIGHBOURHOOD'),
        wards:shared('IN_WARD'),
        services:shared('OFFERS_SERVICE')
      });
    }
    const pairMarkup=pairs.length
      ? `<div class="table-scroll"><table class="data-table" aria-label="Pairwise relationships between selected branches"><caption class="visually-hidden">Pairwise relationships between selected branches</caption><thead><tr><th scope="col">Branch Pair</th><th scope="col">Shared Neighbourhood</th><th scope="col">Shared Ward</th><th scope="col">Shared Services</th></tr></thead><tbody>${pairs.map(pair=>`<tr><th scope="row">${escapeHtml(pair.left)} / ${escapeHtml(pair.right)}</th><td>${pair.neighbourhoods.length?escapeHtml(pair.neighbourhoods.join(', ')):'None'}</td><td>${pair.wards.length?escapeHtml(pair.wards.join(', ')):'None'}</td><td>${pair.services.length?`${number(pair.services.length)}: ${escapeHtml(pair.services.join(', '))}`:'None'}</td></tr>`).join('')}</tbody></table></div>`
      : '<p class="small-note">Select at least two branches to compare their relationships.</p>';

    const allServices=[...new Set(branches.flatMap(branch=>edgeNames(branch,'OFFERS_SERVICE')))].sort((a,b)=>a.localeCompare(b));
    const matrix=allServices.map(service=>{
      const offered=branches.filter(branch=>edgeNames(branch,'OFFERS_SERVICE').some(name=>name.toLowerCase()===service.toLowerCase()));
      return {service,offered};
    });
    const matrixMarkup=matrix.length
      ? `<div class="table-scroll"><table class="data-table" aria-label="Service distribution across selected branches"><caption class="visually-hidden">Service distribution across selected branches</caption><thead><tr><th scope="col">Service</th>${branches.map(branch=>`<th scope="col">${escapeHtml(branch.branch_name)}</th>`).join('')}<th scope="col">Branch Coverage</th></tr></thead><tbody>${matrix.map(item=>`<tr><th scope="row">${escapeHtml(item.service)}</th>${branches.map(branch=>`<td>${item.offered.some(found=>found.branch_code===branch.branch_code)?'Reported':'—'}</td>`).join('')}<td>${number(item.offered.length)} / ${number(branches.length)}</td></tr>`).join('')}</tbody></table></div>`
      : '<p class="small-note">No reported service relationships were found for the selected branches.</p>';

    const commonPairs=pairs.filter(pair=>pair.neighbourhoods.length||pair.wards.length||pair.services.length).length;
    const branchOnlyServices=matrix.filter(item=>item.offered.length===1);
    const commonServices=matrix.filter(item=>item.offered.length===branches.length);
    const takeaways=[];
    takeaways.push(`${commonPairs} of ${pairs.length} branch pairs have at least one shared neighbourhood, ward or service connection.`);
    if(commonServices.length)takeaways.push(`${commonServices.length} reported ${commonServices.length===1?'service is':'services are'} offered by every selected branch.`);
    if(branchOnlyServices.length)takeaways.push(`${branchOnlyServices.length} reported ${branchOnlyServices.length===1?'service appears':'services appear'} at only one selected branch.`);
    return `<ul class="branch-explorer-takeaways">${takeaways.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul><section class="branch-explorer-block"><h3>How Selected Branches Connect</h3>${pairMarkup}</section><section class="branch-explorer-block"><h3>Reported Service Distribution</h3>${matrixMarkup}</section>`;
  }
  async function installExplorer(target, mode, selectedCodes) {
    if (!target) return;
    const codes=(selectedCodes||[]).filter(Boolean);
    if(mode==='comparison'&&codes.length<2){
      target.querySelector(':scope > #branch-explorer')?.remove();
      target.innerHTML='<p class="small-note">Select at least two branches to explore their shared neighbourhoods, wards and reported services.</p>';
      return;
    }
    if(!codes.length)return;
    const currentKey=codes.join(',');
    const existing=target.querySelector(':scope > #branch-explorer');
    if(existing&&existing.dataset.mode===mode&&existing.dataset.selection===currentKey)return;
    existing?.remove();
    const section=createSection('branch-explorer','Branch Explorer',mode==='comparison'
      ? 'Compare shared neighbourhoods, wards and reported services across the selected branches.'
      : 'See which branches share the selected branch’s local area and how reported services compare.');
    section.dataset.mode=mode;
    section.dataset.selection=currentKey;
    section.innerHTML+='<div class="branch-explorer-summary" aria-live="polite" aria-atomic="true"><p class="small-note" role="status">Loading connected branch insights…</p></div>';
    target.append(section);
    const summary=section.querySelector('.branch-explorer-summary');
    try{
      const graph=await getJSON(`/relate/explorer?branch_codes=${encodeURIComponent(codes.join(','))}`);
      const selected=(graph.selected||[]).filter(branch=>codes.includes(branch.branch_code));
      if(mode==='comparison'){
        if(selected.length<2){summary.innerHTML='<p class="small-note">The selected branches could not all be found in the graph.</p>';return;}
        summary.innerHTML=pairwiseInsights(selected);
      }else{
        const branch=selected[0];
        if(!branch){summary.innerHTML='<p class="notice error" role="alert">The selected branch could not be found in the graph.</p>';return;}
        summary.innerHTML=branchExplorerInsights(branch);
      }
    }catch(error){summary.innerHTML=`<p class="notice error" role="alert">${escapeHtml(error.message||'The Branch Explorer could not be loaded.')}</p>`;}
  }

  let enhancementTimer;
  let enhancing=false;
  let enhanceAgain=false;
  function enhance(){
    clearTimeout(enhancementTimer);
    enhancementTimer=setTimeout(async()=>{
      if(enhancing){enhanceAgain=true;return;}
      enhancing=true;
      try{
        if(page==='branches'){
          const profile=document.querySelector('#branch-profile');
          const content=profile?.querySelector('.profile-render-content');
          const code=profile?.dataset.branchCode||'';
          const explorerHost=content?.querySelector('#branch-explorer-host');
          if(content&&code&&explorerHost&&!profile.querySelector('.profile-loading-overlay'))await installExplorer(explorerHost,'branch',[code]);
        }else if(page==='comparisons'){
          const result=document.querySelector('#comparison-results');
          const explorerHost=result?.querySelector('#comparison-explorer-host');
          if(explorerHost){
            const codes=[...document.querySelectorAll('#compare-list input[type="checkbox"]:checked')].map(item=>item.value);
            await installExplorer(explorerHost,'comparison',codes);
          }
        }
      }finally{
        enhancing=false;
        if(enhanceAgain){enhanceAgain=false;enhance();}
      }
    },100);
  }
  const observer=new MutationObserver(()=>enhance());
  observer.observe(root,{childList:true,subtree:true});
  document.addEventListener('change',event=>{if(event.target.matches('#compare-list input[type="checkbox"]'))enhance();});
  enhance();
})();

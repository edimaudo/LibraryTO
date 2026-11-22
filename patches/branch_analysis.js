function rankingMetricPanel(data,metric,index) {
  const rows=branchTotals(data,metric).sort((a,b)=>a.value-b.value);
  const build=(items,label)=>{
    if(!items.length)return empty('No reported values are available for this measure.');
    const trace={type:'bar',orientation:'h',x:items.map(x=>x.value),y:items.map(x=>x.branch.name),marker:{color:'#286b83'},
      customdata:items.map(x=>[x.branch.code,tierName(x.branch.service_tier_code),x.observations]),
      hovertemplate:'%{y}<br>Total reported: %{x:,.0f}<br>Branch code: %{customdata[0]}<br>%{customdata[1]}<extra></extra>'};
    return chart('',[trace],{height:400,margin:{l:160,r:28,t:28,b:65},title:{text:''},
      xaxis:{rangemode:'tozero',title:'Total across available reporting years'},
      yaxis:{autorange:'reversed',automargin:true},showlegend:false},label);
  };
  const years=(data.annual_values?.[metric]||[]).map(row=>String(row.year));
  const selectedYear=years[years.length-1]||'';
  return `<section id="ranking-panel-${index}" data-metric="${esc(metric)}" class="tab-panel ranking-metric-panel" role="tabpanel" aria-labelledby="ranking-tab-${index}" ${index?'hidden':''}>
    <div class="grid-2 ranking-charts">
      <section class="rank-chart-section"><h3>Top 10 branches</h3>${build(rows.slice(-10).reverse(),`Top 10 branches by ${METRICS[metric]}`)}</section>
      <section class="rank-chart-section"><h3>Bottom 10 branches</h3>${build(rows.slice(0,10),`Bottom 10 branches by ${METRICS[metric]}`)}</section>
    </div>
    <section class="rank-chart-section branch-size-section">
      <div class="branch-size-heading"><h3>Annual activity and branch size</h3><div class="form-field"><label for="activity-size-year-${index}">Reporting year</label><select id="activity-size-year-${index}" class="control activity-size-year">${years.map(year=>`<option value="${esc(year)}" ${year===selectedYear?'selected':''}>${esc(year)}</option>`).join('')}</select></div></div>
      <div class="activity-size-chart">${years.length?branchActivitySizeChart(data,metric,selectedYear):empty('No annual values are available for this measure.')}</div>
    </section>
  </section>`;
}
function branchActivitySizeChart(data,metric,year) {
  const annual=(data.annual_values?.[metric]||[]).find(row=>String(row.year)===String(year));
  if(!annual)return empty('No annual values are available for this reporting year.');
  const rows=(data.branches||[]).filter(branch=>Number(branch.square_footage)>0&&annual.values?.[branch.code]!==null&&annual.values?.[branch.code]!==undefined);
  if(!rows.length)return empty('No branches have both a reported annual value and floor area for this year.');
  const tiers=['DL','NL','RR','Other'];
  const traces=tiers.map(code=>{
    const items=rows.filter(branch=>(branch.service_tier_code||'Other')===code);
    return {type:'scatter',mode:'markers',name:tierName(code),x:items.map(branch=>Number(branch.square_footage)),y:items.map(branch=>Number(annual.values[branch.code])),
      customdata:items.map(branch=>[branch.name,branch.code,Number(annual.values[branch.code])/Number(branch.square_footage)*1000]),
      marker:{size:10,color:TIER_COLORS[code]||TIER_COLORS.Other},
      hovertemplate:`%{customdata[0]}<br>%{customdata[1]}<br>Year: ${esc(year)}<br>Branch size: %{x:,.0f} sq ft<br>${esc(METRICS[metric])}: %{y:,.0f}<br>Per 1,000 sq ft: %{customdata[2]:,.2f}<extra></extra>`};
  }).filter(trace=>trace.x.length);
  return chart(`${METRICS[metric]} and branch size · ${year}`,traces,{height:390,margin:{l:82,r:25,t:58,b:100},
    xaxis:{title:{text:'Branch size (sq ft)',standoff:14},rangemode:'tozero'},
    yaxis:{title:METRICS[metric],rangemode:'tozero'},
    legend:{orientation:'h',y:-.3,yanchor:'top',x:.5,xanchor:'center'}});
}
function rankingTabs(data) {
  const keys=Object.keys(METRICS);
  return `${tabsMarkup(keys.map(metric=>METRICS[metric]),'ranking')}${keys.map((metric,index)=>rankingMetricPanel(data,metric,index)).join('')}`;
}

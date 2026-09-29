// Typed result views. Provider text is always escaped; it can never supply HTML or scripts.
const $ = id => document.getElementById(id);
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = value => new Intl.NumberFormat('en-IN',{maximumFractionDigits:6}).format(Number(value));
const money = (value, unit='INR') => { try {return new Intl.NumberFormat('en-IN',{style:'currency',currency:unit,maximumFractionDigits:2}).format(value);} catch {return `${number(value)} ${esc(unit)}`;} };
const date = (value, short=false) => {const d=new Date(`${String(value).slice(0,10)}T12:00:00`);return Number.isNaN(+d)?value:d.toLocaleDateString('en-GB',{day:'numeric',month:short?'short':'long',...(!short?{year:'numeric'}:{})});};
export function safeUrl(value) {try {const url=new URL(value);return ['https:','http:'].includes(url.protocol) && !url.username && !url.password ? url.href : '';}catch{return '';}}
const names={travel:'Flight shortlist',rooms:'A space to meet',device:'A closer look',weather:'Weather',calculate:'The numbers',convert:'Unit conversion',currency:'Exchange',clock:'World clock',world_clocks:'Around the world',dates:'On the calendar',research:'Source collection',web:'From the web',sports:'Match room',timer:'Time to focus',document:'Working document',notes:'Your notebook',library:'Saved notes'};
const provenance={live:'LIVE SOURCE',computed:'CALCULATED LOCALLY',draft:'DRAFT',saved:'SAVED ON THIS LAPTOP',archived:'ARCHIVED NOTE',demo:'DEMO INVENTORY'};
const labels={date:'Date',after:'After',before:'Before',passengers:'Travellers',nonstop:'Direct',seat:'Seat',people:'People',duration_minutes:'Minutes',projector:'Projector',model:'Model',indicator:'Indicator',symptom:'Reported',country_code:'Country',days:'Forecast days'};
const statuses={prepared:'Preparing',submitted:'Awaiting outcome',cancel_requested:'Cancellation pending',not_submitted:'Not submitted',not_performed:'No action taken',completed:'Confirmed',cancelled:'Cancelled',unknown:'Outcome unknown',failed:'Failed'};
let current, viewed=null, lastWeb=null, lastSession=null, lastResult=null, lastComparison=null;
const checkedItems=new Set();
function html(id,markup){if($(id).innerHTML!==markup)$(id).innerHTML=markup;}
const arrow='<span aria-hidden="true">↗</span>';
function link(url,label){const safe=safeUrl(url);return safe?`<a class="source-link" href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(label)} ${arrow}</a>`:'';}
function mark(code='TH') {
  const color={AS:'#b66a41',SO:'#606f62',KA:'#4b606b'}[code] || '#b66a41';
  const shape={AS:'M5 25 16 5 27 25 20 21 16 13 12 21Z',SO:'M5 19C6 7 25 5 27 16 22 10 15 11 12 17L25 17 20 23 8 25Z',KA:'M16 4 27 15 16 26 5 15ZM16 17 20 27 15 24 11 29Z'}[code] || 'M5 23 17 6 15 20 26 12 21 26 15 20Z';
  return `<span class="airline-mark" style="--brand-color:${color}" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="${shape}"/></svg></span>`;
}
function flight(item, selected, disabled) {
  return `<button class="flight-card ${selected?'selected':''}" data-select="${esc(item.id)}" aria-label="Select ${esc(item.airline || 'demo airline')} ${esc(item.departure)}, ${esc(item.origin)} to ${esc(item.destination)}, ${esc(date(item.date))}" ${disabled?'disabled':''}>
    <div class="carrier-line">${mark(item.airline_code)}<div><b>${esc(item.airline || 'THREAD Air')}</b><small>${esc(item.flight_number || 'Demo flight')} · Economy</small></div><span class="card-choice">${selected?'✓':'↗'}</span></div>
    <div class="flight-route"><div><strong>${esc(item.departure)}</strong><span>${esc(item.origin)}</span></div><div class="route-stroke"><span>${item.nonstop?'NONSTOP':'1 STOP'}</span><i></i><svg viewBox="0 0 24 24"><path d="m3 12 7-2 3-7 2 0-1 7 6 2-6 2 1 7-2 0-3-7-7-2Z"/></svg></div><div class="flight-destination"><strong>${esc(item.destination)}</strong><span>Arrival city</span></div></div>
    <div class="ticket-bottom"><div><b>${esc(date(item.date))}</b><small>${esc(item.passengers)} ${item.passengers===1?'traveller':'travellers'} · Demo fare</small></div><div><strong>${money(item.price,item.currency)}</strong><small>${selected?'Selected':'Total, all travellers'}</small></div></div>
  </button>`;
}
function weather(item) {
  const sun = item.code<=2;
  return `<article class="weather-card"><div class="weather-place"><span class="micro-label">${esc([item.region,item.country].filter(Boolean).join(' · '))}</span><h3>${esc(item.title)}</h3></div><div class="weather-now"><strong>${number(item.temperature)}<sup>°</sup></strong><div class="weather-glyph ${sun?'sun':'cloud'}" aria-hidden="true"><i></i><i></i><i></i></div></div><p class="weather-condition">${esc(item.condition)}</p><div class="weather-facts"><span>Humidity <b>${number(item.humidity)}%</b></span><span>Wind <b>${number(item.wind)} km/h</b></span></div><div class="forecast">${item.forecast.map(d=>`<div><span>${new Date(d.date+'T12:00:00').toLocaleDateString('en-GB',{weekday:'short'})}</span><i class="forecast-symbol">${d.code<=2?'☀':d.code>=51?'☂':'☁'}</i><b>${number(d.high)}°</b><small>${number(d.low)}°</small><em>${d.rain==null?'—':number(d.rain)+'%'}</em></div>`).join('')}</div><small class="weather-stamp">Rain probability · Updated ${esc(item.observed_at?.replace('T',' '))} (${esc(item.timezone)})</small></article>`;
}
function resultNumber(item,kind){
  let heading=item.title, expression=item.expression || '', value=String(item.value), unit='', detail='';
  if(kind==='convert'){expression=`${number(item.from_value)} ${item.from_unit}`;value=number(item.value);unit=item.to_unit;detail=`${item.dimension} · ${item.from_unit} → ${item.to_unit}`;}
  if(kind==='currency'){expression=money(item.amount,item.base);value=money(item.value,item.target);detail=`1 ${item.base} = ${number(item.rate)} ${item.target} · ${item.date?date(item.date):'Same currency'}`;}
  if(kind==='dates'){expression=item.end?`${date(item.start,true)} → ${date(item.end,true)}`:`${date(item.start,true)} ${item.days<0?'−':'+'} ${Math.abs(item.days)} days`;unit=item.unit||'';value=item.unit?number(item.value):date(item.value);detail=item.weekday||item.detail||'';}
  return `<article class="number-card"><span class="micro-label">${esc(heading)}</span>${expression?`<div class="number-expression">${esc(expression)}</div>`:''}<div class="number-result ${value.length>16?'long':''}">${esc(value)}${unit?`<span>${esc(unit)}</span>`:''}</div><div class="number-rule"></div><p>${esc(detail || 'Computed by THREAD, with up to 28 significant digits.')}</p>${kind==='currency'?'<small>Reference rate · Bank fees and spreads excluded</small>':''}</article>`;
}
function worldClock(item){return `<article class="clock-card"><div class="clock-origin"><span class="micro-label">${esc(item.from_zone.replaceAll('_',' '))}</span><b>${esc(item.from_time.slice(11,16))}</b><small>${esc(date(item.from_time))}</small></div><span class="clock-arrow">↘</span><div class="clock-destination"><span class="micro-label">${esc(item.to_zone.replaceAll('_',' '))}</span><strong>${esc(item.value)}</strong><small>${esc(date(item.date))}</small></div></article>`;}
function source(item,index){return `<article class="reference-card"><div class="reference-top"><span class="source-monogram ${item.kind==='book'?'book-spine':''}">${esc(item.kind==='paper'?'DOI':item.kind==='book'?'Aa':'W')}</span><div><span class="micro-label">${esc(item.provider || 'Reference')}</span><small>${esc(item.published?.slice(0,10) || '')}</small></div><span class="reference-index">${String(index+1).padStart(2,'0')}</span></div><h3>${esc(item.title)}</h3>${item.detail?`<p>${esc(item.detail)}</p>`:''}${link(item.url,item.kind==='paper'?'View publication':item.kind==='book'?'View book':'Read source')}</article>`;}
function crest(url, title){const safe=safeUrl(url);return safe && new URL(safe).hostname==='a.espncdn.com'?`<img class="club-crest" src="${esc(safe)}" alt="${esc(title)} crest" loading="lazy" referrerpolicy="no-referrer">`:`<span class="crest-fallback" aria-hidden="true">${esc(title.slice(0,2))}</span>`;}
function sportsProfile(item){
  const records=item.records || [],selected={basketball:['points','totalRebounds','assists'],baseball:['hits','homeRuns','RBIs'],football:['passingYards','passingTouchdowns','rushingYards'],hockey:['goals','assists','points']}[item.sport];
  const portrait=safeUrl(item.portrait), hasPortrait=portrait && new URL(portrait).hostname==='a.espncdn.com';
  const unit=item.sport==='cricket'?'innings':item.sport==='racing'?(records.length===1?'Grand Prix':'Grands Prix'):item.sport==='soccer'&&item.entity_type==='player'?(records.length===1?'appearance':'appearances'):['tennis','soccer'].includes(item.sport)?(records.length===1?'match':'matches'):(records.length===1?'game':'games');
  const metric=(s)=>`<div><strong>${esc(s.value??'—')}</strong><span>${esc(s.label)}</span></div>`;
  return `<article class="sports-profile"><header class="athlete-hero ${hasPortrait?'has-portrait':''}">${hasPortrait?`<img class="athlete-photo" src="${esc(portrait)}" alt="${esc(item.title)}" loading="lazy" referrerpolicy="no-referrer">`:''}<div class="athlete-identity"><span class="sport-name">${esc(item.sport_label || item.sport || 'Sport')}</span><h3>${esc(item.title)}</h3><p>${esc(item.team || item.league || '')}</p></div></header>${item.metrics?.length?`<div class="athlete-metrics">${item.metrics.map(metric).join('')}</div><p class="metric-scope">Across these ${records.length} ${unit}</p>`:''}<div class="sports-record-heading"><h4>${records.length?`Last ${records.length} recorded ${unit}`:'Recent records unavailable'}</h4></div><div class="sports-records">${records.map(r=>{
    const url=safeUrl(r.url),stats=selected?(r.stats||[]).filter(s=>selected.includes(s.key)):(r.stats||[]).slice(0,3);
    return `<section class="sports-record"><div class="sports-record-date">${esc(date(r.date,true))}<span class="form-${esc(r.result)}">${esc(r.result || '')}</span></div><div class="sports-record-main">${r.logo?crest(r.logo,r.title):''}<div><h5>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}</a>`:esc(r.title)}</h5><p>${esc(r.subtitle || '')}</p></div><strong>${esc(r.score || '—')}</strong></div>${stats.length?`<div class="sports-record-stats">${stats.map(s=>`<span><b>${esc(s.value??'—')}</b> ${esc(s.label)}</span>`).join('')}</div>`:''}${r.status?`<small class="record-status">${esc(r.status)}</small>`:''}${r.stats?.length>stats.length?`<details class="full-box-score"><summary>Full box score</summary><dl>${r.stats.map(s=>`<div><dt>${esc(s.label)}</dt><dd>${esc(s.value??'—')}</dd></div>`).join('')}</dl></details>`:''}</section>`;
  }).join('')}</div><p class="sports-coverage">${esc(item.coverage || '')}</p>${link(item.url,'View source profile')}</article>`;
}
function matchRoom(item){
  if(item.entity_type==='player')return sportsProfile({...item,sport:'soccer',sport_label:'Football',coverage:item.scope,metrics:[{label:'Goals',value:item.goals},{label:'Assists',value:item.assists}],records:item.matches.map(m=>({id:m.id,date:m.date,title:`${m.home} v ${m.away}`,subtitle:m.competition,score:`${m.home_score} – ${m.away_score}`,result:m.result,url:m.url,stats:[{key:'goals',label:'goals',value:m.goals},{key:'assists',label:'assists',value:m.assists},...(m.minutes!=null?[{key:'minutes',label:'minutes',value:m.minutes}]:[])]}))});
  const first=item.matches[0],player=item.entity_type==='player';
  const stat=(v)=>v==null?'—':number(v);
  return `<article class="match-room"><header class="match-heading">${crest(item.logo,item.team||item.title)}<div><h3>${esc(item.title)}</h3><p>Last ${item.matches.length} ${player?'appearances':'matches'}</p></div></header>${player?`<div class="player-totals"><div><strong>${stat(item.goals)}</strong><span>Goals</span></div><div><strong>${stat(item.assists)}</strong><span>Assists</span></div><div class="form-line" aria-label="Most recent result first">${item.matches.map(m=>`<span class="form-${esc(m.result)}">${esc(m.result)}</span>`).join('')}</div></div>`:first?`<div class="match-feature"><p>${esc(date(first.date,true))} · ${esc(first.competition)}</p><div class="scoreboard"><div>${crest(first.home_logo,first.home)}<span>${esc(first.home)}</span></div><strong>${esc(first.home_score)}<i>–</i>${esc(first.away_score)}</strong><div>${crest(first.away_logo,first.away)}<span>${esc(first.away)}</span></div></div><small>${esc(first.status)}${first.home_penalties!=null&&first.away_penalties!=null?` · Penalties ${stat(first.home_penalties)}–${stat(first.away_penalties)}`:''}</small></div>`:''}<div class="match-list">${item.matches.map(m=>`<a class="match-row" href="${esc(safeUrl(m.url))}" target="_blank" rel="noopener noreferrer" aria-label="${esc(m.home)} ${esc(m.home_score)} to ${esc(m.away_score)} ${esc(m.away)}, ${esc(date(m.date))}"><div class="match-date"><b>${esc(date(m.date,true))}</b><small>${esc(m.competition)}</small></div><div class="match-teams"><span>${esc(m.home)}</span><b>${esc(m.home_score)} – ${esc(m.away_score)}</b><span>${esc(m.away)}</span></div>${player?`<div class="player-match-stats"><span>${stat(m.goals)} goals</span><span>${stat(m.assists)} assists</span>${m.minutes!=null?`<span>${stat(m.minutes)} min</span>`:''}</div>`:''}<span class="match-outcome form-${esc(m.result)}">${esc(m.result)}</span></a>`).join('')}</div><p class="match-scope">${esc(item.scope)}. Most recent first.</p>${(item.warnings||[]).map(w=>`<p class="match-warning">${esc(w)}</p>`).join('')}${link(item.url,'ESPN player record'.replace('player',player?'player':'team'))}</article>`;
}
function sportsChoice(item,result){return `<button class="sports-choice" data-prompt="${esc(`Show the last ${result.arguments?.limit || 5} games for ${item.title}, ${item.detail}. Sport: ${item.sport || 'soccer'}. Use the returned ${item.entity_type} record ${item.id}.`)}">${crest(item.logo,item.title)}<span><b>${esc(item.title)}</b><small>${esc(item.detail)}</small></span><span aria-hidden="true">↗</span></button>`;}
function documentCard(item,resultId){
  const d=item.document,kind=d.kind;
  const blocks=d.blocks.map((b,i)=>`<section class="document-block ${['itinerary','plan','study'].includes(kind)?'timeline-block':''}">${['itinerary','plan','study'].includes(kind)?`<span class="block-number">${String(i+1).padStart(2,'0')}</span>`:''}<div><h4>${esc(b.heading)}</h4>${b.text?(kind==='code'?`<pre class="code-content"><code>${esc(b.text)}</code></pre>`:`<p>${esc(b.text)}</p>`):''}${b.items?.length?`<ul class="${['checklist','recipe'].includes(kind)?'checklist-items':''}">${b.items.map((text,n)=>`<li>${kind==='checklist'?`<label><input type="checkbox" data-check="${esc(resultId)}-${i}-${n}"><span>${esc(text)}</span></label>`:esc(text)}</li>`).join('')}</ul>`:''}</div></section>`).join('');
  const table=d.rows?.length?`<div class="comparison-scroll"><table><thead><tr>${d.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${d.rows.map(row=>`<tr>${row.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'';
  return `<article class="document-card kind-${esc(kind)}"><div class="document-cover"><span class="micro-label">${esc(kind)} · WORKING DRAFT</span><h3>${esc(d.title)}</h3>${d.summary?`<p>${esc(d.summary)}</p>`:''}<div class="document-flourish" aria-hidden="true">⌁</div></div><div class="document-body">${table}${blocks}</div></article>`;
}
function timer(item){return `<article class="timer-card"><span class="micro-label">${esc(item.title)}</span><div class="timer-dial"><svg viewBox="0 0 200 200" aria-hidden="true"><circle class="timer-track" cx="100" cy="100" r="89"/><circle class="timer-progress" cx="100" cy="100" r="89" pathLength="100"/></svg><strong data-timer="${esc(item.end_at)}" data-total="${esc(item.seconds)}" data-cancelled="${!!item.cancelled}" data-paused="${esc(item.paused_at || '')}">—</strong></div><p>${item.cancelled?'Timer cancelled.':item.paused_at?'Timer paused.':'A little room for one thing.'}</p><small>Visual countdown · Keep this page open</small></article>`;}
function noteCard(item,saved){return `<article class="note-card"><span class="micro-label">${saved?'FROM YOUR NOTEBOOK':'NOTE PREVIEW'}</span><h3>${esc(item.title)}</h3><p>${esc(item.body)}</p>${item.created?`<small>Saved ${esc(date(item.created))}</small>`:''}</article>`;}
function generic(item,state,result){
  const canSelect=current?.capability?.can_create && result.id===current?.results?.id;
  return `<${canSelect?'button':'article'} class="reference-card ${current?.selection?.id===item.id?'selected':''}" ${canSelect?`data-select="${esc(item.id)}" ${state.paused||state.floor_held?'disabled':''}`:''}><span class="micro-label">${esc(result.domain==='rooms'?'MEETING SPACE · DEMO':result.domain==='device'?'SUPPLIED MANUAL':'RESULT')}</span><h3>${esc(item.title)}</h3><p>${esc(item.detail||'')}</p>${item.price!=null?`<div class="room-price">${money(item.price,item.currency)}<span>Demo reservation</span></div>`:''}${item.date?`<small>${esc(date(item.date))} · ${esc(item.start||'')}</small>`:''}</${canSelect?'button':'article'}>`;
}
export function renderCards(result,state={}){
  if(!result.items.length)return `<div class="no-results"><span>○</span><p>${esc(result.note || 'No results match these details.')}</p></div>`;
  return result.items.map((item,index)=>{
    try {
    switch(item.kind || result.domain){
      case 'flight': return flight(item,state.selection?.id===item.id,state.paused||state.floor_held||result.id!==state.results?.id);
      case 'weather':return weather(item);
      case 'calculate':case 'convert':case 'currency':case 'dates':return resultNumber(item,item.kind);
      case 'clock':return worldClock(item);
      case 'world_clocks':return `<article class="clock-card"><div class="clock-destination"><span class="micro-label">${esc(item.title)}</span><strong data-world-zone="${esc(item.zone)}">${esc(item.value)}</strong><small data-world-date="${esc(item.zone)}">${esc(item.date)}</small></div></article>`;
      case 'sports':return matchRoom(item);
      case 'sports_profile':return sportsProfile(item);
      case 'sports_choice':return sportsChoice(item,result);
      case 'source':case 'paper':case 'book':return source(item,index);
      case 'document':return documentCard(item,result.id);
      case 'timer':return timer(item);
      case 'notes':return noteCard(item,result.provenance==='saved');
      default:return generic(item,state,result);
    }
    } catch {return generic(item,state,result);}
  }).join('');
}
export function asMarkdown(result){
  const lines=[`# ${result.items[0]?.title || names[result.domain] || 'THREAD result'}`,`Source: ${result.source}`,`Status: ${provenance[result.provenance] || 'Returned evidence'}`,''];
  for(const item of result.items){
    if(item.document){const d=item.document;if(d.summary)lines.push(d.summary,'');if(d.rows?.length)lines.push('| '+d.columns.join(' | ')+' |','| '+d.columns.map(()=>'---').join(' | ')+' |',...d.rows.map(r=>'| '+r.join(' | ')+' |'),'');for(const block of d.blocks)lines.push('## '+block.heading,block.text || '',...(block.items||[]).map(x=>'- '+x),'');}
    else if(item.records){lines.push('## '+item.title,item.coverage,'',...item.records.map(r=>`${date(r.date)} · ${r.title} · ${r.score}\n${r.subtitle || ''}\n${(r.stats||[]).map(s=>`${s.label}: ${s.value??'unavailable'}`).join(' · ')}\n${r.url || ''}`),'');}
    else if(item.matches){lines.push('## '+item.title,item.scope,'',...item.matches.map(m=>`${date(m.date)} · ${m.competition}\n${m.home} ${m.home_score} – ${m.away_score} ${m.away}${m.goals!=null?` · Goals ${m.goals}, assists ${m.assists??'unavailable'}`:''}\n${m.url}`),'');}
    else if(item.body)lines.push('## '+item.title,item.body,'');
    else lines.push('## '+item.title,...Object.entries(item).filter(([k,v])=>!['id','kind','title'].includes(k) && ['string','number','boolean'].includes(typeof v)).map(([k,v])=>`${k.replaceAll('_',' ')}: ${v}`),'');
  }
  return lines.join('\n');
}
export function renderWorkspace(state){
  current=state;
  if(lastSession!==state.session_id){viewed=null;lastWeb=null;lastResult=null;lastComparison=null;checkedItems.clear();lastSession=state.session_id;}
  const shelf=state.workspace||[];
  if(state.results?.id&&state.results.id!==lastResult){lastResult=state.results.id;viewed=null;}
  const compared=shelf.findLast(r=>r.comparison);
  if(compared?.id&&compared.id!==lastComparison){lastComparison=compared.id;viewed=compared.id;}
  const web=shelf.find(r=>r.domain==='web');
  if(web?.id && web.id!==lastWeb){lastWeb=web.id;viewed=web.id;}
  let result=viewed?shelf.find(r=>r.id===viewed):state.results;
  if(viewed&&!result)viewed=null;
  result=result || state.results;
  const historical=!!viewed && result?.id!==state.results?.id;
  $('workspace-tabs').hidden=!shelf.length;
  html('workspace-tabs',shelf.map(r=>`<button data-shelf="${esc(r.id)}" class="workspace-tab ${r.id===result?.id?'active':''}" aria-pressed="${r.id===result?.id}">${esc(r.comparison?'Comparison':r.domain==='document'?r.arguments.kind:names[r.domain]||r.domain)}</button>`).join(''));
  $('empty-context').hidden=!!state.domain||!!result;
  $('active-task').hidden=!state.domain&&!result;
  const domain=historical?result.domain:state.domain;
  $('domain-label').textContent=names[domain] || state.capability?.title || domain;
  $('revision').textContent=historical?'EARLIER IN THE THREAD':state.revision?'UP TO DATE':'';
  const s=historical?result.arguments:state.slots;
  $('task-title').textContent=domain==='travel'?`${s.origin||'From…'} to ${s.destination||'To…'}`:domain==='research'?s.query||'Following a thought.':domain==='weather'?s.city||'A look outside.':domain==='document'?s.title||'Taking shape.':domain==='notes'?s.title||'Something to keep.':names[domain]||state.capability?.title||'';
  $('task-title').hidden=!!result&&['document','weather','notes','sports'].includes(domain);
  const showSlots=['travel','rooms','device','weather'].includes(domain);
  $('slots').hidden=!showSlots;
  html('slots',showSlots?Object.entries(s).filter(([k])=>labels[k]).map(([k,v])=>`<dl class="slot"><dt>${esc(labels[k])}</dt><dd>${esc(k==='date'?date(v,true):typeof v==='boolean'?v?'Yes':'No':v)}</dd></dl>`).join(''):'');
  const running=state.operations.some(op=>op.purpose==='lookup'&&op.status==='running'&&!op.obsolete);
  const failed=!result&&!running?[...state.operations].reverse().find(op=>op.domain===state.domain&&op.status==='failed'&&op.purpose==='lookup'&&!op.obsolete):null;
  $('task-state').textContent=historical?'Kept from earlier. Your current task continues.':state.unresolved.length?'An action is awaiting a confirmed outcome.':state.paused?'Paused. Your work is kept.':state.missing.length?`Still needed: ${state.missing.map(k=>k.replaceAll('_',' ')).join(', ')}.`:running?'Working on the details…':result?.provenance==='demo'?'Illustrative inventory. No real bookings or prices.':result?.provenance==='draft'?'Ready to shape together. Change any detail by speaking.':result?'The details are here. Keep the conversation going.':'Following your thought.';
  $('task-state').classList.toggle('working',running&&!historical);
  $('results-card').hidden=!result&&!running&&!failed;
  if(result){
    $('result-label').textContent=provenance[result.provenance] || 'RETURNED EVIDENCE';
    $('result-label').dataset.provenance=result.provenance||'';
    $('result-count').textContent=result.items.length===1?'01':String(result.items.length).padStart(2,'0');
    html('results',renderCards(result,state));
    // Isolated provider Search Suggestions: no scripts, same-origin access, forms or top navigation.
    html('search-suggestions',result.domain==='web'&&result.search_suggestions?`<iframe title="Google Search suggestions" sandbox="allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" srcdoc="${esc('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src https: data:;">'+result.search_suggestions)}"></iframe>`:'');
    $('result-source').textContent=result.source+(result.evidence?.page?` · Page ${result.evidence.page}`:'')+(result.retrieved_at?` · Retrieved ${new Date(result.retrieved_at).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})}`:'');
    $('artifact-actions').hidden=!result.items.length;
    $('download-artifact').href=`/api/sessions/${encodeURIComponent(state.session_id)}/artifacts/${encodeURIComponent(result.id)}`;
    for(const box of document.querySelectorAll('[data-check]'))box.checked=checkedItems.has(box.dataset.check);
  } else {
    $('result-label').textContent=failed?'NEEDS A MOMENT':'TAKING SHAPE';
    $('result-count').textContent='';$('result-source').textContent='';$('artifact-actions').hidden=true;
    html('search-suggestions','');
    html('results',failed?`<div class="no-results"><span>⌁</span><p>${esc(failed.result?.error || 'This tool could not complete the request. Your details are kept.')}</p><button class="text-button" data-retry>Try again</button></div>`:running?'<div class="workspace-loading"><i></i><i></i><i></i><p>Bringing the details together.</p></div>':'');
  }
  const notesReady=state.domain==='notes'&&!!state.results?.items.length;
  const noteSaved=notesReady&&state.operations.some(op=>op.domain==='notes'&&op.purpose==='create'&&op.status==='completed'&&op.arguments.option_id===state.results.items[0].id);
  $('book').hidden=historical||!state.capability?.can_create||(!state.selection&&!notesReady);
  $('book').disabled=state.floor_held||state.paused||state.ended||state.understanding||noteSaved;
  $('book').textContent=state.domain==='notes'?noteSaved?'Saved to notebook ✓':'Save to my notebook':state.domain==='device'?'Create demo support ticket':'Reserve this demo option';
  const actions=state.operations.filter(o=>o.purpose==='create').slice(-5);
  $('action-section').hidden=!state.domain;
  html('operations',actions.map(op=>`<div class="operation"><div class="operation-title"><span>${op.domain==='notes'?'Notebook':op.domain==='device'?'Support ticket':'Demo reservation'}</span><span class="badge ${esc(op.status)}">${esc(op.domain==='notes'&&op.status==='completed'?'Saved':statuses[op.status]||op.status)}</span></div><small>${esc(op.selection?.title||'')}</small>${op.result?.reference?`<small>${esc(op.result.reference)}</small>`:''}</div>`).join(''));
  tickTimers();
}
function visibleResult(){return (current?.workspace||[]).find(r=>r.id===viewed) || current?.results;}
document.addEventListener('click',event=>{
  const tab=event.target.closest('[data-shelf]');if(tab){viewed=tab.dataset.shelf===current?.results?.id?null:tab.dataset.shelf;renderWorkspace(current);}
  if(event.target.closest('#copy-artifact')){const result=visibleResult();if(result)navigator.clipboard.writeText(asMarkdown(result)).then(()=>{$('copy-artifact').textContent='Copied ✓';setTimeout(()=>{$('copy-artifact').textContent='Copy';},1800);}).catch(()=>{$('copy-artifact').textContent='Use download';});}
});
document.addEventListener('change',event=>{if(event.target.matches('[data-check]')){if(event.target.checked)checkedItems.add(event.target.dataset.check);else checkedItems.delete(event.target.dataset.check);}});
function tickTimers(){for(const el of document.querySelectorAll('[data-world-zone]')){try{el.textContent=new Intl.DateTimeFormat(undefined,{timeZone:el.dataset.worldZone,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date());}catch{el.textContent='Timezone unavailable';}}for(const el of document.querySelectorAll('[data-world-date]')){try{el.textContent=new Intl.DateTimeFormat(undefined,{timeZone:el.dataset.worldDate,weekday:'short',month:'short',day:'numeric',timeZoneName:'short'}).format(new Date());}catch{el.textContent='';}}for(const el of document.querySelectorAll('[data-timer]')){const seconds=Math.max(0,Math.ceil((new Date(el.dataset.timer)-(el.dataset.paused?new Date(el.dataset.paused):Date.now()))/1000));el.textContent=el.dataset.cancelled==='true'?'—':`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;el.closest('.timer-dial').classList.toggle('finished',seconds===0&&el.dataset.cancelled!=='true');const progress=el.parentElement.querySelector('.timer-progress');progress.style.strokeDasharray=`${Math.min(100,seconds/Number(el.dataset.total)*100)} 100`;}}
setInterval(tickTimers,500);

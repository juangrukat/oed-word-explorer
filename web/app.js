'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const soundModes=new Set(['rhyme','near-rhyme','sounds-like']);
const modeNames={headword:'Headwords',definitions:'Definitions / ideas',quotations:'Quotations',rhyme:'Exact rhymes','near-rhyme':'Near rhymes','sounds-like':'Similar pronunciation'};
const state = {searchOffset:0, entry:null, sense:null, searchSeq:0, entrySeq:0, relatedSeq:0, quotationOffset:0, connObscure:false, connLiterary:false};
const status = (message, error=false) => {$('#status').textContent=message; $('#status').classList.toggle('error',error);};
async function api(path, params={}) {
  const response = await fetch(path+'?'+new URLSearchParams(params));
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
const excerpt = (value, length=230) => value.length>length ? value.slice(0,length).trim()+'…' : value;
function badges(labels=[], inferred=false) {
  labels=labels.filter(x=>!x.startsWith('Status:'));
  return '<div class="badges">'+labels.map(x=>'<span class="badge">'+esc(x)+'</span>').join('')+(inferred?'<span class="badge inferred">Inferred connection</span>':'')+'</div>';
}
function searchParams() {
  const sound=soundModes.has($('#mode').value);
  return {q:$('#query').value.trim(),mode:$('#mode').value,pos:$('#pos').value,
    obscure:$('#obscure').checked?'1':'0',literary:$('#literary').checked?'1':'0',
    syllables:sound?$('#syllables').value:'',stress:sound?$('#stress').value:'',
    input:sound?$('#input-type').value:'word',pronunciation:sound && $('#input-type').value==='word'?$('#pronunciation').value:''};
}
function updateSettings() {
  const sound=soundModes.has($('#mode').value);
  document.querySelectorAll('.sound-controls').forEach(e=>e.hidden=!sound);
  ['syllables','stress','input-type'].forEach(id=>$('#'+id).disabled=!sound);
  if(!sound) $('#pronunciation-area').hidden=true;
  $('#query-label').textContent=sound?($('#input-type').value==='ipa'?'IPA pronunciation':'A word to match by sound'):'A headword or an idea';
  $('#query').placeholder=sound?($('#input-type').value==='ipa'?'kæt, ˈneɪʃən, laɪt…':'light, nation, read…'):'lament, elegy, a poem of mourning…';
  $('#query-help').textContent=sound?'Sound search uses recorded pronunciations; select a variant when a word has several.':'Headword patterns: ? matches one character; * matches any number.';
  const filters=[];
  if($('#mode').value!=='headword') filters.push(['mode',modeNames[$('#mode').value]]);
  if($('#pos').value!=='any') filters.push(['pos',$('#pos').selectedOptions[0].textContent]);
  if($('#literary').checked) filters.push(['literary','Literary']);
  if($('#obscure').checked) filters.push(['obscure','Obsolete / rare / dialectal']);
  if(sound && $('#syllables').value) filters.push(['syllables',$('#syllables').value+' syllables']);
  if(sound && $('#stress').value) filters.push(['stress','Stress '+$('#stress').value]);
  if(sound && $('#input-type').value==='ipa') filters.push(['input-type','IPA input']);
  $('#active-filters').innerHTML=filters.map(([id,label])=>`<button type="button" data-remove-filter="${id}" aria-label="Remove ${esc(label)} filter">${esc(label)} ×</button>`).join('');
  $('#advanced-count').textContent=filters.length?filters.length+' active':'';
  $('#active-filters').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{
    const field=$('#'+button.dataset.removeFilter);
    if(field.type==='checkbox')field.checked=false;
    else field.value=field.id==='mode'?'headword':field.id==='pos'?'any':field.id==='input-type'?'word':'';
    updateSettings();if($('#query').value.trim())search();
  }));
}
function renderPronunciations(data,params) {
  const options=data.pronunciations||[];
  if(!soundModes.has(params.mode)||params.input==='ipa'||!options.length){$('#pronunciation-area').hidden=true;return;}
  $('#pronunciation-area').hidden=false;
  $('#pronunciation').innerHTML='<option value="">Choose a pronunciation…</option>'+options.map(o=>`<option value="${esc(o.key)}">/${esc(o.ipa)}/ · ${o.syllables} syllable${o.syllables===1?'':'s'}${o.stress?' · stress '+esc(o.stress):' · stress unrecorded'}</option>`).join('');
  $('#pronunciation').value=params.pronunciation||data.selected_pronunciation?.key||'';
  $('#pronunciation-help').textContent=data.needs_pronunciation?'This word has several recorded forms. Choose one to see its sound matches.':'Matches use this recorded pronunciation; optional segments may yield more than one form.';
}
function entryLink(id,sense) {
  const p=new URLSearchParams(searchParams()); if(state.searchOffset)p.set('offset',state.searchOffset); p.set('entry',String(id));
  if (sense) p.set('sense',sense);
  return '#'+p.toString();
}
function resultCard(result,inferred=false) {
  const id=result.entry_id??result.id;
  const sense=result.matched_sense_id || (result.entry_id!==undefined && typeof result.id==='string' ? result.id : '');
  const support=(result.supporting_senses||[]).map(s=>`<p class="small muted">Another supporting sense: ${esc(excerpt(s.definition,180))}</p>`).join('');
  const phone=result.phonetic_match;
  const soundEvidence=phone?`<span class="sound-evidence">/${esc(phone.ipa)}/ <span class="small muted">· ${phone.syllables} syllable${phone.syllables===1?'':'s'}${phone.stress?' · stress '+esc(phone.stress):''}</span></span>`:'';
  return `<a class="result-card ${state.entry?.id===id?'active':''}" href="${esc(entryLink(id,sense))}"><div class="result-head"><strong>${esc(result.headword)}</strong><span class="pos">${esc(result.pos)} ${esc(result.homonym)}</span></div>${badges(result.labels,inferred)}${soundEvidence}<p>${esc(excerpt(result.definition||''))}</p>${support}<div class="reason">${esc(result.explanation||result.connection||'Dictionary reference')}</div></a>`;
}
function highlightedIPA(ipa,ending) {
  if(!ending || !ipa.endsWith(ending))return '/'+esc(ipa)+'/';
  return '/'+esc(ipa.slice(0,-ending.length))+'<mark>'+esc(ending)+'</mark>/';
}
function soundGroup(result,mode) {
  const entries=new Map();
  for(const variant of result.variants||[result]){if(!entries.has(variant.id))entries.set(variant.id,{...variant,phones:[]});entries.get(variant.id).phones.push(variant.phonetic_match);}
  const variants=[...entries.values()];
  return `<article class="sound-group"><h3>${esc(result.headword)} <span class="small muted">${result.entry_count||1} matching dictionary entr${result.entry_count===1?'y':'ies'}</span></h3>${variants.map(v=>{
    const phone=v.phonetic_match;
    const ipa=highlightedIPA(phone.ipa,mode==='sounds-like'?'':phone.ending);
    const hint=phone.homophone?`Same recorded pronunciation as <strong>${esc(phone.homophone)}</strong>. `:'';
    const why=mode==='rhyme'?`Shares ${phone.ending_hint?esc(phone.ending_hint)+' ':''}<strong>/${esc(phone.ending)}/</strong> with your selected pronunciation.`:esc(v.explanation);
    return `<a class="result-card sound-card ${state.entry?.id===v.id?'active':''}" href="${esc(entryLink(v.id))}"><div class="result-head"><span class="pos">${esc(v.pos)} ${v.homonym?' · dictionary entry '+esc(v.homonym):''}</span></div><p class="pronunciation-line"><strong>Pronunciation:</strong> ${ipa}</p>${v.phones.slice(1).map(p=>`<p class="pronunciation-line"><strong>Also matches:</strong> ${highlightedIPA(p.ipa,mode==='sounds-like'?'':p.ending)}${p.homophone?' · same recorded pronunciation as '+esc(p.homophone):''}</p>`).join('')}${hint?`<p class="pronunciation-hint">${hint}</p>`:''}${badges(v.usage_labels)}<p><strong>Meaning:</strong> ${esc(excerpt(v.definition,300))}</p><p class="rhyme-reason"><strong>${mode==='rhyme'?'Why it rhymes':'Why it matches'}:</strong> ${why}</p><span class="small muted">${phone.syllables} syllable${phone.syllables===1?'':'s'}${phone.optional?' · recorded optional sound variant':''} · Open this dictionary entry →</span></a>`;
  }).join('')}</article>`;
}
function soundSummary(data,params) {
  const selected=data.selected_pronunciation, summary=data.sound_summary;
  if(!selected || !summary)return '';
  const exact=params.mode==='rhyme';
  return `<div class="sound-summary"><h3>${esc(modeNames[params.mode])} ${params.input==='ipa'?'for':'for '+esc(params.q)}</h3><p>Selected pronunciation: <strong>${highlightedIPA(selected.ipa,exact?summary.ending:'')}</strong></p>${exact?`<p>Matching ending: <strong>${summary.ending_hint?esc(summary.ending_hint)+' · ':''}/${esc(summary.ending)}/</strong>. The highlighted sounds rhyme; spelling can differ completely.</p>`:'<p>These are approximate sound matches. Each card shows the pronunciation actually compared.</p>'}<p class="small muted">Historical, dialectal and obscure words are included. Usage labels describe the dictionary entry and may concern individual senses.</p></div>`;
}
async function search(updateHash=true,offset=0) {

  updateSettings();
  const params=searchParams(); if (!params.q) return;
  if(soundModes.has(params.mode)){params.offset=String(offset);state.searchOffset=offset;}else state.searchOffset=0;
  const seq=++state.searchSeq;
  $('#search-form button[type="submit"]').disabled=true;
  status('Searching your dictionary…');
  if(updateHash) history.replaceState(null,'','#'+new URLSearchParams(params));
  try {
    const data=await api('/api/search',params); if(seq!==state.searchSeq) return;
    renderPronunciations(data,params);
    $('#results-title').textContent=modeNames[params.mode]||'Results';
    $('#result-count').textContent=data.total!==undefined?`${data.total} words · ${data.results.length?Number(data.offset)+1:0}–${Number(data.offset)+data.results.length} shown`:data.results.length+(data.results.length===40?' shown':' results');
    $('#results').innerHTML=data.needs_pronunciation?'<div class="empty"><h3>Choose a pronunciation above.</h3><p>Each form can have different rhymes.</p></div>':data.results.length?soundSummary(data,params)+data.results.map(x=>x.variants?soundGroup(x,params.mode):resultCard(x)).join(''):'<div class="empty"><h3>No matches in this view.</h3><p>Try fewer words, switch to definitions, or remove a filter.</p></div>';
    if(data.total!==undefined && (offset>0 || data.next_offset!==null)) {
      $('#results').insertAdjacentHTML('beforeend',`<nav class="sound-pagination" aria-label="Sound result pages">${offset>0?'<button type="button" id="sound-prev" class="subtle-button">← Previous words</button>':''}${data.next_offset!==null?'<button type="button" id="sound-next" class="subtle-button">More words →</button>':''}</nav>`);
      const changePage=async next=>{await search(true,next);$('#results-panel').scrollIntoView({block:'start'});};
      $('#sound-prev')?.addEventListener('click',()=>changePage(Math.max(0,offset-40)));
      $('#sound-next')?.addEventListener('click',()=>changePage(data.next_offset));
    }
    status(data.notice||'Select an entry to explore its senses and connections.');
  } catch(error) {if(seq===state.searchSeq) status(error.message,true);}
  finally {if(seq===state.searchSeq) $('#search-form button[type="submit"]').disabled=false;}
}
function referenceCard(ref) {
  const choices=(ref.targets||[]).map(t=>`<a class="chip" href="${esc(entryLink(t.id,t.sense_id))}">${esc(t.headword)} <span class="pos">${esc(t.pos)} ${esc(t.homonym)}</span></a>`).join('');
  return `<div class="reference"><div>${esc(ref.text||ref.target)}${ref.context==='etymology'?' · etymology':''}${ref.context==='quotation'?' · quotation':''}</div>${choices||'<span class="small muted">Target not resolved in this corpus.</span>'}</div>`;
}
function renderEntry(entry,preferredSense) {
  state.entry=entry;
  state.sense=entry.senses.find(s=>s.id===preferredSense)?.id||entry.senses[0]?.id;
  state.quotationOffset=entry.quotations.length;
  $('.workspace').classList.add('open');
  $('#entry-panel').hidden=false;
  const senseNodes=entry.senses.map(s=>`<button class="sense ${s.parent_id?'indented':''} ${s.id===state.sense?'selected':''}" data-sense="${esc(s.id)}" aria-pressed="${s.id===state.sense}"><span class="sense-number">${esc(s.number||(s.tag==='sub'?'SUBENTRY':'MEANING'))}${s.parent_id?' · SUBSENSE':''}</span>${badges(s.labels)}<span class="definition">${esc(s.definition)}</span></button>`).join('');
  $('#entry-panel').innerHTML=`<div class="entry-controls"><span>DICTIONARY ENTRY</span><button id="close-entry">Close entry ×</button></div><div class="entry-header"><h2>${esc(entry.headword)}</h2><div class="head-details"><span class="pos">${esc(entry.pos)} ${esc(entry.homonym)}</span><span>${esc(entry.pronunciation)}</span></div>${badges(entry.labels)}${entry.headwords.length>1?`<p class="small muted">Also in this entry: ${entry.headwords.slice(1).map(esc).join(" · ")}</p>`:""}<p class="small muted">${entry.senses.length} meanings · ${entry.quotation_total} quotations${entry.kind==='ve'?' · variant entry':''}</p></div><p class="small muted">Select a meaning to explore its connections.</p><div class="sense-list">${senseNodes}</div><section class="connections"><h3>Where this meaning leads</h3><div class="connection-filter"><label><input id="conn-obscure" type="checkbox" ${state.connObscure?'checked':''}> Obsolete, rare & dialectal</label><label><input id="conn-literary" type="checkbox" ${state.connLiterary?'checked':''}> Literary candidates</label></div><div id="connections-content" aria-live="polite">Finding connections…</div></section>${entry.etymologies.length?`<details class="evidence-section"><summary>Etymology</summary>${entry.etymologies.map(x=>'<p>'+esc(x)+'</p>').join('')}</details>`:''}<details class="evidence-section"><summary>Historical quotations (${entry.quotation_total})</summary><div id="quotations">${entry.quotations.map(x=>'<p class="quote">'+esc(x)+'</p>').join('')}</div>${entry.quotation_total>state.quotationOffset?'<button id="more-quotes" class="subtle-button">Load more quotations</button>':''}</details><details class="evidence-section"><summary>All dictionary references (${entry.references.length})</summary>${entry.references.map(referenceCard).join('')||'<p class="muted">No explicit references.</p>'}</details><details class="evidence-section source"><summary>Source evidence</summary><p class="small">Original SGML at corpus byte ${entry.source.corpus_offset.toLocaleString()}, ${entry.source.length.toLocaleString()} bytes.</p><p class="small muted">SHA-256: ${esc(entry.source.sha256)}</p><p><a href="/api/raw?id=${entry.id}" target="_blank" rel="noopener">Read original markup ↗</a></p>${entry.source.unmapped_entities.length?`<p class="small muted">Unmapped characters retained: ${entry.source.unmapped_entities.map(esc).join(', ')}</p>`:''}</details>`;
  $('#close-entry').addEventListener('click',()=>{
    ++state.entrySeq; ++state.relatedSeq; state.entry=null;
    $('#entry-panel').hidden=true; $('.workspace').classList.remove('open');
    history.replaceState(null,'','#'+new URLSearchParams(searchParams()));
  });
  $('#entry-panel').querySelectorAll('[data-sense]').forEach(button=>button.addEventListener('click',()=>selectSense(button.dataset.sense)));
  $('#conn-obscure').addEventListener('change',()=>{state.connObscure=$('#conn-obscure').checked;related();});
  $('#conn-literary').addEventListener('change',()=>{state.connLiterary=$('#conn-literary').checked;related();});
  $('#more-quotes')?.addEventListener('click',moreQuotations);
  related();
}
function selectSense(id) {
  state.sense=id;
  $('#entry-panel').querySelectorAll('[data-sense]').forEach(b=>{b.classList.toggle('selected',b.dataset.sense===id);b.setAttribute('aria-pressed',String(b.dataset.sense===id));});
  history.replaceState(null,'',entryLink(state.entry.id,id));
  related();
}
async function related() {
  if(!state.entry) return;
  const seq=++state.relatedSeq;
  $('#connections-content').textContent='Finding connections…';
  try {
    const data=await api('/api/related',{id:state.entry.id,sense:state.sense||'',obscure:state.connObscure?'1':'0',literary:state.connLiterary?'1':'0'});
    if(seq!==state.relatedSeq || !$('#connections-content')) return;
    const explicit=data.explicit.length?`<div class="connection-group"><h4>Explicit connections from this sense</h4>${data.explicit.map(referenceCard).join('')}</div>`:'';
    const incoming=data.incoming.length?`<div class="connection-group"><h4>Entries referring to this headword</h4><p class="small muted">These can concern a different sense or homonym.</p>${data.incoming.map(x=>referenceCard({text:x.text,context:x.context,targets:[x]})).join('')}</div>`:'';
    const family=data.family?.length?`<div class="connection-group"><h4>Subentries grouped with this word</h4>${data.family.map(x=>resultCard(x)).join('')}</div>`:'';
    const inferred=`<div class="connection-group"><h4>Explore similar definitions</h4><p class="small muted">Inferred suggestions, not verified synonyms. Obscure filters use historical dictionary labels.</p>${data.suggestions.length?data.suggestions.map(x=>resultCard(x,true)).join(''):'<p class="muted">No suggestions with these filters. Try another sense or widen the filters.</p>'}</div>`;
    $('#connections-content').innerHTML=explicit+family+inferred+incoming+`<p class="terms">Definition terms used: ${data.terms.length?data.terms.map(esc).join(' · '):'none'}</p>`;
  } catch(error) {if(seq===state.relatedSeq && $('#connections-content')) $('#connections-content').textContent=error.message;}
}
async function moreQuotations() {
  const id=state.entry.id;
  const button=$('#more-quotes'); button.disabled=true;
  try {
    const data=await api('/api/quotations',{id,offset:state.quotationOffset});
    if(state.entry?.id!==id) return;
    $('#quotations').insertAdjacentHTML('beforeend',data.quotations.map(x=>'<p class="quote">'+esc(x)+'</p>').join(''));
    state.quotationOffset+=data.quotations.length;
    if(state.quotationOffset>=state.entry.quotation_total) button.remove(); else button.disabled=false;
  } catch(error) {status(error.message,true);button.disabled=false;}
}
async function openEntry(id,sense) {
  const seq=++state.entrySeq;
  status('Opening entry…');
  try {
    const entry=await api('/api/entry',{id}); if(seq!==state.entrySeq) return;
    renderEntry(entry,sense); status('Select a sense to change the connections below.');
    if(window.innerWidth<850) $('#entry-panel').scrollIntoView({behavior:'smooth',block:'start'});
  } catch(error) {if(seq===state.entrySeq) status(error.message,true);}
}
async function route() {
  const p=new URLSearchParams(location.hash.slice(1));
  if(p.has('q')) $('#query').value=p.get('q');
  if(Object.hasOwn(modeNames,p.get('mode'))) $('#mode').value=p.get('mode');
  if([...$('#pos').options].some(o=>o.value===p.get('pos')))$('#pos').value=p.get('pos');else $('#pos').value='any';
  $('#syllables').value=p.get('syllables')||'';$('#stress').value=p.get('stress')||'';
  $('#input-type').value=p.get('input')==='ipa'?'ipa':'word';
  $('#pronunciation').innerHTML=p.get('pronunciation')?`<option value="${esc(p.get('pronunciation'))}">Saved pronunciation</option>`:'<option value="">Choose a pronunciation…</option>';
  updateSettings();
  if(soundModes.has($('#mode').value)||$('#pos').value!=='any')$('#advanced-panel').open=true;
  $('#obscure').checked=p.get('obscure')==='1'; $('#literary').checked=p.get('literary')==='1';
  if(p.get('q')) await search(false,Number(p.get('offset'))||0);
  if(p.has('entry')) {
    const id=Number(p.get('entry'));
    if(!Number.isSafeInteger(id)||id<0) return status('Invalid entry link.',true);
    await openEntry(id,p.get('sense'));
  } else if(state.entry) {
    ++state.entrySeq;++state.relatedSeq;state.entry=null;
    $('#entry-panel').hidden=true;$('.workspace').classList.remove('open');
  }
}
$('#search-form').addEventListener('submit',event=>{event.preventDefault();search();});
$('.examples').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{
  $('#query').value=button.dataset.example;$('#mode').value=button.dataset.mode||'headword';
  $('#pos').value='any';$('#syllables').value='';$('#stress').value='';$('#pronunciation').value='';$('#input-type').value='word';
  $('#obscure').checked=button.dataset.obscure==='1';$('#literary').checked=false;search();
}));
['mode','pos','literary','obscure','syllables','stress','input-type'].forEach(id=>$('#'+id).addEventListener('change',()=>{
  if(id==='input-type'||(id==='mode'&&!soundModes.has($('#mode').value))){$('#pronunciation').value='';$('#pronunciation-area').hidden=true;}
  updateSettings();
}));
$('#query').addEventListener('input',()=>{$('#pronunciation').value='';$('#pronunciation-area').hidden=true;});
$('#pronunciation').addEventListener('change',()=>{if($('#pronunciation').value)search();});
$('#reset-filters').addEventListener('click',()=>{
  $('#mode').value='headword';$('#pos').value='any';$('#literary').checked=false;$('#obscure').checked=false;
  $('#syllables').value='';$('#stress').value='';$('#input-type').value='word';$('#pronunciation').value='';
  updateSettings();
});
updateSettings();
window.addEventListener('hashchange',route);
api('/api/status').then(data=>{$('#corpus-status').textContent=`YOUR LIBRARY · ${data.entries.toLocaleString()} entries · ${data.senses.toLocaleString()} meanings${data.phonetic_entries?` · sounds for ${data.phonetic_entries.toLocaleString()} entries`:""} · works offline`}).catch(error=>{$('#corpus-status').textContent=error.message});
route();

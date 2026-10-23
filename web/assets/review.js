(() => {
  const $=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let config,record=null,pollTimer=null,working=false;
  const lastOpenedKey='property-screening:last-opened';
  let lastOpened=null;
  try{lastOpened=localStorage.getItem(lastOpenedKey);}catch(e){}
  const drafts=new Map(),previewUrls=new Map(),instructions=new Map(),revisionResults=new Map(),additionalNotes=new Map();
  function remember(id){
    lastOpened=id;
    try{if(id)localStorage.setItem(lastOpenedKey,id);else localStorage.removeItem(lastOpenedKey);}catch(e){}
  }
  function message(text,target='system'){
    if(target==='generation'){
      $('generation-error').textContent='There was an error while generating the report, please try again (if the error persists, please contact Pablo Rubio).';
      $('generation-error').hidden=false;
    }else if(target==='revision-result'&&record){
      $('revision-result').textContent=text;revisionResults.set(record.id,text);
    }else if(text)console.warn(text);
  }
  async function api(path,options={}){
    options.headers={...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),'X-Local-Token':config?.token||'',...options.headers};
    const response=await fetch(path,options);
    let data;
    try{data=await response.json();}catch(e){throw Error('The local server returned an unreadable response. Check that it is still running.');}
    if(!response.ok)throw Error(data.error||'The request failed');return data;
  }
  const post=(path,data)=>api(path,{method:'POST',body:JSON.stringify(data)});
  async function list(){
    const data=await api('/api/records');
    $('submissions-title').hidden=data.records.length===0;
    $('records').innerHTML=data.records.map(r=>`<div class="record-card"><button type="button" class="record-button ${record?.id===r.id?'active':''}" data-record="${esc(r.id)}" ${working?'disabled':''}><strong>${esc(r.address)}</strong><small>${esc(r.postcode)} · ${esc(r.status.replaceAll('_',' '))}</small><small>${esc(r.investor||'No client name')}</small></button><button type="button" class="record-delete" data-delete-record="${esc(r.id)}" data-record-status="${esc(r.status)}" aria-label="Delete ${esc(r.address)}" title="${r.status==='running'?'Wait until processing finishes':'Delete'}" ${working||r.status==='running'?'disabled':''}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg></button></div>`).join('');
    return data.records;
  }
  function draft(){
    if(!drafts.has(record.id)||(!drafts.get(record.id).dirty&&drafts.get(record.id).revision!==record.revision)){
      let cover=null;const gallery=[];
      (record.photos||[]).forEach((p,i)=>{if((p.role||(i===0?'cover':'gallery'))==='cover'&&!cover)cover=p;else gallery.push(p);});
      drafts.set(record.id,{cover,gallery,dirty:false,revision:record.revision});
    }
    return drafts.get(record.id);
  }
  function busy(){return working||record?.status==='running';}
  function finalizationBlock(){
    if(!record?.artifacts?.pdf)return 'Generate a report first.';
    if(record.status==='running')return 'Wait for the report to finish updating.';
    const d=draft();
    if(!d.cover||d.cover instanceof File||!d.cover.filename)return 'Add a cover photo to the PDF first.';
    if(d.dirty)return 'Save your photo changes first.';
    if($('revision-instruction').value.trim())return 'Apply or clear your requested edits first.';
    return '';
  }
  function controls(){
    document.querySelectorAll('#record button,#record input,#record textarea').forEach(el=>el.disabled=busy());
    document.querySelectorAll('[data-record]').forEach(el=>el.disabled=working);
    document.querySelectorAll('[data-delete-record]').forEach(el=>{
      const running=(record?.id===el.dataset.deleteRecord?record.status:el.dataset.recordStatus)==='running';
      el.disabled=working||running;el.title=running?'Wait until processing finishes':'Delete';
    });
    document.querySelectorAll('[data-photo-zone]').forEach(el=>el.classList.toggle('is-disabled',busy()));
    if(record)$('save-photos').disabled=busy()||!record.artifacts?.pdf||!draft().dirty;
    const reason=busy()?'Wait for the current operation to finish.':finalizationBlock();
    $('finalize').disabled=!!reason;
    $('finalize').title=reason;
  }
  function release(file){if(file instanceof File&&previewUrls.has(file)){URL.revokeObjectURL(previewUrls.get(file));previewUrls.delete(file);}}
  function imageUrl(photo){
    if(!(photo instanceof File))return '/api/records/'+record.id+'/photos/'+encodeURIComponent(photo.filename);
    if(!previewUrls.has(photo))previewUrls.set(photo,URL.createObjectURL(photo));
    return previewUrls.get(photo);
  }
  function renderPhotos(){
    const d=draft();
    for(const role of ['cover','gallery']){
      const photos=role==='cover'?(d.cover?[d.cover]:[]):d.gallery;
      $(role+'-photo-preview').innerHTML=photos.map((photo,index)=>`<div class="upload-thumb"><img src="${esc(imageUrl(photo))}" alt="${role==='cover'?'Cover photo':'House photo '+(index+1)}"><button type="button" data-remove-photo="${role}" data-index="${index}" aria-label="Remove ${role==='cover'?'cover photo':'house photo '+(index+1)}" title="Remove photo">×</button></div>`).join('');
    }
    controls();
  }
  function choosePhotos(role,files){
    if(!record?.artifacts?.pdf||busy())return;
    files=Array.from(files);if(!files.length)return;
    const d=draft();
    if(role==='cover'&&files.length>1)throw Error('Choose one cover photo at a time.');
    if(role==='gallery'&&d.gallery.length+files.length>10)throw Error('You can add up to ten house photos. Remove one first to make room.');
    for(const file of files){
      if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Choose JPEG, PNG or WebP photos.');
      if(file.size>10*1024*1024)throw Error('Each photo must be 10 MB or smaller.');
    }
    if(role==='cover'){release(d.cover);d.cover=files[0];}else d.gallery.push(...files);
    d.dirty=true;renderPhotos();
  }
  function renderReport(){
    const area=record.inputs.enquiry?.kind==='area';
    $('area-panel').hidden=!area;
    const status=area?['ready','Needs follow-up']:record.status==='approved'?['approved','Approved']:record.status==='ready_for_review'?['ready','Ready for review']:['draft','Draft'];
    $('report-status').className='tag status-'+status[0];
    $('report-status').textContent=status[1];
    $('report-status').hidden=false;
    const hasPdf=!!record.artifacts?.pdf;
    $('draft-controls').hidden=hasPdf;
    $('photo-panel').hidden=!hasPdf;
    $('run-panel').hidden=area||(hasPdf&&record.status!=='needs_input');
    $('review-approval').hidden=!hasPdf;
    const missingRent=record.status==='needs_input';
    const failedGeneration=record.status==='error'&&!hasPdf;
    $('generation-error').textContent=missingRent||failedGeneration?'There was an error while generating the report, please try again (if the error persists, please contact Pablo Rubio).':'';
    $('generation-error').hidden=!(missingRent||failedGeneration);
    const base='/api/records/'+record.id+'/download/';
    const preview=hasPdf?base+'pdf?inline=1&r='+record.revision+'&final='+!!record.approval:'';
    if(preview){if($('pdf-preview').getAttribute('src')!==preview)$('pdf-preview').src=preview;}else $('pdf-preview').removeAttribute('src');
    $('report-pages').textContent=record.artifacts?.page_count?record.artifacts.page_count+' pages':'Saved PDF';
    $('downloads').innerHTML=hasPdf?`<a class="button" href="${base}pdf">Download ${record.approval?'reviewed':'draft'} PDF</a><a class="button secondary" target="_blank" href="${base}pdf?inline=1">Open PDF</a><a class="small" href="${base}cashflow_png">Cash-flow image</a>${record.artifacts.calculations_png?`<a class="small" href="${base}calculations_png">Calculation sheet</a>`:''}<a class="small" href="${base}cashflow_csv">Full CSV</a>`:'';
    $('revision-result').textContent=revisionResults.get(record.id)||'';
    $('finalize').textContent=record.approval?'Download final PDF':'Approve & finalize';
  }
  function render(){
    $('record').hidden=false;
    const enquiry=record.inputs.enquiry||{};
    const area=enquiry.kind==='area';
    $('record-title').textContent=area?enquiry.area:record.inputs.property.address;
    if(area){
      const money=new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP',maximumFractionDigits:0});
      const consent=record.consent||enquiry;
      $('area-details').textContent=[
        'Purchase budget: '+money.format(enquiry.budget),
        'Contact: '+record.inputs.investor.name+' · '+record.inputs.investor.email,
        'Purpose: '+({buy:'Considering a purchase',viewing:'Arranging a viewing',comparison:'Comparing investments',client:'Research for a client'}[enquiry.purpose]||enquiry.purpose),
        'Goal: '+record.inputs.investor.goal,
        record.inputs.investor.notes?'Notes: '+record.inputs.investor.notes:'',
        'Feedback call: '+(consent.feedback_call?'May contact':'Not opted in'),
        'Testimonial request: '+(consent.testimonial_contact?'May contact later':'Not opted in')
      ].filter(Boolean).join('\n\n');
    }
    $('record-subtitle').textContent=record.inputs.property.postcode+' · '+(record.inputs.investor.name||'Client');
    $('json-link').href='/api/records/'+record.id+'/download/json';
    $('generate').textContent=record.status==='running'?'Working…':'Generate report';
    $('additional-info').value=additionalNotes.get(record.id)??record.inputs.analyst_notes??'';
    renderReport();renderPhotos();
    if(record.status==='running')poll();
  }
  async function open(id){
    clearTimeout(pollTimer);record=await api('/api/records/'+id);$('revision-instruction').value=instructions.get(id)||'';render();remember(id);history.replaceState(null,'','/review?id='+id);await list();
  }
  async function openLast(records,requestedId){
    const selected=records.find(r=>r.id===requestedId)||records.find(r=>r.id===lastOpened)||records[0];
    if(selected)await open(selected.id);
    else{remember(null);history.replaceState(null,'','/review');}
  }
  function finishRevision(){
    if(record.job?.kind!=='revise')return;
    if(record.job.state==='done'){
      $('revision-instruction').value='';instructions.delete(record.id);
      revisionResults.set(record.id,record.edit_history?.at(-1)?.message||'');
    }else if(record.job.state==='failed')revisionResults.set(record.id,record.job.message);
  }
  function poll(){
    clearTimeout(pollTimer);const id=record.id;
    pollTimer=setTimeout(async()=>{try{
      const latest=await api('/api/records/'+id);if(record?.id!==id)return;record=latest;
      if(record.status==='running')poll();
      else{
        finishRevision();
        render();await list();if(record.job?.state==='failed'&&record.job.kind!=='revise')message(record.job.message);
      }
    }catch(e){message(e.message);if(record?.id===id)poll();}},1200);
  }
  async function pipeline(){
    await post('/api/records/'+record.id+'/pipeline',{revision:record.revision,provider:record.mode==='demo'?'none':config.default_provider||'none',analyst_notes:$('additional-info').value,refresh_evidence:record.status==='needs_input'});
    record=await api('/api/records/'+record.id);additionalNotes.delete(record.id);render();
  }
  async function savePhotos(){
    const d=draft();if(!d.dirty)return;
    const payload=new FormData();payload.set('revision',record.revision);
    payload.set('keep_cover',d.cover&&!(d.cover instanceof File)?d.cover.filename:'');
    if(d.cover instanceof File)payload.append('cover',d.cover);
    payload.set('keep_gallery',JSON.stringify(d.gallery.filter(p=>!(p instanceof File)).map(p=>p.filename)));
    d.gallery.filter(p=>p instanceof File).forEach(file=>payload.append('gallery',file));
    const updated=await api('/api/records/'+record.id+'/photos',{method:'POST',body:payload});
    release(d.cover);d.gallery.forEach(release);drafts.delete(record.id);record=updated;render();
  }
  function action(fn,target='system'){return async event=>{
    event?.preventDefault();if(working)return;working=true;controls();
    try{await fn(event);}catch(e){message(e.message,target);}finally{working=false;if(record)renderPhotos();else controls();}
  };}
  async function deleteRecord(id){
    const target=record?.id===id?record:await api('/api/records/'+id);
    if(target.status==='running')throw Error('Wait for this property to finish processing before deleting it.');
    if(!window.confirm(`Delete “${target.inputs.enquiry?.kind==='area'?target.inputs.enquiry.area:target.inputs.property.address}” and its reports, photos and data?`))return;
    await api('/api/records/'+id,{method:'DELETE',body:JSON.stringify({revision:target.revision})});
    const photos=drafts.get(id);if(photos){release(photos.cover);photos.gallery.forEach(release);}
    drafts.delete(id);instructions.delete(id);revisionResults.delete(id);additionalNotes.delete(id);
    if(record?.id===id){
      clearTimeout(pollTimer);record=null;remember(null);$('record').hidden=true;$('report-status').hidden=true;
      $('report-status').textContent='';$('pdf-preview').removeAttribute('src');
      $('revision-instruction').value='';$('additional-info').value='';
    }
    const records=await list();if(!record)await openLast(records);
  }
  $('records').addEventListener('click',action(async e=>{
    const remove=e.target.closest('[data-delete-record]');if(remove)return deleteRecord(remove.dataset.deleteRecord);
    const button=e.target.closest('[data-record]');if(button)await open(button.dataset.record);
  }));
  $('additional-info').addEventListener('input',()=>{
    if(!record)return;
    const value=$('additional-info').value;
    if(value===(record.inputs.analyst_notes||''))additionalNotes.delete(record.id);
    else additionalNotes.set(record.id,value);
  });
  $('generate').addEventListener('click',action(async()=>{await savePhotos();await pipeline();},'generation'));
  $('delete-record').addEventListener('click',action(()=>deleteRecord(record.id)));
  $('delete-area').addEventListener('click',action(()=>deleteRecord(record.id)));
  $('photo-form').addEventListener('submit',action(async()=>{if(!record?.artifacts?.pdf)return;await savePhotos();await list();}));
  for(const role of ['cover','gallery']){
    const input=$(role+'-photo-input'),zone=input.closest('[data-photo-zone]');let depth=0;
    input.addEventListener('change',()=>{try{choosePhotos(role,input.files);}catch(e){message(e.message);}finally{input.value='';}});
    zone.addEventListener('dragenter',e=>{e.preventDefault();depth++;if(!busy())zone.classList.add('drag-over');});
    zone.addEventListener('dragover',e=>{e.preventDefault();if(e.dataTransfer)e.dataTransfer.dropEffect=busy()?'none':'copy';});
    zone.addEventListener('dragleave',e=>{e.preventDefault();if(--depth<=0)zone.classList.remove('drag-over');});
    zone.addEventListener('drop',e=>{e.preventDefault();depth=0;zone.classList.remove('drag-over');try{choosePhotos(role,e.dataTransfer.files);}catch(error){message(error.message);}});
  }
  $('photo-form').addEventListener('click',e=>{
    const button=e.target.closest('[data-remove-photo]');if(!button||busy())return;
    const d=draft();if(button.dataset.removePhoto==='cover'){release(d.cover);d.cover=null;}else release(d.gallery.splice(Number(button.dataset.index),1)[0]);
    d.dirty=true;renderPhotos();
  });
  $('revision-instruction').addEventListener('input',()=>{
    if(record)instructions.set(record.id,$('revision-instruction').value);
    controls();
  });
  $('revision-form').addEventListener('submit',action(async()=>{
    message('','revision-result');
    await savePhotos();
    await post('/api/records/'+record.id+'/revise',{revision:record.revision,provider:config.default_provider||'none',instruction:$('revision-instruction').value});
    record=await api('/api/records/'+record.id);
    finishRevision();
    render();
  },'revision-result'));
  $('finalize').addEventListener('click',action(async()=>{
    const reason=finalizationBlock();if(reason)throw Error(reason);
    if(!record.approval){
      $('finalize').textContent='Finalizing…';
      try{
        record=await post('/api/records/'+record.id+'/approve',{revision:record.revision,reviewer:'Local analyst',notes:'',acknowledged:true});
      }finally{renderReport();}
    }
    const link=document.createElement('a');link.href='/api/records/'+record.id+'/download/pdf';link.download='';document.body.appendChild(link);link.click();link.remove();
    await list();
  }));
  window.addEventListener('beforeunload',event=>{if(additionalNotes.size||[...drafts.values()].some(d=>d.dirty)){event.preventDefault();event.returnValue='';}});
  async function init(){
    try{
      config=await api('/api/config');
      await openLast(await list(),new URLSearchParams(location.search).get('id'));
      setInterval(()=>{
        if(!document.hidden&&!working)list().then(records=>{if(!record&&!working&&records.length)return openLast(records);}).catch(()=>{});
      },5000);
    }catch(e){message('Could not load the local dashboard: '+e.message);}
  }
  init();
})();

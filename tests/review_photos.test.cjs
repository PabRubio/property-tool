const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'../web/assets/review.js'),'utf8');
const id='a'.repeat(32);

async function dashboard(overrides={}){
  const elements=new Map(),warnings=[],uploads=[],edits=[];
  let server={id,revision:1,status:'ready_for_review',mode:'demo',photos:[],
    inputs:{enquiry:{kind:'property'},property:{address:'12 Example Road',postcode:'M1 1AA'},investor:{name:'Test investor'}},
    analysis:{available:true},artifacts:{pdf:'original.pdf',page_count:10},approval:null,...overrides};
  let rejectUpload=false;
  let token='test',rejectToken=false,editRaces=0,editFailure=null;
  function element(key){
    if(!elements.has(key))elements.set(key,{id:key,value:'',textContent:'',innerHTML:'',files:[],hidden:false,disabled:false,
      handlers:{},attributes:{},classList:{add(){},remove(){},toggle(){}},
      addEventListener(name,fn){this.handlers[name]=fn;},
      setAttribute(name,value){this.attributes[name]=value;},getAttribute(name){return this.attributes[name]??this[name];},
      removeAttribute(name){delete this.attributes[name];delete this[name];},
      closest(){return element(key+'-zone');}});
    return elements.get(key);
  }
  const response=(data,status=200)=>({ok:status<400,status,json:async()=>structuredClone(data)});
  const fetch=async(url,options={})=>{
    if(url==='/api/config')return response({token,default_provider:'codex'});
    if(url==='/api/records')return response({records:[{id,address:'12 Example Road',postcode:'M1 1AA',status:server.status}]});
    if(url==='/api/records/'+id)return response(server);
    if(url==='/api/records/'+id+'/revise'){
      const body=JSON.parse(options.body);edits.push(body);
      if(rejectToken||options.headers['X-Local-Token']!==token)return response({error:'Refresh the local page before saving'},403);
      if(editRaces>0){editRaces--;server={...server,revision:server.revision+1};}
      if(body.revision!==server.revision)return response({error:'This record changed. Refresh it before saving.'},400);
      if(['running','checking_inputs'].includes(server.status))return response({error:'An operation is already running for this property'},400);
      if(editFailure)return response({error:editFailure},400);
      server={...server,revision:server.revision+1,job:{kind:'revise',state:'done'},
        edit_history:[{message:'Edit applied'}],artifacts:{...server.artifacts,pdf:'edited.pdf'}};
      return response({id,status:'running'},202);
    }
    assert.equal(url,'/api/records/'+id+'/photos','Only local photo API requests are expected');
    assert.equal(options.method,'POST');
    const form=options.body;uploads.push(form);
    if(rejectUpload)return response({error:'Mock photo failure'},400);
    if(Number(form.get('revision'))!==server.revision)return response({error:'This record changed. Refresh it before saving.'},400);
    const next=[];
    if(form.get('keep_cover'))next.push(server.photos.find(p=>p.filename===form.get('keep_cover')));
    if(form.get('cover'))next.push({filename:'cover-'+(server.revision+1)+'.jpg',role:'cover'});
    for(const name of JSON.parse(form.get('keep_gallery')))next.push(server.photos.find(p=>p.filename===name));
    form.getAll('gallery').forEach((file,index)=>next.push({filename:'gallery-'+(server.revision+1)+'-'+index+'.jpg',role:'gallery'}));
    server={...server,revision:server.revision+1,photos:next,
      artifacts:{...server.artifacts,pdf:'updated-'+(server.revision+1)+'.pdf'}};
    return response(server);
  };
  vm.runInNewContext(source,{document:{getElementById:element,querySelectorAll:()=>[],hidden:false},
    window:{addEventListener(){}},history:{replaceState(){}},location:{search:'?id='+id},
    localStorage:{getItem(){return null;},setItem(){},removeItem(){}},
    fetch,File,FormData,URL,URLSearchParams,setTimeout,clearTimeout,setInterval:()=>0,
    console:{warn:text=>warnings.push(text)}});
  await until(()=>element('record-title').textContent==='12 Example Road');
  return {element,uploads,warnings,edits,get server(){return server;},
    restart(){token='new-session-token';},
    rejectTokens(){rejectToken=true;},
    raceEdits(count){editRaces=count;},
    failEdit(message){editFailure=message;},
    async edit(instruction='Make the summary shorter.'){
      element('revision-instruction').value=instruction;element('revision-instruction').handlers.input();
      await element('revision-form').handlers.submit({preventDefault(){}});
    },
    advance(changes={}){server={...server,...changes,revision:server.revision+1};},
    reject(value){rejectUpload=value;},
    choose(role,count=1){
      const input=element(role+'-photo-input');
      input.files=Array.from({length:count},(_,index)=>new File(['fixture'],role+index+'.png',{type:'image/png'}));
      input.handlers.change();
    },
    remove(role,index=0){element('photo-form').handlers.click({target:{closest:()=>({dataset:{removePhoto:role,index:String(index)}})}});}};
}

async function until(condition){
  for(let i=0;i<100;i++){
    await new Promise(resolve=>setTimeout(resolve,5));
    if(condition())return;
  }
  assert.fail('Dashboard action did not complete');
}

test('selecting and removing photos saves automatically and refreshes the PDF',async()=>{
  const ui=await dashboard();
  ui.choose('cover');await until(()=>ui.server.revision===2);
  assert.equal(ui.server.photos[0].role,'cover');
  assert.match(ui.element('pdf-preview').getAttribute('src'),/updated-2.pdf/);
  ui.choose('gallery',2);await until(()=>ui.server.revision===3);
  assert.equal(ui.server.photos.length,3);
  ui.remove('gallery');await until(()=>ui.server.revision===4);
  assert.equal(ui.server.photos.length,2);
  ui.remove('cover');await until(()=>ui.server.revision===5);
  assert.deepEqual(ui.server.photos.map(p=>p.role),['gallery']);
  assert.equal(ui.uploads.length,4);
  assert.deepEqual(ui.warnings,[]);
});

test('an older tab fetches the latest report revision while retaining selected files',async()=>{
  const ui=await dashboard();
  ui.advance();ui.advance();
  ui.choose('cover');await until(()=>ui.server.revision===4);
  assert.equal(ui.uploads.length,1);
  assert.equal(ui.uploads[0].get('revision'),'3');
  assert.equal(ui.uploads[0].get('cover').name,'cover0.png');
  assert.deepEqual(ui.warnings,[]);
});

test('concurrent photo changes are protected from overwrite',async()=>{
  const ui=await dashboard();
  ui.advance({photos:[{filename:'another-tab.jpg',role:'cover'}]});
  ui.choose('cover');await until(()=>ui.warnings.length>0);
  assert.equal(ui.uploads.length,0);
  assert.equal(ui.server.photos[0].filename,'another-tab.jpg');
  assert.match(ui.warnings[0],/Photos changed in another tab/);
});

test('a failed automatic upload preserves the displayed report and chosen photo',async()=>{
  const ui=await dashboard();ui.reject(true);
  ui.choose('cover');await until(()=>ui.warnings.length>0);
  assert.equal(ui.server.revision,1);
  assert.match(ui.element('pdf-preview').getAttribute('src'),/original.pdf/);
  assert.match(ui.element('cover-photo-preview').innerHTML,/blob:/);
  ui.reject(false);ui.choose('cover');await until(()=>ui.server.revision===2);
  assert.equal(ui.server.photos.length,1);
});

test('a saved incomplete PDF stays in review without reopening draft controls or the research warning',async()=>{
  const ui=await dashboard({status:'needs_input',analysis:{available:false}});
  assert.equal(ui.element('draft-controls').hidden,true);
  assert.equal(ui.element('run-panel').hidden,true);
  assert.equal(ui.element('generation-error').textContent,'');
  assert.equal(ui.element('generation-error').hidden,true);
  assert.equal(ui.element('review-approval').hidden,false);
  assert.equal(ui.element('photo-panel').hidden,false);
  assert.match(ui.element('pdf-preview').getAttribute('src'),/original.pdf/);
  assert.equal(ui.element('finalize').disabled,true);
  assert.deepEqual(ui.warnings,[]);
});

test('a fresh brief still shows its input check and generation controls',async()=>{
  const ui=await dashboard({status:'draft',analysis:{},artifacts:{},
    preflight:{status:'clear',summary:'No material mistakes found.'}});
  assert.equal(ui.element('draft-controls').hidden,false);
  assert.equal(ui.element('run-panel').hidden,false);
  assert.equal(ui.element('generation-error').textContent,'Submission check: No material mistakes found.');
  assert.equal(ui.element('review-approval').hidden,true);
  assert.equal(ui.element('generate').disabled,false);
  assert.deepEqual(ui.warnings,[]);
});

test('AI edits refresh the session token after a server restart without losing the instruction',async()=>{
  const ui=await dashboard();ui.restart();await ui.edit('Add cited transport links.');
  assert.equal(ui.server.revision,2);
  assert.equal(ui.edits.length,2);
  assert.ok(ui.edits.every(edit=>edit.instruction==='Add cited transport links.'));
  assert.equal(ui.element('revision-result').textContent,'Edit applied');
});

test('AI edits fetch the latest report version before submitting',async()=>{
  const ui=await dashboard();ui.advance();ui.advance();await ui.edit();
  assert.equal(ui.server.revision,4);
  assert.equal(ui.edits.length,1);
  assert.equal(ui.edits[0].revision,3);
});

test('one revision race is recovered without submitting the accepted edit twice',async()=>{
  const ui=await dashboard();ui.raceEdits(1);await ui.edit();
  assert.equal(ui.server.revision,3);
  assert.equal(ui.edits.length,2);
  assert.equal(ui.element('revision-result').textContent,'Edit applied');
});

test('repeated revision conflicts stop and keep the typed instruction',async()=>{
  const ui=await dashboard();ui.raceEdits(2);await ui.edit('Keep this request.');
  assert.equal(ui.edits.length,2);
  assert.equal(ui.element('revision-instruction').value,'Keep this request.');
  assert.match(ui.element('revision-result').textContent,/changed again.*try again/i);
  assert.equal(ui.server.job,undefined);
});

test('persistent authentication failures stop after one token refresh',async()=>{
  const ui=await dashboard();ui.rejectTokens();await ui.edit('Keep this request.');
  assert.equal(ui.edits.length,2);
  assert.equal(ui.element('revision-instruction').value,'Keep this request.');
  assert.equal(ui.server.revision,1);
});

test('an already-running operation and unrelated failures never retry an edit',async()=>{
  const ui=await dashboard();ui.advance({status:'running'});await ui.edit();
  assert.equal(ui.edits.length,0);
  assert.match(ui.element('revision-result').textContent,/already running|finish/i);
  const other=await dashboard();other.failEdit('Mock provider failure');await other.edit();
  assert.equal(other.edits.length,1);
  assert.equal(other.element('revision-result').textContent,'Mock provider failure');
});

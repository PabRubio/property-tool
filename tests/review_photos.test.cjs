const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'../web/assets/review.js'),'utf8');
const id='a'.repeat(32);

async function dashboard(){
  const elements=new Map(),warnings=[],uploads=[];
  let server={id,revision:1,status:'ready_for_review',mode:'demo',photos:[],
    inputs:{enquiry:{kind:'property'},property:{address:'12 Example Road',postcode:'M1 1AA'},investor:{name:'Test investor'}},
    analysis:{available:true},artifacts:{pdf:'original.pdf',page_count:10},approval:null};
  let rejectUpload=false;
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
    if(url==='/api/config')return response({token:'test',default_provider:'none'});
    if(url==='/api/records')return response({records:[{id,address:'12 Example Road',postcode:'M1 1AA',status:server.status}]});
    if(url==='/api/records/'+id)return response(server);
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
  await until(()=>element('pdf-preview').getAttribute('src')?.includes('original.pdf'));
  return {element,uploads,warnings,get server(){return server;},
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

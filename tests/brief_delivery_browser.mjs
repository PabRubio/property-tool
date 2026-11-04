import assert from 'node:assert/strict';
import {existsSync, readFileSync, writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

const [debugPort, sitePort, directory, root] = process.argv.slice(2);
const base = `http://127.0.0.1:${sitePort}/`;
const tabs = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
const ws = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener('open', resolve, {once: true}));
let sequence = 0;
const pending = new Map();
let pageLoaded=null;
function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, {resolve, reject});
    ws.send(JSON.stringify({id, method, params}));
  });
}
ws.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (!message.id) {
    if(message.method==='Page.loadEventFired'&&pageLoaded){pageLoaded();pageLoaded=null;}
    return;
  }
  const request = pending.get(message.id);
  pending.delete(message.id);
  message.error ? request.reject(message.error) : request.resolve(message.result);
});
async function evaluate(expression) {
  const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
  if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
}
async function until(expression) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw Error('Timed out: ' + expression);
}
async function navigate(url) {
  const loaded=new Promise(resolve=>{pageLoaded=resolve;});
  const navigation=await command('Page.navigate', {url});
  if(!navigation.loaderId)await command('Page.reload');
  let timeout;
  try{await Promise.race([loaded,new Promise((_,reject)=>{timeout=setTimeout(()=>reject(Error('Page load timed out: '+url)),15000);})]);}
  finally{clearTimeout(timeout);}
  await until(`document.readyState==='complete' && document.getElementById('submit-brief')`);
}
async function fixture(area = false) {
  await evaluate(`(() => {
    const f=document.getElementById('brief-form');
    f.elements.area_only.checked=${area};
    const values={name:'Test <&> investor',email:'investor@example.com',address:'12 Example Road',postcode:'M1 1AA',property_type:'terraced_house',bedrooms:'2',price_status:'asking',asking_price:'£250,000',financing:'cash',buyer_type:'individual',additional_property:'no',uk_resident:'yes',monthly_rent:'£1,500',area:'Manchester',budget:'£300,000'};
    // Use the existing non-unknown price option rather than assuming its internal value.
    values.price_status=[...f.elements.price_status.options].find(option=>option.value!=='unknown').value;
    for(const [key,value] of Object.entries(values))f.elements[key].value=value;
    f.elements.notes.value=${JSON.stringify('Quotes: "hello", symbols: <&>, pounds: £, accents: Muñoz, emoji: 🏡\nSecond line. '+ 'x'.repeat(7800))};
    f.elements.england.checked=true;f.elements.terms_accepted.checked=true;
    f.dispatchEvent(new Event('change',{bubbles:true}));
    if(!f.reportValidity())throw Error('Invalid test fixture: '+[...f.elements].filter(el=>el.validity&&!el.validity.valid).map(el=>el.name));
  })()`);
}
async function captured() {
  return evaluate(`(async()=>{
    const sent=window.__sent[window.__sent.length-1];if(!sent)return null;
    const fields=Object.fromEntries([...sent.data].filter(([,value])=>typeof value==='string'));
    const file=sent.data.get('attachment');
    return {action:sent.action,method:sent.method,enctype:sent.enctype,fields,
      attachment:file instanceof File?{name:file.name,type:file.type,text:await file.text()}:null};
  })()`);
}
try {
  await command('Page.enable');
  await command('Runtime.enable');
  await command('Network.enable');
  // No real submissions, email, fonts, analytics or CDN requests leave this test.
  await command('Network.setBlockedURLs', {urls:['https://*','http://forms.un-static.com/*']});
  await command('Browser.setDownloadBehavior', {behavior:'allow',downloadPath:directory});
  await command('Page.addScriptToEvaluateOnNewDocument', {source:`
    window.__sent=[];
    HTMLFormElement.prototype.submit=function(){
      window.__sent.push({action:this.action,method:this.method,enctype:this.enctype,data:new FormData(this)});
    };
  `});
  await navigate(base+'#contact');
  await evaluate(`document.getElementById('submit-brief').click()`);
  assert.equal(await evaluate('window.__sent.length'),0,'Invalid briefs must not be sent');
  await fixture();
  await evaluate(`document.getElementById('export-brief').click()`);
  for(let attempt=0;attempt<100&&!existsSync(directory+'/investor-brief.json');attempt++)await new Promise(resolve=>setTimeout(resolve,50));
  const downloadedText=readFileSync(directory+'/investor-brief.json','utf8');
  const downloaded=JSON.parse(downloadedText);
  await evaluate(`document.getElementById('submit-brief').click()`);
  const property=await captured();
  assert.ok(property,'Submitting a valid brief must hand the JSON text to Un-static');
  assert.equal(property.action,'https://forms.un-static.com/forms/ac1ba609175f688c47e9908a6e4d9060d24ecf30');
  assert.equal(property.method,'post');assert.equal(property.enctype,'application/x-www-form-urlencoded');
  assert.equal(property.attachment,null,'Account-free submission must not upload a file');
  assert.deepEqual(Object.keys(property.fields),['message'],'Submit only the JSON text, without duplicated contact fields or provider metadata');
  const brief=JSON.parse(property.fields.message);
  assert.equal(brief.schema_version,2);
  assert.equal(brief.inputs.property.asking_price,250000);
  assert.equal(brief.inputs.assumptions.monthly_rent,1500);
  assert.equal(brief.inputs.investor.name,'Test <&> investor');
  assert.equal(brief.inputs.investor.email,'investor@example.com');
  assert.equal(brief.inputs.investor.notes,'Quotes: "hello", symbols: <&>, pounds: £, accents: Muñoz, emoji: 🏡\nSecond line. '+ 'x'.repeat(7800));
  assert.equal(property.fields.message,downloadedText,'The email field must contain exactly the exported JSON');
  assert.deepEqual(brief,downloaded);
  writeFileSync(directory+'/property-brief.json',property.fields.message);
  assert.equal(await evaluate(`document.getElementById('brief-entry').hidden`),false,'Sending alone must not show success');
  assert.equal(await evaluate(`document.getElementById('brief-success').hidden`),true);
  assert.ok(await evaluate(`sessionStorage.getItem('property-screening:brief-draft:v1')`),'Keep draft before confirmation');
  await evaluate(`document.getElementById('brief-form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))`);
  assert.equal(await evaluate('window.__sent.length'),1,'Duplicate submission while navigating is blocked');
  await navigate(base+'?submitted=1#contact');
  assert.equal(await evaluate(`document.getElementById('brief-success').hidden`),false,'The configured return from Un-static must show confirmation');
  assert.equal(await evaluate(`document.getElementById('brief-entry').hidden`),true);
  assert.equal(await evaluate(`sessionStorage.getItem('property-screening:brief-draft:v1')`),null,'Clear draft after confirmation');
  assert.equal(await evaluate(`new URL(location.href).searchParams.has('submitted')`),false,'Remove one-use return marker');
  await navigate(base+'?submitted=1#contact');
  assert.equal(await evaluate(`document.getElementById('brief-success').hidden`),true,'A bare or reused return URL must not claim success');

  await navigate(base+'#contact');await fixture(true);
  await evaluate(`document.getElementById('submit-brief').click()`);
  const area=await captured();
  const areaBrief=JSON.parse(area.fields.message);
  assert.equal(areaBrief.inputs.enquiry.kind,'area');assert.equal(areaBrief.inputs.enquiry.area,'Manchester');
  assert.equal(areaBrief.inputs.enquiry.budget,300000);assert.deepEqual(areaBrief.inputs.property,{});
  assert.deepEqual(areaBrief.inputs.assumptions,{});
  writeFileSync(directory+'/area-brief.json',area.fields.message);
  // Simulate Back after a provider error/cancelled captcha, including BFCache pageshow.
  await evaluate(`dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))`);
  assert.equal(await evaluate(`document.getElementById('submit-brief').disabled`),false);
  assert.equal(await evaluate(`document.getElementById('brief-form').elements.area.value`),'Manchester');
  await evaluate(`document.getElementById('submit-brief').click()`);
  const departed=await command('Page.navigate',{url:base+'provider-error'});
  await until(`location.pathname==='/provider-error'&&document.readyState==='complete'`);
  const history=await command('Page.getNavigationHistory');
  await command('Page.navigateToHistoryEntry',{entryId:history.entries[history.currentIndex-1].id});
  await until(`location.href===${JSON.stringify(base+'#contact')}&&document.getElementById('submit-brief')&&!document.getElementById('submit-brief').disabled`);
  assert.equal(await evaluate(`document.getElementById('brief-form').elements.area.value`),'Manchester','Actual Back navigation must retain answers');
  assert.equal(await evaluate(`document.getElementById('brief-success').hidden`),true);
  await navigate(base+'?submitted=1#contact');
  assert.equal(await evaluate(`document.getElementById('brief-success').hidden`),true,'Back after cancellation must invalidate the pending return');
  assert.equal(await evaluate(`document.getElementById('brief-form').elements.area.value`),'Manchester');
  await navigate(base+'?brief=unrelated#contact');
  assert.equal(await evaluate(`document.getElementById('brief-success').hidden`),true,'An unrelated return marker cannot report success');
  assert.equal(await evaluate(`document.getElementById('brief-form').elements.area.value`),'Manchester');

  await fixture();
  await evaluate(`window.DataTransfer=undefined;document.getElementById('submit-brief').click()`);
  assert.equal(await evaluate('window.__sent.length'),1,'Text delivery must work without file attachment APIs');
  assert.deepEqual(Object.keys((await captured()).fields),['message']);
  await navigate(base+'#contact');await fixture();
  await evaluate(`HTMLFormElement.prototype.submit=function(){throw Error('Submission unavailable')};document.getElementById('submit-brief').click()`);
  assert.equal(await evaluate('window.__sent.length'),0);
  assert.equal(await evaluate(`document.getElementById('brief-error').hidden`),false);
  assert.equal(await evaluate(`document.getElementById('submit-brief').disabled`),false);
  assert.ok(await evaluate(`sessionStorage.getItem('property-screening:brief-draft:v1')`));
  await navigate(base+'?submitted=1#contact');
  assert.equal(await evaluate(`document.getElementById('brief-success').hidden`),true,'A failed dispatch must not leave a pending success');
  await navigate(base+'#contact');await fixture(true);
  await evaluate(`Storage.prototype.setItem=function(){throw Error('Storage blocked')};document.getElementById('submit-brief').click()`);
  const withoutStorage=await captured();assert.ok(withoutStorage.fields.message,'Storage restrictions must not block delivery');
  assert.deepEqual(Object.keys(withoutStorage.fields),['message']);
  await navigate(base+'?submitted=1#contact');
  assert.equal(await evaluate(`document.getElementById('brief-success').hidden`),true,'An untracked return must not claim success');
  assert.ok(await evaluate(`sessionStorage.getItem('property-screening:brief-draft:v1')`),'An untracked return must not clear the draft');

  await navigate(pathToFileURL(root+'/web/public/index.html').href+'#contact');await fixture();
  await evaluate(`document.getElementById('submit-brief').click()`);
  assert.equal(await evaluate('window.__sent.length'),0,'Local file preview must explain that submissions need HTTP(S)');
  assert.equal(await evaluate(`document.getElementById('brief-error').hidden`),false);
  assert.equal(await evaluate(`document.getElementById('brief-success').hidden`),true);
  console.log('PASS: validation, JSON text/export equality, property/area briefs, confirmation, duplicate prevention, retry, draft retention and preview fallback. No email was sent.');
} finally {
  // Orderly browser shutdown waits for profile writers before Python removes it.
  await command('Browser.close');
  ws.close();
}

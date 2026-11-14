import assert from 'node:assert/strict';
import {existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync} from 'node:fs';
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
async function fixture(area = false, asset = 'residential', type = 'terraced_house') {
  await evaluate(`(() => {
    const f=document.getElementById('brief-form');
    f.elements.area_only.checked=${area};
    f.elements.asset_class.value=${JSON.stringify(asset)};
    f.dispatchEvent(new Event('change',{bubbles:true}));
    const values={name:'Test <&> investor',email:'investor@example.com',address:'12 Example Road',postcode:'M1 1AA',property_type:${JSON.stringify(type)},bedrooms:'2',price_status:'asking',asking_price:'£250,000',financing:'cash',buyer_type:'individual',additional_property:'no',uk_resident:'yes',monthly_rent:'£1,500',area:'Manchester',budget:'£300,000',annual_rent:'£24,000',occupancy:'let',floor_area_basis:${JSON.stringify(type==='offices'?'nia':'gia')},floor_area_sqm:'150',lease_remaining_months:'60',break_month:'36',rent_review_month:'24',rent_review_annual_rent:'£26,000',rent_free_months:'3',reletting_void_months:'6',reletting_annual_rent:'£25,000',business_rates_annual:'£8,000',rates_relief_months:'0',purchase_vat_pct:'20',purchase_vat_recoverable_pct:'50',vat_recovery_month:'3',repair_responsibility:'tenant',insurance_responsibility:'landlord',rent_vat_status:'exclusive',use_class:'E',lease_years:'99'};
    // Use the existing non-unknown price option rather than assuming its internal value.
    values.price_status=[...f.elements.price_status.options].find(option=>option.value!=='unknown').value;
    for(const [key,value] of Object.entries(values))f.elements[key].value=value;
    f.elements.notes.value=${JSON.stringify('Quotes: "hello", symbols: <&>, pounds: £, accents: Muñoz, emoji: 🏡\nSecond line. '+ 'x'.repeat(7800))};
    f.elements.england.checked=true;f.elements.terms_accepted.checked=true;f.elements.single_unit.checked=true;
    f.dispatchEvent(new Event('change',{bubbles:true}));
    if(!f.reportValidity())throw Error('Invalid test fixture: '+[...f.elements].filter(el=>el.validity&&!el.validity.valid).map(el=>el.name));
  })()`);
}
async function downloadBrief() {
  const file=directory+'/investor-brief.json';
  if(existsSync(file))unlinkSync(file);
  await evaluate(`document.getElementById('export-brief').click()`);
  for(let attempt=0;attempt<100&&!existsSync(file);attempt++)await new Promise(resolve=>setTimeout(resolve,50));
  return readFileSync(file,'utf8');
}
async function screenshot(name,width) {
  const folder='/tmp/lacewing-public-commercial-screenshots';mkdirSync(folder,{recursive:true});
  await command('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:width<500});
  await evaluate('document.fonts.ready');
  await until(`getComputedStyle(document.getElementById('pre')).visibility==='hidden'`);
  await evaluate('scrollTo(0,0)');
  assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,'Form must fit viewport '+width);
  const capture=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width,height:await evaluate('document.documentElement.scrollHeight'),scale:1}});
  writeFileSync(folder+'/'+name+'.png',Buffer.from(capture.data,'base64'));
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
  assert.equal(await evaluate(`!!document.getElementById('brief-form').elements.asset_class`),true,'Public form must offer residential and commercial investments');
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

  await navigate(base+'#contact');
  for(const invalid of [
    {rent_review_month:''},{rent_review_annual_rent:''},
    {reletting_void_months:''},{reletting_annual_rent:''},
    {purchase_vat_pct:'0'},{purchase_vat_pct:''},{vat_recovery_month:''},
  ]){
    await fixture(false,'commercial','offices');
    await evaluate(`(()=>{const f=document.getElementById('brief-form');for(const [key,value] of Object.entries(${JSON.stringify(invalid)})){f.elements[key].value=value;f.elements[key].dispatchEvent(new Event('input',{bubbles:true}));}document.getElementById('submit-brief').click();})()`);
    assert.equal(await evaluate('window.__sent.length'),0,'Incomplete commercial terms must not be emailed: '+JSON.stringify(invalid));
    assert.equal(await evaluate(`document.getElementById('brief-form').checkValidity()`),false);
  }
  await fixture(false,'commercial','offices');
  await evaluate(`(()=>{const f=document.getElementById('brief-form');for(const key of ['rent_review_month','rent_review_annual_rent','reletting_void_months','purchase_vat_recoverable_pct'])f.elements[key].value='0';f.elements.purchase_vat_pct.value='';f.elements.vat_recovery_month.value='';f.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  const zeroes=JSON.parse(await downloadBrief()).inputs.assumptions;
  assert.equal(zeroes.rent_review_month,0);assert.equal(zeroes.rent_review_annual_rent,0);
  assert.equal(zeroes.reletting_void_months,0);assert.equal(zeroes.purchase_vat_recoverable_pct,0);
  await evaluate(`(()=>{const f=document.getElementById('brief-form');f.elements.rent_review_annual_rent.value='';f.dispatchEvent(new Event('change',{bubbles:true}));f.elements.asset_class.value='residential';f.elements.property_type.value='terraced_house';f.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  assert.equal(await evaluate(`document.getElementById('brief-form').checkValidity()`),true,'Hidden commercial errors must not block residential briefs');
  await fixture(false,'commercial','offices');
  await evaluate(`(()=>{const f=document.getElementById('brief-form');f.elements.reletting_annual_rent.value='';f.dispatchEvent(new Event('change',{bubbles:true}));f.elements.area_only.checked=true;f.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  assert.equal(await evaluate(`document.getElementById('brief-form').checkValidity()`),true,'Hidden commercial errors must not block area enquiries');
  for(const type of ['retail','offices','industrial']){
    await navigate(base+'#contact');await fixture(false,'commercial',type);
    assert.equal(await evaluate(`document.getElementById('brief-form').elements.bedrooms.matches(':disabled')`),true);
    assert.equal(await evaluate(`document.getElementById('brief-form').elements.additional_property.matches(':disabled')`),true);
    if(type==='retail'){
      await evaluate(`document.querySelectorAll('#brief-form details').forEach(el=>el.open=true)`);
      for(const width of [1440,768,390])await screenshot('commercial-'+width,width);
    }
    if(type==='offices'){
      await navigate(base+'#contact');
      assert.equal(await evaluate(`document.getElementById('brief-form').elements.asset_class.value`),'commercial','Commercial drafts survive reload');
      assert.equal(await evaluate(`document.getElementById('brief-form').elements.annual_rent.value`),'£24,000');
      await evaluate(`const basis=document.getElementById('brief-form').elements.floor_area_basis;basis.value='gia';basis.dispatchEvent(new Event('change',{bubbles:true}));document.getElementById('submit-brief').click()`);
      assert.equal(await evaluate('window.__sent.length'),0,'Wrong area basis must not be submitted');
      await fixture(false,'commercial',type);
    }
    const exported=await downloadBrief();
    await evaluate(`document.getElementById('submit-brief').click()`);
    const sent=await captured();assert.ok(sent,'Commercial brief must reach the email transport');
    assert.equal(sent.action,property.action);assert.deepEqual(Object.keys(sent.fields),['message']);
    assert.equal(sent.fields.message,exported,'Commercial email matches JSON export');
    const {inputs}=JSON.parse(sent.fields.message),p=inputs.property,a=inputs.assumptions;
    assert.equal(p.asset_class,'commercial');assert.equal(p.property_type,type);assert.equal(p.bedrooms,null);
    assert.equal(p.floor_area_basis,type==='offices'?'nia':'gia');assert.equal(p.floor_area_sqm,150);
    assert.equal(p.unit_count,1);assert.equal(p.mixed_use,false);assert.equal(p.lease_years,99);
    assert.equal(a.annual_rent,24000);assert.equal(a.lease_remaining_months,60);assert.equal(a.break_month,36);
    assert.equal(a.rent_review_annual_rent,26000);assert.equal(a.reletting_annual_rent,25000);
    assert.equal(a.business_rates_annual,8000);assert.equal(a.purchase_vat_pct,20);assert.equal(a.purchase_vat_recoverable_pct,50);
    assert.equal(a.monthly_rent,undefined);assert.equal(a.additional_property,undefined);assert.equal(a.nonresident,undefined);
    writeFileSync(directory+'/commercial-'+type+'.json',sent.fields.message);
    await navigate(base+'?submitted=1#contact');
    assert.equal(await evaluate(`document.getElementById('brief-success').hidden`),false);
  }
  // Switching back must not leak stale commercial rent, VAT or lease assumptions.
  await navigate(base+'#contact');await fixture(false,'commercial','retail');await fixture();
  const switched=JSON.parse(await downloadBrief()).inputs;
  assert.equal(switched.property.asset_class,'residential');assert.equal(switched.property.bedrooms,2);
  assert.equal(switched.assumptions.monthly_rent,1500);
  for(const key of ['annual_rent','purchase_vat_pct','lease_remaining_months','business_rates_annual'])assert.equal(switched.assumptions[key],undefined);
  await screenshot('residential-390',390);
  // Unknown commercial terms remain absent; do not turn blanks into zeroes.
  await fixture(false,'commercial','industrial');
  await evaluate(`(()=>{const f=document.getElementById('brief-form');for(const key of ['annual_rent','lease_remaining_months','break_month','business_rates_annual','rent_review_month','rent_review_annual_rent','purchase_vat_pct','purchase_vat_recoverable_pct','vat_recovery_month'])f.elements[key].value='';f.elements.floor_area_basis.value='unknown';f.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  const unknown=JSON.parse(await downloadBrief()).inputs;
  assert.equal(unknown.property.floor_area_basis,'unknown');
  for(const key of ['annual_rent','lease_remaining_months','break_month','business_rates_annual','purchase_vat_pct'])assert.equal(unknown.assumptions[key],undefined);

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
  console.log('PASS: residential/area and all commercial types, email/export equality, switching, unknown terms, confirmation, duplicate prevention, retry, draft recovery, responsive screenshots and preview fallback. No email was sent.');
} finally {
  // Orderly browser shutdown waits for profile writers before Python removes it.
  await command('Browser.close');
  ws.close();
}

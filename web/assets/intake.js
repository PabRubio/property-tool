(() => {
  const form=document.getElementById('brief-form'),entry=document.getElementById('brief-entry'),success=document.getElementById('brief-success');
  const $=id=>document.getElementById(id);
  const draftKey='property-screening:brief-draft:v1';
  const numberFields=Array.from(form.querySelectorAll('[data-number]'));
  let token=null,submitting=false;
  function parseNumber(value,kind){
    let text=String(value??'').trim();
    if(!text)return null;
    if(kind==='money')text=text.replace(/^([+-]?)\s*£\s*/,'$1');
    if(kind==='percent')text=text.replace(/\s*%$/,'');
    if(!/^[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)$/.test(text))return NaN;
    if(kind==='money'&&/\.\d{3,}$/.test(text))return NaN;
    return Number(text.replaceAll(',',''));
  }
  function validateNumber(input){
    input.setCustomValidity('');
    if(input.matches(':disabled'))return;
    const value=parseNumber(input.value,input.dataset.number);
    if(value===null){if(input.required)input.setCustomValidity('Please enter an amount.');return;}
    if(!Number.isFinite(value))input.setCustomValidity(input.dataset.number==='money'?'Enter an amount in pounds, such as £1,520.50.':'Enter a percentage, such as 5.5%.');
    else if(value<Number(input.dataset.min)||value>Number(input.dataset.max))input.setCustomValidity('Enter a value between '+input.dataset.min+' and '+input.dataset.max+'.');
  }
  function saveDraft(){
    if(entry.hidden)return;
    const fields={};
    for(const input of form.elements){
      if(!input.name)continue;
      fields[input.name]=input.type==='checkbox'?input.checked:input.value;
    }
    try{sessionStorage.setItem(draftKey,JSON.stringify(fields));}
    catch(e){/* Storage restrictions must not prevent completing the form. */}
  }
  function restoreDraft(){
    try{
      const fields=JSON.parse(sessionStorage.getItem(draftKey)||'null');
      if(!fields||typeof fields!=='object'||Array.isArray(fields))return;
      for(const input of form.elements){
        if(!input.name||!Object.hasOwn(fields,input.name))continue;
        if(input.type==='checkbox'&&typeof fields[input.name]==='boolean')input.checked=fields[input.name];
        else if(input.type!=='checkbox'&&typeof fields[input.name]==='string')input.value=fields[input.name];
      }
    }catch(e){/* A missing or unreadable draft must not prevent a new submission. */}
  }
  function toggle(id,visible){const el=$(id);el.hidden=!visible;el.disabled=!visible;}
  function update(){
    const area=form.elements.area_only.checked;
    toggle('area-fields',area);toggle('property-fields',!area);toggle('investment-fields',!area);
    const mortgage=!area&&form.elements.financing.value==='mortgage';
    toggle('mortgage-fields',mortgage);
    for(const [id,key,visible] of [
      ['deposit-amount-field','deposit_amount',form.elements.deposit_format.value==='amount'],
      ['deposit-percent-field','deposit_pct',form.elements.deposit_format.value==='percent'],
      ['mortgage-term-field','mortgage_term_years',form.elements.repayment_type.value==='repayment'],
      ['reset-rate-field','rate_after_fix_pct',!['unknown','tracker'].includes(form.elements.rate_type.value)]
    ]){$(id).hidden=!visible;form.elements[key].disabled=!mortgage||!visible;}
    const works=form.elements.refurb_level.value!=='none';
    $('refurb-budget-field').hidden=!works;form.elements.refurbishment.disabled=!works;
    $('refurb-finish-field').hidden=!works;form.elements.refurb_finish.disabled=!works;
    const priced=form.elements.price_status.value!=='unknown';
    $('price-field').hidden=!priced;form.elements.asking_price.disabled=!priced;
    const bungalow=form.elements.property_type.value==='bungalow';
    $('attachment-field').hidden=!bungalow;form.elements.building_attachment.disabled=!bungalow;
    if(form.elements.property_type.value==='studio')form.elements.bedrooms.value='0';
    form.elements.bedrooms.readOnly=form.elements.property_type.value==='studio';
    $('submit-brief').textContent=area?'Submit enquiry':'Submit property';
    numberFields.forEach(validateNumber);
  }
  form.addEventListener('input',event=>{if(event.target.matches('[data-number]'))validateNumber(event.target);saveDraft();});
  form.addEventListener('change',()=>{update();saveDraft();});
  form.addEventListener('invalid',event=>{const details=event.target.closest('details');if(details)details.open=true;},true);
  window.addEventListener('pagehide',saveDraft);
  window.addEventListener('pageshow',()=>{$('submit-brief').disabled=false;submitting=false;update();});
  function inputs(){
    const f=new FormData(form),num=k=>{
      const value=f.get(k);
      if(value===null||value.trim()==='')return null;
      return form.elements[k]?.dataset.number?parseNumber(value,form.elements[k].dataset.number):Number(value);
    },checked=k=>f.get(k)==='on';
    const area=checked('area_only'),followUpContact=checked('follow_up_contact');
    const out={enquiry:{kind:area?'area':'property',area:f.get('area')||'',budget:num('budget'),purpose:f.get('purpose'),terms_accepted:checked('terms_accepted'),feedback_call:followUpContact,testimonial_contact:followUpContact},investor:{name:f.get('name'),email:f.get('email'),cash_budget:num('cash_budget'),goal:f.get('goal'),notes:f.get('notes')},property:{},assumptions:{}};
    if(area)return out;
    for(const k of ['address','postcode','property_type','listing_url','construction_date','finish_quality','outdoor_space','tenure','price_status'])out.property[k]=f.get(k);
    for(const k of ['asking_price','bedrooms','bathrooms','floor_area_sqm','off_street_parking','lease_years'])out.property[k]=num(k);
    Object.assign(out.property,{country:'England',new_build:checked('new_build'),building_attachment:f.get('building_attachment')||''});
    Object.assign(out.assumptions,{financing:f.get('financing')==='mortgage'?f.get('repayment_type'):f.get('financing'),buyer_type:f.get('buyer_type'),additional_property:f.get('additional_property')==='yes',nonresident:f.get('uk_resident')!=='yes',refurbishment_planned:f.get('refurb_level')!=='none',refurb_level:f.get('refurb_level'),refurb_finish:f.get('refurb_finish')||'medium',rent_source:f.get('rent_source')||''});
    for(const k of ['deposit_amount','deposit_pct','holding_years','rate_after_fix_pct','regular_cleaning','turnover_cleaning','interest_rate_pct','mortgage_term_years','refurbishment','min_net_yield_pct','min_monthly_cashflow','monthly_rent','legal_fees','survey_fees','service_charge','ground_rent']){if(num(k)!==null)out.assumptions[k]=num(k);}
    if(!out.assumptions.refurbishment_planned)out.assumptions.refurbishment=0;
    if(out.assumptions.financing!=='cash'){
      const rateType=f.get('rate_type');
      out.assumptions.rate_type=['unknown','tracker'].includes(rateType)?rateType:'fixed';
      if(out.assumptions.rate_type==='fixed')out.assumptions.fixed_rate_years=Number(rateType);
      out.assumptions.finance_source='Client-supplied deposit; '+(num('interest_rate_pct')===null?'interest rate unknown, 5.5% modelling assumption.':'expected rate supplied, quote not independently verified.');
    }
    return out;
  }
  $('export-brief').addEventListener('click',()=>{
    numberFields.forEach(validateNumber);
    if(!form.reportValidity())return;
    const href=URL.createObjectURL(new Blob([JSON.stringify({schema_version:2,inputs:inputs()},null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=href;a.download='investor-brief.json';a.click();setTimeout(()=>URL.revokeObjectURL(href),5000);
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(submitting||entry.hidden||!form.reportValidity())return;
    const error=$('brief-error');error.hidden=true;
    if(!token){error.textContent='Unable to connect. Refresh the page or download your brief.';error.hidden=false;return;}
    $('submit-brief').disabled=true;submitting=true;
    try{
      const data=inputs();const response=await fetch('/api/records',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify({inputs:data})});
      const result=await response.json();if(!response.ok)throw Error(result.error||'Could not save brief');
      try{sessionStorage.removeItem(draftKey);}catch(e){}
      form.reset();numberFields.forEach(input=>input.setCustomValidity(''));update();
      $('success-title').textContent=data.enquiry.kind==='area'?'Enquiry submitted successfully':'Property submitted successfully';
      success.querySelector('p').textContent=data.enquiry.kind==='area'?'We will contact you to discuss your area and budget.':'Your property brief has been received and is being processed.';
      entry.hidden=true;success.hidden=false;success.focus({preventScroll:true});window.scrollTo(0,0);
    }catch(e){error.textContent=e.message;error.hidden=false;}finally{$('submit-brief').disabled=false;submitting=false;}
  });
  if(location.protocol==='file:'){$('submit-brief').hidden=true;$('review-link').href='http://127.0.0.1:8000/review';}
  else fetch('/api/config').then(r=>{if(!r.ok)throw Error();return r.json();}).then(c=>{token=c.token;}).catch(()=>{});
  restoreDraft();update();
})();

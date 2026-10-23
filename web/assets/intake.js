(() => {
  const form=document.getElementById('brief-form'),entry=document.getElementById('brief-entry'),success=document.getElementById('brief-success');
  const $=id=>document.getElementById(id);
  let token=null,submitting=false;
  function toggle(id,visible){const el=$(id);el.hidden=!visible;el.disabled=!visible;}
  function update(){
    const area=form.elements.area_only.checked;
    toggle('area-fields',area);toggle('property-fields',!area);toggle('investment-fields',!area);
    toggle('mortgage-fields',!area&&['interest_only','repayment'].includes(form.elements.financing.value));
    const works=form.elements.refurbishment_planned.value==='yes';
    $('refurb-budget-field').hidden=!works;form.elements.refurbishment.disabled=!works;
    const priced=form.elements.price_status.value!=='unknown';
    $('price-field').hidden=!priced;form.elements.asking_price.disabled=!priced;
    const bungalow=form.elements.property_type.value==='bungalow';
    $('attachment-field').hidden=!bungalow;form.elements.building_attachment.disabled=!bungalow;
    if(form.elements.property_type.value==='studio')form.elements.bedrooms.value='0';
    form.elements.bedrooms.readOnly=form.elements.property_type.value==='studio';
    $('submit-brief').textContent=area?'Submit enquiry':'Submit property';
  }
  form.addEventListener('change',update);
  window.addEventListener('pageshow',()=>{form.reset();entry.hidden=false;success.hidden=true;$('submit-brief').disabled=false;submitting=false;update();});
  function inputs(){
    const f=new FormData(form),num=k=>f.get(k)===null||f.get(k)===''?null:Number(f.get(k)),checked=k=>f.get(k)==='on';
    const area=checked('area_only'),followUpContact=checked('follow_up_contact');
    const out={enquiry:{kind:area?'area':'property',area:f.get('area')||'',budget:num('budget'),purpose:f.get('purpose'),terms_accepted:checked('terms_accepted'),feedback_call:followUpContact,testimonial_contact:followUpContact},investor:{name:f.get('name'),email:f.get('email'),cash_budget:num('cash_budget'),goal:f.get('goal'),notes:f.get('notes')},property:{},assumptions:{}};
    if(area)return out;
    for(const k of ['address','postcode','property_type','listing_url','construction_date','finish_quality','outdoor_space','tenure','price_status'])out.property[k]=f.get(k);
    for(const k of ['asking_price','bedrooms','bathrooms','floor_area_sqm','off_street_parking','lease_years'])out.property[k]=num(k);
    Object.assign(out.property,{country:'England',new_build:checked('new_build'),building_attachment:f.get('building_attachment')||''});
    Object.assign(out.assumptions,{financing:f.get('financing'),buyer_type:f.get('buyer_type'),additional_property:f.get('additional_property')==='yes',nonresident:f.get('uk_resident')!=='yes',refurbishment_planned:f.get('refurbishment_planned')==='yes',refurb_level:f.get('refurb_level'),refurb_finish:f.get('refurb_finish'),rent_source:f.get('rent_source')||''});
    for(const k of ['mortgage_amount','interest_rate_pct','mortgage_term_years','refurbishment','min_net_yield_pct','min_monthly_cashflow','monthly_rent','legal_fees','survey_fees','service_charge','ground_rent']){if(num(k)!==null)out.assumptions[k]=num(k);}
    if(out.assumptions.financing!=='cash')out.assumptions.finance_source='Client-supplied expected mortgage terms; quote not independently verified';
    return out;
  }
  $('export-brief').addEventListener('click',()=>{
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
      $('success-title').textContent=data.enquiry.kind==='area'?'Enquiry submitted successfully':'Property submitted successfully';
      success.querySelector('p').textContent=data.enquiry.kind==='area'?'We will contact you to discuss your area and budget.':'Your property brief has been received for review.';
      entry.hidden=true;success.hidden=false;success.focus({preventScroll:true});window.scrollTo(0,0);
    }catch(e){error.textContent=e.message;error.hidden=false;}finally{$('submit-brief').disabled=false;submitting=false;}
  });
  if(location.protocol==='file:'){$('submit-brief').hidden=true;$('review-link').href='http://127.0.0.1:8000/review';}
  else fetch('/api/config').then(r=>{if(!r.ok)throw Error();return r.json();}).then(c=>{token=c.token;}).catch(()=>{});
  update();
})();

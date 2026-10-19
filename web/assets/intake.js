(() => {
  const form=document.getElementById('brief-form');
  const entry=document.getElementById('brief-entry'),success=document.getElementById('brief-success');
  let token=null,submitting=false;
  const message=document.getElementById('message');
  window.addEventListener('pageshow',()=>{
    form.reset();entry.hidden=false;success.hidden=true;message.textContent='';
    document.getElementById('submit-brief').disabled=false;submitting=false;
  });
  function inputs(){
    const f=new FormData(form), num=k=>f.get(k)===''?null:Number(f.get(k));
    return {investor:{name:f.get('name'),email:f.get('email'),cash_budget:num('cash_budget'),goal:f.get('goal'),risk_tolerance:f.get('risk_tolerance'),notes:f.get('notes')},property:{address:f.get('address'),postcode:f.get('postcode'),country:'England',asking_price:num('asking_price'),property_type:f.get('property_type'),bedrooms:num('bedrooms'),listing_url:f.get('listing_url'),listing_checked:''},assumptions:{holding_years:num('holding_years')}};
  }
  document.getElementById('export-brief').addEventListener('click',()=>{
    if(!form.reportValidity())return;
    const blob=new Blob([JSON.stringify({schema_version:1,inputs:inputs()},null,2)],{type:'application/json'});
    const href=URL.createObjectURL(blob),a=document.createElement('a');a.href=href;a.download='investor-brief.json';a.click();setTimeout(()=>URL.revokeObjectURL(href),5000);
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(submitting||entry.hidden||!form.reportValidity())return;
    if(!token){message.className='error';message.textContent='Unable to connect. Refresh the page or download your brief.';return;}
    const button=document.getElementById('submit-brief');button.disabled=true;submitting=true;message.textContent='';
    try{
      const response=await fetch('/api/records',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify({inputs:inputs()})});
      const data=await response.json();if(!response.ok)throw Error(data.error||'Could not save brief');
      entry.hidden=true;success.hidden=false;success.focus({preventScroll:true});window.scrollTo(0,0);
    }catch(error){message.className='error';message.textContent=error.message;}finally{button.disabled=false;submitting=false;}
  });
  if(location.protocol==='file:'){
    document.getElementById('submit-brief').hidden=true;document.getElementById('review-link').href='http://127.0.0.1:8000/review';
  }else{
    fetch('/api/config').then(r=>{if(!r.ok)throw Error('Connection unavailable');return r.json();}).then(config=>{token=config.token;}).catch(()=>{message.className='error';message.textContent='Unable to connect. Refresh the page or download your brief.';});
  }
})();

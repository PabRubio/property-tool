#!/usr/bin/env python3
"""Run python3 app.py, then visit http://127.0.0.1:8000. No database."""
import json
import os
import secrets
import copy
import threading
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException
from screening.schema import defaults, validate, validate_submission, FIELDS, string
from screening.evidence import enriched_inputs, clear_profile_inputs, invalidate_size_evidence
from screening.store import Store, atomic_json
from screening.providers import gather, now, scrub
from screening.finance import analyse
from screening.narrative import generate, validate_content, allowed_sources, default_provider, plan_revision
from screening.reports import generate_report
from screening.photos import photo_groups, prepare_image

ROOT = Path(__file__).resolve().parent


def load_env():
    path=ROOT/".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line: continue
            key,value=line.split("=",1)
            os.environ.setdefault(key.strip(),value.strip().strip("\"'"))
    for canonical,alias in (("ANTHROPIC_API_KEY","CLAUDE_API_KEY"),("GEMINI_API_KEY","GOOGLE_API_KEY")):
        if not os.getenv(canonical) and os.getenv(alias): os.environ[canonical]=os.environ[alias]


def provenance(new, old=None, supplied=None):
    base=defaults()
    new["input_provenance"]=(old or {}).get("input_provenance",{}).copy()
    for section in ("property","investor","assumptions"):
        for key,value in new[section].items():
            path=section+"."+key
            if not old or old.get(section,{}).get(key)!=value:
                basis="Illustrative default (unverified)" if section=="assumptions" and value==base[section][key] else "User / analyst input"
                if supplied is not None and key in supplied.get(section, {}): basis="User / analyst input"
                if value is None or value=="": basis="Not supplied"
                new["input_provenance"][path]={"basis":basis,"recorded_at":now()}
    return new


def create_app(data_dir=None):
    app=Flask(__name__,static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=112*1024*1024,JSON_SORT_KEYS=False)
    store=Store(data_dir or os.getenv("PROPERTY_DATA_DIR",str(ROOT/"data/records")))
    app.store=store
    token=secrets.token_urlsafe(32)
    app.csrf_token=token
    # A process restart interrupts jobs, never leaves records stuck as running.
    for item in store.listing():
        if item["status"]=="running":
            r=store.load(item["id"]); r.update(status="error",job={"state":"failed","message":"Local server restarted. Retry the operation."}); store.save(r,"Interrupted job recovered")

    @app.before_request
    def local_only():
        limit=(112 if request.endpoint=='photo' else 12)*1024*1024
        if request.content_length and request.content_length>limit:
            return jsonify(error='Upload is too large. Each photo must be 10 MB or smaller.'),413
        if request.host.split(":")[0] not in ("localhost","127.0.0.1"):
            return jsonify(error="This application accepts localhost requests only"),403
        origin=request.headers.get("Origin")
        if origin and origin!=request.host_url.rstrip("/"):
            return jsonify(error="Cross-origin requests are not allowed"),403
        if request.method not in ("GET","HEAD","OPTIONS") and not secrets.compare_digest(request.headers.get("X-Local-Token",""),token):
            return jsonify(error="Refresh the local page before saving"),403

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["X-Frame-Options"]="SAMEORIGIN" if request.path.endswith('/download/pdf') else "DENY"
        response.headers["Cache-Control"]="no-store"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc,HTTPException): return jsonify(error=exc.description),exc.code
        if isinstance(exc,FileNotFoundError): return jsonify(error="Record or file not found"),404
        if isinstance(exc,ValueError): return jsonify(error=scrub(str(exc))),400
        app.logger.error("Local operation failed: %s",type(exc).__name__)
        return jsonify(error="The local operation failed. Check that data files are writable and installed dependencies are available."),500

    def body():
        value=request.get_json(silent=True)
        if not isinstance(value,dict): raise ValueError("Request body must be a JSON object")
        return value

    def writable(record_id, payload):
        r=store.load(record_id)
        if r["status"]=="running": raise ValueError("A job is already running for this property")
        if payload.get("revision")!=r["revision"]: raise ValueError("This record changed. Refresh it before saving.")
        return r

    @app.route("/")
    def index(): return send_from_directory(str(ROOT/"web"),"index.html")

    @app.route("/review")
    def review_page(): return send_from_directory(str(ROOT/"web"),"review.html")

    @app.route("/terms")
    @app.route("/privacy")
    def placeholder_page():
        return '<!doctype html><html lang="en"><head><meta charset="utf-8"><title></title></head><body></body></html>'

    @app.route("/assets/<path:name>")
    def assets(name): return send_from_directory(str(ROOT/"web/assets"),name)

    # Relative assets work when index.html is opened directly from disk.
    @app.route("/api/config")
    def config():
        return jsonify(token=token,defaults=defaults(),default_provider=default_provider(),fields=[dict(zip(("key","label","group","default","min","max"),f)) for f in FIELDS],brand=os.getenv("REPORT_BRAND","Property Screening"),
                       providers={"propertydata":bool(os.getenv("PROPERTYDATA_API_KEY")),"anthropic":bool(os.getenv("ANTHROPIC_API_KEY")),"openai":bool(os.getenv("OPENAI_API_KEY")),"gemini":bool(os.getenv("GEMINI_API_KEY"))})

    @app.route("/api/records",methods=["GET","POST"])
    def records():
        if request.method=="GET": return jsonify(records=store.listing())
        b=body()
        supplied=b.get("inputs",b)
        inputs=provenance(validate_submission(supplied),supplied=supplied)
        mode="demo" if b.get("mode")=="demo" else "manual"
        r=store.create(inputs,mode)
        return jsonify(r),201

    @app.route("/api/records/<record_id>",methods=["GET","PUT","DELETE"])
    def record(record_id):
        if request.method=="GET": return jsonify(store.load(record_id))
        b=body()
        with store.lock:
            r=writable(record_id,b)
            if request.method=="DELETE":
                store.delete(record_id)
                return jsonify(deleted=record_id)
            new=provenance(validate(b["inputs"]),r["inputs"])
            query_keys=("address","postcode","property_type","bedrooms","uprn","building_attachment","new_build","tenure")
            query_changed=any(new["property"].get(k)!=r["inputs"]["property"].get(k,defaults()["property"][k]) for k in query_keys)
            avm_keys=("floor_area_sqm","construction_date","finish_quality","outdoor_space","bathrooms","off_street_parking")
            avm_changed=any(new["property"][k]!=r["inputs"]["property"][k] for k in avm_keys)
            store.invalidate(r,"Inputs changed; approval and outputs invalidated")
            if query_changed:
                r["evidence"]={}
                clear_profile_inputs(new,r['inputs'])
                # Imported selections must be explicitly reviewed for the new subject.
                for c in new["comparables"]: c["selected"]=False
            elif avm_changed:
                for endpoint in ("valuation-sale","valuation-rent","build-cost"):
                    r["evidence"].get("market",{}).pop(endpoint,None)
                    r["evidence"].get("raw",{}).pop(endpoint,None)
                r["evidence"]["sources"]=[s for s in r["evidence"].get("sources",[]) if not s["id"].startswith("valuation-") and s['id']!='build-cost']
            if any(new['assumptions'].get(k)!=r['inputs']['assumptions'].get(k,defaults()['assumptions'][k]) for k in ('refurb_level','refurb_finish')):
                r['evidence'].get('market',{}).pop('build-cost',None)
                r['evidence'].get('raw',{}).pop('build-cost',None)
                r['evidence']['sources']=[s for s in r['evidence'].get('sources',[]) if s['id']!='build-cost']
            if new['property'].get('floor_area_sqm') != r['inputs']['property'].get('floor_area_sqm'):
                invalidate_size_evidence(r['evidence'])
            r["inputs"]=new
            r['status']='needs_follow_up' if new['enquiry']['kind']=='area' else 'draft'
            store.save(r)
        return jsonify(r)

    def run_job(record_id,kind,b):
        with store.lock:
            r=writable(record_id,b)
            if r['inputs'].get('enquiry',{}).get('kind')=='area': raise ValueError('Area enquiries are saved for manual follow-up; select a property before generating a report')
            if kind=="gather" and r["mode"]=="demo": raise ValueError("Demo records remain fictional. Create a new brief to use live data.")
            provider=b.get("provider",default_provider())
            if provider not in ("none","anthropic","openai","gemini"): raise ValueError("Unknown AI provider")
            if kind=="gather" and not os.getenv("PROPERTYDATA_API_KEY"): raise ValueError("Add PROPERTYDATA_API_KEY to .env and restart the server")
            analyst_notes=string(b.get("analyst_notes",r["inputs"].get("analyst_notes","")),"Additional information")
            store.invalidate(r,"Started "+kind)
            r["inputs"]["analyst_notes"]=analyst_notes
            r.update(status="running",job={"state":"running","kind":kind,"message":"Starting "+kind})
            store.save(r)
        def progress(message):
            with store.lock:
                live=store.load(record_id); live["job"]["message"]=message; store.save(live)
        def worker():
            try:
                if kind=="pipeline" and r['mode']!='demo':
                    evidence=r.get('evidence',{})
                    try:
                        age=(datetime.now(timezone.utc)-datetime.fromisoformat(evidence.get('retrieved_at','').replace('Z','+00:00'))).days
                    except (ValueError,TypeError): age=999
                    pd_ready=bool(os.getenv('PROPERTYDATA_API_KEY'))
                    needs_pd=pd_ready and (evidence.get('version',0)<3 or not any(s.get('id')=='rents' for s in evidence.get('sources',[])))
                    if not evidence or b.get('refresh_evidence') is True or age>=60 or needs_pd:
                        progress('Researching the property and HM Land Registry records')
                        r['evidence']=gather(r['inputs'],progress,include_profile=b.get('include_profile',True) is True,public_only=not pd_ready,
                                             cache_dir=store.root/'.research-cache',refresh_cache=b.get('refresh_evidence') is True)
                        r['mode']='live'
                if kind=="gather":
                    new_evidence=gather(r["inputs"],progress,include_profile=b.get("include_profile",True) is True,
                                        cache_dir=store.root/'.research-cache',refresh_cache=b.get('refresh_evidence') is True)
                    r.update(evidence=new_evidence,mode="live",status="draft")
                    message="Evidence gathered. Review sources and select comparables, then calculate."
                else:
                    progress("Calculating cash flow and checking assumptions")
                    r['inputs']=enriched_inputs(r['inputs'],r['evidence'])
                    r["analysis"]=analyse(r["inputs"],r["evidence"],r["mode"])
                    if not r["analysis"]["available"]:
                        r["status"]="needs_input"; message="There was an error while generating the report, please try again."
                    else:
                        progress("Drafting analysis" if provider!="none" else "Assembling the report")
                        r["narrative"]=generate(r,provider)
                        progress("Generating PDF, cash-flow image and CSV")
                        r["artifacts"]=generate_report(r,store.folder(record_id))
                        r["status"]="ready_for_review"; message="Draft ready for review"
                r["job"]={"state":"done","kind":kind,"message":message}
                store.save(r,kind+" completed")
            except Exception as exc:
                message=scrub(str(exc)) if isinstance(exc,ValueError) else "Operation failed (%s). Retry after checking local dependencies and evidence." % type(exc).__name__
                r.update(status="error",job={"state":"failed","kind":kind,"message":message})
                store.save(r,kind+" failed")
        threading.Thread(target=worker,daemon=True).start()
        return jsonify(id=record_id,status="running"),202

    @app.route("/api/records/<record_id>/gather",methods=["POST"])
    def gather_route(record_id): return run_job(record_id,"gather",body())

    @app.route("/api/records/<record_id>/analyse",methods=["POST"])
    def analyse_route(record_id): return run_job(record_id,"analyse",body())

    @app.route("/api/records/<record_id>/pipeline",methods=["POST"])
    def pipeline_route(record_id): return run_job(record_id,"pipeline",body())

    @app.route("/api/records/<record_id>/revise",methods=["POST"])
    def revise_route(record_id):
        b=body()
        instruction=string(b.get('instruction',''),'Edit request',3000)
        if not instruction: raise ValueError('Describe the change you want')
        provider=b.get('provider',default_provider())
        if provider not in ('anthropic','openai','gemini'): raise ValueError('Configure an AI API key in .env and restart the server to request edits')
        if not os.getenv({'anthropic':'ANTHROPIC_API_KEY','openai':'OPENAI_API_KEY','gemini':'GEMINI_API_KEY'}[provider]):
            raise ValueError('The selected AI provider has no API key configured')
        with store.lock:
            r=writable(record_id,b)
            if not r.get('artifacts',{}).get('pdf'): raise ValueError('Generate a report before requesting edits')
            original=copy.deepcopy(r)
            r.update(status='running',job={'state':'running','kind':'revise','message':'Reading your edit request'})
            store.save(r)
        def worker():
            try:
                if not original.get('report_document'):
                    # Older saved reports predate the editable text catalog.
                    with tempfile.TemporaryDirectory(prefix='report-editor-') as preview:
                        generate_report(original,preview)
                inputs, explanation, changes, presentation, rewrite=plan_revision(original,provider,instruction)
                revised=copy.deepcopy(original)
                revised['inputs']=provenance(inputs,original['inputs'])
                for change in changes:
                    field=change['section']+'.'+change['key']
                    revised['inputs']['input_provenance'][field]={'basis':'Analyst supplied via AI edit; unverified','recorded_at':now()}
                revised['presentation']=presentation
                query_keys=('address','postcode','property_type','bedrooms','uprn','building_attachment','new_build','tenure')
                if any(inputs['property'].get(k)!=original['inputs']['property'].get(k,defaults()['property'][k]) for k in query_keys):
                    revised['evidence']={}
                    clear_profile_inputs(revised['inputs'],original['inputs'])
                    for c in revised['inputs']['comparables']:c['selected']=False
                elif any(inputs['property'][k]!=original['inputs']['property'][k] for k in ('floor_area_sqm','construction_date','finish_quality','outdoor_space','bathrooms','off_street_parking')):
                    for endpoint in ('valuation-sale','valuation-rent','build-cost'):
                        revised['evidence'].get('market',{}).pop(endpoint,None)
                        revised['evidence'].get('raw',{}).pop(endpoint,None)
                    revised['evidence']['sources']=[s for s in revised['evidence'].get('sources',[]) if not s['id'].startswith('valuation-') and s['id']!='build-cost']
                if any(inputs['assumptions'].get(k)!=original['inputs']['assumptions'].get(k,defaults()['assumptions'][k]) for k in ('refurb_level','refurb_finish')):
                    revised['evidence'].get('market',{}).pop('build-cost',None)
                    revised['evidence'].get('raw',{}).pop('build-cost',None)
                    revised['evidence']['sources']=[s for s in revised['evidence'].get('sources',[]) if s['id']!='build-cost']
                revised.update(revision=original['revision']+1,approval=None,status='ready_for_review')
                if inputs['property'].get('floor_area_sqm') != original['inputs']['property'].get('floor_area_sqm'):
                    invalidate_size_evidence(revised['evidence'])
                revised['inputs']=enriched_inputs(revised['inputs'],revised['evidence'])
                upgraded=revised['analysis'].get('version') != 3
                if changes or upgraded or not revised['analysis'].get('horizons'):revised['analysis']=analyse(revised['inputs'],revised['evidence'],revised['mode'])
                if not revised['analysis']['available']: raise ValueError('That edit leaves missing financial inputs: '+', '.join(revised['analysis'].get('missing',[])))
                with store.lock:
                    pending=store.load(record_id);pending['job']['message']='Applying your changes and rebuilding the PDF';store.save(pending)
                if rewrite or changes or upgraded:revised['narrative']=generate(revised,provider,instructions=instruction,strict=True)
                revised['artifacts']=generate_report(revised,store.folder(record_id))
                revised.setdefault('edit_history',[]).append({'at':now(),'request':instruction,'message':explanation,'changes':changes,'presentation':presentation,'rewrite_commentary':rewrite,'revision':revised['revision']})
                revised['job']={'state':'done','kind':'revise','message':'Report updated. '+explanation}
                with store.lock:
                    atomic_json(store.folder(record_id)/'history'/('revision-%s.json'%original['revision']),original)
                    store.save(revised,'AI edit applied; review reset')
            except Exception as exc:
                reason=scrub(str(exc)) if isinstance(exc,ValueError) else 'AI edit failed. Check the provider connection and try again.'
                original['job']={'state':'failed','kind':'revise','message':reason+' Existing report kept.'}
                store.save(original,'AI edit failed; previous report preserved')
        threading.Thread(target=worker,daemon=True).start()
        return jsonify(id=record_id,status='running'),202

    @app.route("/api/records/<record_id>/narrative",methods=["PUT"])
    def edit_narrative(record_id):
        b=body()
        with store.lock:
            r=writable(record_id,b)
            if not r.get("narrative"): raise ValueError("Generate a draft first")
            content=validate_content(b.get("content"),allowed_sources(r))
            # Copy before invalidation to retain calculations and provenance.
            model=r["analysis"]; narrative=r["narrative"]
            store.invalidate(r,"Analyst edited narrative; review reset")
            r["analysis"]=model; r["narrative"]=dict(narrative,content=content,edited_by_analyst_at=now())
            r["artifacts"]=generate_report(r,store.folder(record_id)); r["status"]="ready_for_review"; store.save(r)
        return jsonify(r)

    @app.route("/api/records/<record_id>/approve",methods=["POST"])
    def approve(record_id):
        b=body()
        with store.lock:
            r=writable(record_id,b)
            if not r.get("analysis",{}) or not r["analysis"].get("available") or not r.get("narrative"): raise ValueError("Generate and review a draft first")
            if r['analysis'].get('version') != 3 or not r['analysis'].get('horizons'): raise ValueError('Update the draft before finalizing so you can review the updated evidence and projections. Reapply your photos or request a PDF update.')
            reviewer=string(b.get("reviewer",""),"Reviewer",150)
            if not reviewer or b.get("acknowledged") is not True: raise ValueError("Enter a reviewer name and acknowledge the assumptions, tax exclusions and evidence gaps")
            folder=store.folder(record_id)
            if not r.get('artifacts',{}).get('pdf') or not (folder/r['artifacts']['pdf']).is_file():
                raise ValueError('Generate and review a draft first')
            cover,_=photo_groups(r)
            if not cover or not (folder/cover['filename']).is_file():
                raise ValueError('Add a cover photo to the PDF before finalizing')
            r["approval"]={"reviewer":reviewer,"at":now(),"revision":r["revision"],"notes":string(b.get("notes",""),"Review notes",5000),"acknowledged":True}
            r["artifacts"]=generate_report(r,folder,final=True); r["status"]="approved"
            store.save(r,("Demo report finalized for testing by " if r['mode']=='demo' else "Report approved by ")+reviewer)
        return jsonify(r)

    @app.route("/api/records/<record_id>/photos",methods=["POST"])
    def photo(record_id):
        try: revision=int(request.form.get("revision",""))
        except ValueError: raise ValueError("Photo revision is required")
        uploads={kind:request.files.getlist(kind) for kind in ('cover','gallery','photo')}
        if set(request.files)-set(uploads): raise ValueError('Unknown photo upload field')
        if len(uploads['cover'])>1: raise ValueError('Choose one cover photo at most')
        if len(uploads['gallery'])>10 or len(uploads['photo'])>1: raise ValueError('Choose up to ten additional photos')
        if uploads['photo'] and (uploads['cover'] or uploads['gallery']): raise ValueError('Use cover and gallery uploads together, or a single legacy photo')
        with store.lock:
            r=writable(record_id,{"revision":revision})
            cover,gallery=photo_groups(r)
            keep_cover=request.form.get('keep_cover',cover['filename'] if cover else '')
            if keep_cover and (not cover or keep_cover!=cover['filename']): raise ValueError('Unknown cover photo')
            if not keep_cover: cover=None
            if 'keep_gallery' in request.form:
                try: keep_gallery=json.loads(request.form['keep_gallery'])
                except ValueError: raise ValueError('Invalid photo selection')
                allowed={p['filename']:p for p in gallery}
                if not isinstance(keep_gallery,list) or len(keep_gallery)>10 or not all(isinstance(v,str) and v in allowed for v in keep_gallery) or len(set(keep_gallery))!=len(keep_gallery):
                    raise ValueError('Unknown or duplicate additional photo')
                gallery=[allowed[name] for name in keep_gallery]
            legacy=bool(uploads['photo'])
            if legacy: uploads['cover' if cover is None else 'gallery']=uploads['photo']
            if len(gallery)+len(uploads['gallery'])>10: raise ValueError('Maximum ten additional photos; remove a photo before adding another')
            if not any(uploads.values()) and 'keep_cover' not in request.form and 'keep_gallery' not in request.form:
                raise ValueError('Choose photos to upload')
            # Validate the entire batch before writing anything or invalidating a report.
            prepared=[(kind,prepare_image(file)) for kind in ('cover','gallery') for file in uploads[kind]]
            revised=copy.deepcopy(r)
            written=[]
            try:
                for kind,data in prepared:
                    filename='photo-'+secrets.token_hex(8)+'.jpg'
                    path=store.folder(record_id)/filename;written.append(path);path.write_bytes(data)
                    item={'filename':filename,'role':kind,'caption':'Cover photograph' if kind=='cover' else 'Property photograph',
                          'source':'Uploaded by analyst','added_at':now()}
                    if legacy:
                        item['caption']=string(request.form.get('caption',''),'Photo caption',300) or item['caption']
                        item['source']=string(request.form.get('source',''),'Photo source',1500) or item['source']
                    if kind=='cover': cover=item
                    else: gallery.append(item)
                revised['photos']=([dict(cover,role='cover')] if cover else [])+[dict(p,role='gallery') for p in gallery]
                revised.update(revision=r['revision']+1,approval=None,artifacts={},status='draft')
                revised.pop('job',None)
                # Reuse the existing calculations and approved wording. Photo changes need no API calls.
                if revised.get('analysis') and revised['analysis'].get('available') and revised.get('narrative'):
                    revised['artifacts']=generate_report(revised,store.folder(record_id))
                    revised['status']='ready_for_review'
                revised['job']={'state':'done','kind':'photos','message':'Photos added to the PDF.' if revised['artifacts'] else 'Photos saved for the report.'}
                atomic_json(store.folder(record_id)/'history'/('revision-%s.json'%r['revision']),r)
                store.save(revised,'Property photos updated; delivery review reset')
            except Exception:
                for path in written:
                    if path.exists(): path.unlink()
                raise
        return jsonify(revised)

    @app.route("/api/records/<record_id>/photos/<name>")
    def photo_get(record_id,name):
        r=store.load(record_id)
        if name not in [p["filename"] for p in r["photos"]]: raise FileNotFoundError()
        return send_from_directory(str(store.folder(record_id)),name)

    @app.route("/api/records/<record_id>/download/<kind>")
    def download(record_id,kind):
        r=store.load(record_id)
        if kind=="json":
            response=jsonify(r); response.headers["Content-Disposition"]='attachment; filename="screening-%s.json"' % record_id[:10]; return response
        if kind not in ("pdf","cashflow_png","cashflow_csv","calculations_png") or not r.get("artifacts",{}).get(kind): raise FileNotFoundError()
        return send_from_directory(str(store.folder(record_id)),r["artifacts"][kind],as_attachment=request.args.get("inline")!="1")

    return app


if __name__=="__main__":
    load_env()
    port=int(os.getenv("PORT","8000"))
    print("Property Screening: http://127.0.0.1:%s | Analyst review: /review" % port)
    print("JSON data stays in data/records. No database. Press Ctrl+C to stop.")
    create_app().run(host="127.0.0.1",port=port,debug=False,threaded=True,use_reloader=False,load_dotenv=False)

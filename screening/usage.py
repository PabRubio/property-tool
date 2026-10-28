"""Private per-operation API metering. Never included in reports, UI or app logs."""
import contextvars
import copy
import functools
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = contextvars.ContextVar('property_api_usage', default=None)
# USD per million tokens; standard global API pricing, verified 2026-10-28.
RATES = {
    'claude-sonnet-5-5': {'input':2.0,'output':10.0,'cache_read':0.10},
    'claude-sonnet-5': {'input':2.0,'output':10.0,'cache_read':0.20},
    'claude-sonnet-4-6': {'input':3.0,'output':15.0,'cache_read':0.30},
    'claude-sonnet-4-5': {'input':3.0,'output':15.0,'cache_read':0.30},
}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def price(model, usage):
    rates=next((v for k,v in RATES.items() if model==k or model.startswith(k+'-') and len(model[len(k)+1:])==8 and model[len(k)+1:].isdigit()),None)
    if rates is None:return None
    rates=dict(rates)
    if model.startswith('claude-sonnet-4-5') and sum(usage.get(k,0) for k in ('input_tokens','cache_creation_input_tokens','cache_read_input_tokens'))>200000:
        rates['input']*=2;rates['output']*=1.5;rates['cache_read']*=2
    cache=usage.get('cache_creation') or {}
    creation=usage.get('cache_creation_input_tokens',0)
    hour=cache.get('ephemeral_1h_input_tokens',0)
    short=cache.get('ephemeral_5m_input_tokens',max(0,creation-hour))
    tool=usage.get('server_tool_use') or {}
    tokens=(usage.get('input_tokens',0)*rates['input']+usage.get('output_tokens',0)*rates['output']+
            usage.get('cache_read_input_tokens',0)*rates['cache_read']+
            short*rates['input']*1.25+hour*rates['input']*2)/1000000
    return {'tokens_usd':round(tokens,8),'search_usd':round(tool.get('web_search_requests',0)*.01,8),
            'total_usd':round(tokens+tool.get('web_search_requests',0)*.01,8),'rates_per_million':rates}


def save(tracker):
    from .store import atomic_json
    record=tracker['record'];calls=record['calls']
    record['elapsed_seconds']=round(time.monotonic()-tracker['started'],3)
    record['reported_usage']={key:sum((c.get('usage') or {}).get(key,0) for c in calls)
                              for key in ('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens')}
    record['web_search_requests']=sum(((c.get('usage') or {}).get('server_tool_use') or {}).get('web_search_requests',0) for c in calls)
    record['known_cost_usd']=round(sum((c.get('cost') or {}).get('total_usd',0) for c in calls),8)
    record['cost_complete']=all(c.get('cost') is not None for c in calls)
    try:
        atomic_json(tracker['path'],record)
    except OSError:
        # Preserve a metering failure in memory if a later checkpoint succeeds;
        # do not print keys, prompts or usage into the application logs.
        record['storage_error']=True


def record_response(url, body, result=None, elapsed=0, error=None):
    tracker=ACTIVE.get()
    if tracker is None or url!='https://api.anthropic.com/v1/messages':return
    model=(result or {}).get('model') or (body or {}).get('model','')
    usage=(result or {}).get('usage')
    call={'at':stamp(),'model':model,'elapsed_seconds':round(elapsed,3),
          'request_id':(result or {}).get('id'),'usage':copy.deepcopy(usage),
          'cost':price(model,usage) if isinstance(usage,dict) else None}
    if error:call['error']=error  # HTTP code / exception class only, no response text.
    tracker['record']['calls'].append(call);save(tracker)


def tracked_worker(root, record_id, revision, operation, worker):
    @functools.wraps(worker)
    def run():
        path=Path(root)/'.usage'/record_id/(uuid.uuid4().hex+'.json')
        tracker={'path':path,'started':time.monotonic(),'record':{
            'record_id':record_id,'revision':revision,'operation':operation,'started_at':stamp(),
            'status':'running','pricing_verified_on':'2026-10-28','calls':[],
            'cost_basis':'Calculated USD list-price cost from provider-reported usage; excludes tax, account discounts and credits. Calls without returned usage are not priced.'}}
        token=ACTIVE.set(tracker);save(tracker)
        try:
            result=worker();tracker['record']['status']='finished';return result
        except BaseException:
            tracker['record']['status']='failed';raise
        finally:
            tracker['record']['finished_at']=stamp();save(tracker);ACTIVE.reset(token)
    return run

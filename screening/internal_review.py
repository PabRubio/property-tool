"""Staff preparation and conflicting research, separate from investor risks."""
import re
from .evidence import matched_profile
from .photos import photo_groups


def investigative(item):
    text=item['text'].lower()
    # Keep financing, licensing and environmental risks in the investor report,
    # even when a paragraph also contains a preparation request.
    if re.search(r'financing|mortgage|licen[cs]|flood|listed status|cladding|fire safety',text): return False
    return bool(re.search(r'bedroom.{0,35}(unverified|discrepan|conflict)|estimated.{0,20}bedroom|price support is weak|price.{0,15}evidence.{0,15}weak|costs are incomplete|cost.{0,20}(research|confirmation)|verify conflicting|retry|failed.{0,20}(request|search)|obtain.{0,40}(quote|floorplan|valuation)|no sale is sufficiently matched|listing availability.{0,20}(check|refresh)|budget unconfirmed|running costs need confirmation',text))


def review_items(record):
    content=record.get('narrative',{}).get('content',{})
    items=[]
    for section in ('purchase_conclusion','rent_conclusion','strengths','risks'):
        values=content.get(section,[])
        if isinstance(values,dict):values=[values]
        items.extend(item for item in values if investigative(item))
    b=matched_profile(record).get('building',{});p=record['inputs']['property']
    conflicts=[]
    if b.get('estimated_bedrooms') is not None and b['estimated_bedrooms']!=p['bedrooms']:
        conflicts.append('bedrooms '+str(p['bedrooms'])+' supplied versus '+str(b['estimated_bedrooms'])+' estimated')
    if b.get('internal_area_sqf') and p.get('floor_area_sqm') and abs(float(b['internal_area_sqf'])/10.7639104167-p['floor_area_sqm'])>1:
        conflicts.append('area '+str(p['floor_area_sqm'])+' m² supplied versus '+str(b['internal_area_sqf'])+' sq ft in the profile')
    if conflicts:items.append({'text':'Verify conflicting records: '+'; '.join(conflicts)+'. Calculations retain supplied facts. Obtain the floorplan and property records.','source_ids':['inputs','property']})
    items.extend(content.get('due_diligence',[]))
    for gap in record.get('analysis',{}).get('missing',[]):
        items.append({'text':'Resolve missing '+gap.replace('_',' ')+'. Dependent figures remain unavailable.','source_ids':['assumptions']})
    cover,gallery=photo_groups(record)
    if not cover:items.append({'text':'Add a subject-property photograph before delivery. Confirm permission to use all uploaded photographs.','source_ids':['inputs']})
    items.append({'text':'Confirm fire precautions, inspection schedules and local licensing; reconcile safety work with refurbishment, service charges and existing cost allowances. Obtain quotes for unknown cleaning and property charges.','source_ids':['assumptions','safety-gov']})
    if record.get('evidence',{}).get('errors'):
        items.append({'text':'Review unresolved / failed evidence requests in the saved JSON research log. Do not treat missing results as cleared checks.','source_ids':['inputs']})
    seen=set();result=[]
    for item in items:
        if item['text'] not in seen:result.append(item);seen.add(item['text'])
    return result


def generate_internal(record,path):
    from .source_report import CitationIndex, single_page
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    index=CitationIndex(record,seed=True)
    style=ParagraphStyle('internal',fontName='Helvetica',fontSize=8.5,leading=11,spaceAfter=8,textColor='#18333c')
    items=review_items(record)
    story=[Paragraph(index.markup(item['text']+' ['+', '.join(item['source_ids'])+']'),style) for item in items]
    single_page(record,path,'Internal review',story,'Staff preparation only. Retain material assumptions and investment risks in the investor report.')
    record['report_citations']=index.used
    record['internal_review_items']=items
    return 1

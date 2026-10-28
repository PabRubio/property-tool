"""A one-page staff handoff, separate from investor conclusions and references."""
import io
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from .evidence import matched_profile
from .narrative import partition_risks


def review_items(record):
    audit = record.get('evidence',{}).get('research',{})
    items = []
    if not any(p.get('role') == 'cover' for p in record.get('photos',[])):
        items.append({'category':'Delivery','title':'Subject photograph','detail':'Add a subject-property photograph before delivery.'})
    reasons = {'private_document':'Private document', 'site_inspection':'Inspection', 'professional_quote':'Property quote',
               'access_blocked':'Access blocked', 'technical_failure':'Retry needed', 'conflicting_evidence':'Evidence conflict',
               'not_found':'Search unfinished', 'not_searched':'Not yet searched'}
    for finding in audit.get('findings',[]):
        if finding.get('status') == 'supported': continue
        reason = reasons.get(finding.get('unresolved_reason'),'Further research')
        items.append({'category':reason,'title':finding.get('gap_id',finding.get('id','Research')),
                      'detail':finding.get('limitations') or finding.get('text',''), 'next_search':finding.get('next_search',''),
                      'source_ids':finding.get('source_ids',[])})
    p = record['inputs']['property']; building = matched_profile(record).get('building',{})
    if building.get('estimated_bedrooms') is not None and building['estimated_bedrooms'] != p['bedrooms']:
        fact = record['evidence'].get('researched_facts',{}).get('property.bedrooms',{})
        if fact.get('value') != p['bedrooms']:
            items.append({'category':'Evidence conflict','title':'Bedroom evidence','detail':'%s bedrooms supplied; provider estimates %s. The estimate is not an EPC bedroom count. Calculations retain the supplied count.' % (p['bedrooms'],building['estimated_bedrooms'])})
    area = building.get('internal_area_sqf')
    if area and p.get('floor_area_sqm') and abs(float(area)/10.7639104167-p['floor_area_sqm'])/p['floor_area_sqm'] > .05:
        items.append({'category':'Evidence conflict','title':'Floor area','detail':'Supplied %s m² versus provider %.1f m²; retain supplied area until resolved.' % (p['floor_area_sqm'],float(area)/10.7639104167)})
    for flag in (record.get('analysis') or {}).get('flags',[]):
        if flag['level'] != 'info':items.append({'category':flag['level'].title(),'title':flag['title'],'detail':flag['detail']})
    for item in (record.get('narrative') or {}).get('content',{}).get('due_diligence',[]):
        items.append({'category':'Analyst follow-up','title':item['text'],'detail':'','source_ids':item['source_ids']})
    items.extend(partition_risks((record.get('narrative') or {}).get('content',{}))[1])
    unique = {}; priority = {'Critical':0,'Evidence conflict':1,'Retry needed':2,'Access blocked':3}
    for item in items:unique.setdefault((item['category'],item['title'],item['detail']),item)
    return sorted(unique.values(),key=lambda i:priority.get(i['category'],4))


def generate_internal(record, path):
    items = review_items(record)
    record['internal_review'] = {'items':items,'research_status':record.get('evidence',{}).get('research',{}).get('status','not_run')}
    stream=io.BytesIO(); pdf=canvas.Canvas(stream,pagesize=A4)
    pdf.setTitle('INTERNAL ONLY - '+record['inputs']['property']['address'])
    pdf.setFont('Helvetica-Bold',17);pdf.drawString(40,A4[1]-43,'Internal review — not for investor delivery')
    style=ParagraphStyle('internal',fontName='Helvetica',fontSize=8.5,leading=11)
    y=A4[1]-66;width=A4[0]-80
    def para(text,bold=False):
        nonlocal y
        paragraph=Paragraph(('<b>'+escape(text)+'</b>') if bold else escape(text),style)
        _,height=paragraph.wrap(width,1000);paragraph.drawOn(pdf,40,y-height);y-=height+5
    para(record['inputs']['property']['address']+' | revision '+str(record['revision']))
    audit=record.get('evidence',{}).get('research',{})
    para('Research: '+audit.get('status','not run')+' | '+str(len(audit.get('rounds',[])))+' rounds | stop: '+audit.get('stop_reason','not recorded'))
    para('Private documents, inspections and tailored quotes require human input. Access failures and search limits mean research is unfinished, not that the information is impossible to find.')
    # Preserve every full task in the record. The one-page handoff groups overflow
    # explicitly instead of silently dropping findings or creating extra pages.
    available=y-77
    details=[]
    for item in items:
        text=item['category']+' — '+item['title']+(': '+item['detail'] if item['detail'] else '')
        if item.get('next_search'):text+=' Next: '+item['next_search']
        details.append(text)
    height=sum(Paragraph(escape(t),style).wrap(width,1000)[1]+5 for t in details)
    if height <= available:
        for line in details:para(line)
    else:
        for category in dict.fromkeys(i['category'] for i in items):
            group=[i for i in items if i['category']==category]
            # Compact titles identify all issues; the explicit count and saved
            # details provide a lossless audit even for very large research runs.
            titles=[i['title'] if len(i['title']) <= 95 else i['title'][:92]+'…' for i in group]
            line=category+' ('+str(len(group))+'): '+'; '.join(titles)
            h=Paragraph(escape(line),style).wrap(width,1000)[1]+5
            if y-h < 83:
                para('Additional tasks are recorded in the full internal review in the saved record. Total: '+str(len(items))+'.')
                break
            para(line)
    if not items:para('No outstanding tasks recorded. This is not a survey, legal clearance or guarantee.')
    pdf.setFont('Helvetica',8);pdf.drawString(40,43,'Full findings, sources, search attempts and action details: saved record / JSON export → internal_review.')
    pdf.drawString(40,29,'Internal use only | 1 / 1');pdf.save();Path(path).write_bytes(stream.getvalue())
    return 1

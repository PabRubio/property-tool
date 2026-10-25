"""Separate, readable evidence register; the investment PDF retains inline citations."""
from xml.sax.saxutils import escape
import re
from urllib.parse import urlparse
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4


def references(record):
    sources=list(record['evidence'].get('sources',[]))
    sources.extend([
        {'id':'room-definition','title':'PropertyData — habitable-room definition','url':'https://propertydata.co.uk/api/documentation/property-types','status':'reference','scope':'Definition, not a room-by-room survey'},
        {'id':'lender-icr','title':'The Mortgage Works — lender-specific income and stress criteria','url':'https://www.themortgageworks.co.uk/intermediaries/lending-criteria/income','status':'reference','scope':'Illustration of lender-specific rules; not applied as automatic eligibility'}])
    rules=(record.get('analysis') or {}).get('sdlt',{}).get('rules',{})
    for index,url in enumerate(rules.get('sources',[])):
        sources.append({'id':'tax-'+str(index+1),'title':'HMRC purchase tax reference','url':url,'status':'stored configuration','retrieved_at':rules.get('verified_on'),'scope':'Tax configuration verification date; not a live legal assessment'})
    for index,row in enumerate(record['inputs'].get('comparables',[])):
        if row.get('selected'):
            sources.append({'id':'comparable-'+str(index+1),'title':row['address'],'url':row.get('source_url',''),'status':'analyst selected','retrieved_at':row.get('date'),'scope':'Selected comparison; matching assumptions require review'})
    return sources


class CitationIndex:
    """Short numbered references, deduplicated by URL, shared by both PDFs."""
    def __init__(self,record):
        self.sources={s['id']:s for s in references(record)};self.used=[];self.by_url={}

    def markup(self,text):
        def cite(match):
            labels=[]
            for sid in match.group(1).split(', '):
                source=self.sources.get(sid)
                if not source:
                    labels.append(sid);continue
                key=source.get('url') or sid
                if key not in self.by_url:
                    entry=dict(source,number=len(self.used)+1);self.used.append(entry);self.by_url[key]=entry
                entry=self.by_url[key];url=source.get('url','');number=str(entry['number'])
                label='<a href="'+escape(url,{'"':'&quot;'})+'" color="#19766e">'+number+'</a>' if url.startswith(('https://','http://')) else number
                if label not in labels:labels.append(label)
            return '['+', '.join(labels)+']'
        return re.sub(r'\[([a-zA-Z0-9_, -]+)\]',cite,escape(str(text)).replace('\n','<br/>'))


def generate_sources(record, path):
    # The client needs a reference list, not the internal research transcript.
    body=ParagraphStyle('source',fontName='Helvetica',fontSize=9,leading=11)
    small=ParagraphStyle('metadata',fontName='Helvetica',fontSize=8.5,leading=10.5,textColor='#43575b')
    story=[];sources=record.get('report_citations')
    if sources is None:
        sources=list({s.get('url') or s['id']:s for s in references(record)}.values())
    for source in sources:
        label=('['+str(source['number'])+'] ') if 'number' in source else '['+source['id']+'] '
        title=str(source.get('title',source['id']))
        if len(title)>110:title=title[:107].rsplit(' ',1)[0]+'…'
        url=source.get('url','');heading=escape(label+title)
        if url.startswith(('https://','http://')):heading='<a href="'+escape(url,{'"':'&quot;'})+'" color="#19766e">'+heading+'</a>'
        date=str(source.get('retrieved_at') or '')[:10] or 'date not recorded'
        metadata=(urlparse(url).hostname or 'Supplied reference')+' | '+date+' | '+source.get('status','unverified')
        story.append(KeepTogether([Paragraph(heading,body),Paragraph(escape(metadata),small),Spacer(1,9)]))
    count=[0]
    def footer(canvas, doc):
        count[0]=doc.page;canvas.setFont('Helvetica-Bold',16);canvas.drawString(40,A4[1]-43,'Sources & Evidence')
        canvas.setFont('Helvetica',9);canvas.drawString(40,A4[1]-60,record['inputs']['property']['address']+' | revision '+str(record['revision']))
        intro=Paragraph('Numbered links match the report. [inputs] are supplied statements; [assumptions] are model inputs; [model] means calculated results. Full searches, excerpts and failed-request logs stay in the saved record / JSON export.',small)
        _,height=intro.wrap(A4[0]-80,50);intro.drawOn(canvas,40,A4[1]-73-height)
        canvas.setFont('Helvetica',8);canvas.drawString(40,28,'Sources & Evidence | '+str(doc.page))
    width=(A4[0]-96)/2;height=A4[1]-174
    doc=BaseDocTemplate(str(path),pagesize=A4,leftMargin=40,rightMargin=40,topMargin=129,bottomMargin=45)
    doc.addPageTemplates(PageTemplate(id='references',frames=[Frame(40,45,width,height,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0),Frame(56+width,45,width,height,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=footer))
    if not story:story=[Paragraph('No external references were cited.',body)]
    doc.build(story)
    return count[0]

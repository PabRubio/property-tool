"""Separate, readable evidence register; the investment PDF retains inline citations."""
from xml.sax.saxutils import escape
import re
from urllib.parse import urlparse
from reportlab.platypus import Paragraph, Table
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4


def references(record):
    sources=list(record['evidence'].get('sources',[]))
    if record['evidence'].get('location'):
        from urllib.parse import quote
        sources.append({'id':'postcode-location','title':'Postcodes.io — postcode location and administrative boundaries',
                        'url':'https://api.postcodes.io/postcodes/'+quote(record['inputs']['property']['postcode']),
                        'status':'Postcode area context','retrieved_at':record['evidence'].get('retrieved_at')})
    from .tax_notes import REFERENCES, VERIFIED_ON
    sources.extend({'id':sid,'title':title,'url':url,'status':'Government guidance','retrieved_at':VERIFIED_ON} for sid,title,url in REFERENCES)
    from .comparisons import comparison_summary
    import hashlib
    for kind in ('asking','rent','sold'):
        for row in comparison_summary(record['inputs'],record['evidence'],kind)['candidates'][:5]:
            for url in row.get('evidence_urls') or [row.get('source_url')]:
              if url:
                sources.append({'id':'listing-'+hashlib.sha256(url.encode()).hexdigest()[:12],
                                'title':row['address'],'url':url,'status':'Sale' if kind=='sold' else 'Observed',
                                'retrieved_at':row.get('date') if kind=='sold' else row.get('observed_at')})
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
    def __init__(self,record,seed=False):
        self.sources={s['id']:s for s in references(record)}
        self.used=list(record.get('report_citations',[])) if seed else []
        self.by_url={s.get('url') or s['id']:s for s in self.used}

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
    body=ParagraphStyle('source',fontName='Helvetica',fontSize=8.2,leading=9.5)
    small=ParagraphStyle('metadata',fontName='Helvetica',fontSize=7.5,leading=9,textColor='#43575b')
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
        entry=Table([[Paragraph(heading,body)],[Paragraph(escape(metadata),small)]],colWidths=[(A4[0]-100)/2],
                    style=[('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
                           ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)])
        entry.spaceAfter=3;story.append(entry)
    if not story:story=[Paragraph('No external references were cited.',body)]
    single_page(record,path,'Sources & Evidence',story,'Numbered links match both PDFs. [inputs]: supplied statements; [assumptions]: model inputs; [model]: calculations.')
    return 1


def single_page(record,path,title,story,intro):
    """Measure two fixed columns before publishing; never spill to a second page."""
    import io
    from pathlib import Path
    from reportlab.pdfgen import canvas
    width=(A4[0]-100)/2
    measured=[(item,item.wrap(width,700)[1]+item.getSpaceAfter()) for item in story]
    # Balanced columns, keeping individual paragraphs intact.
    split=min(range(len(measured)+1),key=lambda n:max(sum(h for _,h in measured[:n]),sum(h for _,h in measured[n:])))
    columns=[measured[:split],measured[split:]]
    small=ParagraphStyle('intro',fontName='Helvetica',fontSize=8,leading=10,textColor='#43575b')
    subtitle=Paragraph(escape(record['inputs']['property']['address']+' | revision '+str(record['revision']))+'<br/>'+escape(intro),small)
    _,height=subtitle.wrap(A4[0]-80,100);top=A4[1]-92-height
    if max(sum(h for _,h in col) for col in columns)>top-45:
        raise ValueError(title+' exceeds its one-page layout. Shorten the internal wording / reference titles; previous report kept.')
    stream=io.BytesIO();pdf=canvas.Canvas(stream,pagesize=A4)
    pdf.setTitle('Lacewing Analytics — '+title);pdf.setAuthor('Lacewing Analytics')
    pdf.setFillColorRGB(.094,.2,.235);pdf.setFont('Helvetica-Bold',10);pdf.drawString(40,A4[1]-35,'Lacewing Analytics')
    pdf.setFont('Helvetica-Bold',18);pdf.drawString(40,A4[1]-62,title)
    subtitle.drawOn(pdf,40,A4[1]-77-height)
    for number,col in enumerate(columns):
        y=top
        for item,height in col:
            item.drawOn(pdf,40+number*(width+20),y-height+item.getSpaceAfter());y-=height
    pdf.setFont('Helvetica',8);pdf.drawString(40,28,title+' | 1 / 1')
    pdf.save();Path(path).write_bytes(stream.getvalue())

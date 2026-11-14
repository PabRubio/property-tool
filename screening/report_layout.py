"""Ten readable report pages, with measured layout and no overflow pages."""
import io
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer, Image, Flowable

from .editor import FONTS
from .evidence import matched_profile, property_history
from .photos import photo_groups
from .providers import now
from . import branding
from .source_report import CitationIndex
from .commercial import is_commercial
from .report_visuals import (Stack, Columns, ResponsiveTable, Cover, Chart, numeric_cell,
                             PAPER, GREEN, GOLD, MUTED, PHOTO, RED)


class Photograph(Flowable):
    def __init__(self, path, width, height, placeholder='Property photograph not supplied'):
        super().__init__();self.path=path;self.width=width;self.height=height;self.placeholder=placeholder

    def draw(self):
        self.canv.setFillColor(PHOTO)
        self.canv.rect(0,0,self.width,self.height,fill=1,stroke=0)
        if self.path and self.path.is_file():
            self.canv.drawImage(str(self.path),0,0,self.width,self.height,preserveAspectRatio=True,anchor='c')
        else:
            label=Paragraph(escape(self.placeholder),ParagraphStyle('photo-placeholder',fontName=branding.BODY,fontSize=7.5,
                            leading=11,alignment=1,textColor=colors.HexColor(branding.MUTED)))
            _,height=label.wrap(self.width-12,self.height)
            label.drawOn(self.canv,6,(self.height-height)/2)


class Layout:
    width=A4[0]-57
    body_top=A4[1]-112.5
    bottom=42

    def __init__(self,record,editor,as_of=None):
        self.as_of=as_of or now()
        self.today=date.fromisoformat(self.as_of[:10])
        self.record=record;self.editor=editor;self.citations=CitationIndex(record,seed=bool(as_of),today=self.today)
        self.ink=colors.HexColor(editor.style['heading_color'])
        self.accent=colors.HexColor(editor.style['accent_color'])
        self.minimum_font=99
        self.density=1

    def paragraph(self,text,size=9,kind='explanation',bold=False,space=5):
        value=self.editor.text(text,kind) if kind else str(text)
        size*=self.editor.style['font_scale']*self.density;self.minimum_font=min(self.minimum_font,size)
        family=self.editor.style['font_family']
        face=branding.HEADING if kind=='heading' and family==branding.BODY else FONTS[family] if bold else family
        style=ParagraphStyle('report',fontName=face,
                             fontSize=size,leading=size*1.22,textColor=self.ink if bold or kind=='heading' else colors.HexColor(branding.INK),spaceAfter=space,
                             splitLongWords=False)
        return Paragraph(self.citations.markup(value),style)

    def heading(self,text):return self.paragraph(text,15,'heading',True,5)

    def chart(self,kind,title,labels,values,height=130,note='',unit='money'):
        if not values or any(value is None for value in values):return None
        import re
        return Chart(kind,self.editor.text(title,'explanation' if re.search(r'\d',title) else 'heading'),
                     [self.editor.text(label,'label') if not re.search(r'\d',str(label)) else str(label) for label in labels],
                     values,height,note,unit,self.editor.style['font_family'],self.accent)

    def prose(self,item):return self.paragraph(item['text']+' ['+', '.join(item['source_ids'])+']',kind=None)

    def table(self,rows,widths,size=8.5,padding=4):
        cells=[[self.paragraph(v,size,'label' if i==0 or j==0 else None,i==0 or str(row[0])=='Total',0) if not isinstance(v,Flowable) else v
                for j,v in enumerate(row)] for i,row in enumerate(rows)]
        import copy
        for i,row in enumerate(cells):
            for j,cell in enumerate(row):
                if isinstance(cell,Paragraph) and i>0:
                    cell.style=copy.copy(cell.style)
                    if j and numeric_cell(rows[i][j]):cell.style.alignment=2
                    value=str(rows[i][j])
                    if value=='FAIL' or value.startswith(('£-','-£','−£')) or (value.startswith(('-', '−')) and numeric_cell(value) and not value.endswith('%')):
                        cell.style.textColor=RED
                    cells[i][j]=Paragraph(cell.text,cell.style)
        return ResponsiveTable(cells,widths,padding*self.density)

    def linked(self,label,url,size=8.5):
        p=self.paragraph(label,size,kind=None,space=0)
        if str(url or '').startswith(('http://','https://')):
            p=Paragraph('<a href="'+escape(url,{'"':'&quot;'})+'" color="'+branding.LINK+'">'+escape(str(label))+'</a>',p.style)
        return p

    def comparisons(self,rows,kind):
        from .reports import gbp
        from .comparisons import maps_url, rent_basis
        import hashlib
        def val(number,decimals=0):return '—' if number is None else format(number,'.'+str(decimals)+'f')
        def limitations(row):
            mapping=[('Bedroom','beds'),('Property type','type'),('Distance','location'),('Floor area','size'),('Tenure','tenure'),
                     ('New-build','new-build'),('listing is','date'),('Sale outside','date'),('Whole-property','rent basis'),('No source','source'),('Subject property','subject itself')]
            return ', '.join(dict.fromkeys(next((label for token,label in mapping if token in reason),'verify') for reason in row.get('limitations',[]))) or 'Review condition / terms'
        commercial=is_commercial(self.record['inputs'])
        result=[['Address / source','Price' if kind!='rent' else 'Rent / mo.','Area basis' if commercial else 'Beds','m² / mi.','Sale date' if kind=='sold' else 'Observed on','Differences / basis']]
        for row in rows[:5]:
            refs=list(row.get('source_ids') or [row.get('source_id') or 'inputs'])
            for url in row.get('evidence_urls') or [row.get('source_url')]:
                if url:refs.append('listing-'+hashlib.sha256(url.encode()).hexdigest()[:12])
            address=[self.linked(row['address'],maps_url(row['address'])),self.paragraph('['+', '.join(refs)+']',7.5,kind=None,space=0)]
            import re
            if not re.search(r'\d',row['address'].split(',')[0]) and not row.get('full_address'):
                address.append(self.paragraph('Unit number unavailable' if commercial else 'House number unavailable',7.5,kind=None,space=0))
            stamp=str(row.get('date') if kind=='sold' else row.get('observed_at') or row.get('date') or '')[:10]
            result.append([address,gbp(row['amount']).replace('.00',''),str(row.get('floor_area_basis') or 'Unknown').upper() if commercial else val(row.get('bedrooms')),
                           val(row.get('floor_area_sqm'),1)+' / '+val(row.get('distance'),2),stamp or 'Unknown',
                           ((str(row.get('lease_terms') or 'Lease terms unknown')+'; ') if commercial else (rent_basis(row)+'; ' if kind=='rent' else ''))+str(row.get('property_type') or 'Type unknown').replace('_',' ')+'; '+limitations(row)])
        # Table supports a small stack of paragraphs inside a cell.
        cells=[]
        for row in result:
            cells.append([Stack(cell) if isinstance(cell,list) else cell for cell in row])
        return self.table(cells,[160,68,36,66,72,136],8.2,2.5)

    def page_header(self,title,subtitle):
        density=self.density
        self.density=1
        titlep=self.paragraph(title,22.5*self.editor.style['heading_size']/23,'heading',True,0)
        titlep.style.fontName=FONTS[self.editor.style['font_family']]
        titlep=Paragraph(titlep.text,titlep.style)
        if titlep.minWidth()>self.width:
            raise ValueError('Page title exceeds the fixed ten-page layout. No text was cut.')
        _,title_height=titlep.wrap(self.width,1000)
        sub=self.paragraph(subtitle,8.25,kind=None,space=0) if subtitle.strip() else None
        if sub:
            sub.style.textColor=MUTED
            sub=Paragraph(sub.text,sub.style)
        sub_height=sub.wrap(self.width,1000)[1] if sub else 0
        subtitle_top=min(A4[1]-88,A4[1]-55-title_height-5.5)
        body_top=min(self.body_top,subtitle_top-sub_height-12)
        self.density=density
        return titlep,title_height,sub,sub_height,subtitle_top,body_top

    def render(self,pages,path,final):
        # Measure before writing: excessive content is an editing error, never
        # an excuse to add pages, clip evidence or silently shrink the document.
        prepared=[]
        for canonical,title,subtitle,story in pages:
            self.editor.page=canonical
            titlep,title_height,sub,sub_height,subtitle_top,body_top=self.page_header(title,subtitle)
            height=sum(item.wrap(self.width,body_top-self.bottom)[1]+item.getSpaceAfter() for item in story)
            if height>body_top-self.bottom:
                raise ValueError('Report page %s (%s) needs shorter wording: %.0f points exceeds the fixed ten-page layout. No text was cut.' % (canonical,title,height))
            prepared.append((canonical,titlep,title_height,sub,sub_height,subtitle_top,body_top,story))
        stream=io.BytesIO();pdf=canvas.Canvas(stream,pagesize=A4)
        pdf.setTitle('Property investment screening - '+self.record['inputs']['property']['address'])
        pdf.setAuthor('Lacewing Analytics')
        for number,(canonical,titlep,title_height,sub,sub_height,subtitle_top,body_top,story) in enumerate(prepared,1):
            if number>1:pdf.showPage()
            self.editor.page=canonical
            branding.page_background(pdf,A4[0],A4[1],header_height=42)
            pdf.setFillColor(GREEN);pdf.rect(0,0,12,A4[1]-42,fill=1,stroke=0)
            branding.header_logo(pdf,63,A4[1]-26)
            pdf.setFillColor(GOLD);pdf.setFont(branding.HEADING,15.75)
            pdf.drawString(63,A4[1]-26.25,'Lacewing Analytics')
            pdf.setFillColor(colors.HexColor(branding.IVORY))
            pdf.setFont(self.editor.style['font_family'],7.125)
            label='DEMO / FICTIONAL' if self.record['mode']=='demo' else 'REVIEWED' if final else 'DRAFT / FOR REVIEW'
            pdf.drawRightString(A4[0]-28.5,A4[1]-24,label)
            titlep.drawOn(pdf,28.5,A4[1]-55-title_height)
            if sub:sub.drawOn(pdf,28.5,subtitle_top-sub_height)
            y=body_top
            for item in story:
                _,height=item.wrap(self.width,y-self.bottom);item.drawOn(pdf,28.5,y-height);y-=height+item.getSpaceAfter()
            pdf.setFillColor(colors.HexColor(branding.MUTED))
            pdf.setFont(self.editor.style['font_family'],6.75);pdf.drawString(28.5,18.4,self.record['id'][:10]+' · r'+str(self.record['revision'])+' · '+self.as_of[:10])
            pdf.drawCentredString(A4[0]/2,18.4,'The Signature Edition')
            pdf.setFillColor(self.ink);pdf.setFont(self.editor.style['font_family'],10.5)
            pdf.drawRightString(A4[0]-28.5,16.9,str(number)+' / 10')
        pdf.save();Path(path).write_bytes(stream.getvalue())
        self.record['report_citations']=self.citations.used
        return {'page_count':len(pages),'condensed':False,'layout_version':5,'report_style':'signature','minimum_font_size':self.minimum_font}


def render_report(record,path,folder,editor,final,cashflow=None,as_of=None):
    from .reports import gbp,pct
    from .comparisons import comparison_summary,months_ago
    from .comparisons import maps_url
    from .internal_review import investigative
    m=record['analysis'];v=m['metrics'];a=m['effective_assumptions'];p=m.get('effective_property',record['inputs']['property'])
    e=record['evidence'];n=record['narrative']['content'];investor=record['inputs']['investor'];L=Layout(record,editor,as_of);W=L.width
    commercial=is_commercial(record['inputs'])
    pages=[]
    def add(number,title,subtitle,build):
        editor.page=number
        body_top=L.page_header(title,subtitle)[-1]
        base={1:1,2:1.07,3:1.03,4:1,5:1.2,6:1.1,7:1.08,8:.96,9:1.08,10:.94}[number]
        # A bounded print typescale accommodates different narratives. Explicit
        # font-size overrides remain exact; no content is removed to make it fit.
        factors=(1,.98,.96,.94,.92,.90) if editor.style['font_scale']==1 else (1,)
        for factor in factors:
            L.density=base*factor
            story=build()
            height=sum(item.wrap(W,10000)[1]+item.getSpaceAfter() for item in story)
            if height<=body_top-L.bottom:break
        pages.append((number,title,subtitle,story))
    span=lambda values:gbp(values[0])+'–'+gbp(values[1]) if values else 'Not established'
    def table(rows,widths=None,**kw):return L.table(rows,widths or [220,W-220],**kw)
    cover,gallery=photo_groups(record)
    no_refurbishment=a['refurb_level']=='none'
    cost_label='Total purchase cost, including tax and fees' if no_refurbishment else 'Total purchase and refurbishment cost'
    def amount(value):
        text=gbp(value)
        return text[:-3] if text.endswith('.00') else text
    def breakdown(total,parts):
        return 'The '+amount(total)+' total consists of '+' + '.join(amount(value)+' '+label for value,label in parts)+'.'
    purchase_parts=[(v['purchase_price'],'purchase price'),(m['sdlt']['total'],'stamp duty'),
                    (a['legal_fees'],'legal fees'),(a['survey_fees'],'survey fees')]
    if a['other_purchase_costs']:purchase_parts.append((a['other_purchase_costs'],'other purchase fees'))
    if not no_refurbishment:purchase_parts.append((v['refurbishment_with_contingency'],'refurbishment including contingency'))
    purchase_parts.append((a['safety_upfront'],'upfront safety provision'))
    if commercial: purchase_parts.append(((v.get('purchase_vat') or 0)-(v.get('recoverable_purchase_vat') or 0),'irrecoverable purchase VAT'))
    purchase_explanation=breakdown(v['total_property_cost'],purchase_parts) if v['total_property_cost'] is not None else 'Total purchase cost unavailable until the missing price / works budget is supplied.'
    if no_refurbishment:purchase_explanation+=' No refurbishment has been selected for this property'
    cash_parts=[(v['purchase_price']-v['loan'] if v['purchase_price'] is not None and v['loan'] is not None else None,'towards the purchase price'),(v['acquisition_costs'],'purchase taxes and fees')]
    if commercial and v.get('recoverable_purchase_vat'):cash_parts.append((v['recoverable_purchase_vat'],'recoverable VAT funded upfront'))
    if v['refurbishment_with_contingency']:cash_parts.append((v['refurbishment_with_contingency'],'refurbishment including contingency'))
    if a['mortgage_fees']:cash_parts.append((a['mortgage_fees'],'finance fees'))
    if a['cash_reserve']:cash_parts.append((a['cash_reserve'],'cash reserve'))
    cash_explanation=breakdown(v['cash_required'],cash_parts).replace(' total consists of ',' cash requirement consists of ',1) if v['cash_required'] is not None else 'Cash requirement unavailable until the dependent acquisition / finance inputs are supplied.'

    def overview_table():
        return table([['Investment overview','Amount / result'],['Listing / offer price',gbp(p['asking_price'])],['Purchase price used',gbp(v['purchase_price'])],
                       ['Purchase price per square foot',gbp(v['purchase_price_per_sqft'])+' / sq ft'],[cost_label,gbp(v['total_property_cost'])],
                       ['Initial cash required / cash available',gbp(v['cash_required'])+' / '+gbp(investor['cash_budget'])],
                       ['Monthly cash before income tax',gbp(v['monthly_cashflow_before_tax'])],['Net yield on total cost',pct(v['net_yield_on_cost_pct'])]],padding=3)
    def introduction():
        location=e.get('location',{});facts=e.get('researched_facts',{})
        nearby=facts.get('property.nearby_places',{})
        loc=', '.join(dict.fromkeys(str(location[k]) for k in ('bua','admin_district','region') if location.get(k))) or p['postcode']+'; location supplied'
        if location.get('admin_ward'):loc+='; electoral ward: '+location['admin_ward']
        loc+='.'
        if location:loc+=' [postcode-location]'
        if nearby:loc+=' '+nearby['text']+' ['+', '.join(nearby['source_ids'])+']'
        else:loc+=' Nearby amenities and transport links have not yet been established.'
        room=facts.get('property.room_layout',{})
        outdoor=p.get('outdoor_space') or 'Not supplied'
        size=(str(p['floor_area_sqm'])+' m²' if p.get('floor_area_sqm') else 'Not supplied')
        provenance=record['inputs'].get('input_provenance',{})
        area_source=provenance.get('property.floor_area_sqm',{}).get('source_id','inputs')
        area_basis=' (supplied)' if area_source=='inputs' else ' (matched PropertyData record)' if area_source in ('property','floor-areas') else ' (cited research)'
        details='Internal area: '+size+(area_basis+' ['+area_source+']' if p.get('floor_area_sqm') else '')+'. '
        outdoor_source=provenance.get('property.outdoor_space',{}).get('source_id','inputs')
        details+='Bedrooms: '+str(p['bedrooms'])+' (supplied). [inputs] '
        details+=('Outdoor space: '+outdoor.replace('_',' ')+(' (supplied)' if outdoor_source=='inputs' else ' (cited research)')+'. ['+outdoor_source+'] ') if p.get('outdoor_space') else 'Outdoor space: Not supplied. '
        details+=('Living areas: '+room['text']+' ['+', '.join(room['source_ids'])+']') if room else 'Separate living-area count is not established.'
        if commercial:
            details='Use: '+p['property_type']+'; '+(p.get('use_class') or 'use class unconfirmed')+'. Area: '+size+' '+p.get('floor_area_basis','unknown').upper()+'. Occupancy: '+p.get('occupancy','unknown')+'. Tenant lease: '+(str(a['lease_remaining_months'])+' months' if a.get('lease_remaining_months') is not None else 'unconfirmed')+'. [inputs, assumptions]'
        price=gbp(p['asking_price'] if p['asking_price'] is not None else v['purchase_price'])
        price_basis=({'listed':'Supplied asking price','under_offer':'Supplied offer price','proposed':'Supplied proposed purchase price'}.get(p.get('price_status'),'Supplied listing / offer price') if p['asking_price'] is not None else m['price_basis'])
        if p.get('price_status')=='proposed':price_basis+='; modelling assumption, not a verified market valuation'
        prepared=L.paragraph('Prepared for '+(investor['name'] or 'Client')+' | Goal: '+(investor['goal'] or 'Not supplied'),8.25)
        address=L.linked(p['address']+', '+p['postcode'],maps_url(p['address']+', '+p['postcode']),21)
        left=[L.heading('Location and nearby amenities'),L.paragraph(loc,10)]
        right=[L.heading('Use, size and occupancy' if commercial else 'Size and accommodation'),L.paragraph(details,10)]
        price_title=L.heading('Price and basis')
        price_text=L.paragraph(price+' — '+price_basis+'. [inputs, model]',10)
        # Keep the map link live while using the approved gold cover typography.
        prepared.style.textColor=PAPER
        prepared=Paragraph(prepared.text,prepared.style)
        address.style.fontName=branding.HEADING;address.style.textColor=GOLD
        address=Paragraph(address.text.replace(branding.LINK,branding.GOLD),address.style)
        price_title.style.textColor=GOLD;price_text.style.textColor=PAPER
        price_title=Paragraph(price_title.text,price_title.style)
        price_text=Paragraph(price_text.text,price_text.style)
        photograph=Photograph(folder/cover['filename'] if cover else None,W,519)
        story=[Cover(prepared,address,Stack([price_title,price_text]),photograph),Columns(left,right)]
        if cover:story.append(L.paragraph(cover.get('caption','')+' | '+cover.get('source',''),8))
        return story
    add(1,'Property screening','',introduction)

    def returns():
        story=[overview_table(),L.paragraph(m['verdict'],17,'heading',True),L.prose(n['summary']),
               L.paragraph('Figures depend on the stated rent, costs and borrowing. Review purchase guidance, comparison evidence and itemised costs before deciding. Income and disposal taxes are excluded unless explicitly budgeted. [model, assumptions]',8.5),
               table([['Measure','Result and calculation'],['Gross rental yield',pct(v['gross_yield_pct'])+' — scheduled rent / purchase price'],
                      ['Net yield on cost',pct(v['net_yield_on_cost_pct'])+' — net operating income / acquisition cost'],
                      ['Cash-on-cash return',pct(v['cash_on_cash_pct'])+' — cash after debt / initial cash'],
                      ['Capitalisation / annual rent reference' if commercial else 'Sale valuation / rental valuation',gbp(m['valuations']['sale'])+' / '+gbp(m['valuations']['rent']*12 if commercial and m['valuations']['rent'] is not None else m['valuations']['rent'])+(' per year' if commercial else ' per month')],
                      ['Annual price / cost scenario; lease rent events' if commercial else 'Annual price / rent / cost growth',
                       ('Price '+pct(a['price_growth_pct'])+'; costs '+pct(a['cost_growth_pct'])+'. Rent follows lease events.' if commercial else pct(a['price_growth_pct'])+' / '+pct(a['rent_growth_pct'])+' / '+pct(a['cost_growth_pct']))]]),
               table([['Ownership','Future property value','Net sale proceeds','Annualised return (IRR)']]+[
                   [str(h['years'])+' years',gbp(h.get('exit',{}).get('sale_price')),gbp(h.get('exit',{}).get('sale_proceeds')),pct(h.get('exit',{}).get('annual_irr_pct'))] for h in m['horizons']], [70,145,145,W-360]),
               L.paragraph('Starting value: '+gbp(m['starting_value'])+'. '+m['value_basis']+'. Sale proceeds deduct debt, selling fees and any supplied disposal-tax budget. [model]',8.5),
               L.paragraph('Works value change: '+gbp(m['refurbishment_value']['uplift'])+'. '+m['refurbishment_value']['basis'].rstrip('.')+'. Separate from annual market growth. ['+', '.join(m['refurbishment_value']['source_ids'])+']',8.5)]
        chart=L.chart('yields','Rental returns · three different measures',['Gross yield','Net yield on cost','Cash-on-cash'],
                      [v['gross_yield_pct'],v['net_yield_on_cost_pct'],v['cash_on_cash_pct']],140,
                      'Percentages use the distinct calculation bases in the table below.','percent')
        return ([chart] if chart else [])+[Columns([story[0]],Stack(story[1:4],colors.HexColor(branding.TINT),9),ratio=.48)]+story[4:]
    add(2,'Returns and growth','Rental yield, capital growth and total investment return are different measures.',returns)

    def purchase():
        guide=m['purchase_guidance'];ref=m['refurbishment_reference']
        story=[table([['Acquisition costs and funding','GBP'],['Purchase price / purchase tax (SDLT)',gbp(v['purchase_price'])+' / '+gbp(m['sdlt']['total'])],
                     ['Legal / survey / other purchase fees',gbp(a['legal_fees'])+' / '+gbp(a['survey_fees'])+' / '+gbp(a['other_purchase_costs'])],
                     ['Upfront fire / safety provision',gbp(a['safety_upfront'])],
                     ['Works including contingency',gbp(v['refurbishment_with_contingency'])],['Mortgage / finance fees / reserve',gbp(v['loan'])+' / '+gbp(a['mortgage_fees'])+' / '+gbp(a['cash_reserve'])],
                     ['Initial cash required',gbp(v['cash_required'])]]),
               L.paragraph(cash_explanation+' [model, assumptions]',8.5),
               L.paragraph(purchase_explanation+' [model, assumptions]',8.5),
               L.paragraph('SDLT: '+m['sdlt']['basis']+'. Fees are budgets unless supported by quotes; the reserve is cash held aside. [tax-1, assumptions]',8.5)]
        if commercial:
            story[1:1]=[L.paragraph('Purchase VAT: '+gbp(v.get('purchase_vat'))+' funded in full at completion; recoverable share '+gbp(v.get('recoverable_purchase_vat'))+'. VAT recovery month: '+str(a.get('vat_recovery_month') or 'not supplied')+'. Net project cost excludes recoverable VAT. [model, assumptions, tax-vat]',8.5)]
        if ref.get('requested',True):story.append(L.paragraph('Refurbishment reference: '+gbp(ref['estimate'])+'. '+ref['basis']+'. '+ref['cost_basis']+'.',8.5))
        story += [L.heading('Purchase price and bidding guidance'),table([['Decision input','Result'],['Matched completed-sale range',span(guide['supported_purchase_range'])],
                  ['Price ceiling for net-yield target',gbp(guide['yield_price_ceiling'])],['Ceiling meeting all configured targets',gbp(guide['all_targets_price_ceiling'])],
                  ['Supported range also meeting targets',span(guide['range_meeting_targets'])]]),
                  L.paragraph('Targets: '+pct(a['min_net_yield_pct'])+' net yield; '+gbp(a['min_monthly_cashflow'])+' monthly cash before tax. '+guide['finance_basis']+' '+guide['reason'],8.5),
                  *([] if investigative(n['purchase_conclusion']) else [L.prose(n['purchase_conclusion'])]),
                  L.paragraph('The ceiling recalculates SDLT, fees, borrowing, reserves and funding needs. It is a return-based limit, not market value or a guaranteed winning bid. Unknown costs remain excluded. [model]',8.5),
                  L.paragraph('Purchase price per square foot: '+gbp(v['purchase_price'])+' / '+str(v['floor_area_sqft'] or 'unknown')+' sq ft = '+gbp(v['purchase_price_per_sqft'])+'. Uses the stated floor area. [inputs, model]',8.5)]
        basis_rows=[['Acquisition / exit input','Effective value and basis']]
        for key,label in [('legal_fees','Legal purchase fees'),('survey_fees','Survey'),('cash_reserve','Cash reserve'),('refurbishment','Works'),('contingency_pct','Works contingency'),('selling_fee_pct','Selling fee incl. VAT'),('sale_legal_fees','Sale legal fees')]:
            if no_refurbishment and key in ('refurbishment','contingency_pct'):continue
            basis_rows.append([label,(pct(a[key]) if key.endswith('_pct') else gbp(a[key]))+' — '+m['modelling_basis'][key]])
        story.append(table(basis_rows,[150,W-150],size=8,padding=2))
        cost_chart=L.chart('stacked','Purchase cost composition · '+gbp(v['total_property_cost']),
                           [{'purchase price':'Purchase','stamp duty':'Stamp duty','legal fees':'Legal','survey fees':'Survey',
                             'irrecoverable purchase VAT':'VAT','upfront safety provision':'Safety','other purchase fees':'Other fees',
                             'refurbishment including contingency':'Works'}.get(label,label) for value,label in purchase_parts],
                           [value for value,label in purchase_parts],102,
                           'Purchase price, tax and fees; the cash reserve is separate.')
        return [Columns([story[0]],story[1:4],ratio=.51)]+([cost_chart] if cost_chart else [])+story[4:]
    add(3,'Purchase costs and bidding','Market evidence and the price needed to meet financial targets are separate.',purchase)

    def cash():
        if not m['monthly']:
            return [L.heading('Financial assessment incomplete'),L.paragraph('Unavailable inputs: '+', '.join(m.get('missing',[]))+'. Known facts and independent calculations are retained. Dependent projections are unavailable.'),
                    table([['Known cash-flow input','Amount'],['Monthly rent',gbp(v['monthly_rent'])],['Stabilised operating income / year',gbp(v['stabilised_noi'])],['Monthly debt payment',gbp(v['monthly_debt_payment'])],['Monthly cash before tax',gbp(v['monthly_cashflow_before_tax'])]])]
        annual=next((h['annual'] for h in m['horizons'] if h['available'] and h['years']==10),m['annual'])
        keys=['scheduled_rent','lost_rent','operating_costs','debt_payment','cashflow_before_tax','tax_budget','cashflow']
        monthly_rows=[['Month','Rent due','Rent lost','Running costs','Mortgage','Before tax','Tax budget','Cash left*']]
        for i,row in enumerate(m['monthly'][:12],1):
            monthly_rows.append([str(i)]+['—' if key=='tax_budget' and a['annual_tax_budget'] is None else '{:,.0f}'.format(row[key]) for key in keys])
        monthly_rows.append(['Total']+['—' if key=='tax_budget' and a['annual_tax_budget'] is None else '{:,.0f}'.format(sum(row[key] for row in m['monthly'][:12])) for key in keys])
        foot='*Income tax not modelled (—); cash left is BEFORE income tax.' if a['annual_tax_budget'] is None else '*Cash left deducts the supplied tax budget; it is not a tax assessment.'
        if commercial:
            foot+=' VAT recovery: '+gbp(v.get('recoverable_purchase_vat'))+' in month '+str(a.get('vat_recovery_month') or 'not supplied')+'; credited once in cash left. Business rates are included in running costs.'
        annual_chart=L.chart('cash',str(len(annual)).capitalize()+'-year annual cash-flow scenario' if len(annual)!=10 else 'Ten-year annual cash-flow scenario',
                             [str(row['year']) for row in annual],[row['cashflow_before_tax'] for row in annual],144,
                             'Before income tax; modelled figures, not a forecast.')
        label='DEMO / FICTIONAL' if record['mode']=='demo' else 'Reviewed' if record.get('approval') else 'DRAFT'
        monthly_heading=Columns([L.heading('First-year cash flow | GBP')],
                                [L.paragraph(label+' | revision '+str(record['revision'])+' | '+p['postcode'],7,kind=None,space=0)],ratio=.66)
        monthly_heading.spaceAfter=0
        story=([annual_chart] if annual_chart else [])+[monthly_heading,
               table(monthly_rows,[40,65,60,82,70,70,68,70],size=7.5,padding=1.4),
               L.paragraph(foot,7.8,kind=None,space=3),
               L.paragraph('Amounts rounded for display. Initial acquisition cash is shown separately. Full precision is in the CSV / JSON.',7.5,kind=None,space=5),
               table([['Year','Rent received','Running costs','Debt service','Cash before tax','Projected equity']]+[[r['year'],gbp(r['collected_rent']),gbp(r['operating_costs']),gbp(r['interest']+r['principal']),gbp(r['cashflow_before_tax']),gbp(r['property_value']-r['loan_balance'])] for r in annual], [30,91,91,91,91,W-394],padding=3),
               L.paragraph('Projected equity is the year-end property value less the outstanding mortgage, before selling costs and tax. Property growth is a scenario; equity is not rental cash flow. [model, assumptions]',8.5),
               L.paragraph('Base vacancy: '+pct(a['void_pct'])+' plus '+str(a['initial_void_months'])+' initial empty months. The CSV contains full monthly schedules for each ownership period; income tax is excluded unless a budget was supplied. [assumptions, model]',8.5)]
        if a['financing']=='cash':story.append(L.paragraph('Cash purchase: no mortgage payments.'))
        else:
            assumed=record['inputs'].get('input_provenance',{}).get('assumptions.mortgage_term_years',{}).get('basis','').startswith('Illustrative default')
            term=str(a['mortgage_term_years'])+('-year modelling assumption (full term not supplied)' if assumed else '-year full term')
            story.append(L.paragraph('Financing: '+a['financing'].replace('_',' ')+'; '+pct(a['interest_rate_pct'])+'; '+term+'. Initial payment: '+gbp(v['monthly_debt_payment'])+'/month. [assumptions, model]',8.5))
            if a.get('fixed_rate_years'):
                reset=a.get('rate_after_fix_pct') if a.get('rate_after_fix_pct') is not None else a['interest_rate_pct']+a['rate_stress_pp']
                story.append(L.paragraph('After the '+str(a['fixed_rate_years'])+'-year fix, the projection uses '+pct(reset)+'. Repayment borrowing is recalculated over the remaining term; refinancing fees/terms are unconfirmed. [assumptions, model]',8.5))
            else:story.append(L.paragraph('No fixed-rate expiry is known. The base projection holds the initial rate constant; the downside tests show rate-change scenarios.',8.5))
        return story
    add(4,'Cash flow and financing','First-year monthly cash flow and ten-year annual projection, before income tax.',cash)

    def stress():
        rows=[['Scenario','Rent / mo.','Rate','Void','Cash / mo.']]
        for s in m['scenarios']:
            label=s['name']
            if s['rent_change_pct']:label+='; rent '+str(s['rent_change_pct'])+'%'
            if s['rate_change_pp']:label+='; rate +'+str(s['rate_change_pp'])+'pp'
            if s['cost_change_pct']:label+='; costs +'+str(s['cost_change_pct'])+'%'
            rows.append([label,gbp(s['monthly_rent']),pct(s['interest_rate_pct']),pct(s['void_pct']),gbp(s['monthly_cashflow'])])
        story=[table(rows,[197,85,60,60,W-402]),L.prose(n['stress_conclusion'])]
        if v['loan']:
            coverage=m['interest_coverage']
            story += [L.heading('Interest-rate comparisons'),table([['Rate','Mortgage / month','Cash before tax / month']]+[[pct(s['rate_pct']),gbp(s['monthly_payment']),gbp(s['monthly_cashflow'])] for s in m['rate_comparisons']],[110,190,238],size=7.8),
                      L.paragraph('Interest coverage: '+pct(coverage['base_pct'])+' initially; '+pct(coverage['stress_pct'])+' at '+pct(coverage['stress_rate_pct'])+'. Scheduled annual rent / annual interest. Lender-specific criteria require a broker check. '+('[model, assumptions]' if commercial else '[model, lender-icr]'),8.5)]
        rows=[['Ownership','Rent collected','Rental cash','Total profit']]
        for h in m['horizons']:
            rows.append([str(h['years'])+' years',gbp(h.get('rental_income')),gbp(h.get('rental_cashflow')),gbp(h.get('exit',{}).get('total_profit'))])
        story += [L.heading('Ownership comparison'),table(rows,[120,140,140,138],size=7.5),L.paragraph('Profit includes rental cash and net sale proceeds after recovering initial investment. Unbudgeted income/disposal taxes are excluded. Interest-only periods beyond the loan term require known refinancing terms. [model]',8.5)]
        chart=L.chart('horizontal','Monthly cash before income tax · downside scenarios',
                      [s['name'] for s in m['scenarios']],[s['monthly_cashflow'] for s in m['scenarios']],168,
                      'Each bar runs from its scenario value to zero.')
        comparisons=Columns(story[2:5],story[5:],ratio=.45) if v['loan'] else Stack(story[2:])
        return ([chart] if chart else [])+story[:2]+[comparisons]
    add(5,'Downside tests and ownership','Changes are quantified; these are scenarios rather than lender offers or forecasts.',stress)

    def property_page():
        profile=matched_profile(record);b=profile.get('building',{});context=m['property_context']
        if commercial:
            rows=[['Property fact','Recorded detail'],
                  ['Type / use class',p['property_type']+' / '+(p.get('use_class') or 'Unconfirmed')],
                  ['Floor area / measurement',str(p.get('floor_area_sqm') or 'Unknown')+' m² / '+p.get('floor_area_basis','unknown').upper()],
                  ['Occupancy / non-domestic EPC',p.get('occupancy','unknown')+' / '+str(p.get('epc_rating') or 'Unknown')],
                  ['Ownership tenure / lease',p['tenure']+' / '+('not applicable' if p['tenure']=='freehold' else str(p.get('lease_years') or 'Unknown')+' years')],
                  ['Tenant lease remaining',str(a.get('lease_remaining_months'))+' months' if a.get('lease_remaining_months') is not None else 'Unconfirmed'],
                  ['Repair / insurance responsibility',p.get('repair_responsibility','unknown')+' / '+p.get('insurance_responsibility','unknown')],
                  ['Rent VAT status',p.get('rent_vat_status','unknown')]]
            rows.extend([fact['label'],fact['value']+(' ['+fact['source_id']+']' if fact.get('source_id') else '')] for fact in context['facts'])
            story=[table(rows,[167,W-167],padding=3),L.paragraph('Tenant lease terms are separate from the ownership lease. Confirm tenant covenant, permitted use, repairing and insurance obligations, access and non-domestic EPC. Supplied facts remain unverified. [inputs, assumptions]',8.5)]
        else:
            rows=[['Property fact','Recorded detail'],['Type / bedrooms / bathrooms',p['property_type'].replace('_',' ')+' / '+str(p['bedrooms'])+' / '+str(p.get('bathrooms') if p.get('bathrooms') is not None else 'Unknown')],
                  ['Floor area / EPC',str(p.get('floor_area_sqm') or 'Unknown')+' m² / '+str(p.get('epc_rating') or 'Unknown')],
                  ['Tenure / remaining lease',p['tenure']+' / '+('not applicable' if p['tenure']=='freehold' else str(p.get('lease_years') or 'Unknown')+' years')],
                  ['Construction / building safety',{'pre_1914':'Before 1914','1914_2000':'1914–2000','2000_onwards':'2000 onwards'}.get(p.get('construction_date'),'Unknown')+' / '+p['cladding_status'].replace('_',' ')]]
            for fact in context['facts']:
                value=fact['value'].replace('No — the matched PropertyData record reports the property outside this designation','No — outside, according to matched provider record')
                rows.append([fact['label'],value+(' ['+fact['source_id']+']' if fact.get('source_id') else '')])
            licence=e.get('researched_facts',{}).get('property.licensing_status')
            rows.append(['Licensing / tenancy use',licence['text']+' ['+', '.join(licence['source_ids'])+']' if licence else 'Local licensing and permitted use unverified; licence fees and material remedial works are not priced. [assumptions]'])
            room_layout=e.get('researched_facts',{}).get('property.room_layout')
            floor=e.get('researched_facts',{}).get('property.floor_level')
            if floor:rows.append(['Floor level',str(floor['value'])+' ['+', '.join(floor['source_ids'])+']'])
            elif b.get('floor_level') is not None:rows.append(['Floor level',str(b['floor_level'])+' [property]'])
            room_note='A total cannot identify the extra room without a floorplan.' if not room_layout else 'The sourced room layout is described below.'
            story=[table(rows,[167,W-167],padding=3),L.paragraph('The profile reports '+str(b.get('habitable_rooms') or 'unknown')+' habitable rooms. This can include living/dining/study rooms as well as bedrooms; it excludes bathrooms and circulation space. '+room_note+' [property, room-definition]',8.5)]
            if room_layout:story.append(L.paragraph(room_layout['text']+' ['+', '.join(room_layout['source_ids'])+']',8.5))
        notes_count=len(story)
        if gallery or not final:
            photos=list(gallery) if final else list(gallery)+[None]*(10-len(gallery))
            columns=5;cell=W/columns;grid=[]
            for offset in range(0,len(photos),columns):
                row=[]
                for idx,photo in enumerate(photos[offset:offset+columns],offset+1):
                    row.append(Photograph(folder/photo['filename'] if photo else None,cell-6,cell-6,'Photo '+str(idx)+' — not supplied'))
                grid.append(row+['']*(columns-len(row)))
            style=[('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),
                   ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]
            story += [L.heading('Property photographs'),Table(grid,colWidths=[cell]*columns,rowHeights=[cell]*len(grid),style=style)]
            if gallery:
                credits=list(dict.fromkeys(photo.get('source') or 'Uploaded by analyst' for photo in gallery))
                story.append(L.paragraph('Photo sources: '+'; '.join(credits)+'.',8))
        if p.get('listing_url'):story.append(L.linked('Open the supplied property listing',p['listing_url']))
        return [Columns([story[0]],Stack(story[1:notes_count],colors.HexColor(branding.TINT),9),ratio=.6)]+story[notes_count:]
    add(6,'Property facts and checks','Provider observations require a matched address; unresolved checks remain explicit.',property_page)

    def market():
        if commercial:
            sample=e.get('market',{}).get('rents-commercial',{})
            rows=[['Quoting-rent context','Observed value'],
                  ['Sample adverts',str(sample.get('points_analysed') or 'Unavailable')],
                  ['Quoted annual rent / sq ft',gbp(sample.get('avg_quoting_rent_per_sqft'))+' / year'],
                  ['Measurement basis',str(sample.get('unit_type') or 'Unconfirmed')],
                  ['Area average annual total',gbp(sample.get('avg_quoting_rent'))]]
            terms=[['Tenant lease scenario','Supplied terms'],['Annual / monthly rent',gbp(v.get('annual_rent'))+' / '+gbp(v['monthly_rent'])],
                   ['Tenant lease remaining',str(a.get('lease_remaining_months'))+' months' if a.get('lease_remaining_months') is not None else 'Unconfirmed'],
                   ['Earliest break month',str(a['break_month']) if a.get('break_month') is not None else 'Not supplied'],
                   ['Contractual rent review',('Month '+str(a['rent_review_month'])+'; '+gbp(a.get('rent_review_annual_rent'))+' / year') if a.get('rent_review_month') is not None else 'Not supplied'],
                   ['Rent-free / initial void',str(a.get('rent_free_months',0))+' / '+str(a.get('initial_void_months',0))+' months'],
                   ['Explicit reletting',('After '+str(a['reletting_void_months'])+' months; '+gbp(a['reletting_annual_rent'])+' / year') if a.get('reletting_void_months') is not None and a.get('reletting_annual_rent') is not None else 'None supplied; rent stops at break / expiry']]
            story=[L.heading('Quoting rents — annual area context'),table(rows),L.paragraph('Quoting rents describe advertised area stock, not the subject lease or achieved rent. Commercial rent and capitalisation estimates require compatible use, size and measurement basis; capitalisation is not completed-sale evidence. [rents-commercial, valuation-commercial-rent, valuation-commercial-sale]',8.5),
                   L.heading('Tenant lease and reletting schedule'),table(terms),L.paragraph('The earliest supplied break is assumed exercised. Income stops at break or expiry unless both a reletting delay and annual rent are supplied. A contractual review is one priced step; no annual rent inflation is applied. Verify tenant covenant and actual lease terms. [assumptions, model]',8.5)]
            return story
        history=property_history(record)
        rows=[['Subject sale date','Recorded price','Source']]+[[r['date'],gbp(r['amount']),L.linked('Recorded transaction',r.get('source_url'))] for r in history[:5]]
        story=[L.heading('This property’s sale history'),table(rows,[145,155,238]) if history else L.paragraph('No exact-match sale history established.')]
        history_story=list(story)
        indicators=[]
        for key,label in [('sales_demand','Sales'),('rental_demand','Rentals')]:
            d=m['market_context'][key];indicators.append(label+': '+str(d['rating'] or 'unavailable')+'; '+'; '.join(x['label']+': '+str(x['value']) for x in d['metrics']))
        activity=L.paragraph('Nearby activity around '+p['postcode']+': '+' | '.join(indicators)+'. These describe the area, not this property’s letting time or vacancy. [demand, demand-rent]',8.5)
        chart=L.chart('line','Local historical prices (GBP)',[row['month'] for row in m['local_growth']],
                      [row['value'] for row in m['local_growth']],178,'Area prices; not a valuation of this property.')
        story=([chart] if chart else [])+[Columns(history_story,[activity],ratio=.47)]
        rows=comparison_summary(record['inputs'],e,'asking',L.today)['candidates']
        story += [L.heading('Top five asking-price comparisons'),L.comparisons(rows,'asking') if rows else L.paragraph('Provider and web research did not establish usable asking-price candidates.'),
                  L.paragraph('Showing '+str(min(5,len(rows)))+' of '+str(len(rows))+' candidates. Asking prices are not achieved sales. “Match gaps” identify incompatible or unverified facts; unknowns are shown as —. Address links open Google Maps; numbered sources retain the original evidence. Street-only adverts have no verified house identity.',8.5)]
        planning=m['property_context']['planning']
        if planning['requested']:story.append(L.paragraph('Nearby planning search: '+str(len(planning['rows']))+' records returned. This limited area search does not establish permission for the proposed works. [planning-applications]',8.5))
        return story
    add(7,'Commercial rents and tenant lease' if commercial else 'Sale history and nearby market','Quoting-rent context and contractual income scenarios.' if commercial else 'The subject’s history, area activity and advertised asking prices are distinct evidence.',market)

    def comparisons():
        if commercial:
            rent=m['rental_evidence'];sold=m['sales_evidence']
            asking=comparison_summary(record['inputs'],e,'asking',L.today)['candidates']
            story=[L.paragraph('Subject rent: '+gbp(v.get('annual_rent'))+' / year; '+gbp(v['monthly_rent'])+' / month, excluding pass-through VAT. '+m['rent_basis']+'. [inputs, assumptions, model]',8.5),
                   L.heading('Advertised unit rents — monthly equivalent'),L.comparisons(rent['candidates'],'rent') if rent['candidates'] else L.paragraph('No usable commercial rental comparisons established.'),
                   L.paragraph('Match subtype, NIA/GIA basis, size, location, lease terms and VAT basis. Quoted rents are not achieved rents; per-square-foot quotations are not total unit rent. Unknown lease terms remain unknown. [assumptions]',8.5),
                   *([] if investigative(n['rent_conclusion']) else [L.prose(n['rent_conclusion'])]),
                   L.heading('Commercial asking prices'),L.comparisons(asking,'asking') if asking else L.paragraph('No usable commercial asking-price comparisons established.'),
                   L.heading('Completed commercial sales'),L.comparisons(sold['candidates'],'sold') if sold['candidates'] else L.paragraph('No compatible completed commercial sales established.'),
                   L.paragraph('Capitalised quoting-rent estimates are indicative references, not completed-sale evidence. Review tenant covenant, lease duration, breaks, repairing obligations and vacant-possession assumptions before relying on values. [valuation-commercial-sale, assumptions]',8.5)]
            return story
        sample=m['market_context']['rent_sample'];bounds=sample['range_80'];rent=m['rental_evidence'];sold=m['sales_evidence']
        detail='Rent used: '+gbp(v['monthly_rent'])+'/month. '+m['rent_basis']+'. '
        if sample['count'] is not None:
            detail+='Local sample: '+str(int(sample['count']))+' adverts; radius '+str(sample['radius_miles'] or 'unverified')+' miles; middle 80% '+span(bounds)+'/month. '
            if e.get('market',{}).get('rent_bedroom_filter_omitted'):detail+='All bedroom counts; area context only. '
        story=[L.paragraph(detail+'[rents, assumptions]',8.5),L.heading('Top five advertised monthly rents'),
               L.comparisons(rent['candidates'],'rent') if rent['candidates'] else L.paragraph('No usable rental candidates established by provider or web research.'),
               L.paragraph('Matched rental evidence: '+str(rent['count'])+' properties; supported range '+span(rent['range'])+'. Advertised rents are not achieved rents; per-room/HMO terms require confirmation.',8.5),
               *([] if investigative(n['rent_conclusion']) else [L.prose(n['rent_conclusion'])]),L.heading('Top five completed sales — last 18 months'),
               L.comparisons(sold['candidates'],'sold') if sold['candidates'] else L.paragraph('No usable completed-sale candidates established.'),
               L.paragraph('Sale window '+months_ago(18,L.today).isoformat()+'–'+L.as_of[:10]+'. Matched sales: '+str(sold['count'])+'; supported range '+span(sold['range'])+'. A range requires at least three dated, compatible properties. “Match gaps” are differences or unknowns, not approved adjustments.',8.5)]
        charts=[]
        for data,title in [(rent,'Advertised rents / month'),(sold,'Completed-sale prices')]:
            candidates=data['candidates'][:5]
            chart=L.chart('evidence',title,[gbp(row['amount']).replace('.00','') for row in candidates],
                          [row['amount'] for row in candidates],98,'Same order as the evidence rows.')
            if chart:charts.append(chart)
        if charts:
            index=4+int(not investigative(n['rent_conclusion']))
            story.insert(index,Columns([charts[0]],[charts[1]]) if len(charts)==2 else charts[0])
        return story
    add(8,'Rental and completed-sale evidence','Up to five candidates per category; sources are linked and unknown facts are retained.',comparisons)

    def conclusion():
        story=[table([['Financial test','Target','Result','Assessment']]+[[t['label'],pct(t['target']) if t['unit']=='%' else gbp(t['target']),pct(t['actual']) if t['unit']=='%' else gbp(t['actual']),'Unavailable' if t['passes'] is None else 'PASS' if t['passes'] else 'FAIL'] for t in m['tests']],[220,95,95,W-410]),
               L.paragraph('Target sources — net yield: '+m['purchase_guidance']['target_basis']['min_net_yield_pct']+'; monthly cash flow: '+m['purchase_guidance']['target_basis']['min_monthly_cashflow']+'. These are configured screening targets, not a universal standard.',8.5),L.heading('Base-case observations')]
        story += [L.prose(item) for item in n['strengths'] if not investigative(item)]
        risk_start=len(story)
        story += [L.heading('Risks and qualifications')]+[L.prose(item) for item in n['risks']]
        funding=m['funding']
        funding_start=len(story)
        story += [L.heading('Funding information'),table([['Cash required / cash available',gbp(funding['cash_required'])+' / '+gbp(funding['cash_available'])],['Initial funding shortfall',gbp(funding.get('initial_shortfall'))],['Projected additional funding / total shortfall',gbp(funding['additional_cash_needed'])+' / '+gbp(funding['shortfall'])]],widths=[205,333],size=8,padding=3),
                  L.paragraph('Funding is separate from the yield and cash-flow tests. Unknown charges are excluded; returns remain conditional on the supplied rent, property facts and cost allowances. [model, assumptions]',8.5),
                  L.paragraph(m['price_growth_basis']+'. '+m['rent_growth_basis']+'. Growth is a scenario, not a forecast.',8.5),L.prose(n['growth_conclusion'])]
        if not m['available']:story.append(L.paragraph('Dependent figures are unavailable: '+', '.join(m['missing'])+'.'))
        # Both narratives retain their original page and all of their citations.
        chart=L.chart('stacked',str(a['holding_years'])+'-year funding shortfall · '+gbp(funding['shortfall']),
                      ['Initial shortfall','Additional funding'],
                      [funding.get('initial_shortfall'),max(0,funding['shortfall']-funding.get('initial_shortfall',0))]
                      if funding['shortfall'] is not None and funding.get('initial_shortfall') is not None else [],
                      108,'Initial gap plus projected unfunded cash needs beyond the reserve.')
        left=story[2:risk_start]+story[funding_start:funding_start+3]+([chart] if chart else [])
        return story[:2]+[Columns(left,story[risk_start:funding_start],ratio=.43)]+story[funding_start+3:]
    add(9,'Investment conclusion','AI reasoning from the supplied figures and cited evidence; material uncertainty is preserved.',conclusion)

    def costs():
        scope={
            'management_pct':'Routine agent management; excludes tenant-finding/renewal fees.',
            'maintenance_pct':'Routine repairs/small replacements; excludes cleaning, refurbishment and major works.',
            'regular_cleaning':'Landlord-paid recurring/common-area cleaning. Confirm frequency, VAT and responsibility.',
            'turnover_cleaning':'Landlord-paid cleaning between tenancies. Confirm price per clean and expected turnovers.',
            'service_charge':'Building/estate charges; check whether cleaning and repairs are already included.',
            'ground_rent':'Lease ground rent, where applicable.',
            'insurance':'Landlord premium; confirm cover and excess with insurer.',
            'compliance':'Inspection/certificate budget; not proof of compliance.',
            'letting_fees':'Tenant-finding/renewal charges, separate from management.',
            'other_annual_costs':'Only the stated budget; no survey-based major-works estimate.',
            'void_cost_monthly':'Vacancy-weighted utilities and other empty-period bills; business rates and lost rent are separate.' if commercial else 'Vacancy-weighted council tax/utilities; lost rent is separate.',
            'business_rates_annual':'Empty-property business rates budget; only supplied relief months apply. Eligibility is unconfirmed.'}
        rows=[['Cost / basis','Annual / monthly','What it covers']]
        for cost in m['operating_costs']:
            basis='Unknown; excluded' if cost['annual'] is None else 'Supplied; unverified' if any(word in cost['basis'].lower() for word in ('user / analyst','analyst supplied','supplied / saved')) else 'Assumption; confirm'
            if commercial and 'unpriced' in cost['basis'].lower():basis='Unpriced; excluded'
            if cost['annual'] is not None and cost['basis'].startswith('Analyst estimate'):basis='Analyst estimate'
            if cost['annual'] is not None and cost['basis'].startswith('Fallback'):basis='Fallback; confirm'
            description=cost['includes'] if cost['key'] in ('management_pct','maintenance_pct') else scope[cost['key']]
            rows.append([cost['label']+'\n'+basis,('Unknown' if cost['annual'] is None else gbp(cost['annual'])+' / '+gbp(cost['monthly'])),description])
        story=[table(rows,[139,116,W-255],size=8.2,padding=3),L.paragraph('Unknown commercial budgets are excluded, not assumed free. Confirm landlord costs during vacancy, tenant recoveries and irrecoverable VAT. Service-charge and works inclusions must be reconciled; rates relief uses only supplied months. [assumptions, tax-rates]' if commercial else 'Unknown budgets are excluded, not assumed free. Safety/compliance includes recurring gas/electrical checks and alarm provision; upfront safety is separate on page 3. Service-charge and works inclusions must be reconciled. [assumptions, safety-gov]',8.2),L.heading('Effective assumptions and basis')]
        defaults_rows=[['Model input','Effective value / basis']]
        for key,label in [('management_pct','Management incl. VAT'),('compliance','Recurring safety'),('safety_upfront','Upfront safety'),('maintenance_pct','Maintenance'),('void_pct','Vacancy'),('cost_growth_pct','Annual cost growth')]:
            value=pct(a[key]) if key.endswith('_pct') else gbp(a[key])
            if key=='maintenance_pct':value+=' of '+('value' if a.get('maintenance_basis')=='value' else 'rent')
            defaults_rows.append([label,value+' — '+m['modelling_basis'][key]])
        story.append(table(defaults_rows,[125,W-125],size=8,padding=2))
        from .tax_notes import tax_explanation
        story += [L.heading('Tax — '+a['buyer_type'].capitalize()+' ownership'),L.paragraph(tax_explanation(a),8.2)]
        story.append(L.paragraph('Sources and Internal review are supplied separately. Full research and calculations remain in JSON. Contains HM Land Registry data © Crown copyright and database right '+L.as_of[:4]+' under the Open Government Licence v3.0.',8))
        labels={'management_pct':'Management','maintenance_pct':'Maintenance','insurance':'Insurance','compliance':'Safety',
                'letting_fees':'Letting / renewal','void_cost_monthly':'Empty-period bills','regular_cleaning':'Regular cleaning',
                'turnover_cleaning':'Tenancy cleaning','service_charge':'Service charge','ground_rent':'Ground rent',
                'other_annual_costs':'Other costs','business_rates_annual':'Business rates'}
        known=[cost for cost in m['operating_costs'] if cost['annual'] is not None and cost['annual']>0]
        chart=L.chart('costs','Known annual running-cost budgets',[labels[cost['key']] for cost in known],
                      [cost['annual'] for cost in known],115,'Bars start at zero. Unknown budgets are excluded; £0 major works is only the stated allowance.')
        return ([chart] if chart else [])+story[:2]+[Columns(story[2:4],story[4:],ratio=.52)]
    add(10,'Running costs and assumptions','Stabilised first-year costs; financing, purchase costs and income tax are separate.',costs)
    L.density=1
    order=record.get('presentation',{}).get('page_order',list(range(1,11)))
    order=[1]+[number for number in order if number!=1]
    return L.render([next(page for page in pages if page[0]==number) for number in order],path,final)

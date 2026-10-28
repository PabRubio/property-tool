"""Ten readable report pages, with measured layout and no overflow pages."""
import io
from pathlib import Path
from xml.sax.saxutils import escape
from urllib.parse import urlencode

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer, Image, Flowable

from .editor import FONTS
from .evidence import matched_profile, property_history
from .photos import photo_groups
from .providers import now
from .source_report import CitationIndex
from .narrative import partition_risks


class Photograph(Flowable):
    def __init__(self, path, width, height):
        super().__init__();self.path=path;self.width=width;self.height=height

    def draw(self):
        self.canv.setFillColor(colors.HexColor('#edf4f2'))
        self.canv.rect(0,0,self.width,self.height,fill=1,stroke=0)
        if self.path and self.path.is_file():
            self.canv.drawImage(str(self.path),0,0,self.width,self.height,preserveAspectRatio=True,anchor='c')
        else:
            self.canv.setFillColor(colors.HexColor('#43575b'));self.canv.setFont('Helvetica',9)
            self.canv.drawCentredString(self.width/2,self.height/2,'Property photograph not supplied')


class Layout:
    width=A4[0]-90
    body_top=A4[1]-118
    bottom=55

    def __init__(self,record,editor):
        self.record=record;self.editor=editor;self.citations=CitationIndex(record)
        self.ink=colors.HexColor(editor.style['heading_color'])
        self.accent=colors.HexColor(editor.style['accent_color'])
        self.minimum_font=99

    def paragraph(self,text,size=9,kind='explanation',bold=False,space=5):
        value=self.editor.text(text,kind) if kind else str(text)
        size*=self.editor.style['font_scale'];self.minimum_font=min(self.minimum_font,size)
        style=ParagraphStyle('report',fontName=FONTS[self.editor.style['font_family']] if bold else self.editor.style['font_family'],
                             fontSize=size,leading=size*1.22,textColor=self.ink,spaceAfter=space)
        return Paragraph(self.citations.markup(value),style)

    def heading(self,text):return self.paragraph(text,11,'heading',True,5)

    def prose(self,item):return self.paragraph(item['text']+' ['+', '.join(item['source_ids'])+']',kind=None)

    def table(self,rows,widths,size=8.5,padding=4):
        cells=[[self.paragraph(v,size,'label' if i==0 or j==0 else None,i==0,0) if not isinstance(v,Flowable) else v
                for j,v in enumerate(row)] for i,row in enumerate(rows)]
        table=Table(cells,colWidths=widths,hAlign='LEFT')
        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf4f2')),
                                   ('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#d9e3e0')),
                                   ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
                                   ('TOPPADDING',(0,0),(-1,-1),padding),('BOTTOMPADDING',(0,0),(-1,-1),padding)]))
        table.spaceAfter=7
        return table

    def linked(self,label,url,size=8.5):
        p=self.paragraph(label,size,kind=None,space=0)
        if str(url or '').startswith(('http://','https://')):
            p=Paragraph('<a href="'+escape(url,{'"':'&quot;'})+'" color="#19766e">'+escape(str(label))+'</a>',p.style)
        return p

    def comparisons(self,rows,kind):
        from .reports import gbp
        def val(number,decimals=0):return '—' if number is None else format(number,'.'+str(decimals)+'f')
        def limitations(row):
            mapping=[('Bedroom','beds'),('Property type','type'),('Distance','location'),('Floor area','size'),('Tenure','tenure'),
                     ('New-build','new-build'),('listing is','date'),('Sale outside','date'),('Whole-property','rent basis'),('No source','source'),('Subject property','subject itself')]
            return ', '.join(dict.fromkeys(next((label for token,label in mapping if token in reason),'unconfirmed') for reason in row.get('limitations',[]))) or 'Compatible recorded facts'
        result=[['Address / evidence','Price' if kind!='rent' else 'Rent / mo.','Beds','m² / mi.','Sale date' if kind=='sold' else 'Observed on','Differences']]
        for row in rows[:5]:
            refs=row.get('source_ids') or [row.get('source_id') or 'inputs']
            maps='https://www.google.com/maps/search/?'+urlencode({'api':1,'query':row['address']+' '+(row.get('postcode') or '')})
            address=[self.linked(row['address'],maps),self.paragraph('['+', '.join(refs)+']',8,kind=None,space=0)]
            stamp=str(row.get('date') if kind=='sold' else row.get('observed_at') or row.get('date') or '')[:10]
            result.append([address,gbp(row['amount']).replace('.00',''),val(row.get('bedrooms')),
                           val(row.get('floor_area_sqm'),1)+' / '+val(row.get('distance'),2),stamp or 'Unknown',limitations(row)])
        # Table supports a small stack of paragraphs inside a cell.
        cells=[]
        for row in result:
            cells.append([Table([[part] for part in cell],colWidths=[149],style=[('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0)]) if isinstance(cell,list) else cell for cell in row])
        return self.table(cells,[157,67,35,59,66,self.width-384],8.2,3)

    def render(self,pages,path,final):
        # Measure before writing: excessive content is an editing error, never
        # an excuse to add pages, clip evidence or silently shrink the document.
        prepared=[]
        for canonical,title,subtitle,story in pages:
            self.editor.page=canonical
            titlep=self.paragraph(title,self.editor.style['heading_size'],'heading',True,0)
            _,title_height=titlep.wrap(self.width,100)
            sub=self.paragraph(subtitle,8.5,kind=None,space=0)
            _,sub_height=sub.wrap(self.width,100)
            subtitle_top=A4[1]-68-title_height-4
            body_top=min(self.body_top,subtitle_top-sub_height-8)
            height=sum(item.wrap(self.width,body_top-self.bottom)[1]+item.getSpaceAfter() for item in story)
            if height>body_top-self.bottom:
                raise ValueError('Report page %s (%s) needs shorter wording: %.0f points exceeds the fixed ten-page layout. No text was cut.' % (canonical,title,height))
            prepared.append((canonical,titlep,title_height,sub,sub_height,subtitle_top,body_top,story))
        stream=io.BytesIO();pdf=canvas.Canvas(stream,pagesize=A4)
        pdf.setTitle('Property investment screening - '+self.record['inputs']['property']['address'])
        for number,(canonical,titlep,title_height,sub,sub_height,subtitle_top,body_top,story) in enumerate(prepared,1):
            if number>1:pdf.showPage()
            self.editor.page=canonical
            pdf.setFillColor(self.ink);pdf.setFont(FONTS[self.editor.style['font_family']],10)
            import os
            pdf.drawString(45,A4[1]-43,os.getenv('REPORT_BRAND','Lacewing Analytics'))
            pdf.setFont(self.editor.style['font_family'],9)
            label='DEMO / FICTIONAL' if self.record['mode']=='demo' else 'REVIEWED' if final else 'DRAFT / FOR REVIEW'
            pdf.drawRightString(A4[0]-45,A4[1]-43,label)
            pdf.setStrokeColor(self.accent);pdf.line(45,A4[1]-55,A4[0]-45,A4[1]-55)
            titlep.drawOn(pdf,45,A4[1]-68-title_height)
            sub.drawOn(pdf,45,subtitle_top-sub_height)
            y=body_top
            for item in story:
                _,height=item.wrap(self.width,y-self.bottom);item.drawOn(pdf,45,y-height);y-=height+item.getSpaceAfter()
            pdf.setStrokeColor(colors.HexColor('#d9e3e0'));pdf.line(45,42,A4[0]-45,42)
            pdf.setFont('Helvetica',8);pdf.drawString(45,29,self.record['id'][:10]+' | r'+str(self.record['revision'])+' | '+now()[:10])
            pdf.drawRightString(A4[0]-45,29,str(number)+' / 10')
        pdf.save();Path(path).write_bytes(stream.getvalue())
        self.record['report_citations']=self.citations.used
        return {'page_count':len(pages),'condensed':False,'layout_version':2,'minimum_font_size':self.minimum_font}


def render_report(record,path,folder,editor,final,cashflow):
    from .reports import gbp,pct,yield_chart,line_chart
    from .comparisons import comparison_summary,months_ago
    m=record['analysis'];v=m['metrics'];a=m['effective_assumptions'];p=m.get('effective_property',record['inputs']['property'])
    e=record['evidence'];n=record['narrative']['content'];investor=record['inputs']['investor'];L=Layout(record,editor);W=L.width
    pages=[]
    def add(number,title,subtitle,build):
        editor.page=number;pages.append((number,title,subtitle,build()))
    span=lambda values:gbp(values[0])+'–'+gbp(values[1]) if values else 'Not established'
    def table(rows,widths=None,**kw):return L.table(rows,widths or [220,W-220],**kw)
    cover,gallery=photo_groups(record)
    no_refurbishment=not m['refurbishment_reference']['included']
    cost_label='Total purchase cost, including tax and fees' if no_refurbishment else 'Total purchase and refurbishment cost'
    def amount(value):
        text=gbp(value)
        return text[:-3] if text.endswith('.00') else text
    def breakdown(total,parts):
        if total is None or any(value is None for value,label in parts):return 'Total not yet calculated. '+m.get('unavailable_reason','')
        return 'The '+amount(total)+' total consists of '+' + '.join(amount(value)+' '+label for value,label in parts)+'.'
    purchase_parts=[(v['purchase_price'],'purchase price'),(m['sdlt']['total'],'stamp duty'),
                    (a['legal_fees'],'legal fees'),(a['survey_fees'],'survey fees')]
    if a['other_purchase_costs']:purchase_parts.append((a['other_purchase_costs'],'other purchase fees'))
    if a.get('fire_safety_upfront'):purchase_parts.append((a['fire_safety_upfront'],'initial fire / safety works'))
    if not no_refurbishment:purchase_parts.append((v['refurbishment_with_contingency'],'refurbishment including contingency'))
    purchase_explanation=breakdown(v['total_property_cost'],purchase_parts)
    if no_refurbishment:purchase_explanation+=' No refurbishment was selected in this brief.'
    cash_parts=[(v['purchase_price']-v['loan'] if v['purchase_price'] is not None and v['loan'] is not None else None,'towards the purchase price'),(v['acquisition_costs'],'purchase taxes and fees')]
    if v['refurbishment_with_contingency']:cash_parts.append((v['refurbishment_with_contingency'],'refurbishment including contingency'))
    if a['mortgage_fees']:cash_parts.append((a['mortgage_fees'],'finance fees'))
    if a['cash_reserve']:cash_parts.append((a['cash_reserve'],'cash reserve'))
    cash_explanation=breakdown(v['cash_required'],cash_parts).replace(' total consists of ',' cash requirement consists of ',1)

    def overview():
        amenities=e.get('researched_facts',{}).get('context.amenities',{})
        location=amenities.get('text') or p['postcode']+'. '+str(e.get('location',{}).get('admin_district') or e.get('location',{}).get('region') or 'England')
        if amenities.get('source_ids'):location+=' ['+', '.join(amenities['source_ids'])+']'
        rooms=e.get('researched_facts',{}).get('property.room_layout',{}).get('value')
        living=rooms.get('living_rooms') if isinstance(rooms,dict) else None
        facts=(str(p['bedrooms'])+' bedrooms (supplied); '+str(p.get('floor_area_sqm') or 'area not supplied')+' m²; '+
               (str(living)+' living rooms' if living is not None else 'living-room count not established')+'; '+
               (p.get('outdoor_space') or 'outdoor space not supplied').replace('_',' ')+'.')
        price_status={'listed':'Asking price','under_offer':'Offer price','proposed':'Proposed purchase price'}.get(p.get('price_status'),'Supplied price')
        price=price_status+': '+gbp(p.get('asking_price'))+'. Modelled purchase: '+gbp(v['purchase_price'])+'. '+m['price_basis']+'.'
        if m['sales_evidence']['range']:price+=' Matched completed-sale range: '+span(m['sales_evidence']['range'])+'.'
        return [L.paragraph('Prepared for '+(investor['name'] or 'Client')+' | Goal: '+(investor['goal'] or 'Not supplied')),
                Photograph(folder/cover['filename'] if cover else None,W,185),Spacer(1,7),
                L.paragraph((cover.get('caption','')+' | '+cover.get('source','')) if cover else '',8),
                L.heading(m['verdict']),L.prose(n['summary']),
                table([['Location and nearby amenities'],[location]],[W],size=9),
                table([['The property'],[facts]],[W],size=9),
                table([['Price and evidence'],[price]],[W],size=9),
                L.paragraph('Detailed returns, funding and assumptions follow. Income and disposal taxes are excluded unless a budget is supplied.',8.5)]
    add(1,'Property investment screening',p['address']+', '+p['postcode'],overview)

    def returns():
        story=[yield_chart([v['gross_yield_pct'],v['net_yield_on_cost_pct'],v['cash_on_cash_pct']],90) if m['available'] else L.paragraph('Return measures are not yet calculated. '+m['unavailable_reason']),Spacer(1,6),
               table([['Measure','Result and calculation'],['Gross rental yield',pct(v['gross_yield_pct'])+' — scheduled rent / purchase price'],
                      ['Net yield on cost',pct(v['net_yield_on_cost_pct'])+' — net operating income / acquisition cost'],
                      ['Cash-on-cash return',pct(v['cash_on_cash_pct'])+' — cash after debt / initial cash'],
                      ['Monthly cash before income tax',gbp(v['monthly_cashflow_before_tax'])],
                      ['Sale valuation / rental valuation',gbp(m['valuations']['sale'])+' / '+gbp(m['valuations']['rent'])+' per month'],
                      ['Annual price / rent / cost growth',pct(a['price_growth_pct'])+' / '+pct(a['rent_growth_pct'])+' / '+pct(a['cost_growth_pct'])]]),
               L.paragraph(m['price_growth_basis']+'. '+m['rent_growth_basis']+'. Costs use an illustrative growth assumption.',8.5),
               table([['Ownership','Future property value','Net sale proceeds','Annualised return (IRR)']]+[
                   [str(h['years'])+' years',gbp(h['exit']['sale_price']) if h['available'] else 'Not modelled',gbp(h['exit']['sale_proceeds']) if h['available'] else 'Not modelled',pct(h['exit']['annual_irr_pct']) if h['available'] else 'Not modelled'] for h in m['horizons']], [70,145,145,W-360]),
               L.paragraph('Starting value: '+gbp(m['starting_value'])+'. '+m['value_basis']+'. Sale proceeds deduct debt, selling fees and any supplied disposal-tax budget. [model]',8.5),
               L.prose(n['growth_conclusion'])]
        uplift=m['refurbishment_uplift']
        if uplift['included']:
            story.append(L.paragraph('Refurbishment value increase: '+gbp(uplift['amount'])+' after '+str(uplift['completion_month'])+' initial empty months (zero means complete at purchase). '+uplift['basis']+' ['+', '.join(uplift['source_ids'])+']',8.5))
            story.append(L.paragraph('Without that uplift: sale value '+gbp(uplift['no_uplift_sale_price'])+'; total profit '+gbp(uplift['no_uplift_total_profit'])+' at the selected holding period, with the same works costs. Selected rent is not increased again.',8.5))
        else:story.append(L.paragraph('No refurbishment selected in this brief; no associated cost or value increase is included.',8.5))
        story.append(L.paragraph('Growth is a scenario, not a forecast. Automated valuations are separate from asking prices, indexed historic estimates and comparison medians. '+('The standard residential valuation endpoints do not support this bedroom count.' if p['bedrooms']>5 else ''),8.5))
        return story
    add(2,'Returns and growth','Rental yield, capital growth and total investment return are different measures.',returns)

    def purchase():
        guide=m['purchase_guidance'];ref=m['refurbishment_reference']
        story=[table([['Acquisition costs and funding','GBP'],['Purchase price / purchase tax (SDLT)',gbp(v['purchase_price'])+' / '+gbp(m['sdlt']['total'])],
                     ['Legal / survey / other purchase fees',gbp(a['legal_fees'])+' / '+gbp(a['survey_fees'])+' / '+gbp(a['other_purchase_costs'])],
                     ['Works including contingency',gbp(v['refurbishment_with_contingency'])],['Mortgage / finance fees / reserve',gbp(v['loan'])+' / '+gbp(a['mortgage_fees'])+' / '+gbp(a['cash_reserve'])],
                     ['Initial fire / safety works',gbp(a.get('fire_safety_upfront'))+' (excluded if unpriced)'],
                     ['Total property cost / initial cash',gbp(v['total_property_cost'])+' / '+gbp(v['cash_required'])],
                     ['Cash available / extra funding needed',gbp(m['funding']['cash_available'])+' / '+gbp(m['funding']['extra_cash_needed'])]]),
               L.paragraph(cash_explanation+' [model, assumptions]',8.5),
               L.paragraph('SDLT: '+m['sdlt']['basis']+'. Fees are budgets unless supported by quotes; the reserve is cash held aside. [tax-1, assumptions]',8.5)]
        if ref.get('requested',True):story.append(L.paragraph('Refurbishment reference: '+gbp(ref['estimate'])+'. '+ref['basis']+'. '+ref['cost_basis']+'.',8.5))
        story += [L.heading('Purchase price and bidding guidance'),table([['Decision input','Result'],['Matched completed-sale range',span(guide['supported_purchase_range'])],
                  ['Price ceiling for net-yield target',gbp(guide['yield_price_ceiling'])],['Ceiling meeting return targets',gbp(guide['all_targets_price_ceiling'])],
                  ['Separate funding ceiling',gbp(guide['funding_price_ceiling'])],
                  ['Supported range also meeting targets',span(guide['range_meeting_targets'])]]),
                  L.paragraph('Targets: '+pct(a['min_net_yield_pct'])+' net yield; '+gbp(a['min_monthly_cashflow'])+' monthly cash before tax. '+guide['finance_basis']+' '+guide['reason'],8.5),
                  L.prose(n['purchase_conclusion']),
                  L.paragraph('The ceiling recalculates SDLT, fees, borrowing, reserves and funding needs. It is a return-based limit, not market value or a guaranteed winning bid. Unknown costs remain excluded. [model]',8.5),
                  L.paragraph('Purchase price per square foot: '+gbp(v['purchase_price'])+' / '+str(v['floor_area_sqft'] or 'unknown')+' sq ft = '+gbp(v['purchase_price_per_sqft'])+'. Supplied area is preserved where it conflicts with a provider estimate. [inputs, model]',8.5)]
        return story
    add(3,'Purchase costs and bidding','Market evidence and the price needed to meet financial targets are separate.',purchase)

    def cash():
        annual=next((h['annual'] for h in m['horizons'] if h['available'] and h['years']==10),m['annual'])
        story=[Image(io.BytesIO(cashflow.read_bytes()),width=W,height=W*1040/1900),Spacer(1,8),
               table([['Year','Rent received','Running costs','Debt service','Cash before tax']]+[[r['year'],gbp(r['collected_rent']),gbp(r['operating_costs']),gbp(r['interest']+r['principal'] if r['interest'] is not None and r['principal'] is not None else None),gbp(r['cashflow_before_tax'])] for r in annual], [33,118,118,118,W-387],padding=3),
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
            story += [L.heading('Interest-rate comparisons'),table([['Rate','Mortgage / month','Cash before tax / month']]+[[pct(s['rate_pct']),gbp(s['monthly_payment']),gbp(s['monthly_cashflow'])] for s in m['rate_comparisons']],[80,180,W-260]),
                      L.paragraph('Interest coverage: '+pct(coverage['base_pct'])+' initially; '+pct(coverage['stress_pct'])+' at '+pct(coverage['stress_rate_pct'])+'. Scheduled annual rent / annual interest. These figures do not establish lender eligibility. [model, lender-icr]',8.5)]
        rows=[['Ownership','Rent collected','Rental cash','Total profit']]
        for h in m['horizons']:
            rows.append([str(h['years'])+' years',gbp(h['rental_income']) if h['available'] else 'Not modelled',gbp(h['rental_cashflow']) if h['available'] else 'Not modelled',gbp(h['exit']['total_profit']) if h['available'] else 'Not modelled'])
        story += [L.heading('Ownership comparison'),table(rows,[80,140,140,W-360]),L.paragraph('Profit includes rental cash and net sale proceeds after recovering initial investment. Unbudgeted income/disposal taxes are excluded. Interest-only periods beyond the loan term require known refinancing terms. [model]',8.5)]
        return story
    add(5,'Downside tests and ownership','Changes are quantified; these are scenarios rather than lender offers or forecasts.',stress)

    def property_page():
        profile=matched_profile(record);b=profile.get('building',{});context=m['property_context']
        rows=[['Property fact','Recorded detail'],['Type / bedrooms / bathrooms',p['property_type'].replace('_',' ')+' / '+str(p['bedrooms'])+' / '+str(p.get('bathrooms') if p.get('bathrooms') is not None else 'Unknown')],
              ['Floor area / EPC',str(p.get('floor_area_sqm') or 'Unknown')+' m² / '+str(p.get('epc_rating') or 'Unknown')],
              ['Tenure / remaining lease',p['tenure']+' / '+('not applicable' if p['tenure']=='freehold' else str(p.get('lease_years') or 'Unknown')+' years')],
              ['Construction / building safety',{'pre_1914':'Before 1914','1914_2000':'1914–2000','2000_onwards':'2000 onwards'}.get(p.get('construction_date'),'Unknown')+' / '+p['cladding_status'].replace('_',' ')]]
        for fact in context['facts']:
            value=fact['value'].replace('No — the matched PropertyData record reports the property outside this designation','No — outside, according to matched provider record')
            rows.append([fact['label'],value+(' ['+fact['source_id']+']' if fact.get('source_id') else '')])
        room_layout=e.get('researched_facts',{}).get('property.room_layout')
        floor=e.get('researched_facts',{}).get('property.floor_level')
        if floor:rows.append(['Floor level',str(floor['value'])+' ['+', '.join(floor['source_ids'])+']'])
        elif b.get('floor_level') is not None:rows.append(['Floor level',str(b['floor_level'])+' [property]'])
        room_note='The supplied bedroom count is used in the analysis.' if not room_layout else 'The sourced room layout is described below.'
        story=[table(rows,[167,W-167],padding=3),L.paragraph('The profile reports '+str(b.get('habitable_rooms') or 'unknown')+' habitable rooms. This can include living/dining/study rooms as well as bedrooms; it excludes bathrooms and circulation space. '+room_note+' [property, room-definition]',8.5)]
        if room_layout:story.append(L.paragraph(room_layout['text']+' ['+', '.join(room_layout['source_ids'])+']',8.5))
        from .tax_summary import tax_summary
        story += [L.heading('Tax review — '+('company' if a['buyer_type']=='company' else 'individual')+' ownership'),L.paragraph(tax_summary(m),8.5)]
        if gallery:
            columns=5 if len(gallery)>6 else 3;cell=(W-12)/columns;grid=[]
            for offset in range(0,len(gallery),columns):
                row=[]
                for photo in gallery[offset:offset+columns]:row.append(Photograph(folder/photo['filename'],cell-5,60 if len(gallery)>6 else 88))
                grid.append(row+['']*(columns-len(row)))
            story += [L.heading('Property photographs'),Table(grid,colWidths=[W/columns]*columns)]
            credits=list(dict.fromkeys(photo.get('source') or 'Uploaded by analyst' for photo in gallery))
            story.append(L.paragraph('Photo sources: '+'; '.join(credits)+'.',8))
        else:story.append(L.paragraph('No additional property photographs supplied.',8.5))
        if p.get('listing_url'):story.append(L.linked('Open the supplied property listing',p['listing_url']))
        return story
    add(6,'Property facts and tax','Supplied facts, matched evidence and the selected ownership structure.',property_page)

    def market():
        history=property_history(record)
        rows=[['Subject sale date','Recorded price','Source']]+[[r['date'],gbp(r['amount']),L.linked('Recorded transaction',r.get('source_url'))] for r in history[:5]]
        story=[L.heading('This property’s sale history'),table(rows,[110,125,W-235]) if history else L.paragraph('No exact-match sale history established.')]
        if m['local_growth']:story += [line_chart([dict(r,index=r['value']) for r in m['local_growth']],'Local historical prices (GBP)',105),Spacer(1,5)]
        indicators=[]
        for key,label in [('sales_demand','Sales'),('rental_demand','Rentals')]:
            d=m['market_context'][key];indicators.append(label+': '+str(d['rating'] or 'unavailable')+'; '+'; '.join(x['label']+': '+str(x['value']) for x in d['metrics']))
        story.append(L.paragraph('Nearby activity around '+p['postcode']+': '+' | '.join(indicators)+'. These describe the area, not this property’s letting time or vacancy. [demand, demand-rent]',8.5))
        rows=client_comparisons(comparison_summary(record['inputs'],e,'asking')['candidates'],p)
        story += [L.heading('Top five asking-price comparisons'),L.comparisons(rows,'asking') if rows else L.paragraph('Provider and web research did not establish usable asking-price candidates.'),
                  L.paragraph('Showing up to five of the best identified comparisons; differences appear in the table. Asking prices are not achieved sales. “Observed on” is the date the listing was observed, not a sale date. Addresses open Google Maps; numbered references open the evidence.',8.5)]
        planning=m['property_context']['planning']
        if planning['requested']:story.append(L.paragraph('Nearby planning search: '+str(len(planning['rows']))+' records returned. This limited area search does not establish permission for the proposed works. [planning-applications]',8.5))
        return story
    add(7,'Sale history and nearby market','The subject’s history, area activity and advertised asking prices are distinct evidence.',market)

    def comparisons():
        sample=m['market_context']['rent_sample'];bounds=sample['range_80'];rent=m['rental_evidence'];sold=m['sales_evidence']
        detail='Rent used: '+gbp(v['monthly_rent'])+'/month. '+m['rent_basis']+'. '
        if sample['count'] is not None:
            detail+='Local sample: '+str(int(sample['count']))+' adverts; radius '+str(sample['radius_miles'] or 'unverified')+' miles; middle 80% '+span(bounds)+'/month. '
            if e.get('market',{}).get('rent_bedroom_filter_omitted'):detail+='All bedroom counts; area context only. '
        story=[L.paragraph(detail+'[rents, assumptions]',8.5),L.heading('Top five advertised monthly rents'),
               L.comparisons(client_comparisons(rent['candidates'],p),'rent') if client_comparisons(rent['candidates'],p) else L.paragraph('No identified, bedroom-compatible rental comparisons established.'),
               L.paragraph('Matched rental evidence: '+str(rent['count'])+' properties; supported range '+span(rent['range'])+'. Advertised rents are not achieved rents; per-room prices are not treated as whole-house rents.',8.5),
               L.prose(n['rent_conclusion']),L.heading('Top five completed sales — last 18 months'),
               L.comparisons(client_comparisons(sold['candidates'],p),'sold') if client_comparisons(sold['candidates'],p) else L.paragraph('No identified, bedroom-compatible completed-sale comparisons established.'),
               L.paragraph('Sale window '+months_ago(18).isoformat()+'–'+now()[:10]+'. Matched sales: '+str(sold['count'])+'; supported range '+span(sold['range'])+'. A range requires at least three dated, compatible properties. “Match gaps” are differences or unknowns, not approved adjustments.',8.5)]
        return story
    add(8,'Rental and completed-sale evidence','Up to five candidates per category; sources are linked and unknown facts are retained.',comparisons)

    def conclusion():
        story=[table([['Financial test','Target','Result','Assessment']]+[[t['label'],pct(t['target']) if t['unit']=='%' else gbp(t['target']),'Not available' if t['actual'] is None else format(t['actual'],'.4f')+'%' if t['unit']=='%' else gbp(t['actual']),'Not assessed' if t['passes'] is None else 'PASS' if t['passes'] else 'FAIL'] for t in m['tests']],[220,95,95,W-410]),
               L.paragraph('Target sources — net yield: '+m['purchase_guidance']['target_basis']['min_net_yield_pct']+'; monthly cash flow: '+m['purchase_guidance']['target_basis']['min_monthly_cashflow']+'. These are configured screening targets, not a universal standard.',8.5),L.heading('Reasons to investigate')]
        story += [L.prose(item) for item in n['strengths']]
        story += [L.heading('Risks and qualifications')]+[L.prose(item) for item in partition_risks(n)[0]]
        story.append(L.paragraph('Conclusions depend on the stated property basis, comparison limitations and excluded costs. Cash availability is a funding consideration, separate from these return targets.',8.5))
        return story
    add(9,'Investment conclusion','Assessment of the supplied figures and cited evidence.',conclusion)

    def costs():
        scope={
            'management_pct':'Routine agent management; excludes tenant-finding/renewal fees.',
            'maintenance_pct':'Routine repairs/small replacements; excludes cleaning, refurbishment and major works.',
            'regular_cleaning':'Landlord-paid recurring/common-area cleaning, if budgeted.',
            'turnover_cleaning':'Landlord-paid cleaning between tenancies, if budgeted.',
            'service_charge':'Building/estate charges. Any covered repairs or cleaning belong here only.',
            'ground_rent':'Lease ground rent, where applicable.',
            'insurance':'Landlord insurance premium allowance; cover and excess are not established.',
            'compliance':'Inspection/certificate budget; not proof of compliance.',
            'fire_safety_annual':'Additional fire checks/servicing; excludes amounts already in compliance.',
            'licensing_annual':'Annual share of applicable property licence fees; unpriced if unknown.',
            'letting_fees':'Tenant-finding/renewal charges, separate from management.',
            'other_annual_costs':'Only the stated budget; no survey-based major-works estimate.',
            'void_cost_monthly':'Vacancy-weighted council tax/utilities; lost rent is separate.'}
        rows=[['Cost / basis','Annual / monthly','What it covers']]
        for cost in m['operating_costs']:
            basis='Unknown; excluded' if cost['annual'] is None else 'Supplied' if cost['basis']=='User / analyst input' else 'Modelling allowance'
            label=cost['label']+((' ('+str(a[cost['key']])+'%)') if cost['key'] in ('management_pct','maintenance_pct') else '')
            rows.append([label+'\n'+basis,('Unknown' if cost['annual'] is None else gbp(cost['annual'])+' / '+gbp(cost['monthly'])),scope[cost['key']]])
        policy=m['cost_policy']['management_basis'].replace('; replace with an applicable agent quote','; an unquoted allowance')
        story=[table(rows,[145,116,W-261],size=8.2,padding=2),L.paragraph('Unknown budgets are excluded, not assumed free. '+policy+'. Annual cleaning depends on frequency and landlord responsibility. Service-charge items must not be counted twice.',8.2),L.heading('Additional modelling assumptions')]
        # These complement amounts/rates explicitly shown on pages 2–5 and the
        # cost table above. Include zero, unset and tax/exit values, not just gains.
        labels={'contingency_pct':'Works contingency %','refurb_uplift_pct_of_cost':'Fallback uplift / works cost %',
                'selling_fee_pct':'Selling fee %','sale_legal_fees':'Sale legal £','early_repayment_fee':'Early repayment £',
                'void_cost_monthly':'Empty-month bills £','annual_tax_budget':'Annual tax £','sale_tax_budget':'Disposal tax £',
                'sdlt_override':'SDLT override £','deposit_amount':'Supplied deposit £','deposit_pct':'Deposit %',
                'mortgage_amount':'Supplied loan £','ltv_pct':'Effective LTV %','fixed_rate_years':'Fixed period years',
                'rate_after_fix_pct':'Supplied reset rate %','refurb_value_uplift':'Supplied uplift £',
                'holding_years':'Selected ownership years','rent_stress_pct':'Rent stress reduction %',
                'rate_stress_pp':'Rate stress rise pp','cost_stress_pct':'Cost stress rise %'}
        values=[label+': '+('unset' if a.get(key) is None else str(a[key])) for key,label in labels.items()]
        story.append(L.paragraph('; '.join(values)+'.',8.2))
        story.append(L.paragraph('Amounts and rates are modelling assumptions unless labelled supplied or linked to evidence. Refurbishment settings apply only when works are selected. Unset overrides use the stated calculation basis. Buyer: '+a['buyer_type']+'; additional property: '+str(a['additional_property'])+'; nonresident: '+str(a['nonresident'])+'; corporate relief confirmed: '+str(a['corporate_relief_confirmed'])+'; new lease: '+str(a['new_lease'])+'.',8.2))
        story.append(L.paragraph('The separate Sources document lists the cited references. Full research logs and calculations remain in the saved record / JSON export. Contains HM Land Registry data © Crown copyright and database right '+now()[:4]+' under the Open Government Licence v3.0.',8))
        return story
    add(10,'Running costs and assumptions','Stabilised first-year costs; financing, purchase costs and income tax are separate.',costs)
    order=record.get('presentation',{}).get('page_order',list(range(1,11)))
    return L.render([next(page for page in pages if page[0]==number) for number in order],path,final)


def client_comparisons(rows, property_):
    from .comparisons import exact_address
    return [r for r in rows if exact_address(r) and r.get('source_url')][:5]

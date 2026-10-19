import csv
import io
import os
import re
from pathlib import Path
from xml.sax.saxutils import escape
from PIL import Image as PILImage, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph
from reportlab.graphics.shapes import Drawing, Rect, String, Line, PolyLine
from .providers import now
from .editor import ReportEditor, FONTS

INK = colors.HexColor("#18333c")
TEAL = colors.HexColor("#19766e")
LIGHT = colors.HexColor("#edf4f2")
RED = colors.HexColor("#a3342a")


def gbp(n):
    return "Not available" if n is None else "£{:,.2f}".format(n)


def pct(n):
    return "Not available" if n is None else "{:.2f}%".format(n)


def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    # ReportLab includes Vera on platforms lacking system fonts.
    import reportlab
    p = Path(reportlab.__file__).parent / "fonts/Vera.ttf"
    return ImageFont.truetype(str(p), size) if p.exists() else ImageFont.load_default()


def cashflow_image(record, path, editor=None):
    editor=editor or ReportEditor(record);editor.page=4
    m = record["analysis"]
    im = PILImage.new("RGB", (1900, 1040), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((0,0,1900,120), fill=editor.style["heading_color"])
    d.text((35,22), editor.text("FIRST-YEAR CASH FLOW | GBP"), fill="white", font=font(34))
    label = "DEMO / FICTIONAL" if record["mode"] == "demo" else "Reviewed" if record.get("approval") else "DRAFT"
    d.text((35,72), "%s | revision %s | %s" % (label, record["revision"], record["inputs"]["property"]["postcode"]), fill="white", font=font(22))
    cols = [("Month", None, 40), ("Rent due", "scheduled_rent", 190), ("Rent lost", "lost_rent", 430), ("Running costs", "operating_costs", 665), ("Mortgage", "debt_payment", 950), ("Before tax", "cashflow_before_tax", 1200), ("Tax budget", "tax_budget", 1430), ("Cash left*", "cashflow", 1660)]
    for title, _, x in cols: d.text((x,146), editor.text(title), fill=editor.style["heading_color"], font=font(23))
    for idx, row in enumerate(m["monthly"][:12]):
        y = 204 + idx * 53
        if idx % 2 == 0: d.rectangle((20,y-8,1880,y+43), fill="#edf4f2")
        for _, key, x in cols:
            val = str(idx+1) if key is None else "{:,.0f}".format(row[key])
            d.text((x,y), val, fill="#a3342a" if key and row[key]<0 else "#18333c", font=font(25))
    y = 866
    d.line((25,y-12,1875,y-12), fill=editor.style["heading_color"], width=3)
    for _, key, x in cols:
        val = "Total" if key is None else "{:,.0f}".format(sum(r[key] for r in m["monthly"][:12]))
        d.text((x,y), val, fill=editor.style["heading_color"], font=font(25))
    foot = "*Income tax excluded; cash left is before income tax." if m["effective_assumptions"]["annual_tax_budget"] is None else "*Cash left deducts the supplied tax budget; it is not a tax assessment."
    d.text((35,942), foot, fill="#43575b", font=font(23))
    d.text((35,981), "Amounts rounded for display. Initial acquisition cash is shown separately. Full precision is in the CSV / JSON.", fill="#43575b", font=font(21))
    im.save(str(path), "PNG")


def bar_chart(labels, values, title, width=495, height=200):
    draw = Drawing(width, height)
    draw.add(String(0, height-12, title, fontName="Helvetica-Bold", fontSize=11, fillColor=INK))
    low, high = min(0, min(values)), max(0, max(values))
    if high == low: high = low + 1
    plot_y, plot_h = 44, height-85
    scale = plot_h/(high-low)
    zero = plot_y-low*scale
    draw.add(Line(0, zero, width, zero, strokeColor=colors.lightgrey))
    step = width/len(values)
    for idx,(label,value) in enumerate(zip(labels, values)):
        x = idx*step+step*.2
        top = zero+value*scale
        draw.add(Rect(x, min(top,zero), step*.6, max(1,abs(value*scale)), fillColor=TEAL if value>=0 else RED, strokeColor=None))
        draw.add(String(x+step*.3, top+(6 if value>=0 else -12), "£{:,.0f}".format(value), textAnchor="middle", fontSize=8, fillColor=INK))
        for j,word in enumerate(label.split("|")[:2]):
            draw.add(String(x+step*.3, 20-j*10, word, textAnchor="middle", fontSize=8, fillColor=INK))
    return draw


def line_chart(series):
    draw = Drawing(495,180)
    draw.add(String(0,168,"England House Price Index — historical context",fontName="Helvetica-Bold",fontSize=11,fillColor=INK))
    vals = [r["index"] for r in series]
    lo,hi = min(vals), max(vals)
    hi = hi if hi != lo else lo+1
    coords = []
    for i,v in enumerate(vals): coords.extend([40+i*440/max(1,len(vals)-1),35+(v-lo)*100/(hi-lo)])
    if len(vals)>1: draw.add(PolyLine(coords,strokeColor=TEAL,strokeWidth=2))
    draw.add(String(0,35,str(round(lo,1)),fontSize=8)); draw.add(String(0,135,str(round(hi,1)),fontSize=8))
    draw.add(String(40,13,series[0]["month"],fontSize=8)); draw.add(String(445,13,series[-1]["month"],fontSize=8))
    return draw


def calculation_image(record, path, editor=None):
    """Spreadsheet-style working, rendered from the same audited model as the PDF."""
    editor=editor or ReportEditor(record);editor.page=3
    m = record['analysis']; v = m['metrics']; a = m['effective_assumptions']
    rows = [
        ('A1', 'SCHEDULED ANNUAL RENT', 'Monthly rent x 12', gbp(v['monthly_rent'] * 12)),
        ('A2', 'NET OPERATING INCOME (NOI)', 'Rent less vacancy and operating costs', gbp(v['stabilised_noi'])),
        ('A3', 'ANNUAL DEBT SERVICE', 'Monthly mortgage payment x 12', gbp(v['monthly_debt_payment'] * 12)),
        ('A4', 'CASH FLOW BEFORE INCOME TAX', 'NOI less annual debt service', gbp(v['stabilised_noi'] - v['monthly_debt_payment'] * 12)),
        ('B1', 'TOTAL PROPERTY COST', 'Price + purchase tax + fees + refurbishment', gbp(v['total_property_cost'])),
        ('B2', 'INITIAL CASH REQUIRED', 'Total cost - loan + finance fees + buffer', gbp(v['cash_required'])),
        ('C1', 'GROSS RENTAL YIELD', 'A1 / purchase price x 100', pct(v['gross_yield_pct'])),
        ('C2', 'NET YIELD ON TOTAL COST', 'A2 / B1 x 100', pct(v['net_yield_on_cost_pct'])),
        ('C3', 'CASH-ON-CASH RETURN', 'A4 / B2 x 100', pct(v['cash_on_cash_pct'])),
        ('C4', 'DEBT SERVICE COVERAGE', 'A2 / A3', str(v['dscr'])+'x' if v['dscr'] is not None else 'No debt'),
        ('D1', 'ANNUAL CAPITAL GROWTH', 'Analyst scenario assumption; not a forecast', pct(a['price_growth_pct'])),
    ]
    im = PILImage.new('RGB', (1900, 1100), 'white'); d = ImageDraw.Draw(im)
    d.rectangle((0,0,1900,120), fill=editor.style['heading_color'])
    d.text((35,25), editor.text('INVESTMENT MODEL | CALCULATION WORKING'), fill='white', font=font(35))
    d.text((35,76), 'Stabilised first-year prices | GBP | Before income tax | Revision '+str(record['revision']), fill='white', font=font(22))
    for title,x in [('CELL',30),('MEASURE',135),('FORMULA / BASIS',800),('RESULT',1640)]: d.text((x,148),editor.text(title),fill=editor.style['heading_color'],font=font(23))
    for i, row in enumerate(rows):
        y=206+i*72
        if i%2==0: d.rectangle((20,y-12,1880,y+54),fill='#edf4f2')
        for column,(value,x,size) in enumerate(zip(row,[30,135,800,1640],[23,24,23,25])):
            if column in (1,2):value=editor.text(value,'explanation' if column==2 else 'label')
            d.text((x,y),value,fill=editor.style['heading_color'],font=font(size))
    d.text((35,1030),'Display amounts are rounded. Formulas use unrounded monthly values; cash required includes the reserve.',fill='#43575b',font=font(23))
    im.save(str(path),'PNG')


class ReportPages:
    """Fixed page coordinates bound every block; long input cannot create an eleventh page."""
    def __init__(self, path, record, final, editor=None):
        from reportlab.pdfgen import canvas
        self.canvas=canvas.Canvas(str(path),pagesize=A4)
        self.record=record; self.final=final; self.page=0; self.shortened=False
        self.editor=editor or ReportEditor(record)
        self.accent=colors.HexColor(self.editor.style['accent_color'])
        self.ink=colors.HexColor(self.editor.style['heading_color'])
        self.width=A4[0]-90; self.top=A4[1]-48
        self.canvas.setTitle(self.editor.text('Property investment screening','heading')+' - '+record['inputs']['property']['address'])
        self.canvas.setAuthor(os.getenv('REPORT_BRAND','Property Screening'))

    def text(self, value, x, y, width, height, size=9, bold=False, color=INK, kind=None):
        text=self.editor.text(value,kind) if kind else str(value)
        size*=self.editor.style['font_scale']
        family=self.editor.style['font_family']
        color=self.accent if color==TEAL else self.ink if color==INK else color
        style=ParagraphStyle('bounded',fontName=FONTS[family] if bold else family,fontSize=size,leading=size*1.35,textColor=color,splitLongWords=True)
        def paragraph(s):
            return Paragraph(escape(s).replace('\n','<br/>'),style)
        p=paragraph(text); _,h=p.wrap(width,height)
        if h>height:
            self.shortened=True
            lo,hi=0,len(text)
            while lo<hi:
                mid=(lo+hi+1)//2
                candidate=paragraph(text[:mid]+' …')
                if candidate.wrap(width,height)[1]<=height: lo=mid
                else: hi=mid-1
            p=paragraph(text[:lo].rsplit(' ',1)[0]+' …');_,h=p.wrap(width,height)
        if h>height: raise ValueError('Report text box is too small')
        p.drawOn(self.canvas,x,y-h)
        return y-h

    def page_start(self, title, subtitle=''):
        if self.page: self.canvas.showPage()
        self.page+=1; c=self.canvas
        label='DEMO / FICTIONAL' if self.record['mode']=='demo' else 'REVIEWED' if self.final else 'DRAFT / FOR REVIEW'
        self.text(os.getenv('REPORT_BRAND','Property Screening'),45,self.top,self.width-160,22,11,True,kind='label')
        self.text(label,A4[0]-198,self.top,153,22,9,True,RED if self.record['mode']=='demo' else TEAL)
        c.setStrokeColor(self.accent);c.line(45,self.top-27,A4[0]-45,self.top-27)
        self.text(title,45,self.top-41,self.width,55,self.editor.style['heading_size'],True,kind='heading')
        if subtitle: self.text(subtitle,45,self.top-101,self.width,32,9,kind='explanation' if title!='Property investment screening' else None)
        c.setStrokeColor(colors.lightgrey);c.line(45,42,A4[0]-45,42)
        self.text('%s | r%s | %s' % (self.record['id'][:10],self.record['revision'],now()[:10]),45,32,self.width-90,15,8)
        self.text('%s / 10'%self.page,A4[0]-96,32,51,15,8,True)
        return self.top-140

    def section(self,title,y):
        self.text(title,45,y,self.width,28,13,True,kind='heading' if title!=self.record['analysis']['verdict'] else None)
        return y-32

    def table(self,rows,y,widths=None,row_height=28,size=8):
        widths=widths or [self.width*.65,self.width*.35]
        for i,row in enumerate(rows):
            if y-row_height<50: raise ValueError('Report table exceeds its fixed page')
            if i==0:
                self.canvas.setFillColor(LIGHT);self.canvas.rect(45,y-row_height,sum(widths),row_height,fill=1,stroke=0)
            x=45
            for value,w in zip(row,widths):
                self.text(value,x+5,y-5,w-10,row_height-8,size,i==0,kind='label' if i==0 or (len(row)==2 and x==45) else None)
                x+=w
            self.canvas.setStrokeColor(colors.lightgrey);self.canvas.line(45,y-row_height,45+sum(widths),y-row_height)
            y-=row_height
        return y-12

    def photo(self,path,x,y,width,height):
        self.canvas.setFillColor(LIGHT);self.canvas.rect(x,y-height,width,height,fill=1,stroke=0)
        if path and path.exists():
            with PILImage.open(str(path)) as img:
                self.canvas.drawImage(ImageReader(img),x,y-height,width,height,preserveAspectRatio=True,anchor='c')
        else:
            self.text('PROPERTY PHOTO NOT SUPPLIED\nUpload a permitted property photograph to include it here.',x+18,y-height/2+25,width-36,65,11)

    def drawing(self,drawing,y):
        from reportlab.graphics import renderPDF
        for shape in drawing.contents:
            for prop in ('fillColor','strokeColor'):
                value=getattr(shape,prop,None)
                if value==TEAL: setattr(shape,prop,self.accent)
                elif value==INK: setattr(shape,prop,self.ink)
            if isinstance(shape,String):
                if not re.fullmatch(r'[£$€\d,.% −x-]+',shape.text):
                    shape.text=self.editor.text(shape.text,'explanation' if re.search(r'\d',shape.text) else 'label')
                shape.fontName=FONTS[self.editor.style['font_family']] if 'Bold' in shape.fontName else self.editor.style['font_family']
        renderPDF.draw(drawing,self.canvas,45,y-drawing.height)
        return y-drawing.height-16


def yield_chart(values):
    drawing=Drawing(495,180)
    low,high=min(0,min(values)),max(1,max(values));scale=105/(high-low)
    zero=40-low*scale
    drawing.add(Line(0,zero,495,zero,strokeColor=colors.lightgrey))
    labels=['Gross yield','Net yield on cost','Cash-on-cash']
    for i,value in enumerate(values):
        x=82+i*165;top=zero+value*scale
        drawing.add(Rect(x-38,min(top,zero),76,max(1,abs(top-zero)),fillColor=TEAL if value>=0 else RED,strokeColor=None))
        drawing.add(String(x,top+(9 if value>=0 else -13),pct(value),fontSize=12,fontName='Helvetica-Bold',textAnchor='middle',fillColor=INK))
        drawing.add(String(x,12,labels[i],fontSize=10,textAnchor='middle',fillColor=INK))
    return drawing


def generate_report(record, folder, final=False):
    from .evidence import matched_profile, property_history
    from .photos import photo_groups
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    prefix='r%s-%s'%(record['revision'],'reviewed' if final else 'draft')
    pdf,png,csv_path,calc=[folder/(prefix+s) for s in ('.pdf','-cashflow.png','-cashflow.csv','-calculations.png')]
    editor=ReportEditor(record)
    cashflow_image(record,png,editor);calculation_image(record,calc,editor)
    m=record['analysis'];v=m['metrics'];a=m['effective_assumptions'];p=record['inputs']['property'];e=record['evidence'];n=record['narrative']['content'];investor=record['inputs']['investor']
    with csv_path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(m['monthly'][0]));w.writeheader();w.writerows(m['monthly'])
    editor.page=1
    r=ReportPages(pdf,record,final,editor);W=r.width
    def note(text,y,height=44,editable=True): return r.text(text,45,y,W,height,9,kind='explanation' if editable else None)-12
    def cited(item): return item['text']+' ['+', '.join(item['source_ids'])+']'
    def picture(path,y,height):
        r.canvas.drawImage(ImageReader(io.BytesIO(path.read_bytes())),45,y-height,width=W,height=height)
        return y-height-16
    def link(label,url,x,y,width=495):
        r.text(label,x,y,width,22,7,color=TEAL)
        if str(url).startswith(('http://','https://')): r.canvas.linkURL(url,(x,y-20,x+width,y),relative=0)

    photo,gallery=photo_groups(record)
    order=record.get("presentation",{}).get("page_order",list(range(1,11)))
    def page_number(canonical):return str(order.index(canonical)+1)

    def page_1():
        # 1. Subject, actual photo and acquisition decision inputs.
        y=r.page_start('Property investment screening',p['address']+', '+p['postcode'])
        y=note('Prepared for '+(investor['name'] or 'Client')+' | England residential rental | '+str(a['holding_years'])+' year scenario',y,28)
        y=note('Brief: '+investor['goal']+' | Risk tolerance: '+investor['risk_tolerance']+' | Available cash: '+gbp(investor['cash_budget']),y,40)
        r.photo(folder/photo['filename'] if photo else None,45,y,W,185);y-=194
        y=note((photo['caption']+' | '+photo['source']) if photo else 'A genuine subject-property photo can be added before delivery.',y,27)
        rows=[['Acquisition overview','GBP'],['Asking price',gbp(p['asking_price'])],['Proposed bid / modelled purchase price',gbp(v['purchase_price'])],['Total acquisition + refurbishment cost',gbp(v['total_property_cost'])],['Initial cash required, including buffer',gbp(v['cash_required'])]]
        y=r.table(rows,y,row_height=27)
        y=r.section(m['verdict'],y)
        y=note('Monthly cash flow before income tax: '+gbp(v['monthly_cashflow_before_tax'])+' | Net yield on cost: '+pct(v['net_yield_on_cost_pct']),y,28)
        note('Bid is an input to this screening, not a valuation recommendation. Acquisition total includes price, SDLT, purchase fees and refurbishment; cash required also reflects borrowing, finance fees and the buffer. Figures remain subject to the evidence gaps on pages '+', '.join(page_number(i) for i in (8,9,10))+'.',y,65)

    def page_2():
        # 2. Comparable yield measures and separate growth scenario.
        y=r.page_start('Yield and growth','Stabilised rental returns, before income tax. Capital growth is shown separately.')
        y=r.drawing(yield_chart([v['gross_yield_pct'],v['net_yield_on_cost_pct'],v['cash_on_cash_pct']]),y)
        y=r.table([['Return measure','Result / calculation'],['Gross rental yield',pct(v['gross_yield_pct'])+' — annual scheduled rent / price'],['Net rental yield on total cost',pct(v['net_yield_on_cost_pct'])+' — NOI / total property cost'],['Cash-on-cash return',pct(v['cash_on_cash_pct'])+' — annual cash after debt / cash required'],['Capital growth assumption',pct(a['price_growth_pct'])+' per year — scenario input, not rental yield']],y,[205,W-205],42,9)
        years=[0]+[x['year'] for x in m['annual']]
        vals=[v['purchase_price']]+[x['property_value'] for x in m['annual']]
        d=Drawing(495,142);lo,hi=min(vals),max(vals);span=max(1,hi-lo)
        d.add(PolyLine([z for i,value in enumerate(vals) for z in (40+430*i/max(1,len(vals)-1),35+(value-lo)*70/span)],strokeColor=TEAL,strokeWidth=2))
        for x,label in [(40,'Today: '+gbp(vals[0])),(295,'Year '+str(years[-1])+': '+gbp(vals[-1]))]:d.add(String(x,12,label,fontSize=9,fillColor=INK))
        d.add(String(0,125,'Property value under the selected growth assumption',fontSize=11,fontName='Helvetica-Bold',fillColor=INK))
        y=r.drawing(d,y)
        note('Net operating income (NOI) deducts vacancy and running costs before mortgage payments. Growth is neither rental income nor a guaranteed return; no refurbishment uplift is assumed.',y,48)

    def page_3():
        # 3. Readable spreadsheet image with formulas, then cash bridge.
        y=r.page_start('Investment model working','Spreadsheet image: calculation labels, formulas and model results.')
        y=picture(calc,y,W*1100/1900)
        y=r.table([['Acquisition and financing bridge','GBP'],['Purchase price',gbp(v['purchase_price'])],['SDLT / purchase tax',gbp(m['sdlt']['total'])],['Legal, survey and other purchase fees',gbp(a['legal_fees']+a['survey_fees']+a['other_purchase_costs'])],['Refurbishment including contingency',gbp(v['refurbishment_with_contingency'])],['Less mortgage borrowing','− '+gbp(v['loan'])],['Plus finance fees and cash buffer',gbp(a['mortgage_fees']+a['cash_reserve'])],['Initial cash required',gbp(v['cash_required'])]],y,row_height=25)
        note('Financing: '+a['financing'].replace('_',' ')+' | Monthly debt payment: '+gbp(v['monthly_debt_payment'])+'\nPurchase tax basis: '+m['sdlt']['basis']+'. Income and disposal tax are excluded unless supplied as separate budgets.',y,60)

    def page_4():
        # 4. First-year screenshot and annual model.
        y=r.page_start('Cash-flow spreadsheet','Monthly first-year working, followed by the ownership-period projection.')
        y=picture(png,y,W*1040/1900)
        annual=m['annual']
        shown=annual if len(annual)<=8 else annual[:4]+annual[-4:]
        rows=[['Year','Rent received','Operating costs','Debt service','Cash before tax']]+[[x['year'],gbp(x['collected_rent']),gbp(x['operating_costs']),gbp(x['interest']+x['principal']),gbp(x['cashflow_before_tax'])] for x in shown]
        y=r.table(rows,y,[36,116,116,116,W-384],24,8)
        y=note('Annual table shows '+('all model years.' if len(annual)<=8 else 'first four and last four years; intervening years are in the full cash-flow CSV.')+' Initial vacancy is included in year one; headline yields use stabilised occupancy.',y,42)
        note('First-year cash flow before income tax: '+gbp(v['first_year_cashflow'])+'. Annual tax budget: '+gbp(a['annual_tax_budget'])+'. Full monthly calculations and the full-size spreadsheet images are available as separate downloads.',y,55)

    def page_5():
        # 5. Risk sensitivities and exit, not a single optimistic number.
        y=r.page_start('Downside tests and exit','Stress scenarios use stabilised occupancy at first-year prices, before income tax.')
        y=r.drawing(bar_chart(['Base','Lower|rent','Higher|interest','Higher|costs','More|vacancy','Combined|downside'],[s['monthly_cashflow'] for s in m['scenarios']],'Monthly cash flow under stress',height=175),y)
        y=r.table([['Scenario','Rent / month','Interest','Vacancy','Cash / month']]+[[s['name'],gbp(s['monthly_rent']),pct(s['interest_rate_pct']),pct(s['void_pct']),gbp(s['monthly_cashflow'])] for s in m['scenarios']],y,[160,90,70,65,W-385],27,8)
        ex=m['exit']
        y=r.table([['Exit after '+str(a['holding_years'])+' years','Scenario result'],['Sale price / selling costs',gbp(ex['sale_price'])+' / '+gbp(ex['selling_costs'])],['Debt to repay / net sale proceeds',gbp(ex['loan_to_repay'])+' / '+gbp(ex['sale_proceeds'])],['Total profit incl. rental cash flow',gbp(ex['total_profit'])],['Annual IRR / return on initial cash',pct(ex['annual_irr_pct'])+' / '+pct(ex['total_return_pct'])]],y,row_height=26)
        note('Price growth '+pct(a['price_growth_pct'])+'; rent growth '+pct(a['rent_growth_pct'])+'; cost growth '+pct(a['cost_growth_pct'])+' annually. Exit tax budget: '+gbp(a['sale_tax_budget'])+'. IRR uses year-end cash flows. Cash buffer is returned separately at exit; additional funding need: '+gbp(v['additional_cash_needed'])+'.',y,68)

    def page_6():
        # 6. Facts, rooms and more actual photographs. Provider facts require identity match.
        y=r.page_start('Property facts and photographs','Client / analyst details [inputs]; matched provider observations are identified separately.')
        profile=matched_profile(record);building=profile.get('building',{})
        provider_area=building.get('internal_area_sqf')
        area=str(p['floor_area_sqm'])+' sqm [inputs]' if p['floor_area_sqm'] else (str(provider_area)+' sqft [property]' if provider_area else 'Unknown')
        facts=[['Property fact','Recorded detail'],['Type / bedrooms / bathrooms',p['property_type'].replace('_',' ')+' / '+str(p['bedrooms'])+' / '+str(p['bathrooms'] if p['bathrooms'] is not None else 'Unknown')],['Floor area / EPC',area+' / '+(p['epc_rating'] if p['epc_rating']!='unknown' else str(building.get('energy_rating','Unknown')))],['Tenure / remaining lease',p['tenure']+' / '+str(p['lease_years'] if p['lease_years'] is not None else 'Unknown')+' years'],['Building safety / construction age',p['cladding_status'].replace('_',' ')+' / '+str(building.get('construction_age_band') or p['construction_date'] or 'Unknown')],['Habitable rooms / floor level',str(building.get('habitable_rooms','Unknown'))+' / '+str(building.get('floor_level','Unknown'))+(' [property]' if building else '')],['Listing checked',p['listing_checked'] or 'Not confirmed']]
        y=r.table(facts,y,[205,W-205],row_height=27)
        y=note(p['listing_notes'] or 'Room dimensions, condition and alterations have not been independently verified. Obtain the floorplan, survey and agent particulars.',y,58)
        photos=gallery
        if photos:
            columns=3 if len(photos)>6 else 2
            rows=(len(photos)+columns-1)//columns
            cell_width=(W-12*(columns-1))/columns
            cell_height=min(158,(y-82)/rows)
            for i,photo in enumerate(photos):
                x=45+(i%columns)*(cell_width+12);top=y-(i//columns)*cell_height
                image_height=cell_height-27
                r.photo(folder/photo['filename'],x,top,cell_width,image_height)
                r.text('Photo '+str(i+1)+' | '+photo.get('source','Uploaded by analyst'),x,top-image_height-4,cell_width,19,7)
        else:
            y=r.section('Additional photographs',y)
            r.canvas.setFillColor(LIGHT);r.canvas.rect(45,y-165,W,165,fill=1,stroke=0)
            r.text('ADDITIONAL PROPERTY PHOTOS\nNo additional photos supplied. Up to ten uploaded house photos will appear here.',65,y-50,W-40,65,11)
        if p['listing_url']:link('Listing reference (open source)',p['listing_url'],45,65,W)

    def page_7():
        # 7. Never relabel same-postcode sales as the subject property's history.
        y=r.page_start('Sale history and market context','Subject history requires an exact address or supplied UPRN match. Absence is not proof of no previous sale.')
        history=property_history(record)
        if history:
            y=r.table([['Recorded sale date','Price paid','Source']]+[[x['date'],gbp(x['amount']),x['source']] for x in history[:6]],y,[115,130,W-245],31,8)
            for i,row in enumerate(history[:6]):
                if str(row.get('source_url','')).startswith(('http://','https://')):
                    top=y+12+(len(history[:6])-i)*31
                    r.canvas.linkURL(row['source_url'],(45,top-31,A4[0]-45,top),relative=0)
            if len(history)>6:y=note('Latest six of '+str(len(history))+' matched transactions shown; complete history retained in JSON.',y,28)
        else:y=note('No exact-match sale history is available in the current evidence. Nearby transactions appear on page '+page_number(8)+' as candidate comparisons, not as this property’s previous sale prices.',y,62)
        y=note('HM Land Registry postcode history query: same property type, standard transactions since 1995, newest 200 records. Some sales are excluded or registered later. Address formatting differences can prevent an automatic match. PropertyData history is used only where the profile identity matches.',y,64)
        if e.get('profile') and not profile:y=note('Returned PropertyData profile could not be matched confidently to this address. Its facts and sale history have not been attributed to this property.',y,46)
        if e.get('hpi'):
            y=r.drawing(line_chart(e['hpi']),y)
            note('Historical England-wide HPI [hpi], observed '+e.get('retrieved_at','unknown')[:10]+'. National context does not establish the value or future growth of this particular property.',y,50)
        else:note('England House Price Index history is unavailable in this record. The capital growth input on page '+page_number(2)+' remains an explicit scenario assumption.',y,48)

    def page_8():
        # 8. Selected evidence and unreviewed candidates visibly distinct.
        y=r.page_start('Comparable evidence','Rent and sold prices are cross-checks. Match location, floor area, age, condition and evidence date.')
        y=note('Selected monthly rent: '+gbp(v['monthly_rent'])+'. Basis: '+m['rent_basis']+'. Area asking-rent baseline: '+gbp(e.get('market',{}).get('monthly_rent'))+'. Gap: '+pct(v['rent_vs_area_pct'])+'.',y,56)
        for kind,title in [('rent','Rental comparisons — monthly asking rent'),('sold','Sold comparisons — transaction price')]:
            y=r.section(title,y)
            selected=[dict(c,source_id='comparable-'+str(i+1)) for i,c in enumerate(record['inputs']['comparables']) if c['kind']==kind and c['selected']]
            candidates=[c for c in e.get('comparables',[]) if c['kind']==kind]
            rows=selected or candidates
            y=note('Analyst-selected matches.' if selected else 'UNREVIEWED CANDIDATES — not selected as property matches and not used for a comparable-based valuation.',y,30)
            if not rows:y=note('No comparison evidence available. Obtain property-matched evidence before relying on the estimate.',y,40)
            for c in rows[:3]:
                text='%s | %s | %s\n%s | %s\n%s' % (c['address'],gbp(c['amount']),c.get('date') or 'Date unknown',c.get('source','Source unknown'),c.get('source_id','candidate'),c.get('notes','Match notes missing'))
                y=r.text(text,45,y,W,41,8)-3
                if c.get('source_url'):link('Open comparable source',c['source_url'],45,y,W)
                y-=20
            if len(rows)>3:y=note('Showing three of '+str(len(rows))+'. Full comparisons and source links are retained in JSON.',y,25)
        note('Selected sold median: '+gbp(v['selected_sold_median'])+'. Price gap: '+pct(v['price_vs_selected_sales_pct'])+'. These are unadjusted comparisons, not a professional valuation. Direct Land Registry transactions are preferred where duplicates are identified.',min(y,115),58)

    def page_9():
        # 9. Written reasoning plus every model warning title.
        y=r.page_start('Investment case and key risks','Evidence-led reasoning for the client’s existing property proposal.')
        y=note(cited(n['summary']),y,60,editable=False)
        y=r.section('Reasons to investigate',y)
        if not n['strengths']:y=note('No clear financial strength has been established under the selected screening targets.',y,30)
        for item in n['strengths'][:2]:y=note('• '+cited(item),y,43,editable=False)
        y=r.section('Risks and qualifications',y)
        for item in n['risks'][:2]:y=note('• '+cited(item),y,43,editable=False)
        y=r.section('Model risk register',y)
        grouped={}
        for flag in m['flags']:
            key=(flag['level'],flag['title'])
            grouped[key]=grouped.get(key,0)+1
        flags=[{'level':level,'title':title+(' ('+str(count)+' items)' if count>1 else '')} for (level,title),count in grouped.items()]
        flags.sort(key=lambda f:{'critical':0,'warning':1,'info':2}.get(f['level'],3))
        if not flags: note('No automated flags. Independent due diligence remains necessary.',y,35)
        rows=(len(flags)+1)//2
        rh=min(32,(y-75)/max(1,rows))
        for i,f in enumerate(flags):
            x=45+(i%2)*(W/2+4);top=y-(i//2)*rh
            r.text(f['level'].upper()+': '+f['title'],x,top,W/2-8,rh-3,8,color=RED if f['level']=='critical' else INK)
        if record['narrative']['provider']=='template':r.text('Template commentary used; AI writing was unavailable or disabled.',45,62,W,15,8)

    def page_10():
        # 10. Concise assumptions, next steps, dated clickable source register.
        y=r.page_start('Assumptions, sources and next steps','Full inputs, raw evidence and audit trail are retained in the JSON record; every monthly row is in the CSV.')
        y=r.section('Operating assumptions and due diligence',y)
        assumptions='Vacancy '+pct(a['void_pct'])+'; initial vacancy '+str(a['initial_void_months'])+' months; management '+pct(a['management_pct'])+' of collected rent; maintenance '+pct(a['maintenance_pct'])+' of scheduled rent. Annual charges: service '+gbp(a['service_charge'])+', ground rent '+gbp(a['ground_rent'])+', insurance '+gbp(a['insurance'])+', compliance '+gbp(a['compliance'])+', letting '+gbp(a['letting_fees'])+', other '+gbp(a['other_annual_costs'])+'. Mortgage '+pct(a['ltv_pct'])+' LTV, '+pct(a['interest_rate_pct'])+' rate, '+str(a['mortgage_term_years'])+' years. Unverified defaults are illustrative, not confirmed costs.'
        y=note(assumptions,y,97)
        for item in n['due_diligence'][:3]:y=note('• '+cited(item),y,34,editable=False)
        y=r.section('Dated source register',y)
        y=r.text('[inputs] Client / analyst entries, revision '+str(record['revision'])+'. [assumptions] Selected model inputs. [model] Python calculation engine. Comparable source links: page '+page_number(8)+'. Provider observations are snapshots as of retrieval, not live assurances.',45,y,W,40,8)-9
        sources=list(e.get('sources',[]))
        for i,url in enumerate(m['sdlt']['rules']['sources']):sources.append({'id':'tax-'+str(i+1),'title':'SDLT rules','url':url,'retrieved_at':m['sdlt']['rules']['verified_on'],'status':'config checked'})
        space=max(80,y-122);rh=min(25,space/max(1,len(sources)))
        for s in sources:
            label='[%s] %s | %s | %s' % (s['id'],s['title'],s['status'],str(s.get('retrieved_at',''))[:10])
            r.text(label,45,y,W,rh-2,7)
            if str(s.get('url','')).startswith(('http://','https://')):r.canvas.linkURL(s['url'],(45,y-rh,A4[0]-45,y),relative=0)
            y-=rh
        foot='Source rows are clickable. Contains HM Land Registry data © Crown copyright and database right '+now()[:4]+' under the Open Government Licence v3.0. Tax rules effective '+m['sdlt']['rules']['effective_from']+'. '
        foot+='This ten-page report condenses long notes and evidence; full wording, all flags, assumptions and source errors remain in JSON. '
        if final:foot+='Reviewed by '+record['approval']['reviewer']+' on '+record['approval']['at'][:10]+'. '
        foot+='Missing evidence remains unresolved after review.'
        r.text(foot,45,110,W,59,7)
    pages={1:page_1,2:page_2,3:page_3,4:page_4,5:page_5,6:page_6,7:page_7,8:page_8,9:page_9,10:page_10}
    for canonical in order:
        editor.page=canonical
        pages[canonical]()
    record["report_document"]=editor.catalog
    r.canvas.save()
    return {'pdf':pdf.name,'cashflow_png':png.name,'cashflow_csv':csv_path.name,'calculations_png':calc.name,'generated_at':now(),'revision':record['revision'],'final':final,'page_count':10,'condensed':r.shortened}

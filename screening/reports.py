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
from .evidence import ranked_comparables

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
            val = str(idx+1) if key is None else ("—" if key == "tax_budget" and m["effective_assumptions"]["annual_tax_budget"] is None else "{:,.0f}".format(row[key]))
            d.text((x,y), val, fill="#a3342a" if key and row[key]<0 else "#18333c", font=font(25))
    y = 866
    d.line((25,y-12,1875,y-12), fill=editor.style["heading_color"], width=3)
    for _, key, x in cols:
        val = "Total" if key is None else ("—" if key == "tax_budget" and m["effective_assumptions"]["annual_tax_budget"] is None else "{:,.0f}".format(sum(r[key] for r in m["monthly"][:12])))
        d.text((x,y), val, fill=editor.style["heading_color"], font=font(25))
    foot = "*Income tax not modelled (—); cash left is BEFORE income tax." if m["effective_assumptions"]["annual_tax_budget"] is None else "*Cash left deducts the supplied tax budget; it is not a tax assessment."
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


def line_chart(series, title="Local historical prices (GBP)", height=180):
    draw = Drawing(495,height)
    draw.add(String(0,height-12,title,fontName="Helvetica-Bold",fontSize=10,fillColor=INK))
    vals = [r["index"] for r in series]
    lo,hi = min(vals), max(vals)
    hi = hi if hi != lo else lo+1
    coords = []
    for i,v in enumerate(vals): coords.extend([65+i*410/max(1,len(vals)-1),35+(v-lo)*(height-80)/(hi-lo)])
    if len(vals)>1: draw.add(PolyLine(coords,strokeColor=TEAL,strokeWidth=2))
    draw.add(String(0,35,"£{:,.0f}".format(lo),fontSize=8)); draw.add(String(0,height-45,"£{:,.0f}".format(hi),fontSize=8))
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


def yield_chart(values, height=155):
    drawing=Drawing(495,height)
    low,high=min(0,min(values)),max(1,max(values));scale=(height-70)/(high-low)
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
    # Upgrade old saved models locally, using their evidence, without API requests.
    if record.get('analysis', {}).get('version') != 3 or not record.get('analysis', {}).get('horizons'):
        from .finance import analyse
        from .narrative import deterministic
        from .evidence import enriched_inputs
        record['inputs'] = enriched_inputs(record['inputs'], record['evidence'])
        record['analysis'] = analyse(record['inputs'], record['evidence'], record['mode'])
        if not record['analysis']['available']: raise ValueError('Missing report inputs: '+', '.join(record['analysis'].get('missing', [])))
        record['narrative'] = deterministic(record, 'Existing report model upgraded using saved evidence')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    prefix='r%s-%s'%(record['revision'],'reviewed' if final else 'draft')
    pdf,png,csv_path,calc=[folder/(prefix+s) for s in ('.pdf','-cashflow.png','-cashflow.csv','-calculations.png')]
    editor=ReportEditor(record)
    cashflow_image(record,png,editor);calculation_image(record,calc,editor)
    m=record['analysis'];v=m['metrics'];a=m['effective_assumptions'];p=m.get('effective_property',record['inputs']['property']);e=record['evidence'];n=record['narrative']['content'];investor=record['inputs']['investor']
    with csv_path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['holding_years']+list(m['monthly'][0]));w.writeheader()
        schedules = [h for h in m['horizons'] if h['available']] or [{'years': a['holding_years'], 'monthly': m['monthly']}]
        for horizon in schedules:
            for row in horizon['monthly']:
                item=dict(row,holding_years=horizon['years'])
                if a['annual_tax_budget'] is None: item['tax_budget']=''
                w.writerow(item)
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
        y=note('Prepared for '+(investor['name'] or 'Client')+' | England rental | 3, 5 and 10 year ownership comparisons',y,28)
        y=note('Goal: '+(investor['goal'] or 'Not supplied')+' | Available cash: '+gbp(investor['cash_budget']),y,40)
        r.photo(folder/photo['filename'] if photo else None,45,y,W,185);y-=194
        y=note((photo['caption']+' | '+photo['source']) if photo else 'A genuine subject-property photo can be added before delivery.',y,27)
        rows=[['Acquisition overview','GBP'],['Client listing / offer price',gbp(p['asking_price'])],['Purchase price used for this scenario',gbp(v['purchase_price'])],['Total acquisition + refurbishment cost',gbp(v['total_property_cost'])],['Initial cash required, including buffer',gbp(v['cash_required'])]]
        y=r.table(rows,y,row_height=27)
        y=r.section(m['verdict'],y)
        y=note('Monthly cash flow before income tax: '+gbp(v['monthly_cashflow_before_tax'])+' | Net yield on cost: '+pct(v['net_yield_on_cost_pct']),y,28)
        note(m['price_basis']+'. Costs include purchase tax, fees and any planned works; cash required also reflects borrowing and reserves. Evidence gaps: pages '+', '.join(page_number(i) for i in (8,9,10))+'.',y,65)

    def page_2():
        y=r.page_start('Rental returns and growth assumptions','Rental returns use stabilised occupancy and are before income tax.')
        y=r.drawing(yield_chart([v['gross_yield_pct'],v['net_yield_on_cost_pct'],v['cash_on_cash_pct']],height=110 if editor.style['font_scale']>1.05 else 155),y)
        sale=e.get('market',{}).get('valuation-sale',{})
        from .providers import numeric
        margin=numeric(sale.get('margin')) if isinstance(sale,dict) else None
        sale_label=gbp(m['valuations']['sale'])
        if m['valuations']['sale'] and margin is not None and margin>=0: sale_label+=' ± '+gbp(margin)
        if m['valuations']['sale'] and sale.get('confidence'): sale_label+=' ('+str(sale['confidence']).replace('_',' ')+' confidence)'
        y=r.table([['Measure','Result / basis'],['Current sale estimate',sale_label],['Current rental estimate',gbp(m['valuations']['rent'])+' per month — property-specific model'],['Gross rental yield',pct(v['gross_yield_pct'])+' — scheduled annual rent / purchase price'],['Net yield on total cost',pct(v['net_yield_on_cost_pct'])+' — income after running costs / total cost'],['Cash-on-cash return',pct(v['cash_on_cash_pct'])+' — cash after debt / initial cash'],['Price growth scenario',pct(a['price_growth_pct'])+' per year'],['Rent growth scenario',pct(a['rent_growth_pct'])+' per year']],y,[190,W-190],25,8)
        y=note(m['price_growth_basis'],y,44)
        y=note(m['rent_growth_basis']+'. Operating costs grow by '+pct(a['cost_growth_pct'])+' per year, an illustrative budget assumption.',y,44)
        y=r.table([['Ownership period','Property value under the growth scenario']]+[[str(h['years'])+' years',gbp(h['exit']['sale_price']) if h['available'] else 'Not modelled: mortgage term'] for h in m['horizons']],y,[190,W-190],26,8)
        note('Starting value: '+gbp(m['starting_value'])+'. '+m['value_basis']+'. Future values are scenarios, not forecasts. No uplift from refurbishment is assumed.',y,56)

    def page_3():
        y=r.page_start('Purchase costs and refurbishment','Each cost is a budget or estimate unless supported by a supplied quote.')
        y=picture(calc,y,180 if editor.style['font_scale']>1.05 else 210)
        rows=[['Acquisition and financing','GBP'],['Purchase price',gbp(v['purchase_price'])],['Purchase tax (SDLT)',gbp(m['sdlt']['total'])],['Legal / survey / other purchase fees',gbp(a['legal_fees'])+' / '+gbp(a['survey_fees'])+' / '+gbp(a['other_purchase_costs'])],['Planned works including contingency',gbp(v['refurbishment_with_contingency'])],['Mortgage funds contributed to purchase','− '+gbp(v['loan'])],['Upfront finance fees / cash reserve',gbp(a['mortgage_fees'])+' / '+gbp(a['cash_reserve'])],['Initial cash required',gbp(v['cash_required'])]]
        y=r.table(rows,y,row_height=24)
        bands='; '.join(gbp(b['portion'])+' at '+pct(b['rate_pct']) for b in m['sdlt']['bands'])
        y=note('Purchase tax: '+m['sdlt']['basis']+'. '+bands+'. Buyer circumstances supplied in the brief; no first-time-buyer relief assumed for a rental investment.',y,50)
        prov=record['inputs'].get('input_provenance',{})
        fee_basis='; '.join(label+': '+prov.get('assumptions.'+key,{}).get('basis','Illustrative budget; confirm quote') for key,label in [('legal_fees','Legal'),('survey_fees','Survey')])
        y=note(fee_basis+'. Reserve is cash held aside, not a fee.',y,36)
        ref=m['refurbishment_reference']
        y=note('Refurbishment reference: '+gbp(ref['estimate'])+'. '+ref['basis']+'. '+ref['cost_basis']+'.',y,65)
        note('Cash purchase: no mortgage interest or repayments.' if a['financing']=='cash' else 'Financing: '+a['financing'].replace('_',' ')+'; '+pct(a['interest_rate_pct'])+' annual interest; '+str(a['mortgage_term_years'])+' year term; '+gbp(v['monthly_debt_payment'])+' monthly payment. Borrowing reduces upfront cash but must be repaid.',y,42)

    def page_4():
        # 4. First-year screenshot and annual model.
        y=r.page_start('Cash-flow spreadsheet','Monthly first-year working, followed by the ownership-period projection.')
        y=picture(png,y,225)
        annual=next((h['annual'] for h in m['horizons'] if h['available'] and h['years']==10),m['annual'])
        shown=annual
        rows=[['Year','Rent received','Operating costs','Debt service','Cash before tax']]+[[x['year'],gbp(x['collected_rent']),gbp(x['operating_costs']),gbp(x['interest']+x['principal']),gbp(x['cashflow_before_tax'])] for x in shown]
        y=r.table(rows,y,[36,116,116,116,W-384],24,8)
        y=note('Annual table shows '+('all model years.' if len(annual)<=8 else 'all years of the longest available comparison.')+' The full CSV contains separate monthly schedules for each ownership period.',y,42)
        note('Base vacancy is '+pct(a['void_pct'])+' plus '+str(a['initial_void_months'])+' initial empty months. At 90% occupancy, stabilised monthly cash flow is '+gbp(next(x['monthly_cashflow'] for x in m['scenarios'] if x['name']=='90% occupancy'))+'. '+('Income tax has not been modelled; a dash is not a zero tax bill.' if a['annual_tax_budget'] is None else 'Supplied annual income-tax budget: '+gbp(a['annual_tax_budget'])) ,y,65)

    def page_5():
        y=r.page_start('Downside tests and ownership periods','Buy, rent out, then sell after 3, 5 or 10 years using the same starting assumptions.')
        y=r.drawing(bar_chart(['Base','Lower|rent','Higher|interest','Higher|costs','90%|occupancy','Combined|downside'],[x['monthly_cashflow'] for x in m['scenarios']],'Monthly cash flow before income tax',height=130),y)
        y=r.table([['Scenario','Rent / month','Interest','Vacancy','Cash / month']]+[[x['name'],gbp(x['monthly_rent']),pct(x['interest_rate_pct']),pct(x['void_pct']),gbp(x['monthly_cashflow'])] for x in m['scenarios']],y,[155,90,70,65,W-380],24,8)
        y=r.section('Ownership comparison',y)
        horizons=m['horizons']
        def value(h,field,exit_field=False,percent=False):
            if not h['available']: return 'Not modelled'
            x=h['exit'][field] if exit_field else h[field]
            return pct(x) if percent else gbp(x)
        rows=[['Measure']+[str(h['years'])+' years' for h in horizons]]
        for label,key,is_exit,is_pct in [('Rent collected','rental_income',False,False),('Operating costs','operating_costs',False,False),('Mortgage payments','debt_paid',False,False),('Rental cash accumulated','rental_cashflow',False,False),('Net sale proceeds','sale_proceeds',True,False),('Total profit incl. rental cash','total_profit',True,False),('Annualised return (IRR)','annual_irr_pct',True,True)]:
            rows.append([label]+[value(h,key,is_exit,is_pct) for h in horizons])
        y=r.table(rows,y,[175]+[(W-175)/3]*3,23,8)
        unavailable=[str(h['years']) for h in horizons if not h['available']]
        reasons=('Periods '+', '.join(unavailable)+' years exceed the interest-only mortgage term; refinancing is unknown.') if unavailable else ''
        note('Sale proceeds deduct selling fees, debt and any supplied sale-tax budget. Rental cash deducts any supplied income-tax budget; otherwise tax is excluded. Longer ownership is not automatically better. '+reasons,y,64)

    def page_6():
        # 6. Facts, rooms and more actual photographs. Provider facts require identity match.
        y=r.page_start('Property facts and photographs','Client details supplemented by a matched property profile; source details remain in the saved record.')
        profile=matched_profile(record);building=profile.get('building',{})
        provider_area=building.get('internal_area_sqf')
        area=str(p['floor_area_sqm'])+' sqm' if p['floor_area_sqm'] else (str(provider_area)+' sqft [property]' if provider_area else 'Unknown')
        facts=[['Property fact','Recorded detail'],['Type / bedrooms / bathrooms',p['property_type'].replace('_',' ')+' / '+str(p['bedrooms'])+' / '+str(p['bathrooms'] if p['bathrooms'] is not None else 'Unknown')],['Floor area / EPC',area+' / '+(p['epc_rating'] if p['epc_rating']!='unknown' else str(building.get('energy_rating','Unknown')))],['Tenure / remaining lease',p['tenure']+(' / not applicable' if p['tenure']=='freehold' else ' / '+str(p['lease_years'] if p['lease_years'] is not None else 'Unknown')+' years')],['Building safety / construction age',p['cladding_status'].replace('_',' ')+' / '+str(building.get('construction_age_band') or p['construction_date'] or 'Unknown')],['Habitable rooms / floor level',str(building.get('habitable_rooms') or 'Unknown')+' / '+str(building.get('floor_level') if building.get('floor_level') is not None else 'Unknown')+(' [property]' if building else '')],['Listing checked',p['listing_checked'] or 'Not confirmed']]
        y=r.table(facts,y,[205,W-205],row_height=25)
        context=m['property_context']
        for j,fact in enumerate(context['facts']):
            x=45+(j%2)*(W/2+4);top=y-(j//2)*35
            r.text(fact['label']+': '+fact['value'],x,top,W/2-8,32,7.5)
        y-=((len(context['facts'])+1)//2)*35+8
        y=note('Profile observations [property]; confirm with searches and survey. '+(p['listing_notes'] or 'Room dimensions and alterations require a floorplan and survey.'),y,32)
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
        y=r.page_start('Sale history and market context','Recorded history and local observations; neither guarantees future prices or letting times.')
        history=property_history(record)
        shown=history[:4]
        if shown:
            y=r.table([['Sale date','Price paid','Source']]+[[x['date'],gbp(x['amount']),'Matched Land Registry record'] for x in shown],y,[100,120,W-220],24,8)
            for i,row in enumerate(shown):
                if str(row.get('source_url','')).startswith(('http://','https://')):
                    top=y+12+(len(shown)-i)*24
                    r.canvas.linkURL(row['source_url'],(45,top-24,A4[0]-45,top),relative=0)
            y=note('Latest '+str(len(shown))+' of '+str(len(history))+' matched sales shown. Registration delays and omitted transactions can leave gaps.',y,28)
        else:y=note('No exact-match subject sale history. Nearby sales are comparisons, not this property’s previous prices.',y,40)
        if m['local_growth']:
            y=r.drawing(line_chart([dict(x,index=x['value']) for x in m['local_growth']], 'Local historical prices (GBP) [growth]', 130),y)
        else:y=note('Local average-price history unavailable; see the growth scenario basis on page '+page_number(2)+'.',y,30)
        check=m['growth_crosscheck']
        if check['price_rate'] is not None and check['psf_rate'] is not None:
            detail='Same-period annualised change ('+check['from']+' to '+check['to']+'): average price '+pct(check['price_rate'])+'; sold price per sqft '+pct(check['psf_rate'])+' [growth-psf]. '+('Material difference: review property mix.' if check['material_difference'] else 'Cross-check only; these rates are not averaged.')
        else:detail='Growth cross-check unavailable: the two series need at least two years of common observations.'
        y=note(detail,y,38)
        rows=[['Local market','Observed activity']]
        for key,label in [('sales_demand','Sales'),('rental_demand','Rentals')]:
            d=m['market_context'][key]
            detail='; '.join(x['label']+': '+str(x['value']) for x in d['metrics'])
            rows.append([label+': '+str(d['rating'] or 'Rating unavailable'),detail or 'Activity figures unavailable'])
        y=r.table(rows,y,[175,W-175],37,7.5)
        y=note('Area demand [demand, demand-rent] does not establish this property’s vacancy rate or time to sell.',y,25)
        planning=m['property_context']['planning']
        if planning['requested']:
            rows=planning['rows']
            detail=('Nearby planning: '+str(len(rows))+' applications returned. ' if rows else 'No usable planning records returned; absence does not establish consent. ')
            if rows:
                item=rows[0]
                detail+='Example: '+str(item.get('address') or 'Address unavailable')+' — '+str(item.get('description') or item.get('reference') or 'Proposal unavailable')+'; '+str(item.get('decision') or 'Decision unavailable')+'. '
            detail+='Limited search [planning-applications]; review the council record. This is not permission for proposed work.'
            r.text(detail,45,y,W,max(25,y-55),7.5)
            if rows and str(rows[0].get('url','')).startswith(('http://','https://')):r.canvas.linkURL(rows[0]['url'],(45,55,45+W,y),relative=0)

    def page_8():
        y=r.page_start('Comparable evidence','Asking prices, advertised rents and completed sales remain separate. Candidates require analyst review.')
        sample=m['market_context']['rent_sample']
        bounds=sample['range_80']
        detail='Monthly rent used: '+gbp(v['monthly_rent'])+'. '+m['rent_basis']+'. '
        detail+='Area rental sample: '+(str(int(sample['count'])) if sample['count'] is not None else 'unknown count')+'; radius '+(str(sample['radius_miles'])+' miles' if sample['radius_miles'] is not None else 'unknown')+'. '
        if bounds:detail+='Middle 80% of advertised rents: '+gbp(bounds[0])+'–'+gbp(bounds[1])+' / month [rents]. This describes the area sample, not a valuation confidence interval.'
        y=note(detail,y,75)
        for kind,title in [('rent','Rental comparisons — monthly asking rent'),('sold','Recorded sales — transaction price'),('asking','For-sale comparisons — asking price')]:
            y=r.section(title,y)
            selected=[dict(c,source_id='comparable-'+str(i+1)) for i,c in enumerate(record['inputs']['comparables']) if c['kind']==kind and c['selected']]
            candidates=ranked_comparables(record,kind)
            rows=selected or candidates
            shown=1 if editor.style['font_scale']>1.05 else 2
            y=r.text(('Analyst-selected' if selected else 'Unverified ranked candidates')+'; showing '+str(min(shown,len(rows)))+' of '+str(len(rows))+'. Full evidence in saved record.',45,y,W,22,7.5)-4
            if not rows:y=r.text('No usable comparison evidence returned.',45,y,W,32,8)-5
            for c in rows[:shown]:
                bed=str(int(c['bedrooms']))+' bed' if c.get('bedrooms') is not None else 'beds unknown'
                area=str(c['floor_area_sqm'])+' sqm' if c.get('floor_area_sqm') else 'size unknown'
                dist=str(c['distance'])+' miles' if c.get('distance') is not None else 'distance unknown'
                stamp=c.get('date') if kind=='sold' else str(c.get('observed_at') or '')[:10]
                timing=('Sale date: ' if kind=='sold' else 'Observed: ')+(stamp or 'unknown')
                if kind!='sold' and c.get('days_on_market') is not None: timing+='; '+str(int(c['days_on_market']))+' days on market'
                text=c['address']+' | '+gbp(c['amount'])+'\n'+bed+'; '+area+'; '+dist+'; '+c.get('property_type','type unknown').replace('_',' ')+'\n'+timing+' ['+c.get('source_id',c.get('source','source unknown'))+']'
                top=y;y=r.text(text,45,y,W,47,8)-8
                if str(c.get('source_url','')).startswith(('http://','https://')):r.canvas.linkURL(c['source_url'],(45,y,45+W,top),relative=0)
        note('Sale estimate: '+gbp(m['valuations']['sale'])+' [valuation-sale]; rental estimate: '+gbp(m['valuations']['rent'])+' / month [valuation-rent]. Click a comparison to open its source. Estimates and advertised prices are not completed transactions.',y,45)

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

    def page_10():
        y=r.page_start('Assumptions, sources and next steps','Research and information only; not financial, tax or legal advice.')
        y=note('Vacancy '+pct(a['void_pct'])+'; management '+pct(a['management_pct'])+' of collected rent; maintenance '+pct(a['maintenance_pct'])+' of scheduled rent. Annual insurance '+gbp(a['insurance'])+', compliance '+gbp(a['compliance'])+', letting '+gbp(a['letting_fees'])+'. Unconfirmed costs remain illustrative budgets.',y,58)
        for item in n['due_diligence'][:2]:y=note('• '+cited(item),y,35,editable=False)
        y=r.section('Sources used and evidence gaps',y)
        y=r.text('Financial tables use the stated inputs and assumptions. Links below open the sources; dates show when evidence was retrieved. The research record retains all inputs, comparisons and evidence gaps.',45,y,W,36,8)-10
        sources=list(e.get('sources',[]))
        tax_urls=m['sdlt']['rules']['sources']
        sources.append({'id':'tax','title':'HMRC — residential purchase tax and surcharges','url':tax_urls[0],'retrieved_at':m['sdlt']['rules']['verified_on'],'status':'config checked'})
        names={'sold-prices':'Nearby recorded sales','rents':'Local advertised rents','growth':'Local historical price growth','demand':'Local sales demand','demand-rent':'Local rental demand','property':'Property facts and sale history','prices-per-sqf':'Local asking prices by floor area','sold-prices-per-sqf':'Local sold prices by floor area','hpi':'England house prices (background)','land-registry':'Direct Land Registry comparisons','land-registry-history':'Direct Land Registry history','valuation-sale':'Property sale valuation','valuation-rent':'Property rental valuation','build-cost':'Refurbishment reference estimate'}
        names['tax']='HMRC — purchase taxes'
        columns=2 if len(sources)>18 else 1
        count=(len(sources)+columns-1)//columns
        rh=min(38 if columns==2 else 25,(y-115)/max(1,count))
        top=y;cell=W/columns
        for index,source in enumerate(sources):
            title=names.get(source['id'],source['title'])
            status={'ok':'Available','error':'Unavailable','no_data':'No records returned','config checked':'Rules checked'}.get(source['status'],source['status'])
            label=title+('\n' if columns==2 else ' | ')+status+' | '+str(source.get('retrieved_at',''))[:10]
            x=45+(index%columns)*cell;y=top-(index//columns)*rh
            r.text(label,x,y,cell-8,rh-3,7.5 if columns==2 or rh<22 else 8,color=RED if source['status']=='error' else INK)
            if str(source.get('url','')).startswith(('http://','https://')):r.canvas.linkURL(source['url'],(x,y-rh,x+cell-8,y),relative=0)
        y=top-count*rh
        failed=[x for x in e.get('errors',[]) if x.get('source') not in {x['id'] for x in sources if x['status']=='error'}]
        if failed and y>90:
            r.text('Other gaps: '+', '.join(x['source'] for x in failed)+'. See saved evidence for details.',45,y-4,W,28,8)
        foot='Unavailable means a request failed or could not be used; it is not proof that no records exist. Contains HM Land Registry data © Crown copyright and database right '+now()[:4]+' under the Open Government Licence v3.0. '
        foot+='Full monthly schedules for each ownership period are in the CSV. '
        if final:foot+='Reviewed by '+record['approval']['reviewer']+' on '+record['approval']['at'][:10]+'. '
        foot+='Review does not resolve missing evidence.'
        r.text(foot,45,102,W,54,7.5)
    pages={1:page_1,2:page_2,3:page_3,4:page_4,5:page_5,6:page_6,7:page_7,8:page_8,9:page_9,10:page_10}
    for canonical in order:
        editor.page=canonical
        pages[canonical]()
    record["report_document"]=editor.catalog
    r.canvas.save()
    return {'pdf':pdf.name,'cashflow_png':png.name,'cashflow_csv':csv_path.name,'calculations_png':calc.name,'generated_at':now(),'revision':record['revision'],'final':final,'page_count':10,'condensed':r.shortened}

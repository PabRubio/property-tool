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
    """Core layouts plus flowing explanations and comparison continuation pages."""
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
        self.text(title,45,self.top-41,self.width,60,min(self.editor.style['heading_size'],18) if len(title)>45 else self.editor.style['heading_size'],True,kind='heading')
        if subtitle: self.text(subtitle,45,self.top-101,self.width,32,9,kind='explanation' if title!='Property investment screening' else None)
        c.setStrokeColor(colors.lightgrey);c.line(45,42,A4[0]-45,42)
        self.text('%s | r%s | %s' % (self.record['id'][:10],self.record['revision'],now()[:10]),45,32,self.width-90,15,8)
        self.text('Page %s'%self.page,A4[0]-96,32,51,15,8,True)
        return self.top-140

    def section(self,title,y):
        if y < 160: y=self.page_start('Assessment — continued')
        self.text(title,45,y,self.width,34,11 if len(title)>48 else 13,True,kind='heading' if title!=self.record['analysis']['verdict'] else None)
        return y-38

    def table(self,rows,y,widths=None,row_height=28,size=8):
        widths=widths or [self.width*.65,self.width*.35]
        for i,row in enumerate(rows):
            if y-row_height<55:
                y=self.page_start('Report details — continued')
            if i==0:
                self.canvas.setFillColor(LIGHT);self.canvas.rect(45,y-row_height,sum(widths),row_height,fill=1,stroke=0)
            x=45
            for value,w in zip(row,widths):
                self.text(value,x+5,y-5,w-10,row_height-8,size,i==0,kind='label' if i==0 or (len(row)==2 and x==45) else None)
                x+=w
            self.canvas.setStrokeColor(colors.lightgrey);self.canvas.line(45,y-row_height,45+sum(widths),y-row_height)
            y-=row_height
        return y-12

    def flow(self, text, y, title='Assessment — continued', size=9):
        """Wrap and paginate in full. Never silently truncate research or reasoning."""
        value = escape(str(text)).replace('\n','<br/>')
        from .source_report import references
        sources = {s['id']:s for s in references(self.record)}
        def cite(match):
            ids = match.group(1).split(', '); labels = []
            for sid in ids:
                url = sources.get(sid,{}).get('url','')
                labels.append('<a href="'+escape(url,{'"':'&quot;'})+'" color="#19766e">'+sid+'</a>' if url.startswith(('http://','https://')) else sid)
            return '['+', '.join(labels)+']'
        value = re.sub(r'\[([a-zA-Z0-9_, -]+)\]',cite,value)
        style=ParagraphStyle('flow',fontName=self.editor.style['font_family'],fontSize=size*self.editor.style['font_scale'],leading=size*1.45*self.editor.style['font_scale'],textColor=self.ink,splitLongWords=True,allowWidows=0,allowOrphans=0)
        pending=[Paragraph(value,style)]
        while pending:
            if y<90:y=self.page_start(title)
            paragraph=pending.pop(0);_,height=paragraph.wrap(self.width,y-58)
            if height>y-58:
                # Keep normal explanations and their citations together; only
                # genuinely long passages need to split across pages.
                if height<=300:
                    y=self.page_start(title);pending.insert(0,paragraph);continue
                parts=paragraph.split(self.width,y-58)
                if not parts:
                    y=self.page_start(title);pending.insert(0,paragraph);continue
                paragraph=parts[0];pending=parts[1:]+pending;_,height=paragraph.wrap(self.width,y-58)
            paragraph.drawOn(self.canvas,45,y-height);y-=height+12
            if pending:y=self.page_start(title)
        return y

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
    if record.get('analysis', {}).get('version') != 4 or not record.get('analysis', {}).get('horizons'):
        if record.get('mode') != 'demo':
            raise ValueError('Generate the report again to refresh its calculations and AI conclusions before applying photos or finalizing this older draft.')
        from .finance import analyse
        from .narrative import deterministic
        from .evidence import enriched_inputs
        record['inputs'] = enriched_inputs(record['inputs'], record['evidence'])
        record['analysis'] = analyse(record['inputs'], record['evidence'], record['mode'])
        if not record['analysis']['available']: raise ValueError('Missing report inputs: '+', '.join(record['analysis'].get('missing', [])))
        record['narrative'] = deterministic(record, 'Demo report model upgraded using saved evidence')
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
    from .report_layout import render_report
    layout=render_report(record,pdf,folder,editor,final,png)
    record["report_document"]=editor.catalog
    from .source_report import generate_sources
    source_path=folder/(prefix+'-sources.pdf')
    source_pages=generate_sources(record,source_path)
    return {'pdf':pdf.name,'sources_pdf':source_path.name,'cashflow_png':png.name,'cashflow_csv':csv_path.name,'calculations_png':calc.name,'generated_at':now(),'revision':record['revision'],'final':final,'sources_page_count':source_pages,**layout}

"""Measured print compositions and vector charts for the Signature Edition."""
import re
from reportlab.lib import colors
from reportlab.platypus import Flowable, Table, TableStyle, Paragraph
from reportlab.pdfbase.pdfmetrics import stringWidth, getAscentDescent
from . import branding

PAPER = colors.HexColor(branding.IVORY)
GREEN = colors.HexColor(branding.GREEN)
GOLD = colors.HexColor(branding.GOLD)
MUTED = colors.HexColor(branding.MUTED)
CHART = colors.HexColor('#e4e8d8')
TABLE_HEAD = colors.HexColor('#dfd8c4')
PHOTO = colors.HexColor('#e4ddcd')
RED = colors.HexColor('#96362b')


class Stack(Flowable):
    def __init__(self, items, background=None, padding=0):
        super().__init__()
        self.items = list(items)
        self.background = background
        self.padding = padding
        self.spaceAfter = 8

    def wrap(self, width, height):
        self.width = width
        for item in self.items:
            if isinstance(item,Paragraph) and item.minWidth()>width-2*self.padding+.1:
                raise ValueError('Unbreakable report text exceeds the fixed ten-page layout. No text was cut.')
        self.sizes = [item.wrap(width-2*self.padding, 10000)[1] for item in self.items]
        self.height = sum(h+item.getSpaceAfter() for item,h in zip(self.items,self.sizes))+2*self.padding
        return self.width, self.height

    def draw(self):
        if self.background:
            self.canv.setFillColor(self.background)
            self.canv.rect(0,0,self.width,self.height,fill=1,stroke=0)
        y = self.height-self.padding
        for item,height in zip(self.items,self.sizes):
            item.drawOn(self.canv,self.padding,y-height)
            y -= height+item.getSpaceAfter()


class Columns(Flowable):
    def __init__(self, left, right, ratio=.5, gap=16):
        super().__init__()
        self.left = left if isinstance(left,Flowable) else Stack(left)
        self.right = right if isinstance(right,Flowable) else Stack(right)
        self.ratio,self.gap = ratio,gap
        self.spaceAfter = 8

    def wrap(self, width, height):
        self.width = width
        self.lw = (width-self.gap)*self.ratio
        self.rw = width-self.gap-self.lw
        self.lh = self.left.wrap(self.lw,height)[1]
        self.rh = self.right.wrap(self.rw,height)[1]
        self.height = max(self.lh,self.rh)
        return width,self.height

    def draw(self):
        self.left.drawOn(self.canv,0,self.height-self.lh)
        self.right.drawOn(self.canv,self.lw+self.gap,self.height-self.rh)


class ResponsiveTable(Flowable):
    def __init__(self, cells, widths, padding=3):
        super().__init__()
        self.cells,self.widths,self.padding = cells,widths,padding
        self.spaceAfter = 8

    def wrap(self, width, height):
        widths = [width*w/sum(self.widths) for w in self.widths]
        for row in self.cells:
            for cell,cell_width in zip(row,widths):
                if isinstance(cell,Paragraph) and cell.minWidth()>cell_width-8+.1:
                    raise ValueError('Table text %r needs %.1f points but its column has %.1f in the fixed ten-page layout. No text was cut.'
                                     % (cell.getPlainText()[:80],cell.minWidth(),cell_width-8))
        self.table = Table(self.cells,colWidths=widths,hAlign='LEFT')
        commands = [('VALIGN',(0,0),(-1,-1),'TOP'),
                    ('BACKGROUND',(0,0),(-1,0),TABLE_HEAD),
                    ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
                    ('TOPPADDING',(0,0),(-1,-1),self.padding),
                    ('BOTTOMPADDING',(0,0),(-1,-1),self.padding)]
        for row in range(2,len(self.cells),2):
            commands.append(('BACKGROUND',(0,row),(-1,row),colors.HexColor(branding.TINT)))
        self.table.setStyle(TableStyle(commands))
        self.width,self.height = self.table.wrap(width,height)
        return self.width,self.height

    def draw(self):
        self.table.drawOn(self.canv,0,0)


class Cover(Flowable):
    def __init__(self, introduction, address, price, photograph, height=519):
        super().__init__()
        self.introduction,self.address,self.price,self.photograph = introduction,address,price,photograph
        self.height=height
        self.spaceAfter=15

    def wrap(self,width,height):
        self.width=width
        self.left=(width-16.5)*.4
        inner=self.left-27
        self.ih=self.introduction.wrap(inner,10000)[1]
        self.ah=self.address.wrap(inner,10000)[1]
        self.ph=self.price.wrap(inner,10000)[1]
        if self.ih+self.ah+self.ph+60>self.height:
            raise ValueError('Cover text exceeds the fixed ten-page layout. No text was cut.')
        self.photograph.width=width-self.left-16.5
        self.photograph.height=self.height
        return width,self.height

    def draw(self):
        c=self.canv
        c.setFillColor(GREEN);c.rect(0,0,self.left,self.height,fill=1,stroke=0)
        self.introduction.drawOn(c,13.5,self.height-18-self.ih)
        self.address.drawOn(c,13.5,self.height-28-self.ih-self.ah)
        self.price.drawOn(c,13.5,18)
        self.photograph.drawOn(c,self.left+16.5,0)


class Chart(Flowable):
    """All marks are derived directly from the provided finite, known values."""
    def __init__(self, kind, title, labels, values, height=130, note='', unit='money', font=branding.BODY, accent=GOLD):
        super().__init__()
        self.kind,self.title,self.labels,self.values = kind,title,list(labels),list(values)
        self.height,self.note,self.unit,self.font = height,note,unit,font
        self.accent=accent
        self.spaceAfter=8

    def wrap(self,width,height):
        self.width=width
        bold=branding.BOLD if self.font==branding.BODY else self.font
        if stringWidth(self.title,bold,9.5)>width-18:
            raise ValueError('Chart heading exceeds its panel in the fixed ten-page layout. Shorten the heading; no text was cut.')
        if self.values:
            available=112 if self.kind=='horizontal' else (width-18)/len(self.values)-6
            size=8 if self.kind=='horizontal' else 7.4 if self.kind=='stacked' else 9.5
            if self.kind in ('horizontal','stacked','yields') and any(stringWidth(str(label),self.font,size)>available for label in self.labels):
                raise ValueError('Chart label exceeds its column in the fixed ten-page layout. No text was cut.')
        return width,self.height

    def label(self,x,y,text,size=8,align='left',bold=False,color=GREEN):
        c=self.canv;c.setFillColor(color)
        font=branding.BOLD if bold and self.font==branding.BODY else self.font
        extent=stringWidth(str(text),font,size)
        left=x-extent/2 if align=='center' else x-extent if align=='right' else x
        ascent,descent=getAscentDescent(font,size)
        if left<0 or left+extent>self.width+.1 or y+descent<0 or y+ascent>self.height+.1:
            raise ValueError('Chart text exceeds its panel in the fixed ten-page layout. No text was cut.')
        c.setFont(font,size)
        method=c.drawCentredString if align=='center' else c.drawRightString if align=='right' else c.drawString
        method(x,y,str(text))

    def money(self,value,short=False):
        if self.unit=='percent':return f'{value:.2f}%'
        sign='−' if value<0 else ''
        return sign+'£'+(f'{abs(value)/1000:,.0f}k' if short and abs(value)>=10000 else f'{abs(value):,.0f}' if short else f'{abs(value):,.2f}')

    def caption(self,text,width,size=7.5):
        from reportlab.lib.styles import ParagraphStyle
        from xml.sax.saxutils import escape
        p=Paragraph(escape(str(text)),ParagraphStyle('chart-caption',fontName=self.font,fontSize=size,
                    leading=size*1.2,alignment=1,textColor=MUTED))
        p.wrap(width,1000)
        return p

    def draw(self):
        c=self.canv;w,h=self.width,self.height
        c.setFillColor(CHART);c.rect(0,0,w,h,fill=1,stroke=0)
        self.label(9,h-17,self.title,9.5,bold=True)
        if self.note:
            # Notes wrap in narrow columns, without changing the plot scale.
            from reportlab.lib.styles import ParagraphStyle
            from xml.sax.saxutils import escape
            p=Paragraph(escape(self.note),ParagraphStyle('chart-note',fontName=self.font,fontSize=7.2,leading=9,textColor=MUTED))
            _,nh=p.wrap(w-18,100);p.drawOn(c,9,7)
        else:nh=0
        bottom=18+nh
        if not self.values:return
        if self.kind=='horizontal':
            lo=min(0,min(self.values));hi=max(0,max(self.values))
            span=hi-lo or 1
            x0,x1=130,w-75
            zero=x0+(0-lo)/span*(x1-x0)
            c.setStrokeColor(colors.HexColor(branding.LINE));c.setLineWidth(.35)
            c.line(zero,bottom+12,zero,h-30)
            row=(h-48-bottom)/len(self.values)
            for i,(label,value) in enumerate(zip(self.labels,self.values)):
                y=h-37-i*row
                end=x0+(value-lo)/span*(x1-x0)
                c.setFillColor(RED if i==len(self.values)-1 else GREEN)
                if value:c.rect(min(zero,end),y-3,abs(end-zero),7,fill=1,stroke=0)
                self.label(9,y-2,label,8,color=MUTED)
                self.label(w-9,y-2,self.money(value),8,align='right',bold=True)
            self.label(x0,bottom,self.money(lo,True),7,color=MUTED)
            self.label(x1,bottom,self.money(hi,True),7,align='right',color=MUTED)
        elif self.kind=='stacked':
            total=sum(self.values)
            y=h-45
            palette=[GREEN,self.accent,colors.HexColor('#6c8775'),colors.HexColor('#a8b8a2'),MUTED]
            x=9
            for i,value in enumerate(self.values):
                size=(w-18)*value/total if total else 0
                c.setFillColor(palette[i%len(palette)])
                if size:c.rect(x,y,size,9,fill=1,stroke=0)
                x+=size
            cell=(w-18)/len(self.values)
            for i,(label,value) in enumerate(zip(self.labels,self.values)):
                self.label(9+i*cell,y-16,label,7.4,color=MUTED)
                self.label(9+i*cell,y-32,self.money(value),8,bold=True)
        elif self.kind=='line':
            lo,hi=min(self.values),max(self.values)
            gap=(hi-lo)*.2 or max(1,abs(hi)*.05)
            low,high=lo-gap,hi+gap
            top=h-52;floor=bottom+16
            x0,x1=65,w-25
            pts=[(x0+i*(x1-x0)/max(1,len(self.values)-1),floor+(value-low)/(high-low)*(top-floor)) for i,value in enumerate(self.values)]
            self.label(9,h-32,'Start £'+f'{self.values[0]:,.0f}',8,color=MUTED)
            self.label(w/2,h-32,'Peak £'+f'{hi:,.0f}',8,align='center',color=MUTED)
            self.label(w-9,h-32,'End £'+f'{self.values[-1]:,.0f}',8,align='right',bold=True)
            for value in (lo,(lo+hi)/2,hi):
                y=floor+(value-low)/(high-low)*(top-floor)
                c.setStrokeColor(colors.HexColor(branding.LINE));c.setLineWidth(.35);c.line(x0,y,x1,y)
                self.label(x0-7,y-3,self.money(value,True),7.5,align='right',color=MUTED)
            c.setStrokeColor(GREEN);c.setLineWidth(1.6)
            if len(pts)==1:c.circle(*pts[0],2,fill=1,stroke=0)
            for left,right in zip(pts,pts[1:]):c.line(*left,*right)
            indices=sorted(set([0,len(self.values)//3,2*len(self.values)//3,len(self.values)-1]))
            for i in indices:self.label(pts[i][0],bottom,self.labels[i],7.5,align='center',color=MUTED)
        elif self.kind=='costs':
            maximum=max(self.values) or 1
            step=(w-30)/len(self.values)
            captions=[self.caption(label,step-4) for label in self.labels]
            legend_height=max(p.height for p in captions)
            amount_y=nh+14
            floor=amount_y+17+legend_height;top=h-30
            for i,(label,value) in enumerate(zip(self.labels,self.values)):
                x=15+(i+.5)*step
                c.setFillColor(GREEN if value==maximum else colors.HexColor('#6c8775'))
                c.rect(x-step*.32,floor,step*.64,max(0,top-floor)*value/maximum,fill=1,stroke=0)
                captions[i].drawOn(c,x-(step-4)/2,floor-6-captions[i].height)
                self.label(x,amount_y,self.money(value),8.5 if len(self.values)<=6 else 6.5,align='center',bold=True)
        else:
            lo=min(0,min(self.values));hi=max(0,max(self.values))
            span=hi-lo or 1
            top=h-(43 if self.kind=='cash' else 38)
            floor=bottom+22
            if self.kind=='evidence':
                top=h-30
                floor=bottom+12
            zero=floor+(0-lo)/span*(top-floor)
            c.setStrokeColor(colors.HexColor(branding.LINE));c.setLineWidth(.35);c.line(16,zero,w-12,zero)
            step=(w-30)/len(self.values)
            for i,(label,value) in enumerate(zip(self.labels,self.values)):
                x=15+(i+.5)*step;end=floor+(value-lo)/span*(top-floor)
                c.setFillColor(RED if value<0 and self.kind=='yields' else GREEN)
                if value:c.rect(x-step*.16,min(zero,end),step*.32,abs(end-zero),fill=1,stroke=0)
                if self.kind not in ('cash','evidence'):self.label(x,top+6,self.money(value),10.5,align='center',bold=True)
                self.label(x,bottom+(1 if self.kind=='evidence' else 7),self.money(value,True) if self.kind=='evidence' else label,
                           9.5 if self.kind=='yields' else 7,align='center',color=MUTED)
            self.label(13,zero+3,'0%' if self.unit=='percent' else '£0',6.8,color=MUTED)
            if self.kind=='cash':
                self.label(18,h-32,'Year '+str(self.labels[0])+': '+self.money(self.values[0]),8,bold=True)
                self.label(w-12,h-32,'Year '+str(self.labels[-1])+': '+self.money(self.values[-1]),8,align='right',bold=True)


def numeric_cell(text):
    return bool(re.fullmatch(r'[£−–+\-\d,./%\s]+(?:years| / sq ft)?',str(text)))

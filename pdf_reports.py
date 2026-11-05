"""Generate the two personal reports in memory from the bot's existing readings."""
from datetime import date
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as RasterImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer

from catalog import CTA, CONTACTS, TELEGRAM_HANDLE, description
from forecast_catalog import forecast_description
from karma_catalog import negative_description, positive_description
from matrix_catalog import matrix_digit_description, read_matrix_catalog
from money_catalog import money_description
from portrait import (calculate, calculate_forecast, calculate_karma, calculate_matrix,
                      calculate_money, calculate_program, calculate_social, matrix_patterns)
from program_catalog import program_description, program_entry
from render import draw_matrix, draw_portrait, draw_program
from social_catalog import social_description

FONT='PortraitSans'
INK=colors.HexColor('#25263B')
VIOLET=colors.HexColor('#473770')
MUTED=colors.HexColor('#65647A')
RULE=colors.HexColor('#E5DFF0')
MARGIN=48
FULL_SECTIONS=('Портрет · 33 позиції','Матриця','Соціальне призначення',
               'Грошове призначення','Плюсова карма','Мінусова карма','Прогнози')
KARMA_INTRO='У цій нумерологічній методиці карма - це те, що Ви принесли з минулого життя як досвід у теперішнє. Вона охоплює як здібності й можливості, так і уроки, до яких Ви можете повертатися.'
KARMA_TYPES={
    'positive': 'Плюсова (позитивна) карма описує Ваші природні таланти, можливості та підтримку, які можуть полегшувати шлях до реалізації. Ці якості можна помічати, розвивати й використовувати у своїх справах.',
    'negative': 'Мінусова (негативна) карма нагадує про помилки минулого й уроки, які можуть проявлятися через повторювані ситуації. Такі ситуації допомагають помітити звичні реакції та спробувати діяти інакше, щоб вони менше обмежували Вас.',
}


class PortraitSheet(Flowable):
    """Fill A4 while keeping the original diagram's proportions."""
    def __init__(self,data):
        super().__init__()
        self.width=self.height=1
        with RasterImage.open(BytesIO(data)) as original:
            width,height=original.size
            page_width=round(height*A4[0]/A4[1])
            left=(page_width-width)//2
            right=page_width-width-left
            # Extend only the outermost background columns, leaving the artwork intact.
            sheet=RasterImage.new('RGB',(page_width,height))
            sheet.paste(original.crop((0,0,1,height)).resize((left,height)),(0,0))
            sheet.paste(original,(left,0))
            sheet.paste(original.crop((width-1,0,width,height)).resize((right,height)),(left+width,0))
        self.sheet=ImageReader(sheet)

    def draw(self):
        self.canv.bookmarkPage('section1')
        self.canv.resetTransforms()
        self.canv.drawImage(self.sheet,0,0,*A4)


def _reading(text):
    """Leave shared contact and consultation details on the cover."""
    for suffix in ('\n\n'+CTA,'\n\n'+CONTACTS):
        if text.endswith(suffix):
            return text[:-len(suffix)]
    return text


class Report:
    def __init__(self,title,birth,sections,name=None,generated=None):
        if FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT,str(Path(__file__).parent/'assets'/'DejaVuSans.ttf')))
        self.glyphs=pdfmetrics.getFont(FONT).face.charWidths
        self.title=title
        self.birth=birth
        self.story=[]
        self.styles={
            'title':ParagraphStyle('title',fontName=FONT,fontSize=30,leading=38,textColor=VIOLET,spaceAfter=18),
            'chapter':ParagraphStyle('chapter',fontName=FONT,fontSize=21,leading=28,textColor=VIOLET,spaceAfter=15,keepWithNext=True),
            'heading':ParagraphStyle('heading',fontName=FONT,fontSize=13,leading=19,textColor=VIOLET,spaceBefore=8,spaceAfter=6,keepWithNext=True),
            'body':ParagraphStyle('body',fontName=FONT,fontSize=10.4,leading=16,textColor=INK,spaceAfter=8),
            'meta':ParagraphStyle('meta',fontName=FONT,fontSize=10,leading=15,textColor=MUTED,spaceAfter=6),
            'index':ParagraphStyle('index',fontName=FONT,fontSize=11,leading=16,textColor=VIOLET,spaceAfter=4),
        }
        self.story.append(Spacer(1,20))
        self.add('НАДІЯ ЦАРЕНКО · НУМЕРОЛОГІЯ','meta')
        self.add(title,'title')
        self.add('Дата народження: '+birth,'body')
        if name:self.add('Ім’я: '+name,'body')
        if generated:self.add('Сформовано: '+generated.strftime('%d.%m.%Y'),'meta')
        self.add('Telegram та Instagram: '+TELEGRAM_HANDLE,'meta')
        self.add('Зміст','heading')
        for i,label in enumerate(sections,1):
            # Keep the cover compact even with all 21 programs.
            markup=f'<link href="#section{i}">{i:02d}  {self.clean(label)}</link>'
            self.story.append(Paragraph(markup,self.styles['index']))
        self.story.append(PageBreak())

    def clean(self,text):
        text=text.replace('–','-').replace('—','-').replace('‑','-')
        return escape(''.join(c for c in text if c=='\n' or ord(c) in self.glyphs)).replace('\n','<br/>')

    def add(self,text,style='body'):
        self.story.append(Paragraph(self.clean(text),self.styles[style]))

    def chapter(self,number,label):
        if number>1:self.story.append(PageBreak())
        self.story.append(Paragraph(f'<a name="section{number}"/>{self.clean(label)}',self.styles['chapter']))

    def reading(self,text):
        for block in _reading(text).split('\n\n'):
            block=block.strip()
            if block:self.add(block)

    def image(self,data,max_width,max_height):
        image=Image(BytesIO(data),kind='proportional',width=max_width,height=max_height)
        image.hAlign='CENTER'
        self.story.extend([image,Spacer(1,10)])

    def build(self):
        out=BytesIO()
        doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=MARGIN,rightMargin=MARGIN,
                              topMargin=55,bottomMargin=48,title=self.title,author='Надія Царенко')
        has_portrait_sheet=any(isinstance(item,PortraitSheet) for item in self.story)
        def frame(canvas,document):
            if has_portrait_sheet and document.page==2:
                return
            width,height=A4
            canvas.saveState()
            canvas.setStrokeColor(RULE)
            canvas.line(MARGIN,height-40,width-MARGIN,height-40)
            canvas.line(MARGIN,38,width-MARGIN,38)
            canvas.setFillColor(MUTED)
            canvas.setFont(FONT,8)
            canvas.drawString(MARGIN,height-32,self.birth)
            canvas.drawRightString(width-MARGIN,height-32,TELEGRAM_HANDLE)
            canvas.drawString(MARGIN,24,'Надія Царенко')
            canvas.drawRightString(width-MARGIN,24,str(document.page))
            canvas.restoreState()
        doc.build(self.story,onFirstPage=frame,onLaterPages=frame)
        return out.getvalue()


def unique_karma(values):
    """Keep one description per arcanum, in first-occurrence order."""
    return tuple(dict.fromkeys(values))


def forecast_periods(birth,today):
    current_year=str(today.year)
    current_month=today.strftime('%m.%Y')
    next_month=date(today.year+(today.month==12),today.month%12+1,1).strftime('%m.%Y')
    year=next(row for row in calculate_forecast(birth,'year',today) if row[0]==current_year)
    months={row[0]:row[1] for row in calculate_forecast(birth,'month',today)}
    return ((current_year,'year',year[1],1),(current_year,'year',year[2],2),
            (current_month,'month',months[current_month],1),(next_month,'month',months[next_month],1))


def build_full_pdf(birth,name,today):
    portrait,_=calculate(birth)
    money=calculate_money(birth,name)
    pdf=Report('Ваш повний нумерологічний розбір',birth,FULL_SECTIONS,money['name'],today)
    pdf.story.extend([PortraitSheet(draw_portrait(birth,portrait)),PageBreak()])
    pdf.add(FULL_SECTIONS[0],'chapter')
    for n in range(1,34):
        heading,*body=_reading(description(n,birth,portrait)).split('\n\n')
        pdf.add(heading.split('\n',1)[0],'heading')
        pdf.reading('\n\n'.join(body))
    pdf.chapter(2,FULL_SECTIONS[1])
    matrix=calculate_matrix(birth)
    pdf.image(draw_matrix(birth,matrix),390,330)
    for digit,count in matrix['counts'].items():
        heading,body=matrix_digit_description(digit,count).split('\n\n',1)
        pdf.add(heading,'heading')
        pdf.reading(body)
    patterns=matrix_patterns(matrix['counts'])
    catalog=read_matrix_catalog()
    for kind,heading in (('lines','Заповнені лінії'),('triangles','Трикутники')):
        pdf.add(heading,'heading')
        selected=patterns['selected_'+kind]
        if not selected:
            pdf.add('Заповнених ліній для опису немає.' if kind=='lines' else 'Повних трикутників немає.')
        elif kind=='triangles' and len(selected)==2:
            pdf.add('Обидва напрями врівноважують один одного.')
        elif kind=='triangles' and all(row['complete'] for row in patterns['triangles'].values()):
            pdf.add('Переважає '+catalog[kind][selected[0]]['title'].lower()+'.')
        for key in selected:
            pdf.add(catalog[kind][key]['title'],'heading')
            pdf.reading(catalog[kind][key]['text'])
    pdf.chapter(3,FULL_SECTIONS[2])
    pdf.reading(social_description(calculate_social(birth)))
    pdf.chapter(4,FULL_SECTIONS[3])
    pdf.reading(money_description(money['arcanum']))
    karma=calculate_karma(birth)
    for chapter,kind,describe in ((5,'positive',positive_description),(6,'negative',negative_description)):
        pdf.chapter(chapter,FULL_SECTIONS[chapter-1])
        if kind=='positive':
            pdf.add('Що таке карма?','heading')
            pdf.add(KARMA_INTRO)
        pdf.add('Що таке '+FULL_SECTIONS[chapter-1].lower()+'?','heading')
        pdf.add(KARMA_TYPES[kind])
        for arcanum in unique_karma(karma[kind]):
            # The first block is the chat heading with a position and date.
            _,body=_reading(describe(1,arcanum,birth)).split('\n\n',1)
            heading,body=body.split('\n\n',1)
            pdf.add(heading,'heading')
            pdf.reading(body)
    pdf.chapter(7,FULL_SECTIONS[6])
    for period,kind,arcanum,slot in forecast_periods(birth,today):
        focus=(' · Робота та фінанси' if slot==1 else ' · Особисте життя') if kind=='year' else ''
        pdf.add(period+focus,'heading')
        pdf.reading(forecast_description(kind,arcanum,slot))
    return pdf.build()


def build_programs_pdf(birth):
    entries=[program_entry(n) for n in range(1,22)]
    labels=[f"Програма {n} · {entry['title']}" for n,entry in enumerate(entries,1)]
    pdf=Report('21 нумерологічна програма',birth,labels)
    for n,entry in enumerate(entries,1):
        values=calculate_program(birth,n)
        pdf.chapter(n,labels[n-1])
        pdf.image(draw_program(birth,n,entry['title'],values),360,240)
        pdf.reading(entry['overview'])
        for q,value in values.items():
            pdf.add(f"Питання {q} · {entry['questions'][q-1]['question']}",'heading')
            # Omit the repeated program and question headings from the chat reply.
            body=program_description(n,q,value).split('\n\n',2)[2]
            pdf.reading(body)
    return pdf.build()

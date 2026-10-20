from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).parent

def draw_matrix(value,result):
    im=Image.new('RGB',(1200,1200),'#fcfbf9'); d=ImageDraw.Draw(im)
    font=lambda size: ImageFont.truetype(str(ROOT/'assets'/'DejaVuSans.ttf'),size)
    def text(x,y,t,size=38,fill='#202934'):
        d.text((x,y),t,font=font(size),fill=fill,anchor='mm')
    text(600,55,'@lakshmi_775',26)
    text(600,115,'Матриця',54)
    text(600,178,value,34)
    for col in range(3):
        for row in range(3):
            digit = col*3+row+1
            x,y = 90+col*340,250+row*265
            d.rectangle((x,y,x+340,y+265),outline='#719bc1',width=3)
            text(x+28,y+30,str(digit),22,fill='#61788d')
            cell = str(digit)*result['counts'][digit] or '−'
            size=72
            while d.textbbox((0,0),cell,font=font(size))[2] > 300:
                size-=2
            text(x+170,y+135,cell,size)
    out=BytesIO(); im.save(out,'PNG'); return out.getvalue()

def draw_karma(result):
    """Two aligned rows of exact calculation values, following the supplied example."""
    im=Image.new('RGB',(1200,650),'white')
    d=ImageDraw.Draw(im)
    fontpath=str(ROOT/'assets'/'DejaVuSans.ttf')
    heading=ImageFont.truetype(fontpath,128)
    numbers=ImageFont.truetype(fontpath,94)
    d.text((62,38),'Карма',font=heading,fill='#111111',anchor='lt')
    for sign,key,y in [('+','positive',335),('−','negative',555)]:
        d.text((78,y),sign,font=numbers,fill='#111111',anchor='mm')
        for x,value in zip([280,480,680,880,1080],result[key]):
            d.text((x,y),str(value),font=numbers,fill='#111111',anchor='mm')
    out=BytesIO(); im.save(out,'PNG'); return out.getvalue()

def draw_portrait(value,p):
    """Reference layout: a tall sheet, narrow blue frames and two open triangles.

    Coordinates use the reference's 707 px sheet width. Draw at double size
    so Telegram can display both the overview and a sharp enlarged portrait.
    """
    from PIL import ImageFilter
    scale=2
    width,height=707,1400
    im=Image.new('RGB',(width*scale,height*scale),'#fdfbf8')
    # Quiet cream and lavender washes leave the calculation itself high contrast.
    wash=Image.new('RGB',im.size,'#fdfbf8'); wd=ImageDraw.Draw(wash)
    wd.ellipse((-180,1600,1150,2980),fill='#f3eef4')
    wd.ellipse((400,-400,1700,1100),fill='#ffffff')
    im=wash.filter(ImageFilter.GaussianBlur(160))
    d=ImageDraw.Draw(im)
    fontpath=str(ROOT/'assets'/'DejaVuSans.ttf')
    def text(x,y,t,size=26,fill='#111111'):
        d.text((round(x*scale),round(y*scale)),t,
               font=ImageFont.truetype(fontpath,round(size*scale)),
               fill=fill,anchor='mm')
    def path(points,fill='#6c9fc3',width=1.5):
        d.line([(round(x*scale),round(y*scale)) for x,y in points],
               fill=fill,width=round(width*scale),joint='curve')
    text(353.5,34,'@lakshmi_775',12,fill='#69717a')
    text(353.5,61,value,14,fill='#4e5660')
    nodes={
        'П11':(157,157),'П19':(389,157),'П20':(493,157),'П21':(585,157),
        'П9':(103,245),'П10':(212,245),'П15':(339,245),
        'П16':(432,245),'П17':(524,245),'П18':(615,245),
        'П13':(88,348),'П14':(405,348),
        'П1':(162,429),'П2':(247,429),'П3':(329,429),
        'П4':(209,530),'П5':(289,530),'П6':(248,620),
        'П12':(96,556),'П7':(408,543),'П30':(149,652),'П8':(249,722),
        'A':(249,824),'B':(199,914),'C':(299,914),
        'D':(159,1010),'E':(248,1010),'F':(339,1010),
        'G1':(405,879),'G2':(477,967),
        'H':(246,1122),'Кп':(339,1175),'J':(429,1175)
    }
    # Connections terminate at frames, exactly as on the supplied sheet.
    path([(133,239),(182,239)])
    path([(88,387),(218,671),(285,671),(402,387)])
    path([(279,724),(411,724),(411,582)])
    path([(84,1054),(203,775),(290,775),(418,1049)])
    path([(412,968),(484,862)])
    for key,(x,y) in nodes.items():
        box=(round((x-30)*scale),round((y-39)*scale),
             round((x+30)*scale),round((y+39)*scale))
        d.rectangle(box,fill='#ffffff',outline='#6c9fc3',width=3)
        result=f"{p['П15а']}\\{p['П15б']}" if key=='П15' else str(p[key])
        text(x,y-8,result,17 if key=='П15' else 26)
        text(x,y+20,key,11)
    # Small, pale lotus ornament sits below all 33 positions.
    def curve(a,b,c,e):
        return [tuple((1-t)**3*a[i]+3*(1-t)**2*t*b[i]+
                      3*(1-t)*t*t*c[i]+t**3*e[i] for i in (0,1))
                for t in [j/32 for j in range(33)]]
    lotus_offset=width/2-452
    base=(452,1332)
    for tip,left,right,color in [
        ((356,1297),(393,1342),(437,1293),'#f3e4e3'),
        ((548,1297),(467,1293),(511,1342),'#f3e4e3'),
        ((390,1275),(404,1326),(449,1282),'#f8eae7'),
        ((514,1275),(455,1282),(500,1326),'#f8eae7'),
        ((420,1261),(419,1312),(463,1283),'#f7e7e4'),
        ((484,1261),(441,1283),(485,1312),'#f7e7e4'),
        ((452,1248),(416,1298),(488,1298),'#fff5ee')]:
        points=curve(base,left,left,tip)+curve(tip,right,right,base)
        d.polygon([(round((x+lotus_offset)*scale),round(y*scale)) for x,y in points],fill=color)
    path([(width/2-125,1343),(width/2+125,1343)],fill='#e7e0df',width=1)
    out=BytesIO(); im.save(out,'PNG'); return out.getvalue()

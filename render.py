from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).parent

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
    im=Image.new('RGB',(2000,2000),'#fcfbf9'); d=ImageDraw.Draw(im)
    fontpath=str(ROOT/'assets'/'DejaVuSans.ttf')
    font=lambda size: ImageFont.truetype(fontpath,size)
    def text(x,y,t,size=28,fill='#202934'):
        d.text((x,y),t,font=font(size),fill=fill,anchor='mm')
    text(1000,47,'@lakshmi_775',25)
    text(1000,91,'Портрет 33 позиції',35)
    text(1000,132,value,28)
    nodes={
      'П11':(350,245),'П19':(1050,245),'П20':(1350,245),'П21':(1650,245),
      'П9':(240,405),'П10':(460,405),'П15':(750,405),'П16':(1050,405),'П17':(1350,405),'П18':(1650,405),
      'П13':(400,565),'П14':(1400,565),
      'П1':(650,725),'П2':(900,725),'П3':(1150,725),
      'П4':(775,885),'П5':(1025,885),'П6':(900,1045),
      'П12':(350,885),'П7':(1400,885),'П30':(500,1085),'П8':(900,1205),
      'A':(900,1365),'B':(775,1525),'C':(1025,1525),
      'D':(650,1685),'E':(900,1685),'F':(1150,1685),
      'G1':(1450,1455),'G2':(1660,1635),'H':(900,1845),'Кп':(1300,1845),'J':(1550,1845)}
    line='#719bc1'
    # Only the connections visible in the supplied reference are drawn.
    d.line([nodes['П9'],nodes['П10']],fill=line,width=3)
    d.line([(400,635),(790,1115),(1010,1115),(1400,635)],fill=line,width=3)
    d.line([nodes['П8'],(1400,1205),nodes['П7']],fill=line,width=3)
    d.line([(470,1755),(790,1285),(1010,1285),(1330,1755)],fill=line,width=3)
    d.line([(1515,1630),(1605,1470)],fill=line,width=3)
    for key,(x,y) in nodes.items():
        d.rectangle((x-70,y-70,x+70,y+70),fill='white',outline=line,width=3)
        result=f"{p['П15а']} / {p['П15б']}" if key=='П15' else str(p[key])
        text(x,y-14,result,34 if key=='П15' else 48)
        text(x,y+43,key,22)
    out=BytesIO(); im.save(out,'PNG'); return out.getvalue()

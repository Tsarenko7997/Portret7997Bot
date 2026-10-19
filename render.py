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
    im=Image.new('RGB',(1200,2000),'#f5f3fa'); d=ImageDraw.Draw(im)
    fontpath=str(ROOT/'assets'/'DejaVuSans.ttf')
    font=lambda s: ImageFont.truetype(fontpath,s)
    def text(x,y,t,size=26,fill='#48375f'):
        d.text((x,y),t,font=font(size),fill=fill,anchor='mm')
    text(600,52,'НАДІЯ ЦАРЕНКО',26)
    text(600,105,'Портрет за датою народження',38)
    text(600,155,value,30)
    nodes={
      'П11':(130,245),'П19':(640,245),'П20':(840,245),'П21':(1040,245),
      'П9':(75,390),'П10':(245,390),'П15':(500,390),'П16':(670,390),'П17':(840,390),'П18':(1010,390),
      'П13':(160,555),'П14':(870,555),
      'П1':(320,710),'П2':(520,710),'П3':(720,710),
      'П4':(420,865),'П5':(620,865),'П6':(520,1020),
      'П12':(1020,865),'П7':(900,1020),'П30':(210,1020),'П8':(520,1175),
      'A':(520,1375),'B':(420,1530),'C':(620,1530),
      'D':(320,1685),'E':(520,1685),'F':(720,1685),
      'G1':(920,1375),'G2':(1040,1530),'H':(520,1850),'Кп':(850,1850),'J':(1040,1850)}
    line='#b1a7c6'
    def connect(a,b): d.line([nodes[a],nodes[b]],fill=line,width=3)
    for a,b in [('П9','П10'),('П9','П11'),('П10','П11'),('П1','П2'),('П2','П3'),('П1','П4'),('П2','П4'),('П2','П5'),('П3','П5'),('П4','П5'),('П4','П6'),('П5','П6'),('A','E'),('B','F'),('C','D')]: connect(a,b)
    d.line([(160,610),(385,1100),(655,1100),(870,610)],fill=line,width=4)
    d.line([(520,1175),(900,1175),(900,1020)],fill=line,width=3)
    d.line([(180,1760),(405,1285),(635,1285),(860,1760)],fill=line,width=4)
    for key,(x,y) in nodes.items():
        main=key in [f'П{i}' for i in range(1,7)]
        shadow=key in ['A','B','C','D','E','F','G1','G2','H']
        fill='#e7dcf7' if main else '#dcecf4' if shadow else '#ffffff'
        d.rounded_rectangle((x-68,y-57,x+68,y+57),radius=16,fill=fill,outline='#afa2c4',width=2)
        result=f"{p['П15а']} / {p['П15б']}" if key=='П15' else str(p[key])
        text(x,y-12,result,32 if key=='П15' else 43)
        text(x,y+34,key,19)
    text(600,1955,'Психологічний • Кармічний • Тіньовий портрет',23)
    out=BytesIO(); im.save(out,'PNG'); return out.getvalue()

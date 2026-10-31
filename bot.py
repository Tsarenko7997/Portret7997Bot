"""Telegram portrait bot with date-scoped paid interpretations."""
import json
import re
from html import escape
import lzma
import os
import secrets
import time
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from portrait import calculate, calculate_karma, calculate_social, calculate_money, calculate_matrix, calculate_forecast, calculate_compatibility
from render import draw_portrait, draw_karma, draw_matrix, draw_compatibility
from catalog import POSITIONS, FREE, description, chunks, position_meaning, TELEGRAM_HANDLE, TELEGRAM_URL, INSTAGRAM_URL, CONTACTS
from karma_catalog import negative_description, positive_description
from money_catalog import money_description
from forecast_catalog import forecast_description
from compatibility_catalog import compatibility_position, compatibility_description
from payments import Store, Prices, PaymentError

ROOT=Path(__file__).parent

def load_env():
    path=ROOT/'.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('\"\''))

class APIError(Exception):
    def __init__(self, code, retry=0):
        self.code,self.retry=code,retry
        super().__init__(f'Telegram API: {code}')

def instagram_nickname_link(method,data):
    """Display the Instagram handle; Telegram link offsets count UTF-16 units."""
    field = 'text' if method == 'sendMessage' else 'caption'
    if method not in ('sendMessage','sendPhoto','sendDocument'):
        return data
    text = data.get(field,'')
    entity_key = 'entities' if field == 'text' else 'caption_entities'
    # These plain-text messages have no pre-existing formatting entities.
    if data.get(entity_key) or data.get('parse_mode'):
        return data
    pieces = text.split(INSTAGRAM_URL)
    result = pieces[0]
    entities = []
    for suffix in pieces[1:]:
        entities.append({'type':'text_link',
                         'offset':len(result.encode('utf-16-le'))//2,
                         'length':len(TELEGRAM_HANDLE.encode('utf-16-le'))//2,
                         'url':INSTAGRAM_URL})
        result += TELEGRAM_HANDLE+suffix
    # Apply after shortening the URL, so all offsets refer to the final text.
    headings = (r'(?m)^(?:Позиція |Плюсова карма · |Мінусова карма · |'
                r'Сумісність · |С[1-8] · |Грошове призначення · |Прогноз на рік · |Прогноз на місяць · |Прогноз на день · |Аркан \d+ |Ваш аркан грошового призначення: )[^\n]+|'
                r'^(?:Позитивні прояви|Можливі труднощі|Внутрішні установки та блоки|'
                r'Кармічна тема|Внутрішні блоки|Сильні сторони|Ваш ресурс|Можливі прояви|'
                r'Що може послаблювати ресурс|Ваш акцент|Ключові слова|Загальний опис|Позитивні події)(?=\. )|'
                r'^(?:Карма|Позитивна карма|Негативна карма)(?=: )')
    for match in re.finditer(headings,result):
        entities.append({'type':'bold','offset':len(result[:match.start()].encode('utf-16-le'))//2,
                         'length':len(match.group().encode('utf-16-le'))//2})
    if not entities:
        return data
    entities.sort(key=lambda entity:entity['offset'])
    updated = {**data,field:result,entity_key:entities}
    if method == 'sendMessage':
        updated['link_preview_options'] = {'is_disabled':True}
    return updated

class Telegram:
    def __init__(self, token):
        self.base='https://api.telegram.org/bot'+token+'/'
        if os.getenv('TELEGRAM_TEST_ENV')=='1':self.base+='test/'
    def call(self, method, data=None, file=None):
        data=instagram_nickname_link(method,data or {})
        headers={}
        if file:
            boundary='Nadia'+secrets.token_hex(12); parts=[]
            for k,v in data.items():
                val=json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v)
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{val}\r\n'.encode())
            name,blob=file[:2]
            filename=file[2] if len(file)==3 else 'portrait.png'
            parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode(),blob,f'\r\n--{boundary}--\r\n'.encode()])
            body=b''.join(parts); headers['Content-Type']='multipart/form-data; boundary='+boundary
        else:
            body=json.dumps(data).encode(); headers['Content-Type']='application/json'
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base+method,data=body,headers=headers),timeout=8 if method == 'answerPreCheckoutQuery' else 45) as response:
                payload=json.load(response)
        except urllib.error.HTTPError as e:
            try: payload=json.loads(e.read())
            except (ValueError,UnicodeError): raise APIError(e.code) from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise APIError(0) from None
        if not payload.get('ok'):
            raise APIError(payload.get('error_code',0),payload.get('parameters',{}).get('retry_after',0))
        return payload['result']
    def say(self, chat, text, **extra): return self.call('sendMessage',{'chat_id':chat,'text':text,**extra})

SUPPORT = TELEGRAM_HANDLE
SECTIONS = {
    'portrait':'Портрет',
    'karma':'Карма +/−',
    'matrix':'Матриця',
    'money':'Грошове призначення',
    'social':'Соціальне призначення',
    'year':'Прогноз на роки',
    'month':'Прогноз на місяці',
    'day':'Прогноз на день',
    'compatibility':'Сумісність',
}
SECTION_ICONS = {'portrait':'👤','karma':'🔮','matrix':'🔢','money':'💰',
                 'social':'👫','year':'📅','month':'📆','day':'📆','compatibility':'👩‍❤️‍👨'}

def main_menu():
    buttons = [{'text':SECTION_ICONS[key]+' '+label,
                'callback_data':'section:'+key} for key,label in SECTIONS.items()]
    return {'inline_keyboard':[
        [buttons[0]], buttons[1:3], buttons[3:5], buttons[5:7], [buttons[7]], [buttons[8]],
        [{'text':'ℹ️ Інфо','callback_data':'info'}],
        [{'text':'Мій доступ','callback_data':'access'},
         {'text':'Написати в Telegram','url':TELEGRAM_URL}],
        [{'text':'Instagram @lakshmi_775','url':INSTAGRAM_URL}]]}

LOCKED_DESCRIPTION = ('🔒 Опис закритий. Повний доступ до описів відкриває автор особисто. '
                      'Для отримання доступу напишіть @lakshmi_775.')

def has_full_access(store,cid):
    return store.membership_until(cid) > int(time.time())

def locked_button(section,active):
    return [] if active else [[{'text':'🔒 Відкрити опис','callback_data':'locked:'+section}]]

def show_description_lock(api,cid,title,birth,store,section):
    text=title+('\nДата народження: '+birth if birth else '')+'\n\n'+LOCKED_DESCRIPTION
    text+='\n\n'+access_text(store,cid)
    api.say(cid,text,reply_markup={'inline_keyboard':[
        [{'text':'Написати автору','url':TELEGRAM_URL}],
        [{'text':'Повернутися до розрахунку','callback_data':'section:'+section}],
        [{'text':'Головне меню','callback_data':'home'}]]})

WELCOME = (
    '✨ <b>Вітаю у нумерологічному просторі Надії Царенко!</b>\n\n'
    'Я — <b>Надія</b>, таронумеролог і таролог. Тут я зібрала розрахунки та пояснення, '
    'які допоможуть Вам дослідити себе через символіку чисел і 22 арканів Таро.\n\n'
    '<b>Пізнайте себе. Розкрийте свій потенціал та дозвольте собі більше 💜</b>\n\n'
    '🔮 <b>Що Ви можете розрахувати в боті?</b>\n\n'
    '• <b>Особистий портрет — 33 позиції:</b> характер, таланти, внутрішні ресурси та життєві уроки.\n'
    '• <b>Позитивну й негативну карму:</b> можливості та повторювані сценарії в межах нумерологічної методики.\n'
    '• <b>Матрицю:</b> поєднання чисел Вашої дати народження. Тлумачення готуються.\n'
    '• <b>Соціальне призначення:</b> аркан реалізації та взаємодії з іншими. Тлумачення готуються.\n'
    '• <b>Грошове призначення:</b> символічні підказки для роздумів про свої здібності й реалізацію.\n'
    '• <b>Прогноз на рік:</b> два аркани для кожного з 10 років та їхні тлумачення.\n'
    '• <b>Прогноз на місяць:</b> аркани для 24 місяців та їхні тлумачення.\n'
    '• <b>Прогноз на день:</b> аркани для 31 дня та їхні тлумачення.\n\n'
    '• <b>Сумісність:</b> партнерський портрет із 8 позицій за двома датами народження.\n\n'
    '🔓 <b>Що доступно безкоштовно?</b>\n\n'
    'Розрахунки та перегляд отриманих чисел і арканів у готових розділах. '
    '<b>Описи 21 і 30 позицій особистого портрета</b> також відкриті для знайомства.\n\n'
    '🔐 <b>Що означає замочок?</b>\n\n'
    'Результат уже розрахований, але його <b>повне тлумачення</b> доступне після відкриття '
    'відповідного доступу. Щоб дізнатися умови, напишіть мені в Telegram.\n\n'
    '💜 <b>Бажаєте особисту консультацію?</b>\n\n'
    'Для індивідуального нумерологічного розбору, консультації Таро або допомоги '
    'з вибором послуги звертайтеся до мене:\n\n'
    f'✉️ Telegram: <a href="{escape(TELEGRAM_URL,quote=True)}">@lakshmi_775</a>\n'
    f'📸 Instagram: <a href="{escape(INSTAGRAM_URL,quote=True)}">@lakshmi_775</a>\n\n'
    '✨ <b>З чого почати?</b>\n\n'
    'Напишіть у чат свою <b>дату народження у форматі ДД.ММ.РРРР</b>.\n\n'
    'Наприклад: <b>16.09.1998</b>\n\n'
    'Після цього оберіть потрібний розділ і перегляньте свій розрахунок.'
)

def show_welcome(api,cid):
    api.say(cid,WELCOME,parse_mode='HTML',link_preview_options={'is_disabled':True},reply_markup=main_menu())

def show_home(api,cid,store):
    store.set_section(cid,'portrait')
    birth = store.current_birth(cid)
    selected = ('Поточна дата: '+birth+'. Щоб змінити її, надішліть нову дату.\n\n') if birth else ''
    api.say(cid,'Вітаю! Це бот @lakshmi_775.\n\n'
        'Оберіть розділ: портрет, карма, матриця, грошове чи соціальне призначення, '
        'прогноз на рік, місяць або день, сумісність.\n\n'
        +selected+access_text(store,cid),reply_markup=main_menu())

def show_section(api,cid,key,store,prices):
    if key not in SECTIONS: return
    birth = store.current_birth(cid)
    if key == 'compatibility':
        store.set_section(cid,key)
        show_compatibility(api,cid,store)
        return
    if key == 'portrait':
        store.set_section(cid,'portrait')
        if birth:
            show_portrait(api,cid,birth,store,prices); return
        text = ('Портрет\n\nНадішліть дату народження у форматі ДД.ММ.РРРР. '
                'Наприклад: 16.09.1998.\nВи отримаєте схему та описи позицій. '
                '21 і 30 відкриті для всіх; усі 33 доступні під час повного доступу.')
    elif key in ('year','month','day'):
        store.set_section(cid,key)
        if birth:
            show_forecast(api,cid,birth,store,key); return
        text = SECTIONS[key]+'\n\nНадішліть дату народження у форматі ДД.ММ.РРРР. '
        text += 'Розрахунок доступний усім. Описи відкриваються після особистого додавання автором.'
    elif key in ('karma','matrix','social','money'):
        store.set_section(cid,key)
        if birth:
            {'karma':show_karma,'matrix':show_matrix,'social':show_social,'money':show_money}[key](api,cid,birth,store)
            return
        text = SECTIONS[key]+'\n\nНадішліть дату народження у форматі ДД.ММ.РРРР. '
        text += 'Розрахунок доступний усім. Описи відкриваються після особистого додавання автором.'
        if key == 'money': text += '\nПісля дати введіть ім’я українською, як у документах.'
    else:
        text = SECTIONS[key]+'\n\nЦей розділ готується. Розрахунок ще недоступний. '
        text += 'Зараз Ви можете скористатися розділом «Портрет».'
        if birth: text += '\n\nПоточна дата: '+birth+'.'
    api.say(cid,text,reply_markup={'inline_keyboard':[
        [{'text':'Головне меню','callback_data':'home'}]]})


def compatibility_navigation():
    return [[{'text':'Інша пара','callback_data':'compat_reset'}],
            [{'text':'Головне меню','callback_data':'home'}]]


def show_compatibility(api,cid,store):
    dates = store.compatibility_dates(cid)
    if len(dates) < 2:
        prompt = ('Надішліть дату народження першої людини у форматі ДД.ММ.РРРР. '
                  'Можна надіслати обидві дати одним повідомленням, кожну з нового рядка.'
                  if not dates else 'Перша людина: '+dates[0]+'.\nНадішліть дату народження другої людини.')
        api.say(cid,'Сумісність · Партнерський портрет\n\n'+prompt,
                reply_markup={'inline_keyboard':compatibility_navigation()})
        return
    rows = calculate_compatibility(*dates)
    active = has_full_access(store,cid)
    caption = 'Сумісність · '+dates[0]+' та '+dates[1]+'\n\n'
    try:
        caption += '\n'.join(f'С{i} · '+compatibility_position(i)[0] for i in range(1,9))
    except (ValueError,KeyError,TypeError):
        caption += 'Пояснення позицій тимчасово недоступні.'
    caption += '\n\nНатисніть номер позиції нижче, щоб відкрити її опис.'
    if not active: caption += '\n\n'+LOCKED_DESCRIPTION
    caption += '\n\n'+CONTACTS
    buttons = [{'text':('' if active else '🔒 ')+str(i),
                'callback_data':f'compat_position:{i}'} for i in range(1,9)]
    keyboard = [buttons[:4],buttons[4:]]+compatibility_navigation()
    # Send a photo with a short position key; reserve long catalogs for text messages.
    if len(caption.encode('utf-16-le'))//2 <= 1024:
        api.call('sendPhoto',{'chat_id':cid,'caption':caption,
                 'reply_markup':{'inline_keyboard':keyboard}},
                 ('photo',draw_compatibility(*dates,rows),'compatibility.png'))
    else:
        api.call('sendPhoto',{'chat_id':cid,'caption':'Сумісність · '+dates[0]+' та '+dates[1]},
                 ('photo',draw_compatibility(*dates,rows),'compatibility.png'))
        for part in chunks(caption):
            api.say(cid,part,reply_markup={'inline_keyboard':keyboard})


def show_compatibility_position(api,cid,number,store):
    dates = store.compatibility_dates(cid)
    if len(dates) != 2 or number not in range(1,9):
        show_compatibility(api,cid,store)
        return
    i,a,b,value = calculate_compatibility(*dates)[number-1]
    title = f'Сумісність · С{i} · Аркан {value}'
    if not has_full_access(store,cid):
        show_description_lock(api,cid,title,None,store,'compatibility')
        return
    try:
        heading, meaning = compatibility_position(i)
        body = compatibility_description(i,value)
    except (OSError,ValueError,KeyError,TypeError,lzma.LZMAError):
        api.say(cid,'Опис тимчасово недоступний. Напишіть '+SUPPORT+'.')
        return
    text = (title+'\n'+dates[0]+' та '+dates[1]+f'\n\nС{i} · '+heading+'\n\n'+meaning+
            '\n\n'+body+
            '\n\n'+CONTACTS)
    api.say(cid,text,reply_markup={'inline_keyboard':[
        [{'text':'Повернутися до сумісності','callback_data':'section:compatibility'}]]+
        compatibility_navigation()})


def receive_compatibility_dates(api,cid,text,store):
    dates = store.compatibility_dates(cid)
    parts = [part.strip() for part in re.split(r'[\s,;]+',text) if part.strip()]
    try:
        if not 1 <= len(parts) <= 2:
            raise ValueError('Надішліть одну або дві дати у форматі ДД.ММ.РРРР.')
        for part in parts: calculate(part)
        # Two dates replace a pair atomically. One date starts a new pair after a completed result.
        updated = parts if len(parts)==2 or len(dates)!=1 else dates+parts
        store.set_compatibility_dates(cid,updated)
    except ValueError as error:
        api.say(cid,str(error))
        return
    show_compatibility(api,cid,store)


def forecast_buttons(birth,section,rows,active):
    prefix = '' if active else '🔒 '
    if section == 'year':
        return [[{'text':f'{prefix}{period} · {icon} {number}',
                  'callback_data':f'forecast:{birth}:year:{period}:{slot}'}
                 for slot,icon,number in ((1,'💼',work),(2,'❤️',personal))]
                for period,work,personal in rows]
    buttons = [{'text':f'{prefix}{row[0]} · {row[1]}',
                'callback_data':f'forecast:{birth}:{section}:{row[0]}:1'} for row in rows]
    midpoint = (len(buttons) + 1) // 2
    return [[buttons[i]] + ([buttons[i+midpoint]] if i+midpoint < len(buttons) else [])
            for i in range(midpoint)]


def show_forecast_period(api,cid,birth,section,period,slot,store):
    if section not in ('year','month','day') or slot not in ('1','2'):
        return
    if section != 'year' and slot != '1':
        return
    formats = {'year':'%Y','month':'%m.%Y','day':'%d.%m.%Y'}
    try:
        target = datetime.strptime(period,formats[section]).date()
        if target.strftime(formats[section]) != period:
            return
        row = next(row for row in calculate_forecast(birth,section,target) if row[0] == period)
    except (ValueError,OverflowError,StopIteration):
        api.say(cid,'Не вдалося відкрити період. Надішліть дату народження та оберіть прогноз ще раз.')
        return
    store.set_section(cid,section)
    title = {'year':'Прогноз на рік','month':'Прогноз на місяць','day':'Прогноз на день'}[section]
    title += ' · '+period
    if not has_full_access(store,cid):
        show_description_lock(api,cid,title,birth,store,section)
        return
    text = title+'\nДата народження: '+birth
    if section == 'year':
        focus = ('Професійний розвиток, кар’єра, бізнес, фінанси' if slot == '1' else
                 'Особисте життя, кохання, стосунки, емоційний стан, сім’я')
        text += '\n'+focus
    try:
        body = forecast_description(section,row[int(slot)],int(slot))
    except (OSError,ValueError,KeyError,lzma.LZMAError):
        api.say(cid,'Опис тимчасово недоступний. Спробуйте пізніше або напишіть '+SUPPORT+'.',
                reply_markup={'inline_keyboard':[
                    [{'text':'Повернутися до розрахунку','callback_data':'section:'+section}]]})
        return
    text += '\n\n'+body+'\n\n'+CONTACTS
    for part in chunks(text):
        api.say(cid,part,reply_markup={'inline_keyboard':[
            [{'text':'Повернутися до розрахунку','callback_data':'section:'+section}],
            [{'text':'Головне меню','callback_data':'home'}]]})


def show_forecast(api,cid,birth,store,section):
    today=datetime.now(ZoneInfo('Europe/Kyiv')).date()
    rows=calculate_forecast(birth,section,today)
    current={'year':str(today.year),'month':today.strftime('%m.%Y'),
             'day':today.strftime('%d.%m.%Y')}[section]
    title={'year':'Прогноз на рік','month':'Прогноз на місяць','day':'Прогноз на день'}[section]
    text=title+' · '+birth+'\n\n'
    if section == 'year':
        text+=('Перше число: професійний розвиток, кар’єра, бізнес, фінанси.\n'
               'Друге число: особисте життя, кохання, стосунки, емоційне здоров’я, сім’я.\n\n')
    text+='\n'.join(' '.join([row[0],'/'.join(map(str,row[1:]))])+
                    (' ← поточний період' if row[0]==current else '') for row in rows)
    active=has_full_access(store,cid)
    text+='\n\nОберіть період нижче, щоб прочитати його опис.'
    if not active: text+='\n\n'+LOCKED_DESCRIPTION
    text+='\n\nДля іншої людини надішліть нову дату народження.\n\n'+CONTACTS
    api.say(cid,text,reply_markup={'inline_keyboard':forecast_buttons(birth,section,rows,active)+[
        [{'text':'📅 Прогноз на роки','callback_data':'section:year'},
         {'text':'📆 Прогноз на місяці','callback_data':'section:month'}],
        [{'text':'📆 Прогноз на день','callback_data':'section:day'}],
        [{'text':'Головне меню','callback_data':'home'}]]})

def show_matrix(api,cid,birth,store):
    result = calculate_matrix(birth)
    active = has_full_access(store,cid)
    caption = ('Матриця · '+birth+'\n\n'
               +('Детальні описи матриці готуються.' if active else LOCKED_DESCRIPTION)
               +'\nДля нового розрахунку надішліть іншу дату.\n\n'
               +CONTACTS)
    api.call('sendPhoto',{'chat_id':cid,'caption':caption,'reply_markup':{'inline_keyboard':locked_button('matrix',active)+[
        [{'text':'Портрет','callback_data':'section:portrait'},
         {'text':'Карма +/−','callback_data':'section:karma'}],
        [{'text':'Головне меню','callback_data':'home'}]]}},('photo',draw_matrix(birth,result),'matrix.png'))

def show_money(api,cid,birth,store):
    name = store.money_name(cid)
    if not name:
        api.say(cid,'Грошове призначення · '+birth+'\n\n'
                'Надішліть лише ім’я українською, як у документах, без прізвища та по батькові. '
                'Наприклад: Надія. Використовується українська таблиця літер.',
                reply_markup={'inline_keyboard':[[{'text':'Головне меню','callback_data':'home'}]]})
        return
    result = calculate_money(birth,name)
    active = has_full_access(store,cid)
    if active:
        try:
            reading = money_description(result['arcanum'])
        except (ValueError,KeyError,OSError,EOFError,lzma.LZMAError):
            reading = 'Описи грошового призначення тимчасово недоступні. Спробуйте пізніше.\n\n'+CONTACTS
    else:
        reading = LOCKED_DESCRIPTION+'\n\n'+CONTACTS
    api.say(cid,'Грошове призначення · '+birth+'\nІм’я: '+result['name']+'\n\n'
            +f"Ваш аркан грошового призначення: {result['arcanum']}.\n\n"
            +'Щоб змінити ім’я, надішліть його тут. Для іншої людини надішліть нову дату та ім’я.\n\n'
            +reading,reply_markup={'inline_keyboard':locked_button('money',active)+[
                [{'text':'Змінити ім’я','callback_data':'money_name'}],
                [{'text':'Соціальне призначення','callback_data':'section:social'}],
                [{'text':'Головне меню','callback_data':'home'}]]})

def show_social(api,cid,birth,store):
    arcanum = calculate_social(birth)
    active = has_full_access(store,cid)
    api.say(cid,'Соціальне призначення · '+birth+'\n\n'
            +f'Ваш аркан: {arcanum}.\n\n'
            +('Детальний опис соціального призначення готується.' if active else LOCKED_DESCRIPTION)+'\n\n'
            +'Для нового розрахунку надішліть іншу дату.\n\n'+CONTACTS,
            reply_markup={'inline_keyboard':locked_button('social',active)+[
                [{'text':'Портрет','callback_data':'section:portrait'},
                 {'text':'Карма +/−','callback_data':'section:karma'}],
                [{'text':'Головне меню','callback_data':'home'}]]})

KARMA_INTRO = (
    'Карма: це те, що Ви принесли із минулого життя й отримали як багаж у цьому.\n\n'
    'Позитивна карма: Ваші таланти, можливості, легкий шлях для реалізації та подарунки від долі.\n\n'
    'Негативна карма: нагадує про помилки минулого, уроки, які потрібно здати на відмінно, '
    'щоб вони не повторювались знову. Життя ніби постійно провокує на мінус, змушуючи робити '
    'ті самі кроки, що були зроблені неправильно колись. Це негативні програми, які можуть '
    'обмежувати, якщо їх не пропрацювати.'
)

def show_karma(api,cid,birth,store):
    result = calculate_karma(birth)
    active = has_full_access(store,cid)
    lock = '' if active else '🔒 '
    buttons = [{'text':lock+f'➖ {value}',
                'callback_data':f'karma_minus:{birth}:{i}'}
               for i,value in enumerate(result['negative'],1)]
    positive_buttons = [{'text':lock+f'➕ {value}',
                         'callback_data':f'karma_plus:{birth}:{i}'}
                        for i,value in enumerate(result['positive'],1)]
    api.call('sendPhoto',{'chat_id':cid,'caption':'Карма +/− · '+birth+'\n\n'+KARMA_INTRO+'\n\n'+('' if active else LOCKED_DESCRIPTION+'\n\n')+CONTACTS+'\n\n'+
        'Натисніть позицію плюсової або мінусової карми нижче, щоб прочитати її опис.\n\n'
        'Для нового розрахунку надішліть іншу дату.',
        'reply_markup':{'inline_keyboard':[positive_buttons[:3],positive_buttons[3:],
                                         buttons[:3],buttons[3:],
                                         [{'text':'Портрет','callback_data':'section:portrait'}],
                                         [{'text':'Головне меню','callback_data':'home'}]]}},
        ('photo',draw_karma(result),'karma.png'))

def show_karma_minus(api,cid,birth,position,store):
    show_karma_interpretation(api,cid,birth,position,store,positive=False)

def show_karma_plus(api,cid,birth,position,store):
    show_karma_interpretation(api,cid,birth,position,store,positive=True)

def show_karma_interpretation(api,cid,birth,position,store,positive=False):
    if not 1 <= position <= 5:
        return
    store.set_section(cid,'karma')
    arcanum = calculate_karma(birth)['positive' if positive else 'negative'][position-1]
    if not has_full_access(store,cid):
        label = 'Плюсова карма' if positive else 'Мінусова карма'
        show_description_lock(api,cid,f'{label} · Позиція {position}\nВаш аркан: {arcanum}.',birth,store,'karma')
        return
    try:
        describe = positive_description if positive else negative_description
        text = describe(position,arcanum,birth)
    except (OSError,ValueError,KeyError,lzma.LZMAError):
        label = 'плюсової' if positive else 'мінусової'
        api.say(cid,'Описи '+label+' карми тимчасово недоступні. Напишіть '+SUPPORT+'.')
        return
    messages = list(chunks(text))
    for i,part in enumerate(messages):
        extra = {'reply_markup':{'inline_keyboard':[
            [{'text':'Карма +/−','callback_data':'section:karma'}],
            [{'text':'Головне меню','callback_data':'home'}]]}} if i == len(messages)-1 else {}
        api.say(cid,part,**extra)

def show_portrait(api,cid,birth,store,prices):
    calculated,_ = calculate(birth)
    api.call('sendPhoto',{'chat_id':cid,'caption':'Ваш портрет · '+birth+'\n'+CONTACTS},
        ('photo',draw_portrait(birth,calculated)))
    show_menu(api,cid,birth,store,prices)

TERMS = (
    'Умови доступу\n\n'
    'Персональне запрошення відкриває всі 33 позиції для необмеженої кількості дат народження '
    'в одному Telegram акаунті на один календарний місяць від підтвердження номера. '
    'Точний строк відображається в /access за київським часом. Повторне відкриття посилання '
    'не починає новий місяць. Посилання можна активувати протягом 7 днів. '
    'Автор може відкликати доступ. Після завершення строку позиції 21 і 30 залишаються відкритими. '
    'Продовження повного доступу: 100 грн на місяць. Для продовження напишіть @lakshmi_775 '
    'та вкажіть свій Telegram ID із /myid. Автор продовжує доступ вручну після перевірки звернення. '
    'Бот не приймає платежів за продовження, не перевіряє банківські перекази та не списує коштів.\n\n'
    'Умови попередніх окремих покупок, якщо вони були:\n'
    'Ви купуєте текст опису позиції для зазначеної дати народження у своєму Telegram акаунті. '
    'Одна позиція відкриває лише її опис і Ваш аркан. П15 включає обидва результати. '
    'Пакет відкриває всі 33 позиції тільки для однієї зазначеної дати. '
    'Позиції 21 і 30 безкоштовні. Покупки для інших дат або акаунтів не переносяться.\n\n'
    'Це одноразова покупка, без автоматичних списань. Повторний перегляд оплаченої позиції '
    'для цієї самої дати не потребує оплати. Пакет має окрему ціну; попередні покупки '
    'окремих позицій автоматично не віднімаються від неї.\n\n'
    'Оплата проходить у Telegram Stars. Суму Stars видно перед підтвердженням. '
    'Їхня вартість у гривнях залежить від способу придбання. '
    'Тексти є символічними трактуваннями для самопізнання.\n\n'
    'Якщо оплату списано, але опис не відкривається, або потрібне повернення, '
    'напишіть ' + SUPPORT + ' і додайте квитанцію Telegram. Не надсилайте токени або дані картки. '
    'Питання покупки вирішує автор бота, а не підтримка Telegram. '
    'Кнопка «Погоджуюсь та купую» підтверджує згоду з цими умовами.'
)

def back_menu(birth):
    return {'inline_keyboard': [[{'text': 'Усі 33 позиції', 'callback_data': 'menu:'+birth}],
                               [{'text':'Головне меню','callback_data':'home'}]]}

def access_text(store,cid):
    until = store.membership_until(cid)
    if until > int(time.time()):
        end = datetime.fromtimestamp(until,ZoneInfo('Europe/Kyiv')).strftime('%d.%m.%Y о %H:%M')
        return ('Усі 33 позиції портрету та готові описи інших розділів відкриті для необмеженої кількості дат народження.\n'
                'Повний доступ діє до '+end+' за київським часом.\n\n'
                'Надішліть будь-яку дату у форматі ДД.ММ.РРРР.')
    if store.had_membership(cid):
        return ('Ваш місяць повного доступу завершився.\n\n'
                'Повний доступ до всіх позицій: 100 грн на місяць.\n'
                'Після продовження Вам будуть доступні всі 33 позиції, готові описи інших розділів та необмежена кількість дат.\n\n'
                'Щоб продовжити користування, напишіть '+SUPPORT+' у приватні повідомлення. '
                'Автор продовжить Ваш доступ вручну.\n'
                f'Ваш Telegram ID: {cid}\n\n'
                'Позиції 21 і 30 залишаються безкоштовними.')
    return ('Позиції 21 і 30 портрету безкоштовні для всіх. В інших розділах доступні розрахунки, '
            'а описи закриті. Персональне запрошення автора відкриває всі 33 позиції та готові описи '
            'інших розділів для необмеженої кількості дат на один місяць від активації.\n\n'
            'Надішліть дату народження у форматі ДД.ММ.РРРР.')

def show_access(api,cid,store):
    api.say(cid,access_text(store,cid),reply_markup={'remove_keyboard':True})

def show_menu(api, cid, birth, store, prices):
    owned = store.owned(cid,birth)
    buttons = [{'text': ('' if n in owned else '🔒 ') + str(n),
                'callback_data': f'position:{birth}:{n}'} for n in range(1,34)]
    rows = [buttons[i:i+6] for i in range(0,33,6)]
    if len(owned) < 33 and prices.bundle:
        price = f' · {prices.bundle} ⭐' if prices.bundle else ''
        rows.append([{'text': 'Відкрити всі 33 позиції'+price, 'callback_data': 'offer:'+birth+':all'}])
    rows.append([{'text': 'Мій доступ', 'callback_data': 'access'}])
    rows.append([{'text':'Карма +/−','callback_data':'section:karma'}])
    rows.append([{'text':'Головне меню','callback_data':'home'}])
    price = f'Одна платна позиція: {prices.single} ⭐.\n' if prices.single else ''
    meanings = []
    for number in range(1,34):
        position = POSITIONS[number]
        meanings.append(f"{number}. {position['key']} · {position_meaning(position)}")
    overview = 'Ваші позиції · '+birth+'\n\nЩо означає кожна позиція\n\n'+'\n\n'.join(meanings)
    overview += '\n\n'+(
        '21 і 30 відкриваються безкоштовно. Натисніть номер, щоб переглянути опис.\n'
        '🔒 Доступ до позиції для цієї дати закритий.\n'+price+
        '\n'+access_text(store,cid))
    messages = list(chunks(overview))
    for index,text in enumerate(messages):
        extra = {'reply_markup':{'inline_keyboard':rows}} if index == len(messages)-1 else {}
        api.say(cid,text,**extra)

def show_position(api, cid, birth, number, store):
    if not store.has(cid,birth,number): return False
    calculated,_ = calculate(birth)
    messages = list(chunks(description(number,birth,calculated)))
    for i,text in enumerate(messages):
        extra = {'reply_markup':back_menu(birth)} if i == len(messages)-1 else {}
        api.say(cid,text,**extra)
    return True

def show_offer(api,cid,birth,product,store,prices):
    owned = store.owned(cid,birth)
    if (product == 'all' and len(owned) == 33) or (product != 'all' and int(product) in owned):
        api.say(cid,'Цей доступ уже відкрито. Повторна оплата не потрібна.',reply_markup=back_menu(birth))
        return
    if product == 'all':
        title = 'Усі 33 позиції'
    else:
        p = POSITIONS[int(product)]
        title = f"Позиція {product} ({p['key']}) · {p['title']}"
    try: amount = prices.amount(product)
    except PaymentError:
        api.say(cid,title+'\nДата народження: '+birth+'\n\n'
            +access_text(store,cid),reply_markup=back_menu(birth)); return
    api.say(cid,title+'\nДата народження: '+birth+f'\nВартість: {amount} ⭐\n\n'
        'Доступ тільки для цієї дати у Вашому акаунті.\n\n'+TERMS,
        reply_markup={'inline_keyboard':[
            [{'text': f'Погоджуюсь та купую · {amount} ⭐', 'callback_data': f'invoice:{birth}:{product}'}],
            [{'text': 'Повернутися до позицій','callback_data':'menu:'+birth}]]})

def send_invoice(api,cid,birth,product,store,prices):
    amount = prices.amount(product)
    oid = store.create_order(cid,birth,product,amount)
    title = 'Усі 33 позиції' if product == 'all' else 'Позиція '+product
    api.call('sendInvoice',{'chat_id':cid,'title':title+' · '+birth,
        'description':title+' для дати '+birth+'. Одноразова оплата. Доступ лише у Вашому акаунті для цієї дати.',
        'payload':oid,'provider_token':'','currency':'XTR',
        'prices':[{'label':title,'amount':amount}],'start_parameter':'order_'+oid})

def show_purchases(api,cid,store):
    if store.had_membership(cid): show_access(api,cid,store)
    dates = store.dates(cid)
    if not dates:
        if store.had_membership(cid): return
        api.say(cid,'У Вас ще немає збереженого доступу. Надішліть дату народження, щоб переглянути портрет.'); return
    # Separate messages keep all purchase history reachable without a button limit.
    for start in range(0,len(dates),40):
        rows = [[{'text':d, 'callback_data':'menu:'+d}] for d in dates[start:start+40]]
        api.say(cid,'Ваш доступ. Оберіть дату народження:',reply_markup={'inline_keyboard':rows})

def handle_invitation(api, msg, cid, store, prices):
    text = msg.get('text','').strip()
    args = text.split()
    command = args[0].split('@')[0] if args else ''
    if command == '/myid':
        api.say(cid,f'Ваш Telegram ID: {cid}'); return True
    if command in ('/invite','/revoke','/renew'):
        owner = os.getenv('BOT_OWNER_ID','')
        if not owner.isdigit() or int(owner) != cid:
            api.say(cid,'Ця команда доступна лише власнику бота.'); return True
        try:
            if command == '/renew':
                if len(args) != 2 or not args[1].isascii() or not args[1].isdigit() or int(args[1]) <= 0:
                    api.say(cid,'Продовження доступу на місяць:\n/renew TELEGRAM_ID\n\n'
                        'Попросіть людину надіслати свій ID із /myid або повідомлення про завершення доступу. '
                        'Продовжуйте після того, як самостійно перевірите звернення.'); return True
                mid = msg.get('message_id')
                if not isinstance(mid,int) or mid <= 0:
                    raise PaymentError('Надішліть команду продовження новим повідомленням.')
                uid = int(args[1])
                until = store.extend_membership(cid,uid,f'renew:{cid}:{mid}')
                end = datetime.fromtimestamp(until,ZoneInfo('Europe/Kyiv')).strftime('%d.%m.%Y о %H:%M')
                api.say(cid,f'Доступ акаунту {uid} продовжено до {end} за київським часом.\n'
                    'Відкрито всі 33 позиції для необмеженої кількості дат. '
                    'Користувач може перевірити строк через /access.'); return True
            if command == '/invite':
                if len(args) != 2:
                    api.say(cid,'Створення запрошення:\n/invite +380XXXXXXXXX\n\n'
                        'Вкажіть номер, прив’язаний до Telegram отримувача. Запрошення відкриває '
                        'всі 33 позиції для необмеженої кількості дат на один календарний місяць від активації.'); return True
                iid, token = store.create_invitation(cid,args[1])
                username = api.call('getMe')['username']
                api.say(cid,'Персональне запрошення на місяць повного доступу\n\n'
                    f'https://t.me/{username}?start=gift_{token}\n\n'
                    'Активувати можна протягом 7 днів, тільки з підтвердженим номером отримувача. '
                    'Після активації відкриваються всі позиції для необмеженої кількості дат на один місяць.\n'
                    f'Відкликати запрошення або вже відкритий ним доступ:\n/revoke {iid}',
                    link_preview_options={'is_disabled':True})
            else:
                if len(args) != 2:
                    api.say(cid,'Відкликати запрошення та його доступ: /revoke ID'); return True
                revoked = store.revoke_invitation(cid,args[1])
                api.say(cid,'Запрошення та наданий ним доступ відкликано.' if revoked else 'Активного запрошення з таким ID не знайдено.')
        except (PaymentError,ValueError) as e: api.say(cid,str(e))
        return True
    if command == '/start' and len(args) == 2 and args[1].startswith('gift_'):
        show_welcome(api,cid)
        try:
            birth = store.begin_invitation(cid,args[1][5:])
            if birth is not None:
                show_access(api,cid,store)
            else:
                api.say(cid,'Це персональне запрошення. Для перевірки натисніть «Поділитися своїм номером». '
                    'Бот звірить номер Вашого Telegram акаунту з номером у запрошенні. '
                    'У базі зберігається лише захищений відбиток номера. '
                    'Після підтвердження почнеться місяць повного доступу для необмеженої кількості дат. '
                    'Перевірка діє 10 хвилин. /cancel скасовує перевірку.',
                    reply_markup={'keyboard':[[{'text':'Поділитися своїм номером','request_contact':True}]],
                                  'resize_keyboard':True,'one_time_keyboard':True})
        except PaymentError as e: api.say(cid,str(e),reply_markup={'remove_keyboard':True})
        return True
    if command == '/cancel':
        with store.db: store.db.execute('DELETE FROM invitation_pending WHERE user_id=?',(cid,))
        api.say(cid,'Перевірку скасовано. Надішліть дату народження для розрахунку.',reply_markup={'remove_keyboard':True})
        return True
    if 'contact' in msg:
        try:
            if msg.get('forward_origin') or msg.get('forward_from'):
                raise PaymentError('Скористайтеся кнопкою «Поділитися своїм номером», без пересилання контакту.')
            store.redeem_invitation(cid,msg['contact'])
            show_access(api,cid,store)
        except PaymentError as e: api.say(cid,str(e))
        return True
    return False

def handle(api, update, store, prices):
    checkout = update.get('pre_checkout_query')
    if checkout:
        answer = {'pre_checkout_query_id':checkout['id'],'ok':False}
        try:
            store.approve(checkout.get('invoice_payload',''),checkout['from']['id'],
                          checkout.get('currency'),checkout.get('total_amount'))
            answer['ok'] = True
        except PaymentError as e: answer['error_message'] = str(e)
        api.call('answerPreCheckoutQuery',answer)
        return
    cb = update.get('callback_query')
    msg = cb.get('message',{}) if cb else update.get('message',{})
    chat = msg.get('chat',{})
    if chat.get('type') != 'private': return
    cid = chat['id']
    # Telegram may send the refund service message without a human sender.
    refund = msg.get('refunded_payment')
    if refund:
        store.mark_refunded(refund['telegram_payment_charge_id'],cid)
        return
    sender = (cb if cb else msg).get('from',{}).get('id')
    if sender != cid: return
    payment = msg.get('successful_payment')
    if payment:
        status,order = store.record_payment(payment.get('invoice_payload',''),cid,
            payment.get('currency'),payment.get('total_amount'),payment.get('telegram_payment_charge_id'))
        if status == 'paid':
            birth = order['birth_date']
            api.say(cid,'Оплату підтверджено. Доступ для дати '+birth+' збережено.')
            if order['product'] != 'all': show_position(api,cid,birth,int(order['product']),store)
            show_menu(api,cid,birth,store,prices)
        elif status == 'refund_pending':
            api.say(cid,'Цей платіж не потрібен для відкриття доступу. Повернення Stars обробляється. '
                        'Якщо потрібна допомога, напишіть '+SUPPORT+'.')
        return
    if cb:
        api.call('answerCallbackQuery',{'callback_query_id':cb['id']})
        args = cb.get('data','').split(':')
        action = args[0]
        if action == 'home': show_home(api,cid,store); return
        if action == 'info': show_welcome(api,cid); return
        if action == 'section':
            if len(args) == 2: show_section(api,cid,args[1],store,prices)
            return
        if action == 'locked':
            if len(args) == 2 and args[1] in ('money','social','matrix','year','month','day'):
                if has_full_access(store,cid): show_section(api,cid,args[1],store,prices)
                else: show_description_lock(api,cid,SECTIONS[args[1]],store.current_birth(cid),store,args[1])
            return
        if action == 'forecast':
            if len(args) == 5:
                birth = store.current_birth(cid) or args[1]
                show_forecast_period(api,cid,birth,args[2],args[3],args[4],store)
            return
        if action == 'compat_reset':
            store.set_section(cid,'compatibility')
            store.set_compatibility_dates(cid,[])
            show_compatibility(api,cid,store); return
        if action == 'compat_position':
            if len(args)==2 and args[1] in tuple(map(str,range(1,9))):
                store.set_section(cid,'compatibility')
                show_compatibility_position(api,cid,int(args[1]),store)
            return
        if action == 'access': show_access(api,cid,store); return
        if action == 'purchases': show_purchases(api,cid,store); return
        if action == 'money_name':
            store.forget_money_name(cid)
            show_section(api,cid,'money',store,prices); return
        if len(args) < 2: return
        birth = args[1]
        # Navigation and position buttons follow the latest date typed by this user.
        # Historical invoice/offer payloads keep their original date and consent.
        if action in ('menu','positions','calc','position','karma_minus','karma_plus'):
            birth = store.current_birth(cid) or birth
        try: calculate(birth)
        except ValueError:
            api.say(cid,'Надішліть дату народження у форматі ДД.ММ.РРРР.'); return
        if action in ('karma_minus','karma_plus'):
            if len(args) == 3 and args[2] in ('1','2','3','4','5'):
                show = show_karma_plus if action == 'karma_plus' else show_karma_minus
                show(api,cid,birth,int(args[2]),store)
            return
        if action in ('menu','positions','calc'):
            store.set_section(cid,'portrait')
            show_menu(api,cid,birth,store,prices); return
        if action in ('position','offer','invoice'):
            if len(args) != 3: return
            product = args[2]
            if product != 'all' and (not product.isdigit() or int(product) not in POSITIONS): return
            if product != 'all': product = str(int(product))
            if action == 'position' and product != 'all':
                if show_position(api,cid,birth,int(product),store): return
            try:
                if action == 'invoice': send_invoice(api,cid,birth,product,store,prices)
                else: show_offer(api,cid,birth,product,store,prices)
            except PaymentError as e: api.say(cid,str(e),reply_markup=back_menu(birth))
            return
        if action == 'karma_png':
            if store.membership_until(cid) <= int(time.time()):
                show_karma(api,cid,birth,store); return
            api.call('sendDocument',{'chat_id':cid,'caption':'Карма без стиснення · '+birth},
                     ('document',draw_karma(calculate_karma(birth)),'karma.png'))
            return
        if action != 'png': return
        calculated,_=calculate(birth)
        api.call('sendDocument',{'chat_id':cid,'caption':'Схема без стиснення · '+birth},
                 ('document',draw_portrait(birth,calculated)))
        return
    text = msg.get('text','').strip()
    if handle_invitation(api,msg,cid,store,prices): return
    command = text.split(' ',1)[0].split('@')[0]
    if command == '/start':
        store.set_section(cid,'portrait')
        show_welcome(api,cid)
        if store.had_membership(cid) and not has_full_access(store,cid):
            show_access(api,cid,store)
        return
    if command == '/info': show_welcome(api,cid); return
    if command in ('/help','/menu'):
        show_home(api,cid,store); return
    if command in ('/year','/month','/day'):
        show_section(api,cid,command[1:],store,prices); return
    if command == '/compatibility': show_section(api,cid,'compatibility',store,prices); return
    if command == '/portrait': show_section(api,cid,'portrait',store,prices); return
    if command == '/karma': show_section(api,cid,'karma',store,prices); return
    if command == '/social': show_section(api,cid,'social',store,prices); return
    if command == '/money': show_section(api,cid,'money',store,prices); return
    if command == '/matrix': show_section(api,cid,'matrix',store,prices); return
    if command == '/forgetdate':
        store.forget_birth(cid)
        api.say(cid,'Поточну дату, дати сумісності та ім’я для грошового призначення видалено. '
                    'Надішліть нову дату народження у форматі ДД.ММ.РРРР.'); return
    if command == '/terms': api.say(cid,TERMS); return
    if command in ('/paysupport','/support'):
        api.say(cid,'Допомога з покупками та поверненнями: '+SUPPORT+'. '
            'Додайте квитанцію Telegram і дату народження, для якої придбали опис. '
            'Питання оплати вирішує автор бота, а не підтримка Telegram.'); return
    if command == '/privacy':
        api.say(cid,'Для збереження покупок бот записує Ваш Telegram ID, дату народження, '
            'придбані позиції, суму Stars та ідентифікатор платежу. Ці дані дозволяють '
            'повторно відкривати оплачені описи та обробляти повернення. '
            'Дати з рахунків зберігаються навіть до завершення оплати. '
            'Остання введена дата народження зберігається у Вашому акаунті для перемикання між розділами. '
            'Для грошового призначення зберігається введене Вами ім’я для поточної дати. '
            'Нова дата видаляє попереднє ім’я. Ім’я можна змінити в розділі грошового призначення. '
            'Нова дата замінює попередню поточну дату. Команда /forgetdate видаляє поточну дату, '
            'але не видаляє дати з історії покупок або повідомлень Telegram. '
            'Для сумісності окремо зберігаються дві введені дати. Кнопка «Інша пара» очищує їх; /forgetdate також видаляє їх. '
            'Обраний розділ зберігається для Вашого акаунту. Повідомлення та результати залишаються в історії чату Telegram. '
            'Для персональних запрошень зберігаються захищений відбиток номера телефону, '
            'строк доступу, Telegram ID після активації та стан запрошення. '
            'Сам номер у базі бота не зберігається. Контакт залишається у Вашій історії чату Telegram. '
            'Ручні продовження записуються з Telegram ID автора й отримувача та попереднім і новим строком доступу. '
            'Дані банківської картки бот не отримує. Питання щодо даних: '+SUPPORT+'.'); return
    if command == '/purchases': show_purchases(api,cid,store); return
    if command == '/access': show_access(api,cid,store); return
    if store.section(cid) == 'compatibility':
        receive_compatibility_dates(api,cid,text,store); return
    try: calculated,_ = calculate(text)
    except ValueError as e:
        if store.section(cid) == 'money' and store.current_birth(cid) and not any(c.isdigit() for c in text):
            try: store.set_money_name(cid,text)
            except ValueError as error: api.say(cid,str(error)); return
            show_money(api,cid,store.current_birth(cid),store); return
        api.say(cid,str(e)); return
    store.set_current_birth(cid,text)
    if store.section(cid) in ('year','month','day'):
        show_forecast(api,cid,text,store,store.section(cid)); return
    if store.section(cid) == 'karma':
        show_karma(api,cid,text,store); return
    if store.section(cid) == 'social':
        show_social(api,cid,text,store); return
    if store.section(cid) == 'matrix':
        show_matrix(api,cid,text,store); return
    if store.section(cid) == 'money':
        show_money(api,cid,text,store); return
    show_portrait(api,cid,text,store,prices)

def process_refunds(api,store):
    for row in store.pending_refunds()[:10]:
        try:
            api.call('refundStarPayment',{'user_id':row['user_id'],
                     'telegram_payment_charge_id':row['charge_id']})
            store.mark_refunded(row['charge_id'],row['user_id'])
        except APIError:
            print('Повернення очікує повторної обробки.',flush=True)

def storage_path(prices):
    volume = os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
    directory = Path(os.getenv('DATA_DIR') or volume or ROOT/'data').resolve()
    if os.getenv('RAILWAY_ENVIRONMENT_ID') and (prices.single or prices.bundle or os.getenv('BOT_OWNER_ID')):
        if not volume or not directory.is_relative_to(Path(volume).resolve()):
            raise SystemExit('Перед увімкненням оплати підключіть Railway Volume і розмістіть DATA_DIR на ньому.')
    return directory/'purchases.sqlite3'

def main():
    load_env()
    token = os.getenv('TELEGRAM_BOT_TOKEN','')
    if not token or token == 'PASTE_TOKEN_HERE': raise SystemExit('Додайте TELEGRAM_BOT_TOKEN у змінні середовища.')
    prices = Prices()
    store = Store(storage_path(prices))
    api = Telegram(token)
    api.call('getMe')
    if api.call('getWebhookInfo').get('url'):
        raise SystemExit('У бота вже налаштований webhook. Вимкніть його перед запуском polling.')
    commands = [('start','Головне меню'),('menu','Розділи бота'),('info','Про бота та консультації'),('portrait','Портрет'),('karma','Карма +/−'),('social','Соціальне призначення'),('money','Грошове призначення'),('matrix','Матриця'),('year','Прогноз на роки'),('month','Прогноз на місяці'),('day','Прогноз на день'),('compatibility','Сумісність'),('forgetdate','Видалити поточну дату'),('access','Мій доступ'),('purchases','Попередні покупки'),('myid','Мій Telegram ID'),('terms','Умови покупки'),
                ('paysupport','Допомога з оплатою'),('privacy','Обробка даних')]
    api.call('setMyCommands',{'commands':[{'command':c,'description':d} for c,d in commands]})
    offset = store.offset()
    print('Бот запущено. Оплати зберігаються в базі; персональні дані не журналюються.',flush=True)
    while True:
        try:
            updates = api.call('getUpdates',{'offset':offset,'timeout':25,
                       'allowed_updates':['message','callback_query','pre_checkout_query']})
            # Answer checkout before slow image work; then process in update order for a durable cursor.
            answered = set()
            for update in updates:
                if 'pre_checkout_query' in update:
                    handle(api,update,store,prices);answered.add(update['update_id'])
            for update in updates:
                try:
                    if update['update_id'] not in answered: handle(api,update,store,prices)
                except APIError as e:
                    # Payment rights have already been committed before attempting delivery.
                    print(f'Відповідь не доставлена (код {e.code}). Доступ зберігається у /purchases.',flush=True)
                offset = update['update_id']+1
                store.set_offset(offset)
            process_refunds(api,store)
        except APIError as e:
            if e.code in (401,409): raise SystemExit(f'Зупинено: код {e.code}. Перевірте токен або інший процес.') from None
            time.sleep(max(3,min(e.retry,30)))
        except (sqlite3.Error,OSError):
            # Do not acknowledge unrecorded financial events. Retry the same updates.
            print('Не вдалося записати стан. Обробку буде повторено.',flush=True)
            time.sleep(3)

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: print('Бот зупинено.')




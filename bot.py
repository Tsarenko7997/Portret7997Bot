"""Telegram portrait bot with date-scoped paid interpretations."""
import json
import os
import secrets
import time
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from portrait import calculate, calculate_karma
from render import draw_portrait, draw_karma
from catalog import POSITIONS, FREE, description, chunks
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

class Telegram:
    def __init__(self, token):
        self.base='https://api.telegram.org/bot'+token+'/'
        if os.getenv('TELEGRAM_TEST_ENV')=='1':self.base+='test/'
    def call(self, method, data=None, file=None):
        data=data or {}
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

SUPPORT = '@Lakshmi_775'
SECTIONS = {
    'portrait':'Портрет 33П',
    'karma':'Карма +/−',
    'matrix':'Матриця',
    'money':'Грошове призначення',
    'social':'Соціальне призначення',
    'year':'Прогноз на роки',
    'month':'Прогноз на місяці',
}

def main_menu():
    buttons = [{'text':label if key in ('portrait','karma') else label+' · Незабаром',
                'callback_data':'section:'+key} for key,label in SECTIONS.items()]
    return {'inline_keyboard':[
        [buttons[0]], buttons[1:3], buttons[3:5], buttons[5:7],
        [{'text':'Мій доступ','callback_data':'access'},
         {'text':'Написати в Telegram','url':'https://t.me/Lakshmi_775'}],
        [{'text':'Instagram @lakshmi_775','url':'https://www.instagram.com/lakshmi_775/'}]]}

def show_home(api,cid,store):
    store.set_section(cid,'portrait')
    birth = store.current_birth(cid)
    selected = ('Поточна дата: '+birth+'. Щоб змінити її, надішліть нову дату.\n\n') if birth else ''
    api.say(cid,'Вітаю! Це бот @lakshmi_775.\n\n'
        'Оберіть розділ. «Портрет 33П» та «Карма +/−» уже доступні, інші розділи готуються.\n\n'
        +selected+access_text(store,cid),reply_markup=main_menu())

def show_section(api,cid,key,store,prices):
    if key not in SECTIONS: return
    birth = store.current_birth(cid)
    if key == 'portrait':
        store.set_section(cid,'portrait')
        if birth:
            show_portrait(api,cid,birth,store,prices); return
        text = ('Портрет 33П\n\nНадішліть дату народження у форматі ДД.ММ.РРРР. '
                'Наприклад: 16.09.1998.\nВи отримаєте схему та описи позицій. '
                '21 і 30 відкриті для всіх; усі 33 доступні під час повного доступу.')
    elif key == 'karma':
        if store.membership_until(cid) > int(time.time()):
            store.set_section(cid,'karma')
            if birth:
                show_karma(api,cid,birth,store); return
            text = ('Карма +/−\n\nНадішліть дату народження у форматі ДД.ММ.РРРР. '
                    'Ви отримаєте п’ять позицій плюсової та п’ять позицій мінусової карми. '
                    'Зараз доступний числовий розрахунок. Трактування готуються.')
        else:
            store.set_section(cid,'portrait')
            text = ('Карма +/−\n\nРозрахунок карми доступний під час повного місячного доступу.\n\n'
                    +access_text(store,cid)+'\n\nЗвернутися до автора: '+SUPPORT+'.')
    else:
        text = SECTIONS[key]+'\n\nЦей розділ готується. Розрахунок ще недоступний. '
        text += 'Зараз Ви можете скористатися розділом «Портрет 33П».'
        if birth: text += '\n\nПоточна дата: '+birth+'.'
    api.say(cid,text,reply_markup={'inline_keyboard':[
        [{'text':'Головне меню','callback_data':'home'}]]})

def show_karma(api,cid,birth,store):
    if store.membership_until(cid) <= int(time.time()):
        api.say(cid,'Карма +/− доступна під час повного місячного доступу.\n\n'+access_text(store,cid),
                reply_markup={'inline_keyboard':[[{'text':'Мій доступ','callback_data':'access'}],
                                                [{'text':'Головне меню','callback_data':'home'}]]})
        return
    result = calculate_karma(birth)
    api.call('sendPhoto',{'chat_id':cid,'caption':'Карма +/− · '+birth+'\nInstagram: @lakshmi_775\n\n'
        'Для нового розрахунку надішліть іншу дату.',
        'reply_markup':{'inline_keyboard':[[{'text':'Портрет 33П','callback_data':'section:portrait'}],
                                         [{'text':'Головне меню','callback_data':'home'}]]}},
        ('photo',draw_karma(result),'karma.png'))

def show_portrait(api,cid,birth,store,prices):
    calculated,_ = calculate(birth)
    api.call('sendPhoto',{'chat_id':cid,'caption':'Ваш портрет · '+birth+'\nInstagram: @lakshmi_775',
        'reply_markup':{'inline_keyboard':[
            [{'text':'Відкрити 33 позиції','callback_data':'menu:'+birth}],
            [{'text':'Карма +/−','callback_data':'section:karma'}],
            [{'text':'Головне меню','callback_data':'home'}]]}},
        ('photo',draw_portrait(birth,calculated)))
    show_menu(api,cid,birth,store,prices)

TERMS = (
    'Умови доступу\n\n'
    'Персональне запрошення відкриває всі 33 позиції для необмеженої кількості дат народження '
    'в одному Telegram акаунті на один календарний місяць від підтвердження номера. '
    'Точний строк відображається в /access за київським часом. Повторне відкриття посилання '
    'не починає новий місяць. Посилання можна активувати протягом 7 днів. '
    'Автор може відкликати доступ. Після завершення строку позиції 21 і 30 залишаються відкритими. '
    'Продовження повного доступу: 100 грн на місяць. Для продовження напишіть @Lakshmi_775 '
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
        return ('Усі 33 позиції відкриті для необмеженої кількості дат народження.\n'
                'Повний доступ діє до '+end+' за київським часом.\n\n'
                'Надішліть будь-яку дату у форматі ДД.ММ.РРРР.')
    if store.had_membership(cid):
        return ('Ваш місяць повного доступу завершився.\n\n'
                'Повний доступ до всіх позицій: 100 грн на місяць.\n'
                'Після продовження Вам будуть доступні всі 33 позиції та необмежена кількість дат.\n\n'
                'Щоб продовжити користування, напишіть '+SUPPORT+' у приватні повідомлення. '
                'Автор продовжить Ваш доступ вручну.\n'
                f'Ваш Telegram ID: {cid}\n\n'
                'Позиції 21 і 30 залишаються безкоштовними.')
    return ('Позиції 21 і 30 безкоштовні для всіх. Персональне запрошення автора відкриває '
            'всі 33 позиції для необмеженої кількості дат на один місяць від активації.\n\n'
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
    api.say(cid, 'Ваші позиції · '+birth+'\n\n'
        '21 і 30 відкриваються безкоштовно. Натисніть номер, щоб переглянути опис.\n'
        '🔒 Доступ до позиції для цієї дати закритий.\n'+price+
        '\n'+access_text(store,cid),
        reply_markup={'inline_keyboard': rows})

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
        if action == 'section':
            if len(args) == 2: show_section(api,cid,args[1],store,prices)
            return
        if action == 'access': show_access(api,cid,store); return
        if action == 'purchases': show_purchases(api,cid,store); return
        if len(args) < 2: return
        birth = args[1]
        # Navigation and position buttons follow the latest date typed by this user.
        # Historical invoice/offer payloads keep their original date and consent.
        if action in ('menu','positions','calc','position'):
            birth = store.current_birth(cid) or birth
        try: calculate(birth)
        except ValueError:
            api.say(cid,'Надішліть дату народження у форматі ДД.ММ.РРРР.'); return
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
    if command in ('/start','/help','/menu'):
        show_home(api,cid,store); return
    if command == '/portrait': show_section(api,cid,'portrait',store,prices); return
    if command == '/karma': show_section(api,cid,'karma',store,prices); return
    if command == '/forgetdate':
        store.forget_birth(cid)
        api.say(cid,'Поточну дату видалено. Надішліть нову дату народження у форматі ДД.ММ.РРРР.'); return
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
            'Нова дата замінює попередню поточну дату. Команда /forgetdate видаляє поточну дату, '
            'але не видаляє дати з історії покупок або повідомлень Telegram. '
            'Обраний розділ зберігається для Вашого акаунту. Повідомлення та результати залишаються в історії чату Telegram. '
            'Для персональних запрошень зберігаються захищений відбиток номера телефону, '
            'строк доступу, Telegram ID після активації та стан запрошення. '
            'Сам номер у базі бота не зберігається. Контакт залишається у Вашій історії чату Telegram. '
            'Ручні продовження записуються з Telegram ID автора й отримувача та попереднім і новим строком доступу. '
            'Дані банківської картки бот не отримує. Питання щодо даних: '+SUPPORT+'.'); return
    if command == '/purchases': show_purchases(api,cid,store); return
    if command == '/access': show_access(api,cid,store); return
    try: calculated,_ = calculate(text)
    except ValueError as e: api.say(cid,str(e)); return
    store.set_current_birth(cid,text)
    if store.section(cid) == 'karma':
        show_karma(api,cid,text,store); return
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
    commands = [('start','Головне меню'),('menu','Розділи бота'),('portrait','Портрет 33П'),('karma','Карма +/−'),('forgetdate','Видалити поточну дату'),('access','Мій доступ'),('purchases','Попередні покупки'),('myid','Мій Telegram ID'),('terms','Умови покупки'),
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


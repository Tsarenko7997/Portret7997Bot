"""Telegram long polling. Only token in .env or environment; no date database."""
import json
import os
import secrets
import time
import urllib.request
import urllib.error
from pathlib import Path
from portrait import calculate
from render import draw_portrait

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
    def __init__(self, token): self.base='https://api.telegram.org/bot'+token+'/'
    def call(self, method, data=None, file=None):
        data=data or {}
        headers={}
        if file:
            boundary='Nadia'+secrets.token_hex(12); parts=[]
            for k,v in data.items():
                val=json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v)
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{val}\r\n'.encode())
            name,blob=file
            parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="portrait.png"\r\nContent-Type: image/png\r\n\r\n'.encode(),blob,f'\r\n--{boundary}--\r\n'.encode()])
            body=b''.join(parts); headers['Content-Type']='multipart/form-data; boundary='+boundary
        else:
            body=json.dumps(data).encode(); headers['Content-Type']='application/json'
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base+method,data=body,headers=headers),timeout=45) as response:
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

POSITION_DESCRIPTIONS = (
    ('ПСИХОЛОГІЧНИЙ ПОРТРЕТ', (
        ('П1', 'Ваш характер, природні риси, реакції, сильні та слабкі сторони.'),
        ('П2', 'Глибинні прагнення Вашої душі.'),
        ('П3', 'Енергія реалізації в матеріальному світі.'),
        ('П4', 'Надумані перешкоди.'),
        ('П5', 'Мініціль. Де Ви проявляєтесь найкраще.'),
        ('П6', 'Основа Вашої особистості. Хобі.'),
        ('П7', 'Покликання, справжнє призначення, місія.'),
        ('П8', 'За рахунок чого Ви досягаєте цілей і реалізуєте своє призначення. Ваші дари.'),
    )),
    ('ПСИХОЛОГІЧНА ГАРМОНІЯ', (
        ('П12', 'Зона комфорту, місце наповнення, внутрішній спокій і стабільність.'),
        ('П13', 'Як Ви сприймаєте себе. Самооцінка, внутрішній образ «Я».'),
        ('П14', 'Як Вас сприймають інші. Яке враження Ви справляєте на людей.'),
    )),
    ('КАРМІЧНИЙ ПОРТРЕТ', (
        ('П9', 'Ким Ви були у минулому житті.'),
        ('П10', 'Чим Ви займалися у минулому житті, яку діяльність, досвід і навички Ваша душа проходила раніше.'),
        ('П11', 'Головний урок, який Вам важливо усвідомити та відпрацювати у цьому житті.'),
        ('П15', 'Через що саме відбувається відпрацювання карми.'),
        ('П16', 'Кармічна проблема. Точка повтору.'),
        ('П17', 'Ваш кармічний комфорт. Стан, у якому Вам легко, безпечно та стабільно жити і розвиватися.'),
        ('П18', 'Як саме Вам варто реалізовувати свою місію в цьому втіленні.'),
        ('П19', 'Ваші слабкі місця, спокуси та ризики, де є ймовірність піти в мінус або втратити баланс.'),
        ('П20', 'Ваша підтримка Вищих сил. Совість, внутрішній компас, духовна опора, яка допомагає Вам у складні моменти та рятує ситуацію.'),
        ('П21', "Що дає задоволення і де одночасно великі обов’язки."),
        ('П30', 'Дискомфорт.'),
    )),
    ('ТІНЬОВИЙ ПОРТРЕТ', (
        ('A', 'Що найбільш сильно впливає на Вас із підсвідомості.'),
        ('B', 'Те, на що Ви можете впливати та не здатні змінити.'),
        ('C', 'Найголовніше у Вашому житті.'),
        ('D', 'Що найбільше впливає на Вашу свідомість.'),
        ('E', 'Що Ви робите добре, але навіть не усвідомлюєте цього.'),
        ('F', 'Що Ви не хочете приймати, що Вас відштовхує або викликає внутрішній опір.'),
        ('G1', 'Перший можливий шлях Вашої реалізації через свій потенціал.'),
        ('G2', 'Другий можливий шлях реалізації, альтернативний сценарій розвитку.'),
        ('H', 'Сфера руйнівних, деструктивних схильностей.'),
        ('Кп', 'Ваш психологічний комфорт. Де Вам спокійно, безпечно і стабільно.'),
        ('J', 'Хто або що стимулює Вас на вчинки, подвиги, звершення та самореалізацію.'),
    )),
)

def describe_positions(value, positions):
    sections = ['Значення позицій · ' + value]
    for title, entries in POSITION_DESCRIPTIONS:
        lines = [title]
        for key, description in entries:
            number = (str(positions['П15а']) + ' / ' + str(positions['П15б'])
                      if key == 'П15' else str(positions[key]))
            label = key if key.startswith('П') else 'П ' + key
            lines.append(f'{label} — {number}: {description}')
        sections.append('\n'.join(lines))
    return '\n\n'.join(sections)

def handle(api, update):
    cb=update.get('callback_query')
    msg=cb.get('message',{}) if cb else update.get('message',{})
    chat=msg.get('chat',{})
    if chat.get('type')!='private': return
    cid=chat['id']
    if cb:
        api.call('answerCallbackQuery',{'callback_query_id':cb['id']})
        action,_,value=cb.get('data','').partition(':')
        if action not in ('positions','calc','png'): return
    else:
        value=msg.get('text','').strip()
        command=value.split(' ',1)[0].split('@')[0]
        if command in ('/start','/help'):
            api.say(cid,'Вітаю! Це калькулятор портрету Надії Царенко.\n\nНадішліть дату народження: ДД.ММ.РРРР.\nНаприклад: 16.09.1998\n\nВи отримаєте схему основного, кармічного й тіньового портретів.\n/start — новий розрахунок\n/privacy — про дані')
            return
        if command=='/privacy':
            api.say(cid,'Бот обробляє дату лише для розрахунку й не записує її у власну базу або журнал. Дата та результати залишаються в історії вашого чату Telegram. Службовий файл offset.json містить тільки номер обробленого оновлення. Кнопки під результатом містять введену дату для повторного обчислення.')
            return
        action='portrait'
    try: p,steps=calculate(value)
    except ValueError as e:
        api.say(cid,str(e)); return
    if action in ('positions', 'calc'):
        api.say(cid, describe_positions(value, p)); return
    blob=draw_portrait(value,p)
    if action=='png':
        api.call('sendDocument',{'chat_id':cid,'caption':'Схема без стиснення · '+value},('document',blob)); return
    api.call('sendPhoto',{'chat_id':cid,'caption':'Ваш портрет · '+value+'\nНадія Царенко\n\nДля нового розрахунку надішліть іншу дату.', 'reply_markup':{'inline_keyboard':[[{'text':'Що означають позиції','callback_data':'positions:'+value}],[{'text':'Завантажити PNG','callback_data':'png:'+value}]]}},('photo',blob))

def main():
    load_env(); token=os.getenv('TELEGRAM_BOT_TOKEN','')
    if not token or token=='PASTE_TOKEN_HERE':
        raise SystemExit('Додайте TELEGRAM_BOT_TOKEN у файл .env. Не публікуйте токен.')
    api=Telegram(token)
    try:
        api.call('getMe')
        if api.call('getWebhookInfo').get('url'):
            raise SystemExit('У бота вже налаштований webhook. Вимкніть його перед запуском polling.')
        api.call('setMyCommands',{'commands':[{'command':'start','description':'Новий розрахунок'},{'command':'help','description':'Як користуватися'},{'command':'privacy','description':'Обробка даних'}]})
    except APIError as e:
        raise SystemExit(f'Не вдалося підключитися до Telegram (код {e.code}). Перевірте токен і мережу.') from None
    state=ROOT/'offset.json'
    try: offset=json.loads(state.read_text())['offset']
    except (OSError,ValueError,KeyError): offset=0
    print('Бот запущений. Зупинка: Ctrl+C. Дати й токен не журналюються.',flush=True)
    while True:
        try:
            updates=api.call('getUpdates',{'offset':offset,'timeout':25,'allowed_updates':['message','callback_query']})
            for update in updates:
                try: handle(api,update)
                except APIError as e:
                    print(f'Не вдалося надіслати відповідь (код {e.code}); користувач може повторити запит.',flush=True)
                    if e.retry: time.sleep(min(e.retry,60))
                offset=update['update_id']+1
                tmp=state.with_suffix('.tmp'); tmp.write_text(json.dumps({'offset':offset})); tmp.replace(state)
        except APIError as e:
            if e.code in (401,409):
                raise SystemExit(f'Зупинено: код {e.code}. Перевірте токен або інший запущений екземпляр.') from None
            print(f'Повтор підключення (код {e.code}).',flush=True)
            time.sleep(max(3,min(e.retry,60)))

if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: print('\nБот зупинено.')

"""Public titles and paid descriptions. Access is checked before reading the body."""
import json
import os
import base64
import hashlib
import lzma
from pathlib import Path

FREE = frozenset((21, 30))
TELEGRAM_HANDLE = '@lakshmi_775'
TELEGRAM_URL = 'https://t.me/lakshmi_775'
INSTAGRAM_URL = 'https://www.instagram.com/lakshmi_775?srtk=dDZ4ajlpODhvc2sw&utm_source=qr'
CONTACTS = 'Telegram: ' + TELEGRAM_HANDLE + '\nInstagram: ' + INSTAGRAM_URL
CTA = ('Для повного розбору з детальним описом Ваших сильних сторін, можливих блоків '
       'і шляхів їх опрацювання пишіть '+TELEGRAM_HANDLE+'.\n\n'+CONTACTS)
def read_catalog():
    """Load private deployment configuration, or a private file. Never fetch public content."""
    count = int(os.getenv('CATALOG_XZ_PARTS','0'))
    if count:
        if not 1 <= count <= 20: raise ValueError('Некоректна кількість частин каталогу.')
        packed = ''.join(os.environ[f'CATALOG_XZ_B64_{i}'] for i in range(1,count+1))
        raw = lzma.decompress(base64.b64decode(packed,validate=True))
        expected = os.environ['CATALOG_SHA256']
        if hashlib.sha256(raw).hexdigest() != expected: raise ValueError('Каталог пошкоджено.')
        return json.loads(raw)
    local_catalog = Path(__file__).parent / 'content' / 'positions.json'
    private_catalog = Path(os.getenv('RAILWAY_VOLUME_MOUNT_PATH','/data'))/'content'/'positions.json'
    catalog_path = Path(os.getenv('CATALOG_PATH') or (local_catalog if local_catalog.exists() else private_catalog))
    return json.loads(catalog_path.read_text())

POSITIONS = {p['number']: p for p in read_catalog()}
assert set(POSITIONS) == set(range(1, 34))
assert all(set(p['arcana']) == set(map(str, range(1, 23))) for p in POSITIONS.values())
assert POSITIONS[21]['key'] == 'П21' and POSITIONS[30]['key'] == 'П30'

def arcana_for(number, calculated):
    key = POSITIONS[number]['key']
    return [calculated['П15а'], calculated['П15б']] if key == 'П15' else [calculated[key]]

def description(number, birth_date, calculated):
    p = POSITIONS[number]
    parts = [f"Позиція {number} ({p['key']}) · {p['title']}\nДата народження: {birth_date}"]
    values = arcana_for(number, calculated)
    for i, value in enumerate(values):
        a = p['arcana'][str(value)]
        prefix = f'Результат {i + 1}. ' if len(values) == 2 else ''
        parts.append(f"{prefix}Аркан {value} {a['name']}")
        parts.extend([a['core'], 'Позитивні прояви. ' + a['positive'],
                      'Можливі труднощі. ' + a['problems'],
                      'Внутрішні установки та блоки. ' + a['blocks']])
    parts.append(CTA)
    return '\n\n'.join(parts)

def chunks(text, limit=3900):
    """Telegram counts UTF-16 units; split safely even for unusually long paragraphs."""
    chunk = ''
    for paragraph in text.split('\n\n'):
        for word in paragraph.split(' '):
            candidate = chunk + (' ' if chunk and not chunk.endswith('\n\n') else '') + word
            if len(candidate.encode('utf-16-le')) // 2 > limit:
                yield chunk.rstrip(); chunk = word
            else: chunk = candidate
        chunk += '\n\n'
    if chunk.strip(): yield chunk.rstrip()

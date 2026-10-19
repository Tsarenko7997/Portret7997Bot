"""Private karma descriptions. Call only after membership checks."""
import base64
import hashlib
import json
import lzma
import os
from functools import lru_cache
from pathlib import Path
from catalog import CTA

FIELDS = ('title', 'theme', 'problems', 'blocks', 'positive')

@lru_cache(maxsize=1)
def read_karma_catalog():
    count = int(os.getenv('KARMA_MINUS_XZ_PARTS', '0'))
    if count:
        if not 1 <= count <= 20:
            raise ValueError('Некоректна кількість частин каталогу карми.')
        packed = ''.join(os.environ[f'KARMA_MINUS_XZ_B64_{i}'] for i in range(1, count + 1))
        raw = lzma.decompress(base64.b64decode(packed, validate=True))
        if hashlib.sha256(raw).hexdigest() != os.environ['KARMA_MINUS_SHA256']:
            raise ValueError('Каталог карми пошкоджено.')
    else:
        local = Path(__file__).parent / 'content' / 'karma_minus.json'
        private = Path(os.getenv('RAILWAY_VOLUME_MOUNT_PATH', '/data')) / 'content' / 'karma_minus.json'
        path = Path(os.getenv('KARMA_MINUS_PATH') or (local if local.exists() else private))
        raw = path.read_bytes()
    entries = json.loads(raw)
    if not isinstance(entries, list) or len(entries) != 22:
        raise ValueError('Каталог карми має містити 22 аркани.')
    catalog = {}
    for entry in entries:
        number = entry.get('number') if isinstance(entry, dict) else None
        if type(number) is not int or not 1 <= number <= 22 or number in catalog:
            raise ValueError('Некоректні номери арканів карми.')
        if any(not isinstance(entry.get(key), str) or not entry[key].strip() for key in FIELDS):
            raise ValueError('Неповний опис аркану карми.')
        catalog[number] = entry
    return catalog

def negative_description(position, arcanum, birth):
    entry = read_karma_catalog()[arcanum]
    parts = [f'Мінусова карма · Позиція {position}\nДата народження: {birth}',
             f"Аркан {arcanum} · {entry['title']}",
             'Кармічна тема. ' + entry['theme'],
             'Можливі труднощі. ' + entry['problems'],
             'Внутрішні блоки. ' + entry['blocks'],
             'Сильні сторони. ' + entry['positive'], CTA]
    return '\n\n'.join(parts)

@lru_cache(maxsize=1)
def read_positive_karma_catalog():
    count = int(os.getenv('KARMA_PLUS_XZ_PARTS', '0'))
    if count:
        if not 1 <= count <= 20:
            raise ValueError('Некоректна кількість частин каталогу карми.')
        packed = ''.join(os.environ[f'KARMA_PLUS_XZ_B64_{i}'] for i in range(1,count+1))
        raw = lzma.decompress(base64.b64decode(packed,validate=True))
        if hashlib.sha256(raw).hexdigest() != os.environ['KARMA_PLUS_SHA256']:
            raise ValueError('Каталог плюсової карми пошкоджено.')
    else:
        local = Path(__file__).parent / 'content' / 'karma_positive.json'
        private = Path(os.getenv('RAILWAY_VOLUME_MOUNT_PATH','/data')) / 'content' / 'karma_positive.json'
        path = Path(os.getenv('KARMA_PLUS_PATH') or (local if local.exists() else private))
        raw = path.read_bytes()
    entries = json.loads(raw)
    if not isinstance(entries,list) or len(entries) != 22:
        raise ValueError('Каталог плюсової карми має містити 22 аркани.')
    catalog = {}
    for entry in entries:
        number = entry.get('number') if isinstance(entry,dict) else None
        if type(number) is not int or not 1 <= number <= 22 or number in catalog:
            raise ValueError('Некоректні номери арканів плюсової карми.')
        if any(not isinstance(entry.get(key),str) or not entry[key].strip()
               for key in ('title','resource','expression','balance')):
            raise ValueError('Неповний опис аркану плюсової карми.')
        catalog[number] = entry
    return catalog

def positive_description(position,arcanum,birth):
    entry = read_positive_karma_catalog()[arcanum]
    parts = [f'Плюсова карма · Позиція {position}\nДата народження: {birth}',
             f"Аркан {arcanum} · {entry['title']}",
             'Ваш ресурс. ' + entry['resource'],
             'Можливі прояви. ' + entry['expression'],
             'Що може послаблювати ресурс. ' + entry['balance'],CTA]
    return '\n\n'.join(parts)

"""Position meanings supplied through private deployment configuration."""
import json
import os
import base64
import hashlib
import lzma
from functools import lru_cache


@lru_cache(maxsize=1)
def read_catalog():
    rows = json.loads(os.environ.get('COMPATIBILITY_POSITIONS_JSON', '{}'))
    if set(rows) != set(map(str, range(1, 9))):
        raise ValueError('Invalid compatibility positions')
    for row in rows.values():
        if not isinstance(row, dict) or set(row) != {'title', 'meaning'}:
            raise ValueError('Invalid compatibility position')
        if any(not isinstance(value, str) or not value.strip() or len(value) > 1500
               for value in row.values()):
            raise ValueError('Invalid compatibility text')
    return rows


def compatibility_position(number):
    row = read_catalog()[str(number)]
    return row['title'], row['meaning']


@lru_cache(maxsize=1)
def read_arcana_catalog():
    count = int(os.environ.get('COMPATIBILITY_XZ_PARTS', '0'))
    if not 1 <= count <= 20:
        raise ValueError('Invalid compatibility catalog parts')
    packed = ''.join(os.environ[f'COMPATIBILITY_XZ_B64_{i}'] for i in range(1, count+1))
    raw = lzma.decompress(base64.b64decode(packed, validate=True))
    if hashlib.sha256(raw).hexdigest() != os.environ['COMPATIBILITY_SHA256']:
        raise ValueError('Invalid compatibility catalog checksum')
    entries = json.loads(raw)
    if not isinstance(entries, list) or len(entries) != 22:
        raise ValueError('Expected 22 compatibility arcana')
    rows = {}
    for entry in entries:
        number = entry['number']
        if type(number) is not int or number not in range(1, 23) or number in rows:
            raise ValueError('Invalid compatibility arcanum')
        for key in ('name', 'keywords'):
            if not isinstance(entry[key], str) or not entry[key].strip() or len(entry[key]) > 250:
                raise ValueError('Invalid compatibility heading')
        if set(entry['positions']) != set(map(str, range(1, 9))):
            raise ValueError('Expected 8 compatibility positions')
        for position in entry['positions'].values():
            if set(position) != {'general', 'positive', 'difficulties'}:
                raise ValueError('Invalid compatibility fields')
            if any(not isinstance(value, str) or not value.strip() or len(value) > 1200
                   for value in position.values()):
                raise ValueError('Invalid compatibility reading')
        rows[number] = entry
    return rows


def compatibility_description(position, number):
    entry = read_arcana_catalog()[number]
    fields = entry['positions'][str(position)]
    return '\n\n'.join([
        f"Аркан {number} · {entry['name']}",
        'Ключові слова. '+entry['keywords'],
        'Загальний опис. '+fields['general'],
        'Позитивні прояви. '+fields['positive'],
        'Можливі труднощі. '+fields['difficulties'],
    ])

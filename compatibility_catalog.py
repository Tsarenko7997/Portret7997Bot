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


def compatibility_position(number, kind='general'):
    if kind not in ('love','general','parent'):
        raise ValueError('Invalid compatibility kind')
    configured = os.environ.get('COMPATIBILITY_MODES_JSON')
    if not configured and kind != 'general':
        raise ValueError('Compatibility position kind unavailable')
    row = json.loads(configured)[kind][str(number)] if configured else read_catalog()[str(number)]
    if any(not isinstance(row.get(key),str) or not row[key].strip() for key in ('title','meaning')):
        raise ValueError('Invalid compatibility meaning')
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
        variants = entry.get('variants')
        if variants is not None:
            if not isinstance(variants,dict) or set(variants) != {'love','general','parent'}:
                raise ValueError('Expected 3 compatibility kinds')
            for variant in variants.values():
                if not isinstance(variant.get('keywords'),str) or not variant['keywords'].strip():
                    raise ValueError('Invalid compatibility keywords')
                if set(variant['positions']) != set(map(str,range(1,9))):
                    raise ValueError('Expected 8 variant positions')
                for fields in variant['positions'].values():
                    if set(fields) != {'general','positive','difficulties','practical'} or any(
                            not isinstance(v,str) or not v.strip() or len(v)>2000 for v in fields.values()):
                        raise ValueError('Invalid compatibility variant fields')
        rows[number] = entry
    return rows


def compatibility_description(position, number, kind='general'):
    if kind not in ('love','general','parent'):
        raise ValueError('Invalid compatibility kind')
    entry = read_arcana_catalog()[number]
    variant = entry.get('variants',{}).get(kind)
    if variant is None and kind != 'general':
        raise ValueError('Compatibility kind unavailable')
    fields = (variant['positions'] if variant else entry['positions'])[str(position)]
    keywords = variant['keywords'] if variant else entry['keywords']
    return '\n\n'.join([
        f"Аркан {number} · {entry['name']}",
        'Ключові слова. '+keywords,
        'Загальний опис. '+fields['general'],
        'Позитивні прояви. '+fields['positive'],
        'Можливі труднощі. '+fields['difficulties'],
    ] + (['Практичний орієнтир. '+fields['practical']] if fields.get('practical') else []))

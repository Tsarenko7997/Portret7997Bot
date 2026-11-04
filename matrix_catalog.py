"""Matrix interpretation catalog, supplied only through private configuration."""
import base64
import hashlib
import json
import lzma
import os
from functools import lru_cache

VARIANTS={1:('1','2','3+'),2:('1','2','3+'),3:('0','1','2+'),
          4:('0','1','2','3+'),5:('0','1','2+'),6:('0','1','2+'),
          7:('0','1','2','3+'),8:('0','1','2','3+'),9:('0','1','2','3+')}
LINE_IDS=('h147','h258','h369','d159','d357','v123','v456','v789')


def _text(value,limit=6500):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise ValueError('Invalid matrix text')


@lru_cache(maxsize=1)
def read_matrix_catalog():
    count=int(os.environ.get('MATRIX_XZ_PARTS','0'))
    if not 1<=count<=20:raise ValueError('Invalid matrix catalog parts')
    packed=''.join(os.environ[f'MATRIX_XZ_B64_{i}'] for i in range(1,count+1))
    raw=lzma.decompress(base64.b64decode(packed,validate=True))
    if hashlib.sha256(raw).hexdigest()!=os.environ['MATRIX_SHA256']:
        raise ValueError('Invalid matrix checksum')
    rows=json.loads(raw)
    if not isinstance(rows,dict) or set(rows)!={'digits','lines','triangles'}:
        raise ValueError('Invalid matrix catalog')
    if set(rows['digits'])!=set(map(str,range(1,10))) or set(rows['lines'])!=set(LINE_IDS) or set(rows['triangles'])!={'altruism','personal'}:
        raise ValueError('Incomplete matrix catalog')
    for digit,keys in VARIANTS.items():
        entry=rows['digits'][str(digit)]
        if set(entry)!={'title','intro','variants'} or set(entry['variants'])!=set(keys):raise ValueError('Invalid matrix variants')
        _text(entry['title'],100);_text(entry['intro'])
        for text in entry['variants'].values():_text(text)
    for entry in list(rows['lines'].values())+list(rows['triangles'].values()):
        if set(entry)!={'title','text'}:raise ValueError('Invalid matrix section')
        _text(entry['title'],120);_text(entry['text'])
    return rows


def matrix_digit_description(digit,count):
    if type(digit) is not int or digit not in VARIANTS or type(count) is not int or count<0:
        raise ValueError('Invalid matrix digit or count')
    entry=read_matrix_catalog()['digits'][str(digit)]
    key=str(count)
    if key not in entry['variants']:
        key=next((key for key in VARIANTS[digit] if key.endswith('+') and count>=int(key[:-1])),None)
    body=entry['variants'][key] if key else 'Для цієї кількості цифр опис поки недоступний.'
    return entry['title']+'\n\n'+entry['intro']+'\n\n'+body

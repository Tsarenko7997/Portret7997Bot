"""Social-purpose descriptions from private deployment configuration."""
import base64
import hashlib
import json
import lzma
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def read_social_catalog():
    count=int(os.environ.get('SOCIAL_XZ_PARTS','0'))
    if not 1<=count<=20:raise ValueError('Invalid social catalog parts')
    packed=''.join(os.environ[f'SOCIAL_XZ_B64_{i}'] for i in range(1,count+1))
    raw=lzma.decompress(base64.b64decode(packed,validate=True))
    if hashlib.sha256(raw).hexdigest()!=os.environ['SOCIAL_SHA256']:
        raise ValueError('Invalid social catalog checksum')
    rows=json.loads(raw)
    if not isinstance(rows,dict) or set(rows)!={'intro','entries'}:
        raise ValueError('Invalid social catalog')
    if not isinstance(rows['intro'],str) or not rows['intro'].strip() or len(rows['intro'])>4000:
        raise ValueError('Invalid social introduction')
    if not isinstance(rows['entries'],dict) or set(rows['entries'])!=set(map(str,range(1,23))):
        raise ValueError('Expected 22 social energies')
    for number,row in rows['entries'].items():
        if not isinstance(row,dict) or set(row)!={'heading','text'}:
            raise ValueError('Invalid social energy')
        if any(not isinstance(value,str) or not value.strip() or len(value)>6000 for value in row.values()):
            raise ValueError('Invalid social text')
        if not row['heading'].startswith(f'{number} ЕНЕРГІЯ · '):
            raise ValueError('Mismatched social energy')
    return rows


def social_description(number):
    if type(number) is not int or not 1<=number<=22:raise ValueError('Invalid social energy')
    catalog=read_social_catalog();entry=catalog['entries'][str(number)]
    return catalog['intro']+'\n\n'+entry['heading']+'\n\n'+entry['text']

"""Private money-purpose readings, loaded only after membership validation."""
import base64
import hashlib
import json
import lzma
import os
from functools import lru_cache
from pathlib import Path
from catalog import CTA


@lru_cache(maxsize=1)
def read_money_catalog():
    count = int(os.getenv('MONEY_XZ_PARTS','0'))
    if count:
        if not 1 <= count <= 20:
            raise ValueError('Некоректна кількість частин каталогу.')
        packed = ''.join(os.environ[f'MONEY_XZ_B64_{i}'] for i in range(1,count+1))
        raw = lzma.decompress(base64.b64decode(packed,validate=True))
        if hashlib.sha256(raw).hexdigest() != os.environ['MONEY_SHA256']:
            raise ValueError('Каталог грошового призначення пошкоджено.')
    else:
        local = Path(__file__).parent/'content'/'money.json'
        private = Path(os.getenv('RAILWAY_VOLUME_MOUNT_PATH','/data'))/'content'/'money.json'
        path = Path(os.getenv('MONEY_PATH') or (local if local.exists() else private))
        raw = path.read_bytes()
    entries = json.loads(raw)
    if not isinstance(entries,list) or len(entries) != 22:
        raise ValueError('Каталог має містити 22 аркани.')
    catalog = {}
    for entry in entries:
        number = entry.get('number') if isinstance(entry,dict) else None
        if type(number) is not int or not 1 <= number <= 22 or number in catalog:
            raise ValueError('Некоректні номери арканів.')
        if any(not isinstance(entry.get(key),str) or not entry[key].strip()
               for key in ('title','directions','focus')):
            raise ValueError('Неповний опис грошового призначення.')
        catalog[number] = entry
    return catalog


def money_description(arcanum):
    if type(arcanum) is not int or not 1 <= arcanum <= 22:
        raise ValueError('Некоректний аркан.')
    entry = read_money_catalog()[arcanum]
    return '\n\n'.join([f"Аркан {arcanum} · {entry['title']}",
                          entry['directions'],'Ваш акцент. '+entry['focus'],CTA])

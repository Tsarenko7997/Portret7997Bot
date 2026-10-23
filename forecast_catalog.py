"""Private forecast content, loaded only after a membership check."""
import base64
import hashlib
import json
import lzma
import os
from functools import lru_cache
from pathlib import Path

FIELDS = ('keywords', 'general', 'positive', 'difficulties')
PERIODS = ('year', 'month', 'day')


@lru_cache(maxsize=1)
def read_forecast_catalog():
    count = int(os.getenv('FORECAST_XZ_PARTS', '0'))
    if count:
        if not 1 <= count <= 20:
            raise ValueError('Некоректна кількість частин каталогу прогнозів.')
        packed = ''.join(os.environ[f'FORECAST_XZ_B64_{i}'] for i in range(1, count + 1))
        raw = lzma.decompress(base64.b64decode(packed, validate=True))
        if hashlib.sha256(raw).hexdigest() != os.environ['FORECAST_SHA256']:
            raise ValueError('Каталог прогнозів пошкоджено.')
    else:
        private = Path(os.getenv('RAILWAY_VOLUME_MOUNT_PATH', '/data')) / 'content' / 'forecasts.json'
        raw = Path(os.getenv('FORECAST_PATH') or private).read_bytes()
    entries = json.loads(raw)
    if not isinstance(entries, list) or len(entries) != 22:
        raise ValueError('Каталог прогнозів має містити 22 аркани.')
    catalog = {}
    for entry in entries:
        number = entry.get('number') if isinstance(entry, dict) else None
        if type(number) is not int or not 1 <= number <= 22 or number in catalog:
            raise ValueError('Некоректні номери арканів прогнозу.')
        if not isinstance(entry.get('name'), str) or not entry['name'].strip():
            raise ValueError('Відсутня назва аркана.')
        forecasts = entry.get('forecasts')
        if not isinstance(forecasts, dict) or set(forecasts) != set(PERIODS):
            raise ValueError('Неповний набір періодів прогнозу.')
        for period in PERIODS:
            variants = [forecasts[period]]
            if period == 'year':
                if not isinstance(forecasts[period], dict):
                    raise ValueError('Неповний опис прогнозу.')
                variants += [forecasts[period].get('professional'), forecasts[period].get('personal')]
            for fields in variants:
                if not isinstance(fields, dict) or any(
                        not isinstance(fields.get(k), str) or not fields[k].strip() for k in FIELDS):
                    raise ValueError('Неповний опис прогнозу.')
        catalog[number] = entry
    return catalog


def forecast_description(section, arcanum, slot=1):
    if section not in PERIODS or slot not in ((1, 2) if section == 'year' else (1,)):
        raise ValueError('Невідома позиція прогнозу.')
    entry = read_forecast_catalog()[arcanum]
    fields = entry['forecasts'][section]
    if section == 'year':
        fields = fields['professional' if slot == 1 else 'personal']
    labels = ('Ключові слова', 'Загальний опис', 'Позитивні події', 'Можливі труднощі')
    return '\n\n'.join([f"Аркан {arcanum} · {entry['name']}"] +
                        [label + '. ' + fields[key] for label, key in zip(labels, FIELDS)])

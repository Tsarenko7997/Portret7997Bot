"""Position meanings supplied through private deployment configuration."""
import json
import os
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

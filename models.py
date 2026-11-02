"""Shared product values and configurable classifications."""
from dataclasses import asdict, dataclass
from datetime import datetime
import re
from zoneinfo import ZoneInfo


def now_iso():
    return datetime.now(ZoneInfo('Asia/Kolkata')).isoformat(timespec='seconds')


@dataclass
class Product:
    id: str
    name: str
    url: str
    price: str | None = None
    status: str = 'unknown'
    sku: str | None = None
    movement: str = ''

    def to_dict(self):
        return asdict(self)


def classify(product, config):
    text = ' '.join(str(product.get(k) or '') for k in ('name', 'sku', 'movement'))
    automatic = any(re.search(p, text, re.I) for p in config['automatic_patterns'])
    for level in ('highest', 'additional'):
        if any(re.search(p, text, re.I) for p in config['priority'][level]):
            return level, automatic
    return ('highest' if automatic else 'standard'), automatic

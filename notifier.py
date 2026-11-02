"""Telegram HTTPS notifications with durable delivery handled by the tracker."""
from datetime import datetime
import os
import time
from zoneinfo import ZoneInfo
import requests


class NotificationError(RuntimeError):
    pass


def ist(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y %H:%M:%S IST')


def format_event(event):
    if event['type'] == 'failure':
        return f"HMT monitoring failed {event['failures']} consecutive times.\nLast valid catalogue preserved.\n{ist(event['time'])}"
    p = event['product']
    label = '🚨 PRIORITY ' if event['priority'] == 'highest' else ''
    auto = ' | AUTOMATIC' if event.get('automatic') else ''
    availability = {'in_stock': 'IN STOCK', 'out_of_stock': 'OUT OF STOCK', 'unknown': 'UNKNOWN'}[p['status']]
    return (f"{label}{event['type'].upper()}{auto}\n{p['name'][:220]}\n"
            f"Price: INR {str(p.get('price') or 'unavailable')[:60]} | {availability}\n"
            f"Model/SKU: {str(p.get('sku') or 'unavailable')[:120]}\n"
            f"Priority: {event['priority']}\n{ist(event['time'])}\n{p['url']}")


def units(text):
    return len(text.encode('utf-16-le')) // 2


def batches(events, limit=3900):
    """Keep event groups stable; plain text avoids HTML escaping and entity limits."""
    current, parts = [], []
    for event in events:
        part = format_event(event)
        if units(part) > limit:
            raise NotificationError('Product message exceeds Telegram limit; inspect product URL.')
        if parts and units('\n\n'.join(parts + [part])) > limit:
            yield current, '\n\n'.join(parts)
            current, parts = [], []
        current.append(event['id'])
        parts.append(part)
    if parts:
        yield current, '\n\n'.join(parts)


class Telegram:
    def __init__(self, token=None, chat_id=None, session=None, sleep=time.sleep):
        self.token = token or os.environ.get('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID')
        if not self.token or not self.chat_id:
            raise NotificationError('Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.')
        self.session = session or requests.Session()
        self.sleep = sleep

    def send(self, text):
        if units(text) > 4096:
            raise NotificationError('Telegram text exceeds 4096 UTF-16 units.')
        for attempt in range(3):
            try:
                response = self.session.post(
                    f'https://api.telegram.org/bot{self.token}/sendMessage',
                    json={'chat_id': self.chat_id, 'text': text,
                          'link_preview_options': {'is_disabled': True}}, timeout=20)
            except requests.RequestException:
                # Ambiguous timeout may already have delivered. Let durable outbox retry
                # next execution; never log exception URLs (they contain the token).
                raise NotificationError('Telegram network failure; delivery remains pending.') from None
            try:
                data = response.json()
            except ValueError:
                raise NotificationError('Telegram returned an invalid response.') from None
            if response.status_code == 200 and data.get('ok') is True:
                return
            if response.status_code == 429 and attempt < 2:
                delay = data.get('parameters', {}).get('retry_after', 2)
                self.sleep(min(max(float(delay), 1), 30))
                continue
            if response.status_code >= 500 and attempt < 2:
                self.sleep(2 ** attempt)
                continue
            raise NotificationError(f'Telegram rejected delivery (HTTP {response.status_code}); check secrets and bot conversation.')
        raise NotificationError('Telegram rate limit persisted; delivery remains pending.')

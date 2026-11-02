"""CLI entry point: scan, dry-run, Telegram test and chat ID lookup."""
import argparse
import copy
import json
import logging
import os
from pathlib import Path
import re
import sys
import requests
import yaml
from detection import IncompleteScan, apply_failure, apply_scan, deliver
from models import classify, now_iso
from notifier import NotificationError, Telegram, ist
from scraper import ScrapeError, Scraper
from state_manager import GitState, LocalState, StateError

log = logging.getLogger('hmt')


def load_config(path):
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    for key in ('request_timeout', 'max_pages', 'minimum_products', 'removed_after_scans', 'failure_alert_after'):
        if not isinstance(config.get(key), (int, float)) or config[key] <= 0:
            raise ValueError(f'Invalid positive configuration value: {key}')
    if not 0 < config['minimum_catalogue_ratio'] <= 1 or config['request_delay'] < 0 or config['retries'] < 0:
        raise ValueError('Invalid scan safety or request setting.')
    for pattern in config['automatic_patterns'] + sum(config['priority'].values(), []):
        re.compile(pattern)
    return config


def report(state, config):
    products = list(state['products'].values())
    active = [p for p in products if not p.get('removed') and p.get('missing_scans', 0) == 0]
    lines = ['# HMT stock report', '', f"Last successful check: {ist(state['last_success']) if state['last_success'] else 'never'}",
             f"Total recorded variants: {len(products)} | Present in latest scan: {len(active)}",
             f"Removed: {sum(bool(p.get('removed')) for p in products)} | Pending alerts: {len(state['pending'])}", '']
    for status in ('in_stock', 'out_of_stock', 'unknown'):
        lines.append(f"- {status}: {sum(p['status'] == status for p in active)}")
    lines.extend(['', '## Priority watches available', ''])
    for p in active:
        if p['status'] == 'in_stock' and classify(p, config)[0] != 'standard':
            lines.append(f"- {p['name'].replace('[', '').replace(']', '')} — INR {p.get('price') or '?'} — {p['url']}")
    lines.extend(['', '## Recent discoveries and restocks', ''])
    for event in reversed(state['history'][-20:]):
        lines.append(f"- {ist(event['time'])}: {event['type']} — {event['product']['name']}")
    return '\n'.join(lines) + '\n'


def run_scan(store, scraper, config, notifier=None, dry_run=False, report_path='stock-report.md'):
    previous = store.load()
    try:
        products = scraper.scan()
        state = apply_scan(previous, products, config, now_iso())
    except (ScrapeError, IncompleteScan) as exc:
        log.error('scan_failed reason=%s', exc)
        if not dry_run:
            state = apply_failure(previous, config, now_iso())
            store.save(state)
            if notifier:
                deliver(state, store, notifier)
        return 1
    if not dry_run:
        store.save(state)  # Must succeed remotely BEFORE sending any event.
        if notifier:
            deliver(state, store, notifier)
    Path(report_path).write_text(report(state, config), encoding='utf-8')
    log.info('scan_success products=%s pending=%s baseline=%s dry_run=%s',
             len(products), len(state['pending']), not previous['initialized'], dry_run)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', choices=['scan', 'test-notification', 'chat-id'], default='scan')
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--state', default='.data/state.json')
    parser.add_argument('--git-state', action='store_true', help='Persist to tracker-state remote branch')
    parser.add_argument('--dry-run', action='store_true', help='Read only; no state writes or Telegram sends')
    parser.add_argument('--no-notify', action='store_true', help='Queue notifications but do not deliver')
    parser.add_argument('--report', default='stock-report.md')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s level=%(levelname)s %(name)s %(message)s')
    store = None
    try:
        if args.command == 'test-notification':
            Telegram().send(f'HMT tracker test notification\n{ist(now_iso())}')
            log.info('telegram_test_success')
            return 0
        if args.command == 'chat-id':
            token = os.environ.get('TELEGRAM_BOT_TOKEN')
            if not token:
                raise NotificationError('Set TELEGRAM_BOT_TOKEN first.')
            try:
                response = requests.get(f'https://api.telegram.org/bot{token}/getUpdates', timeout=20)
                data = response.json()
                if response.status_code != 200 or data.get('ok') is not True:
                    raise ValueError()
                ids = {update['message']['chat']['id'] for update in data['result'] if 'message' in update}
            except (requests.RequestException, ValueError, KeyError):
                raise NotificationError('Cannot obtain chat ID; check token and send /start to the bot.') from None
            print('\n'.join(str(i) for i in sorted(ids)) if ids else 'No chats found. Send /start to your bot, then rerun.')
            return 0
        config = load_config(args.config)
        notifier = None if args.dry_run or args.no_notify else Telegram()
        store = GitState() if args.git_state else LocalState(args.state)
        return run_scan(store, Scraper(config), config, notifier, args.dry_run, args.report)
    except (StateError, NotificationError, ValueError, OSError) as exc:
        log.error('tracker_stopped reason=%s', exc)
        return 1
    finally:
        if isinstance(store, GitState):
            store.close()


if __name__ == '__main__':
    sys.exit(main())

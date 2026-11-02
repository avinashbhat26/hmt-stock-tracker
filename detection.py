"""Pure state transitions: unknown and missing never mean out of stock."""
import copy
from models import classify


class IncompleteScan(RuntimeError):
    pass


def apply_scan(previous, products, config, timestamp):
    if len(products) < config['minimum_products']:
        raise IncompleteScan('Catalogue is smaller than configured minimum.')
    existing_count = sum(not p.get('removed', False) for p in previous['products'].values())
    if previous['initialized'] and len(products) < existing_count * config['minimum_catalogue_ratio']:
        raise IncompleteScan('Catalogue shrank beyond the safety threshold; review before accepting.')
    state = copy.deepcopy(previous)
    state['scan_sequence'] += 1
    found = set()
    for product in products:
        p = product.to_dict()
        key = p['id']
        if key in found:
            raise IncompleteScan('Scanner returned duplicate product identifiers.')
        found.add(key)
        old = state['products'].get(key)
        confirmed = p['status'] if p['status'] != 'unknown' else (old or {}).get('confirmed')
        transition = (old or {}).get('transition', 0)
        if old and confirmed and confirmed != old.get('confirmed'):
            transition += 1
        event_type = None
        if state['initialized']:
            if old is None:
                event_type = 'new launch' if p['status'] != 'in_stock' else 'new launch — available'
            elif old.get('confirmed') == 'out_of_stock' and p['status'] == 'in_stock':
                event_type = 'restock'
        p.update(first_seen=(old or {}).get('first_seen', timestamp), last_seen=timestamp,
                 last_checked=timestamp, confirmed=confirmed, transition=transition,
                 missing_scans=0, removed=False)
        state['products'][key] = p
        if event_type:
            priority, automatic = classify(p, config)
            event = {'id': f'{key}:{transition}:{event_type}', 'type': event_type,
                     'time': timestamp, 'priority': priority, 'automatic': automatic,
                     'product': copy.deepcopy(p)}
            if event['id'] not in state['sent'] and not any(e['id'] == event['id'] for e in state['pending']):
                state['pending'].append(event)
                state['history'].append(copy.deepcopy(event))
    for key, p in state['products'].items():
        if key not in found:
            p['missing_scans'] += 1
            p['removed'] = p['missing_scans'] >= config['removed_after_scans']
    state.update(initialized=True, last_success=timestamp, failures=0, failure_notified=False)
    state['history'] = state['history'][-500:]
    state['pending'].sort(key=lambda e: {'highest': 0, 'additional': 1}.get(e.get('priority'), 2))
    return state


def apply_failure(previous, config, timestamp):
    state = copy.deepcopy(previous)
    state['failures'] += 1
    if state['failures'] >= config['failure_alert_after'] and not state['failure_notified']:
        state['pending'].append({'id': f"failure:{timestamp}", 'type': 'failure',
                                 'time': timestamp, 'failures': state['failures']})
        state['failure_notified'] = True
    return state


def deliver(state, store, notifier):
    from notifier import batches
    for ids, message in batches(list(state['pending'])):
        notifier.send(message)
        state['pending'] = [e for e in state['pending'] if e['id'] not in ids]
        state['sent'] = (state['sent'] + ids)[-2000:]
        store.save(state)

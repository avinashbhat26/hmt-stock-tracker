from dataclasses import replace
from unittest.mock import Mock
import pytest
import requests
from detection import apply_scan, deliver
from notifier import NotificationError, Telegram, batches, format_event, units
from state_manager import LocalState, empty_state

T = '2026-11-02T12:00:00+05:30'


def event(product):
    return {'id': 'test', 'type': 'restock', 'time': T, 'priority': 'highest',
            'automatic': True, 'product': product.to_dict()}


def test_format(product):
    text = format_event(event(replace(product, status='in_stock')))
    for part in ('PRIORITY', 'RESTOCK', 'AUTOMATIC', '3599', 'JGGL 01', 'IN STOCK', 'IST', product.url):
        assert part in text


def test_batching_utf16(product):
    events = [dict(event(replace(product, name='⌚' * 220)), id=str(n)) for n in range(30)]
    groups = list(batches(events))
    assert len(groups) > 1
    assert all(units(text) <= 3900 for _, text in groups)
    assert [key for ids, _ in groups for key in ids] == [str(n) for n in range(30)]


def test_missing_secrets(monkeypatch):
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)
    with pytest.raises(NotificationError):
        Telegram()


def test_https_payload():
    session = Mock()
    session.post.return_value = Mock(status_code=200)
    session.post.return_value.json.return_value = {'ok': True}
    Telegram('fake-token', '123', session=session).send('test')
    args = session.post.call_args
    assert args.args[0].startswith('https://api.telegram.org/')
    assert args.kwargs['json']['chat_id'] == '123'
    assert args.kwargs['json']['text'] == 'test'


def test_secret_not_in_exception():
    session = Mock()
    session.post.side_effect = requests.Timeout('https://api.telegram.org/botSUPERSECRET/sendMessage')
    with pytest.raises(NotificationError) as exc:
        Telegram('SUPERSECRET', '123', session=session).send('test')
    assert 'SUPERSECRET' not in str(exc.value)


def test_rate_limit_retry():
    limited = Mock(status_code=429)
    limited.json.return_value = {'ok': False, 'parameters': {'retry_after': 2}}
    success = Mock(status_code=200)
    success.json.return_value = {'ok': True}
    session = Mock()
    session.post.side_effect = [limited, success]
    sleep = Mock()
    Telegram('fake-token', '123', session=session, sleep=sleep).send('test')
    sleep.assert_called_once_with(2)


def test_failed_delivery_retained(config, product, tmp_path):
    store = LocalState(tmp_path / 'state.json')
    state = apply_scan(empty_state(), [product], config, T)
    state = apply_scan(state, [replace(product, status='in_stock')], config, T)
    store.save(state)
    notifier = Mock()
    notifier.send.side_effect = NotificationError('offline')
    with pytest.raises(NotificationError):
        deliver(state, store, notifier)
    assert len(store.load()['pending']) == 1
    notifier.send.side_effect = None
    deliver(store.load(), store, notifier)
    assert not store.load()['pending']


def test_partial_batch_delivery_saved(product, tmp_path):
    store = LocalState(tmp_path / 'state.json')
    state = empty_state()
    state['pending'] = [dict(event(replace(product, name='A' * 220)), id=str(n)) for n in range(20)]
    store.save(state)
    notifier = Mock()
    notifier.send.side_effect = [None, NotificationError('offline')]
    with pytest.raises(NotificationError):
        deliver(state, store, notifier)
    persisted = store.load()
    assert persisted['sent'] and persisted['pending']
    assert not set(persisted['sent']) & {e['id'] for e in persisted['pending']}

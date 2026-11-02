from dataclasses import replace
from unittest.mock import Mock
import copy
import pytest
from detection import IncompleteScan, apply_failure, apply_scan, deliver
from models import classify
from state_manager import empty_state, LocalState, StateError
from tracker import run_scan

T = '2026-11-02T12:00:00+05:30'


def test_baseline_and_restock(config, product):
    baseline = apply_scan(empty_state(), [product], config, T)
    assert baseline['initialized'] and not baseline['pending']
    updated = apply_scan(baseline, [replace(product, status='in_stock')], config, T)
    assert len(updated['pending']) == 1
    assert updated['pending'][0]['type'] == 'restock'
    again = apply_scan(updated, [replace(product, status='in_stock')], config, T)
    assert len(again['pending']) == 1
    assert baseline['products']['1239']['status'] == 'out_of_stock'


def test_unknown_preserves_confirmed_history(config, product):
    state = apply_scan(empty_state(), [product], config, T)
    state = apply_scan(state, [replace(product, status='unknown')], config, T)
    assert not state['pending']
    assert state['products']['1239']['confirmed'] == 'out_of_stock'
    state = apply_scan(state, [replace(product, status='in_stock')], config, T)
    assert len(state['pending']) == 1


def test_unknown_to_stock_does_not_invent_restock(config, product):
    state = apply_scan(empty_state(), [replace(product, status='unknown')], config, T)
    assert not apply_scan(state, [replace(product, status='in_stock')], config, T)['pending']


@pytest.mark.parametrize('status', ['in_stock', 'out_of_stock', 'unknown'])
def test_new_products(config, product, status):
    state = apply_scan(empty_state(), [product], config, T)
    state = apply_scan(state, [product, replace(product, id='999', status=status)], config, T)
    assert len(state['pending']) == 1
    assert state['pending'][0]['type'].startswith('new launch')
    assert ('available' in state['pending'][0]['type']) == (status == 'in_stock')


def test_removed_not_out_of_stock(config, product):
    other = replace(product, id='999')
    state = apply_scan(empty_state(), [product, other], config, T)
    state = apply_scan(state, [other], config, T)
    assert not state['products']['1239']['removed']
    state = apply_scan(state, [other], config, T)
    assert state['products']['1239']['removed']
    assert state['products']['1239']['confirmed'] == 'out_of_stock'
    assert not state['pending']


def test_shrunken_catalogue_does_not_mutate(config, product):
    state = apply_scan(empty_state(), [product, replace(product, id='2'), replace(product, id='3')], config, T)
    before = copy.deepcopy(state)
    with pytest.raises(IncompleteScan):
        apply_scan(state, [product], config, T)
    assert state == before


@pytest.mark.parametrize('name,level,auto', [
    ('HMT KOHINOOR', 'highest', False), ('Sangam Gold', 'highest', False),
    ('Gandaberunda gold', 'highest', False), ('Kannadiga', 'highest', False),
    ('Pragati', 'additional', False), ('Tareeq', 'additional', False),
    ('NASS', 'additional', False), ('Hand-wound mechanical', 'additional', False),
    ('Limited edition', 'additional', False), ('Self Winding', 'highest', True),
    ('Stellar Automatic', 'highest', True), ('Plain Quartz', 'standard', False)])
def test_classification(config, product, name, level, auto):
    p = replace(product, name=name).to_dict()
    assert classify(p, config) == (level, auto)


def test_movement_classification(config, product):
    assert classify(replace(product, name='Stellar', movement='Automatic').to_dict(), config) == ('highest', True)


def test_failures_only_after_threshold(config, product):
    state = apply_scan(empty_state(), [product], config, T)
    for n in range(1, 6):
        state = apply_failure(state, config, T)
        assert len(state['pending']) == (1 if n >= 3 else 0)
    assert state['products']['1239']['confirmed'] == 'out_of_stock'
    state = apply_scan(state, [product], config, T)
    assert state['failures'] == 0 and not state['failure_notified']


def test_separate_runs_and_delivery_dedup(config, product, tmp_path):
    path = tmp_path / 'state.json'
    store = LocalState(path)
    store.save(apply_scan(store.load(), [product], config, T))
    store = LocalState(path)
    state = apply_scan(store.load(), [replace(product, status='in_stock')], config, T)
    store.save(state)
    notifier = Mock()
    deliver(state, store, notifier)
    later = LocalState(path).load()
    deliver(later, store, notifier)
    assert notifier.send.call_count == 1
    assert len(later['sent']) == 1 and not later['pending']


def test_no_send_before_persistence(config, product, tmp_path):
    old = apply_scan(empty_state(), [product], config, T)
    store = Mock()
    store.load.return_value = old
    store.save.side_effect = StateError('push conflict')
    scraper = Mock()
    scraper.scan.return_value = [replace(product, status='in_stock')]
    notifier = Mock()
    with pytest.raises(StateError):
        run_scan(store, scraper, config, notifier, report_path=tmp_path / 'report.md')
    notifier.send.assert_not_called()

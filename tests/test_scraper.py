from dataclasses import replace
from unittest.mock import Mock
import pytest
import requests
from scraper import BASE, ScrapeError, Scraper, parse_catalogue, parse_detail


def response(text='', data=None, status=200):
    r = Mock(status_code=status, text=text)
    r.json.return_value = data
    return r


def test_real_catalogue_and_stable_identity(fixture_text):
    first, more = parse_catalogue(fixture_text('catalogue-1.html'))
    second, _ = parse_catalogue(fixture_text('catalogue-2.html'))
    assert more and len(first) == 2
    assert set(first) < set(second)
    assert first['1239'].url != second['1239'].url
    assert first['1239'].status == 'unknown'


def test_duplicate_cards(fixture_text):
    html = fixture_text('catalogue-1.html')
    products, _ = parse_catalogue(html + html)
    assert len(products) == 2


def test_real_detail(fixture_text, product):
    p = parse_detail(fixture_text('detail-out.html'), product)
    assert p.name == 'HMT Kannadiga Gents JGGL 01'
    assert p.status == 'out_of_stock'
    assert p.sku == 'JGSL 01 Kannadiga'
    assert p.movement == 'Quartz'
    assert p.price == '3599'


def test_footer_button_is_not_availability(fixture_text, product):
    html = fixture_text('detail-out.html') + '<button class="add_to_cart">Add To Cart</button>'
    assert parse_detail(html, product).status == 'out_of_stock'


def test_synthetic_purchase_control_and_contradiction(fixture_text, product):
    # Positive purchase markup is synthetic: no in-stock page was available live.
    html = fixture_text('detail-out.html').replace('Out Of Stock', '')
    html = html.replace('id="notifyMe" onclick="notifyMe(1239)"',
                        'onclick="add_cart(1239,1)"').replace('Notify Me', 'Add To Cart')
    assert parse_detail(html, product).status == 'in_stock'
    assert parse_detail(html.replace('Add To Cart', 'Notify Me'), product).status == 'unknown'
    assert parse_detail(html.replace('type="button"', 'disabled type="button"'), product).status == 'unknown'
    assert parse_detail(html.replace('class="rating"', 'class="vote"')
                        .replace('0 reviews', 'Out Of Stock'), product).status == 'unknown'


def test_wrong_variant_rejected(fixture_text, product):
    with pytest.raises(ScrapeError):
        parse_detail(fixture_text('detail-out.html'), replace(product, id='999'))


@pytest.mark.parametrize('html', ['', '<html>maintenance</html>', '<div class="all_watches"></div>'])
def test_incomplete_response(html):
    with pytest.raises(ScrapeError):
        parse_catalogue(html)


def scan_session(fixture_text, pages):
    session = Mock()
    session.request.side_effect = [response('User-agent: *\nDisallow:\n'),
        response('<input id="load_more_count" value="1"><script>/filter_products</script>')]
    results = list(session.request.side_effect)
    results.extend(response(data={'html': fixture_text(p)}) for p in pages)
    detail = fixture_text('detail-out.html')
    for key in ('1239', '1238', '1237', '1236'):
        results.append(response(detail.replace('(1239)', f'({key})')))
    session.request.side_effect = results
    return session


def test_multiple_cumulative_pages(config, fixture_text):
    session = scan_session(fixture_text, ['catalogue-1.html', 'catalogue-2.html', 'catalogue-3.html'])
    products = Scraper(config, session=session, sleep=lambda _: None).scan()
    assert len(products) == 4
    calls = [c for c in session.request.call_args_list if c.args[0] == 'POST']
    assert [c.kwargs['data']['load_more_count'] for c in calls] == [1, 2, 4]
    assert all(c.kwargs['data']['availability_filter'] == -1 for c in calls)


def test_stalled_pagination(config, fixture_text):
    with pytest.raises(ScrapeError, match='stalled'):
        Scraper(config, scan_session(fixture_text, ['catalogue-1.html'] * 2), sleep=lambda _: None).scan()


def test_robots_restriction(config):
    session = Mock()
    session.request.return_value = response('User-agent: *\nDisallow: /mens\n')
    with pytest.raises(ScrapeError, match='robots'):
        Scraper(config, session, sleep=lambda _: None).scan()
    assert session.request.call_count == 1


@pytest.mark.parametrize('status', [403, 429])
def test_access_restrictions_no_retries(config, status):
    session = Mock()
    session.request.return_value = response(status=status)
    with pytest.raises(ScrapeError):
        Scraper(config, session, sleep=lambda _: None).request('GET', BASE + '/mens')
    assert session.request.call_count == 1


def test_network_retry(config):
    session = Mock()
    session.request.side_effect = [requests.Timeout(), response('ok')]
    assert Scraper(config, session, sleep=lambda _: None).request('GET', BASE + '/mens').text == 'ok'
    assert session.request.call_count == 2

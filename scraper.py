"""Adapter verified against HMT's public HTML and filter_products on 2026-11-02.

The load-more counter increases a cumulative result window (27, 54, ...).
Each listed variant has a numeric ID in its controls. Encrypted URLs are NOT IDs.
"""
import logging
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from models import Product

BASE = 'https://www.hmtwatches.in'
AGENT = 'HMTStockTracker/1.0'
log = logging.getLogger(__name__)


class ScrapeError(RuntimeError):
    pass


def parse_catalogue(html):
    soup = BeautifulSoup(html, 'html.parser')
    if not soup.select_one('.all_watches'):
        raise ScrapeError('Catalogue wrapper missing; markup changed or incomplete response.')
    cards = soup.select('.bc_p_item')
    if not cards:
        raise ScrapeError('Empty catalogue; refusing to reset baseline.')
    products = {}
    for card in cards:
        link = card.select_one('a.bc_p_name[href]')
        ids = set()
        for control in card.select('[onclick]'):
            match = re.search(r'\b(?:notifyMe|getProductDetails|getCompareProduct|add_cart)\(\s*[\'"]?(\d+)', control['onclick'])
            if match:
                ids.add(match.group(1))
        if not link or len(ids) != 1:
            raise ScrapeError('Product card missing a unique numeric ID or purchase link.')
        key = ids.pop()
        url = urljoin(BASE, link['href'])
        if urlsplit(url).netloc != urlsplit(BASE).netloc or urlsplit(url).path != '/product_overview':
            raise ScrapeError('Unexpected product link; adapter requires review.')
        product = Product(id=key, name=link.get_text(' ', strip=True), url=url)
        if key in products and products[key].name != product.name:
            raise ScrapeError('Conflicting duplicate product cards.')
        products[key] = product
    return products, bool(soup.select_one('#loadMoreBtnData'))


def parse_detail(html, product):
    soup = BeautifulSoup(html, 'html.parser')
    scope = soup.select_one('._product-detail-content')
    if scope is None or not scope.select_one('.product-title'):
        raise ScrapeError(f'Product {product.id}: detail content missing.')
    # Prevent login/error pages, stale redirects, or a different variant being accepted.
    control_ids = set()
    for control in scope.select('[onclick]'):
        match = re.search(r'\b(?:notifyMe|getCompareProduct|favourite|add_cart|update_product_details_cart)\(\s*[\'"]?(\d+)', control['onclick'])
        if match:
            control_ids.add(match.group(1))
    if product.id not in control_ids or control_ids != {product.id}:
        raise ScrapeError(f'Product {product.id}: variant identity mismatch.')
    product.name = scope.select_one('.product-title').get_text(' ', strip=True)
    price = scope.select_one('.discountPrice')
    if price:
        match = re.search(r'[\d,]+(?:\.\d{1,2})?', price.get_text(' ', strip=True))
        product.price = match.group(0).replace(',', '') if match else None
    for row in soup.select('ul.mobilePaddingNone li'):
        label = row.find('strong')
        values = row.find_all('div', recursive=False)
        if label and len(values) == 2:
            field = label.get_text(' ', strip=True).lower()
            value = values[1].get_text(' ', strip=True)
            if field == 'model no.':
                product.sku = value
            elif field == 'movement':
                product.movement = value
    vote_text = ' '.join(v.get_text(' ', strip=True).lower() for v in scope.select('.vote'))
    unavailable = 'out of stock' in vote_text
    purchase = False
    for control in scope.select('.action a, .action button'):
        text = control.get_text(' ', strip=True).lower()
        code = control.get('onclick', '')
        if ('add to cart' in text or 'buy now' in text) and re.search(
                rf'\b(?:add_cart|update_product_details_cart)\(\s*[\'"]?{re.escape(product.id)}\b', code):
            if not control.has_attr('disabled') and control.get('aria-disabled') != 'true' and 'disabled' not in control.get('class', []):
                purchase = True
    # Global footer quick-view contains an Add To Cart button even for unavailable
    # products. Only a control in this product's action area is eligible evidence.
    product.status = ('unknown' if purchase and unavailable else
                      'in_stock' if purchase else 'out_of_stock' if unavailable else 'unknown')
    return product


class Scraper:
    def __init__(self, config, session=None, sleep=time.sleep):
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update({'User-Agent': AGENT})
        self.sleep = sleep
        self.robots = None

    def request(self, method, url, **kwargs):
        if urlsplit(url).netloc != urlsplit(BASE).netloc:
            raise ScrapeError('Only the official HMT host is allowed.')
        if self.robots and not self.robots.can_fetch(AGENT, url):
            raise ScrapeError('HMT robots.txt disallows this request.')
        for attempt in range(self.config['retries'] + 1):
            self.sleep(self.config['request_delay'])
            try:
                response = self.session.request(method, url, timeout=self.config['request_timeout'],
                                                allow_redirects=False, **kwargs)
            except requests.RequestException:
                if attempt == self.config['retries']:
                    raise ScrapeError('HMT network request failed after limited retries.') from None
                self.sleep(2 ** attempt)
                continue
            if response.status_code in (401, 403):
                raise ScrapeError('HMT access restriction; stopped without bypassing it.')
            if response.status_code == 429:
                raise ScrapeError('HMT rate limit; stopped until a later scheduled run.')
            if response.status_code >= 500 and attempt < self.config['retries']:
                self.sleep(2 ** attempt)
                continue
            if response.status_code != 200:
                raise ScrapeError(f'HMT returned HTTP {response.status_code}.')
            if re.search(r'captcha|cf-chl-|just a moment', response.text, re.I):
                raise ScrapeError('Possible HMT access challenge; manual review required.')
            return response
        raise ScrapeError('HMT request retries exhausted.')

    def scan(self):
        robots = self.request('GET', BASE + '/robots.txt')
        self.robots = RobotFileParser()
        self.robots.parse(robots.text.splitlines())
        landing = self.request('GET', self.config['catalogue_url'])
        soup = BeautifulSoup(landing.text, 'html.parser')
        if not soup.select_one('#load_more_count') or '/filter_products' not in landing.text:
            raise ScrapeError('Men\'s catalogue loader changed; adapter requires review.')
        token = soup.select_one('meta[name="csrf-token"]')
        csrf = token.get('content') if token else None
        if not csrf:
            match = re.search(r'[\'"]_token[\'"]\s*:\s*[\'"]([^\'"]+)', landing.text)
            csrf = match.group(1) if match else None
        headers = {'X-Requested-With': 'XMLHttpRequest', 'Referer': self.config['catalogue_url']}
        if csrf:
            headers['X-CSRF-TOKEN'] = csrf
        previous = set()
        count = 1
        while True:
            data = {'load_more_count': count, 'menu_val': '',
                    'availability_filter': -1, 'gender_filter[]': 1}
            if csrf:
                data['_token'] = csrf
            response = self.request('POST', BASE + '/filter_products', data=data, headers=headers)
            try:
                body = response.json()
                html = body['html']
                if not isinstance(html, str):
                    raise ValueError('Invalid html')
            except (ValueError, KeyError, TypeError):
                raise ScrapeError('Invalid catalogue JSON response.') from None
            products, more = parse_catalogue(html)
            ids = set(products)
            if not previous.issubset(ids) or (previous and ids == previous and more):
                raise ScrapeError('Cumulative pagination changed or stalled; refusing partial scan.')
            log.info('catalogue_page counter=%s products=%s more=%s', count, len(ids), more)
            if not more:
                break
            if count >= self.config['max_pages']:
                raise ScrapeError('Catalogue exceeded maximum load-more window.')
            previous = ids
            count = min(count * 2, self.config['max_pages'])
        if len(products) < self.config['minimum_products']:
            raise ScrapeError('Catalogue below minimum product count.')
        result = []
        for index, product in enumerate(products.values(), 1):
            detail = self.request('GET', product.url)
            result.append(parse_detail(detail.text, product))
            if index % 10 == 0:
                log.info('product_details checked=%s total=%s', index, len(products))
        return result

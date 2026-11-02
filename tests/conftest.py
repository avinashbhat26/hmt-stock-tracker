from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from models import Product
from tracker import load_config


@pytest.fixture
def config():
    c = load_config(Path(__file__).resolve().parents[1] / 'config.yaml')
    c.update(minimum_products=1, minimum_catalogue_ratio=0.5, request_delay=0, retries=1)
    return c


@pytest.fixture
def fixture_text():
    return lambda name: (Path(__file__).parent / 'fixtures' / name).read_text(encoding='utf-8')


@pytest.fixture
def product():
    return Product('1239', 'HMT Kannadiga', 'https://www.hmtwatches.in/product_overview?id=fixture',
                   price='3599', status='out_of_stock', sku='JGGL 01')

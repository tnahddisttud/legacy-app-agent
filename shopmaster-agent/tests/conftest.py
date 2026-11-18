import pytest

from shopmaster import operations as ops
from shopmaster.client import ShopMasterClient
from tests.fake_shop import FakeShop


@pytest.fixture
def shop():
    return FakeShop()


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def client(shop, sleeps):
    """A real ShopMasterClient talking to the fake server. Sleeping is recorded, not performed."""
    c = ShopMasterClient(transport=shop.transport(), sleep=sleeps.append, rate_max=1000)
    ops.set_client(c)
    yield c
    ops.set_client(None)

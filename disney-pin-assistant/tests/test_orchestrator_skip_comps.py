import pytest
from src.config import settings


def test_ebay_keys_have_default():
    assert isinstance(settings.ebay_client_id, str)

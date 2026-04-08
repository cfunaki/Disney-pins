import pytest
from src.config import settings


def test_ebay_keys_empty_by_default():
    assert settings.ebay_client_id == "" or settings.ebay_client_id == "your-ebay-client-id"

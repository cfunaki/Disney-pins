from src.config import Settings


def test_rapidapi_key_defaults_to_empty():
    s = Settings(anthropic_api_key="x", _env_file=None)
    assert s.rapidapi_key == ""


def test_rapidapi_sold_delay_defaults():
    s = Settings(anthropic_api_key="x", _env_file=None)
    assert s.rapidapi_sold_delay_sec == 2.0


def test_collection_data_dir_defaults():
    s = Settings(anthropic_api_key="x", _env_file=None)
    assert str(s.collection_data_dir) == "data"


def test_collection_parse_labels_defaults_true():
    s = Settings(anthropic_api_key="x", _env_file=None)
    assert s.collection_parse_labels is True

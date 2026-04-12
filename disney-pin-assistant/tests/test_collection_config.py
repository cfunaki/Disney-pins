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


def test_comp_lookup_daily_limit_default():
    from src.config import Settings
    s = Settings()
    assert s.comp_lookup_daily_limit == 50


def test_comp_recency_half_life_days_default():
    from src.config import Settings
    s = Settings()
    assert s.comp_recency_half_life_days == 90


def test_comp_min_parsed_fields_default():
    from src.config import Settings
    s = Settings()
    assert s.comp_min_parsed_fields == 2


def test_comp_cache_min_hits_default():
    from src.config import Settings
    s = Settings()
    assert s.comp_cache_min_hits == 5


def test_comp_max_results_per_lookup_default():
    from src.config import Settings
    s = Settings()
    assert s.comp_max_results_per_lookup == 50

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    upload_dir: Path = Path("./uploads")
    database_url: str = "sqlite+aiosqlite:///./pins.db"
    max_concurrent_processing: int = 5
    rapidapi_key: str = ""
    rapidapi_sold_delay_sec: float = 2.0
    collection_data_dir: Path = Path("data")
    collection_parse_labels: bool = True
    comp_lookup_daily_limit: int = 50
    comp_recency_half_life_days: int = 90
    comp_min_parsed_fields: int = 2
    comp_cache_min_hits: int = 5
    comp_max_results_per_lookup: int = 60  # RapidAPI only accepts 60/120/240

    model_config = {"env_file": ".env"}


settings = Settings()

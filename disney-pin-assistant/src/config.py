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

    model_config = {"env_file": ".env"}


settings = Settings()

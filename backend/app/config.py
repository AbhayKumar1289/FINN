from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./finn.db"
    volume_lookback_days: int = 20
    price_history_period: str = "1y"
    cors_origins: str = "http://localhost:3000"
    # Vercel gives every deploy its own URL; this lets all of them call the API
    cors_origin_regex: str = r"https://.*\.vercel\.app"
    # A fresh server (e.g. a free host with no persistent disk) starts from this snapshot
    seed_db_path: str = "./demo/finn_demo.db"
    # NSE archive files (RSS, equity list) are public; identify ourselves honestly.
    nse_user_agent: str = "FINN-research-prototype/0.1"
    http_timeout: float = 30.0
    # Background polling. Off locally (uvicorn --reload would double-run it); on in deployment.
    enable_scheduler: bool = False
    poll_minutes: int = 15
    # LLM routing: cheap model for bulk extraction, strong model for escalation/reasoning
    gemini_api_key: str = ""
    model_cheap: str = "gemini-flash-lite-latest"
    model_strong: str = "gemini-3.5-flash"
    max_enrich_per_cycle: int = 10
    docs_dir: str = "./data/docs"
    # Wikimedia requires a contact (URL or email) in the User-Agent; Wikipedia bio lookups
    # stay off until one is set.
    wiki_contact: str = ""

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

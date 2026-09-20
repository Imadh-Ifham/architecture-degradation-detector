from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Architecture Degradation Detector"
    app_env: str = "development"

    postgres_host: str
    postgres_port: int = 5434
    postgres_db: str
    postgres_user: str
    postgres_password: str

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
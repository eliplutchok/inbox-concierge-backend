from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    google_client_id: str
    google_client_secret: str
    openai_api_key: str
    jwt_secret: str
    encryption_key: str
    frontend_url: str = "http://localhost:5173"

    model_config = {"env_file": ".env"}


settings = Settings()

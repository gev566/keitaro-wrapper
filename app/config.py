"""Настройки приложения. Читаются из переменных окружения и файла .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Адрес трекера без /admin_api/v1, например https://tracker.example.com
    keitaro_url: str = ""
    keitaro_api_key: str = ""
    keitaro_timeout: float = 20.0

    database_url: str = "sqlite:///./adrobot.db"

    # Префикс, который обязателен для названий тестовых кампаний
    campaign_prefix: str = "test_babloyan_"

    # Значения по умолчанию для новой кампании (ищутся в Keitaro по имени)
    default_group_name: str = "FORTESTS"
    default_source_name: str = "FORTESTS"
    default_domain_name: str = ""  # пусто — берём первый активный домен

    # Куда первый поток отправляет посетителей из выбранной страны
    geo_redirect_url: str = "https://google.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()

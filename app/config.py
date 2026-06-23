"""
config.py — Configuración centralizada del sistema
RG S.A. — Sistema de Asistencia Inteligente
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres123@localhost:5433/rg_asistente"
    openai_api_key: str = "sk-demo"
    secret_key: str = "clave_secreta_desarrollo"
    algorithm: str = "HS256"
    access_token_expire_hours: int = 8
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
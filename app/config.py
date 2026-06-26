"""
config.py — Configuración centralizada del sistema
RG S.A. — Sistema de Asistencia Inteligente
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Base de datos
    database_url: str = "postgresql://usuario:password@localhost:5432/rg_asistente"

    # OpenAI
    openai_api_key: str = "sk-..."

    # JWT
    secret_key: str = "clave_secreta_desarrollo"
    algorithm: str = "HS256"
    access_token_expire_hours: int = 8

    # Email SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

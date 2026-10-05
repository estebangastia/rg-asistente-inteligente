"""
config.py — Configuración centralizada del sistema
RG S.A. — Sistema de Asistencia Inteligente
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Base de datos
    database_url: str = "postgresql://usuario:password@localhost:5432/rg_asistente"

    # OpenAI (motor de referencia con pgvector: app/rag_engine_openai.py)
    openai_api_key: str = "sk-..."

    # Modelo de lenguaje del asistente (cualquier API compatible con OpenAI)
    # Sin LLM_API_KEY el asistente funciona con el motor de reglas (modo demo).
    llm_provider: str = "groq"   # groq | openai | gemini | openrouter | otro
    llm_api_key: str = ""
    llm_model: str = ""          # vacío = modelo por defecto del proveedor
    llm_base_url: str = ""       # vacío = URL por defecto del proveedor
    llm_timeout_seconds: int = 20

    # JWT
    secret_key: str = "clave_secreta_desarrollo"
    algorithm: str = "HS256"
    access_token_expire_hours: int = 8

    # Política de acceso (sección Seguridad del TFG)
    max_intentos_fallidos: int = 5
    minutos_bloqueo: int = 15
    dias_vigencia_password: int = 90
    passwords_historial: int = 3

    # Respaldo de la base de datos
    backup_dir: str = "backups"
    backup_retencion_dias: int = 7
    pg_bin_dir: str = ""         # carpeta de pg_dump/pg_restore si no están en el PATH

    # Email por API HTTPS (funcionan donde SMTP está bloqueado, como en Railway)
    resend_api_key: str = ""
    resend_from: str = ""            # vacío = onboarding@resend.dev (sin dominio propio)
    sendgrid_api_key: str = ""
    email_notificaciones: str = ""   # casilla que recibe los avisos internos
    email_altas: bool = False        # enviar la contraseña inicial por email (producción)

    # Email SMTP (alternativa para servidores propios)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()

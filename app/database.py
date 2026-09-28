"""
database.py — Configuracion de conexion a PostgreSQL
RG S.A. — Sistema de Asistencia Inteligente
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

settings = get_settings()

def _normalizar_url(url: str) -> str:
    """
    Fuerza el driver psycopg2 cuando la URL no indica uno.
    SQLAlchemy 2.1 cambió el driver por defecto de 'postgresql://' a psycopg (v3),
    que no está en requirements.txt; sin esta normalización una instalación
    nueva falla al conectarse.
    """
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    return url


engine = create_engine(
    _normalizar_url(settings.database_url),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Generador de sesion para inyeccion de dependencias en FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Inicializa la base de datos:
      - Intenta habilitar pgvector (opcional; necesario solo para
        app/rag_engine_openai.py)
      - Crea todas las tablas definidas en models.py
    """
    from app.models import Base
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        print("pgvector habilitado.")
    except Exception:
        print("pgvector no disponible — el sistema funciona en modo demo sin busqueda vectorial.")

    Base.metadata.create_all(bind=engine)
    _migrar_columnas_seguridad()
    print("Base de datos inicializada correctamente.")


def _migrar_columnas_seguridad():
    """
    Agrega las columnas de seguridad a la tabla usuarios si la base fue
    creada con una versión anterior del prototipo (create_all no modifica
    tablas existentes). Es idempotente: se puede ejecutar siempre.
    """
    sentencias = [
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS intentos_fallidos INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS bloqueado_hasta TIMESTAMP NULL",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS debe_cambiar_password BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS password_actualizada TIMESTAMP DEFAULT now()",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ultimo_acceso TIMESTAMP NULL",
    ]
    with engine.begin() as conn:
        for sql in sentencias:
            conn.execute(text(sql))

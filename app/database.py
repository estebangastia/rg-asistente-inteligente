"""
database.py — Configuracion de conexion a PostgreSQL
RG S.A. — Sistema de Asistencia Inteligente
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
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
    print("Base de datos inicializada correctamente.")

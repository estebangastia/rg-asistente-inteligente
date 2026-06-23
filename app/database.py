"""
database.py — Configuración de conexión a PostgreSQL
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
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.models import Base
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        print("pgvector habilitado.")
    except Exception:
        print("Modo demo sin pgvector.")
    Base.metadata.create_all(bind=engine)
    print("Base de datos inicializada correctamente.")
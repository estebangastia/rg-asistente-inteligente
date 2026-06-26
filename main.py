"""
main.py — Punto de entrada de la aplicación
RG S.A. — Sistema de Asistencia Inteligente

Inicializa FastAPI, registra los routers, arranca el scheduler
de APScheduler y configura los eventos de inicio y cierre.
"""
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routers import (
    auth_router, asistente_router,
    alquileres_router, obras_router, panel_router
)
from app.database import init_db
from jobs.scheduler import crear_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s"
)
logger = logging.getLogger(__name__)

# Instancia global del scheduler
scheduler = crear_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Eventos de ciclo de vida de la aplicación:
      - startup: inicializa la DB y arranca el scheduler
      - shutdown: detiene el scheduler limpiamente
    """
    # Startup
    logger.info("Iniciando Sistema de Asistencia Inteligente — RG S.A.")
    init_db()
    scheduler.start()
    logger.info(f"Scheduler iniciado con {len(scheduler.get_jobs())} jobs activos.")
    for job in scheduler.get_jobs():
        logger.info(f"  → {job.name} | próxima ejecución: {job.next_run_time}")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler detenido. Sistema cerrado.")


app = FastAPI(
    title="Sistema de Asistencia Inteligente — RG S.A.",
    description=(
        "API REST del sistema de asistencia inteligente para la gestión operativa "
        "de RG S.A. Implementa un motor RAG (Lewis et al., 2020) sobre PostgreSQL "
        "con búsqueda semántica pgvector y automatización con APScheduler."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — en producción restringir a los orígenes del frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro de routers
app.include_router(auth_router)
app.include_router(asistente_router)
app.include_router(alquileres_router)
app.include_router(obras_router)
app.include_router(panel_router)


@app.get("/api/health", tags=["Health"])
def health_check():
    """Endpoint de verificación de estado del sistema."""
    return {
        "sistema": "RG S.A. — Asistente Inteligente",
        "estado": "operativo",
        "version": "1.0.0",
        "jobs_activos": [job.name for job in scheduler.get_jobs()],
    }


# ── Interfaz web (sirve la SPA en la raíz) ────────────────────────────────────
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

if os.path.isdir(_STATIC_DIR):
    @app.get("/", include_in_schema=False)
    def serve_index():
        """Sirve la interfaz web del sistema."""
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
else:
    @app.get("/", tags=["Health"])
    def root():
        return {"sistema": "RG S.A.", "docs": "/docs"}

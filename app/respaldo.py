"""
respaldo.py — Respaldo y prueba de restauración de la base de datos
RG S.A. — Sistema de Asistencia Inteligente

Implementa la política de respaldo de la sección Seguridad del TFG:

  - Copia diaria automática de PostgreSQL (job de APScheduler a las 00:00)
    con pg_dump en formato comprimido, retención de 7 días y borrado
    automático de las copias más antiguas.
  - Prueba de restauración: restaura la última copia en una base de datos
    temporal aislada y compara la cantidad de registros de las tablas
    clave contra la base en producción. Luego elimina la base temporal.

Las copias semanal (Amazon S3, cifrada AES-256) y mensual (servidor central)
se generan a partir de estos mismos archivos .dump.

Uso manual:
    python backup.py              → genera una copia ahora
    python backup.py --verificar  → prueba de restauración de la última copia
    python backup.py --listar     → lista las copias disponibles
"""
from __future__ import annotations
import glob
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLAS_CLAVE = ["usuarios", "contratos", "inquilinos", "obras", "etapas_obra", "oportunidades"]
DB_PRUEBA = "rg_asistente_prueba_restauracion"


class ErrorRespaldo(Exception):
    pass


def _dir_backups() -> str:
    ruta = settings.backup_dir
    if not os.path.isabs(ruta):
        ruta = os.path.join(BASE_DIR, ruta)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _buscar_binario(nombre: str) -> str:
    """Busca pg_dump/pg_restore en PG_BIN_DIR, en el PATH o en la instalación estándar de Windows."""
    exe = nombre + (".exe" if os.name == "nt" else "")
    if settings.pg_bin_dir:
        candidato = os.path.join(settings.pg_bin_dir, exe)
        if os.path.isfile(candidato):
            return candidato
    en_path = shutil.which(nombre)
    if en_path:
        return en_path
    if os.name == "nt":
        encontrados = glob.glob(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                             "PostgreSQL", "*", "bin", exe))
        if encontrados:
            # la versión más nueva primero (pg_dump debe ser >= a la del servidor)
            encontrados.sort(key=lambda p: int(os.path.basename(os.path.dirname(os.path.dirname(p)))
                                               if os.path.basename(os.path.dirname(os.path.dirname(p))).isdigit() else 0),
                             reverse=True)
            return encontrados[0]
    raise ErrorRespaldo(
        f"No se encontró {nombre}. Agregue la carpeta 'bin' de PostgreSQL al PATH "
        f"o configure PG_BIN_DIR en el archivo .env."
    )


def _conexion():
    url = make_url(settings.database_url)
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    args = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres"]
    return url, args, env


def listar_backups() -> list[dict]:
    archivos = sorted(glob.glob(os.path.join(_dir_backups(), "rg_asistente_*.dump")), reverse=True)
    return [
        {
            "archivo": os.path.basename(a),
            "fecha": datetime.fromtimestamp(os.path.getmtime(a)).strftime("%d/%m/%Y %H:%M"),
            "tamano_kb": round(os.path.getsize(a) / 1024, 1),
        }
        for a in archivos
    ]


def _aplicar_retencion() -> int:
    limite = datetime.now() - timedelta(days=settings.backup_retencion_dias)
    borrados = 0
    for a in glob.glob(os.path.join(_dir_backups(), "rg_asistente_*.dump")):
        if datetime.fromtimestamp(os.path.getmtime(a)) < limite:
            os.remove(a)
            borrados += 1
    return borrados


def crear_backup() -> dict:
    """Genera una copia completa de la base con pg_dump (formato custom, comprimido)."""
    pg_dump = _buscar_binario("pg_dump")
    url, args, env = _conexion()
    nombre = f"rg_asistente_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dump"
    destino = os.path.join(_dir_backups(), nombre)

    r = subprocess.run([pg_dump, *args, "-F", "c", "-f", destino, url.database],
                       env=env, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        if os.path.exists(destino):
            os.remove(destino)
        raise ErrorRespaldo(f"pg_dump falló: {r.stderr.strip()[:400]}")

    borrados = _aplicar_retencion()
    info = {"archivo": nombre, "tamano_kb": round(os.path.getsize(destino) / 1024, 1),
            "copias_eliminadas_por_retencion": borrados}
    logger.info(f"Backup generado: {info}")
    return info


def _contar(engine) -> dict:
    with engine.connect() as conn:
        return {t: conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() for t in TABLAS_CLAVE}


def verificar_restauracion(archivo: str | None = None) -> dict:
    """
    Restaura la última copia (o la indicada) en una base temporal aislada y
    compara la cantidad de registros de las tablas clave contra producción.
    """
    backups = listar_backups()
    if not backups:
        raise ErrorRespaldo("No hay copias de seguridad para verificar. Ejecute primero: python backup.py")
    archivo = archivo or backups[0]["archivo"]
    ruta = os.path.join(_dir_backups(), os.path.basename(archivo))
    if not os.path.isfile(ruta):
        raise ErrorRespaldo(f"No existe la copia {archivo}.")

    pg_restore = _buscar_binario("pg_restore")
    url, args, env = _conexion()
    admin = create_engine(url.set(drivername="postgresql+psycopg2", database="postgres"),
                          isolation_level="AUTOCOMMIT")
    prod = create_engine(url.set(drivername="postgresql+psycopg2"))
    prueba = create_engine(url.set(drivername="postgresql+psycopg2", database=DB_PRUEBA))

    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_PRUEBA}"'))
            conn.execute(text(f'CREATE DATABASE "{DB_PRUEBA}"'))

        r = subprocess.run([pg_restore, *args, "--no-owner", "-d", DB_PRUEBA, ruta],
                           env=env, capture_output=True, text=True, timeout=300)
        # pg_restore puede terminar con advertencias no críticas (por ejemplo, si la
        # extensión pgvector no está instalada); la validez se comprueba contando registros.
        conteo_prod = _contar(prod)
        try:
            conteo_backup = _contar(prueba)
        except Exception as e:
            raise ErrorRespaldo(f"La copia no se pudo restaurar: {r.stderr.strip()[:400] or e}")
        detalle = {t: {"produccion": conteo_prod[t], "backup": conteo_backup[t]} for t in TABLAS_CLAVE}
        ok = all(v["produccion"] == v["backup"] for v in detalle.values())
        return {"archivo": archivo, "resultado": "OK" if ok else "DIFERENCIAS", "tablas": detalle,
                "nota": "Si hay diferencias, pueden deberse a datos cargados después de la copia."}
    finally:
        prueba.dispose()
        prod.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_PRUEBA}"'))
        admin.dispose()


def job_backup_diario() -> None:
    """Job de APScheduler: copia diaria a las 00:00 con registro en la auditoría."""
    from app.database import SessionLocal
    from app.seguridad import auditar
    db = SessionLocal()
    try:
        info = crear_backup()
        auditar(db, "backup_ok", "sistema", f"{info['archivo']} ({info['tamano_kb']} KB)")
    except Exception as e:
        logger.error(f"Error en el backup diario: {e}")
        auditar(db, "backup_error", "sistema", str(e)[:400])
    finally:
        db.close()

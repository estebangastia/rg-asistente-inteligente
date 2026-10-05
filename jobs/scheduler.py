"""
scheduler.py — Jobs de automatización con APScheduler
RG S.A. — Sistema de Asistencia Inteligente

Las tareas son funciones Python que consultan PostgreSQL, actualizan el
estado de los registros y envían avisos por email (app/notificador.py).
Cada aviso queda registrado en la tabla NOTIFICACION.

Jobs definidos (también se pueden ejecutar a mano desde la interfaz,
sección Automatización, o por POST /automatizacion/ejecutar/{job}):
  - verificar_vencimientos(): ejecuta diariamente a las 08:00
  - verificar_mora():         ejecuta diariamente a las 08:30
  - verificar_desvios_obra(): ejecuta diariamente a las 09:00
  - job_backup_diario():      ejecuta diariamente a las 00:00 (app/respaldo.py)
"""
import logging
from datetime import date, timedelta
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Contrato, Inquilino, Obra, EtapaObra, Notificacion
from app.config import get_settings
from app.notificador import enviar_email, destinatario_avisos
from app.seguridad import ahora

# Zona horaria explícita: evita depender de la configuración del sistema
# operativo (en Windows requiere el paquete tzdata, incluido en requirements).
TZ = "America/Argentina/Buenos_Aires"

settings = get_settings()
logger = logging.getLogger(__name__)


# ── AVISO + REGISTRO ──────────────────────────────────────────────────────────

def _avisar(db: Session, tipo: str, asunto: str, cuerpo: str,
            id_contrato: Optional[int] = None) -> str:
    """Envía el aviso y lo registra en la tabla NOTIFICACION. Devuelve el estado."""
    destinatario = destinatario_avisos()
    estado, detalle = enviar_email(destinatario, asunto, cuerpo)
    db.add(Notificacion(
        id_contrato=id_contrato, tipo=tipo, asunto=asunto[:200], fecha_envio=ahora(),
        destinatario=destinatario or "-", estado_envio=estado,
    ))
    db.commit()
    return estado


def _resumen(nombre: str, detectados: int, estados: list[str]) -> dict:
    r = {
        "job": nombre, "detectados": detectados,
        "enviados": estados.count("enviado"), "fallidos": estados.count("fallido"),
        "simulados": estados.count("simulado"),
    }
    logger.info(f"{nombre}: {r}")
    return r


# ── JOB 1: VERIFICACIÓN DE VENCIMIENTOS ───────────────────────────────────────

def verificar_vencimientos() -> dict:
    """
    Job diario — 08:00 hs.
    Busca contratos que vencen en los próximos 30 días y avisa a administración.
    A 7 días o menos el aviso es urgente (HU-004).
    """
    db: Session = SessionLocal()
    estados: list[str] = []
    try:
        hoy = date.today()
        filas = (
            db.query(Contrato, Inquilino)
            .join(Inquilino)
            .filter(
                Contrato.fecha_vencimiento >= hoy,
                Contrato.fecha_vencimiento <= hoy + timedelta(days=30),
                Contrato.estado != "vencido",
            )
            .all()
        )
        for contrato, inquilino in filas:
            dias = (contrato.fecha_vencimiento - hoy).days
            urgente = dias <= 7
            asunto = (f"URGENTE — El contrato de {inquilino.apellido} vence en {dias} días" if urgente
                      else f"Aviso — El contrato de {inquilino.apellido} vence en {dias} días")
            cuerpo = f"""
            <h3>Aviso de vencimiento de contrato</h3>
            <p><strong>Inquilino:</strong> {inquilino.apellido}, {inquilino.nombre}</p>
            <p><strong>Vencimiento:</strong> {contrato.fecha_vencimiento.strftime('%d/%m/%Y')} ({dias} días)</p>
            <p><strong>Monto mensual:</strong> ${contrato.monto_mensual:,.0f}</p>
            <p>Gestionar la renovación o el cierre del contrato.</p>
            <p style="color:#888">Sistema de Asistencia Inteligente — RG S.A.</p>"""
            estados.append(_avisar(db, "vencimiento_urgente" if urgente else "vencimiento",
                                   asunto, cuerpo, contrato.id_contrato))
            # Solo pasa a "por vencer" si estaba al día: no pisa una mora
            if contrato.estado == "al_dia":
                contrato.estado = "por_vencer"
                db.commit()
        return _resumen("Vencimientos", len(filas), estados)
    except Exception as e:
        logger.error(f"Error en verificar_vencimientos: {e}")
        db.rollback()
        return {"job": "Vencimientos", "error": str(e)}
    finally:
        db.close()


# ── JOB 2: VERIFICACIÓN DE MORA ───────────────────────────────────────────────

def verificar_mora() -> dict:
    """
    Job diario — 08:30 hs.
    Un contrato vigente sin pago registrado en el período actual, pasados
    5 días de su vencimiento mensual, pasa a "en mora" y se avisa (HU-005).
    """
    db: Session = SessionLocal()
    estados: list[str] = []
    detectados = 0
    try:
        hoy = date.today()
        periodo_actual = hoy.strftime("%Y-%m")
        limite_mora = hoy - timedelta(days=5)
        filas = (
            db.query(Contrato, Inquilino)
            .join(Inquilino)
            .filter(
                Contrato.estado.in_(["al_dia", "por_vencer"]),
                Contrato.fecha_inicio <= hoy,
                Contrato.fecha_vencimiento >= hoy,
            )
            .all()
        )
        for contrato, inquilino in filas:
            pago = next((p for p in contrato.pagos if p.periodo == periodo_actual), None)
            vencimiento_mes = hoy.replace(day=min(contrato.fecha_inicio.day, 28))
            if pago is not None or vencimiento_mes > limite_mora:
                continue
            detectados += 1
            contrato.estado = "en_mora"
            db.commit()
            dias = (hoy - vencimiento_mes).days
            asunto = f"Mora detectada — {inquilino.apellido}, {inquilino.nombre} ({dias} días)"
            cuerpo = f"""
            <h3>Alerta de mora</h3>
            <p><strong>Inquilino:</strong> {inquilino.apellido}, {inquilino.nombre} — DNI {inquilino.dni}</p>
            <p><strong>Teléfono:</strong> {inquilino.telefono} · <strong>Email:</strong> {inquilino.email}</p>
            <p><strong>Período sin pago:</strong> {periodo_actual} (vencido hace {dias} días)</p>
            <p><strong>Monto adeudado:</strong> ${contrato.monto_mensual:,.0f}</p>
            <p style="color:#888">Sistema de Asistencia Inteligente — RG S.A.</p>"""
            estados.append(_avisar(db, "mora", asunto, cuerpo, contrato.id_contrato))
        return _resumen("Mora", detectados, estados)
    except Exception as e:
        logger.error(f"Error en verificar_mora: {e}")
        db.rollback()
        return {"job": "Mora", "error": str(e)}
    finally:
        db.close()


# ── JOB 3: VERIFICACIÓN DE DESVÍOS DE OBRA ───────────────────────────────────

def verificar_desvios_obra() -> dict:
    """
    Job diario — 09:00 hs.
    Detecta etapas cuya fecha planificada ya pasó sin llegar al 100%,
    marca la obra como demorada y avisa a gerencia (HU-008).
    """
    db: Session = SessionLocal()
    estados: list[str] = []
    try:
        hoy = date.today()
        filas = (
            db.query(EtapaObra, Obra)
            .join(Obra)
            .filter(
                EtapaObra.fecha_fin_plan < hoy,
                EtapaObra.pct_avance < 100,
                Obra.estado.in_(["en_curso", "demorada"]),
            )
            .all()
        )
        for etapa, obra in filas:
            dias = (hoy - etapa.fecha_fin_plan).days
            if obra.estado != "demorada":
                obra.estado = "demorada"
                db.commit()
            asunto = f"Desvío de cronograma — {obra.nombre}: {etapa.nombre_etapa} ({dias} días)"
            cuerpo = f"""
            <h3>Alerta de desvío de cronograma</h3>
            <p><strong>Obra:</strong> {obra.nombre} ({obra.direccion})</p>
            <p><strong>Etapa demorada:</strong> {etapa.nombre_etapa}</p>
            <p><strong>Fecha planificada:</strong> {etapa.fecha_fin_plan.strftime('%d/%m/%Y')} — {dias} días de desvío</p>
            <p><strong>Avance actual:</strong> {float(etapa.pct_avance):.0f}%</p>
            <p style="color:#888">Sistema de Asistencia Inteligente — RG S.A.</p>"""
            estados.append(_avisar(db, "desvio_obra", asunto, cuerpo))
        return _resumen("Desvíos de obra", len(filas), estados)
    except Exception as e:
        logger.error(f"Error en verificar_desvios_obra: {e}")
        db.rollback()
        return {"job": "Desvíos de obra", "error": str(e)}
    finally:
        db.close()


JOBS_MANUALES = {
    "vencimientos": verificar_vencimientos,
    "mora": verificar_mora,
    "desvios": verificar_desvios_obra,
}


# ── CONFIGURACIÓN DEL SCHEDULER ───────────────────────────────────────────────

def crear_scheduler() -> BackgroundScheduler:
    """
    Crea y configura el scheduler de APScheduler con los jobs diarios
    (vencimientos, mora, desvíos de obra y copia de seguridad).
    Se inicia junto con la aplicación FastAPI en el evento startup.
    """
    scheduler = BackgroundScheduler(timezone=TZ)

    scheduler.add_job(
        verificar_vencimientos,
        trigger=CronTrigger(hour=8, minute=0, timezone=TZ),
        id="verificar_vencimientos",
        name="Verificación diaria de vencimientos de contratos",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        verificar_mora,
        trigger=CronTrigger(hour=8, minute=30, timezone=TZ),
        id="verificar_mora",
        name="Verificación diaria de mora en alquileres",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        verificar_desvios_obra,
        trigger=CronTrigger(hour=9, minute=0, timezone=TZ),
        id="verificar_desvios_obra",
        name="Verificación diaria de desvíos de cronograma de obra",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    from app.respaldo import job_backup_diario
    scheduler.add_job(
        job_backup_diario,
        trigger=CronTrigger(hour=0, minute=0, timezone=TZ),
        id="backup_diario",
        name="Copia de seguridad diaria de PostgreSQL",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    return scheduler

"""
scheduler.py — Jobs de automatización con APScheduler
RG S.A. — Sistema de Asistencia Inteligente

Implementa los procesos de automatización sin dependencias externas.
Todas las tareas son funciones Python puras que ejecutan queries
directamente sobre PostgreSQL y envían notificaciones por SMTP.

Jobs definidos:
  - verificar_vencimientos(): ejecuta diariamente a las 08:00
  - verificar_mora():         ejecuta diariamente a las 08:30
  - verificar_desvios_obra(): ejecuta diariamente a las 09:00
  - job_backup_diario():      ejecuta diariamente a las 00:00 (app/respaldo.py)
"""
import smtplib
import logging
from datetime import date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Contrato, Inquilino, Obra, EtapaObra, Notificacion
from app.config import get_settings

# Zona horaria explícita: evita depender de la configuración del sistema
# operativo (en Windows requiere el paquete tzdata, incluido en requirements).
TZ = "America/Argentina/Buenos_Aires"

settings = get_settings()
logger = logging.getLogger(__name__)


# ── ENVÍO DE EMAIL ─────────────────────────────────────────────────────────────

def _enviar_email(destinatario: str, asunto: str, cuerpo: str) -> bool:
    """
    Envía un email por SMTP.
    Registra el resultado en el log de la aplicación.
    """
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = settings.email_from
        msg["To"] = destinatario
        msg.attach(MIMEText(cuerpo, "html"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.email_from, destinatario, msg.as_string())

        logger.info(f"Email enviado a {destinatario}: {asunto}")
        return True

    except Exception as e:
        logger.error(f"Error al enviar email a {destinatario}: {e}")
        return False


def _registrar_notificacion(
    db: Session,
    id_contrato: int,
    tipo: str,
    destinatario: str,
    estado: str
) -> None:
    """Persiste cada notificación enviada en la tabla NOTIFICACION de PostgreSQL."""
    notif = Notificacion(
        id_contrato=id_contrato,
        tipo=tipo,
        destinatario=destinatario,
        estado_envio=estado,
    )
    db.add(notif)
    db.commit()


# ── JOB 1: VERIFICACIÓN DE VENCIMIENTOS ───────────────────────────────────────

def verificar_vencimientos() -> None:
    """
    Job diario — 08:00 hs.
    Consulta PostgreSQL buscando contratos con fecha_vencimiento
    entre hoy y hoy+30 días y envía notificación al administrativo.
    """
    db: Session = SessionLocal()
    try:
        hoy = date.today()
        limite_30 = hoy + timedelta(days=30)
        limite_7 = hoy + timedelta(days=7)

        contratos_por_vencer = (
            db.query(Contrato, Inquilino)
            .join(Inquilino)
            .filter(
                Contrato.fecha_vencimiento >= hoy,
                Contrato.fecha_vencimiento <= limite_30,
                Contrato.estado != "vencido"
            )
            .all()
        )

        for contrato, inquilino in contratos_por_vencer:
            dias_restantes = (contrato.fecha_vencimiento - hoy).days
            urgente = dias_restantes <= 7
            tipo = "vencimiento_urgente" if urgente else "vencimiento"

            asunto = (
                f"⚠️ URGENTE — Contrato por vencer en {dias_restantes} días"
                if urgente
                else f"Aviso — Contrato de {inquilino.apellido} vence en {dias_restantes} días"
            )

            cuerpo = f"""
            <h3>Aviso de vencimiento de contrato</h3>
            <p><strong>Inquilino:</strong> {inquilino.apellido}, {inquilino.nombre}</p>
            <p><strong>Vencimiento:</strong> {contrato.fecha_vencimiento.strftime('%d/%m/%Y')}</p>
            <p><strong>Días restantes:</strong> {dias_restantes}</p>
            <p><strong>Monto mensual:</strong> ${contrato.monto_mensual:,.2f}</p>
            <p>Por favor, gestionar la renovación o cierre del contrato.</p>
            """

            exito = _enviar_email(
                destinatario=settings.smtp_user,  # email del área administración
                asunto=asunto,
                cuerpo=cuerpo
            )

            _registrar_notificacion(
                db, contrato.id_contrato, tipo,
                settings.smtp_user,
                "enviado" if exito else "fallido"
            )

            # Actualizar estado del contrato
            contrato.estado = "por_vencer"
            db.commit()

        logger.info(f"verificar_vencimientos: {len(contratos_por_vencer)} contratos procesados.")

    except Exception as e:
        logger.error(f"Error en verificar_vencimientos: {e}")
        db.rollback()
    finally:
        db.close()


# ── JOB 2: VERIFICACIÓN DE MORA ───────────────────────────────────────────────

def verificar_mora() -> None:
    """
    Job diario — 08:30 hs.
    Detecta contratos en mora verificando si hay pagos registrados
    para el período actual. Si el contrato venció hace más de 5 días
    sin pago registrado, se marca como en_mora y notifica.
    """
    db: Session = SessionLocal()
    try:
        hoy = date.today()
        periodo_actual = hoy.strftime("%Y-%m")
        limite_mora = hoy - timedelta(days=5)

        # Contratos cuya fecha de vencimiento mensual superó los 5 días
        # sin tener pago registrado en el período actual
        contratos_activos = (
            db.query(Contrato, Inquilino)
            .join(Inquilino)
            .filter(
                Contrato.estado.in_(["al_dia", "por_vencer"]),
                Contrato.fecha_inicio <= hoy,
                Contrato.fecha_vencimiento >= hoy
            )
            .all()
        )

        mora_detectada = 0
        for contrato, inquilino in contratos_activos:
            # Verificar si tiene pago registrado para este período
            pago_periodo = next(
                (p for p in contrato.pagos if p.periodo == periodo_actual),
                None
            )

            # Día de vencimiento mensual del alquiler
            dia_venc_mensual = contrato.fecha_inicio.day
            fecha_venc_este_mes = hoy.replace(day=min(dia_venc_mensual, 28))

            if pago_periodo is None and fecha_venc_este_mes <= limite_mora:
                # Mora confirmada
                contrato.estado = "en_mora"
                db.commit()
                mora_detectada += 1

                # Construir cuerpo del email
                reincidente = sum(
                    1 for p in contrato.pagos
                    if p.periodo and p.periodo < periodo_actual
                ) < (hoy.month - contrato.fecha_inicio.month)

                asunto = f"🔴 Mora detectada — {inquilino.apellido}, {inquilino.nombre}"
                cuerpo = f"""
                <h3>Alerta de mora</h3>
                <p><strong>Inquilino:</strong> {inquilino.apellido}, {inquilino.nombre}</p>
                <p><strong>DNI:</strong> {inquilino.dni}</p>
                <p><strong>Teléfono:</strong> {inquilino.telefono}</p>
                <p><strong>Email:</strong> {inquilino.email}</p>
                <p><strong>Período sin pago:</strong> {periodo_actual}</p>
                <p><strong>Monto adeudado:</strong> ${contrato.monto_mensual:,.2f}</p>
                {"<p><strong>⚠️ Inquilino reincidente en mora.</strong></p>" if reincidente else ""}
                """

                exito = _enviar_email(
                    destinatario=settings.smtp_user,
                    asunto=asunto,
                    cuerpo=cuerpo
                )

                _registrar_notificacion(
                    db, contrato.id_contrato, "mora",
                    settings.smtp_user,
                    "enviado" if exito else "fallido"
                )

        logger.info(f"verificar_mora: {mora_detectada} situaciones de mora detectadas.")

    except Exception as e:
        logger.error(f"Error en verificar_mora: {e}")
        db.rollback()
    finally:
        db.close()


# ── JOB 3: VERIFICACIÓN DE DESVÍOS DE OBRA ───────────────────────────────────

def verificar_desvios_obra() -> None:
    """
    Job diario — 09:00 hs.
    Detecta etapas de obra cuya fecha_fin_plan ya pasó
    sin alcanzar el 100% de avance y notifica a gerencia.
    """
    db: Session = SessionLocal()
    try:
        hoy = date.today()

        etapas_demoradas = (
            db.query(EtapaObra, Obra)
            .join(Obra)
            .filter(
                EtapaObra.fecha_fin_plan < hoy,
                EtapaObra.pct_avance < 100,
                Obra.estado.in_(["en_curso", "demorada"])
            )
            .all()
        )

        for etapa, obra in etapas_demoradas:
            dias_desvio = (hoy - etapa.fecha_fin_plan).days

            # Actualizar estado de la obra a demorada
            if obra.estado != "demorada":
                obra.estado = "demorada"
                db.commit()

            asunto = f"⚠️ Desvío de cronograma — {obra.nombre}"
            cuerpo = f"""
            <h3>Alerta de desvío de cronograma</h3>
            <p><strong>Obra:</strong> {obra.nombre}</p>
            <p><strong>Dirección:</strong> {obra.direccion}</p>
            <p><strong>Etapa demorada:</strong> {etapa.nombre_etapa}</p>
            <p><strong>Fecha plan:</strong> {etapa.fecha_fin_plan.strftime('%d/%m/%Y')}</p>
            <p><strong>Avance actual:</strong> {etapa.pct_avance}%</p>
            <p><strong>Días de desvío:</strong> {dias_desvio} días</p>
            """

            _enviar_email(
                destinatario=settings.smtp_user,
                asunto=asunto,
                cuerpo=cuerpo
            )

        logger.info(f"verificar_desvios_obra: {len(etapas_demoradas)} etapas demoradas detectadas.")

    except Exception as e:
        logger.error(f"Error en verificar_desvios_obra: {e}")
        db.rollback()
    finally:
        db.close()


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

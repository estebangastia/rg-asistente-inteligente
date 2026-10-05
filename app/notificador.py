"""
notificador.py — Envío de emails del sistema
RG S.A. — Sistema de Asistencia Inteligente

Elige el canal de envío según la configuración:

  1. Resend por API HTTPS (RESEND_API_KEY), el servicio que recomienda
     Railway. Sin dominio propio envía desde onboarding@resend.dev, solo a
     la casilla de la cuenta: alcanza para los avisos internos de la demo.
  2. SendGrid por API HTTPS (SENDGRID_API_KEY), el servicio previsto en el
     análisis de costos del TFG.
     Ambos funcionan donde el puerto SMTP está bloqueado (Railway lo bloquea
     en sus planes Free, Trial y Hobby).
  3. SMTP clásico (SMTP_USER + SMTP_PASSWORD), para servidores propios.
  4. Sin canal configurado: el aviso se registra como "simulado" y no se
     envía. La demo funciona igual y no llena el log de errores.

Devuelve siempre (estado, detalle): estado = enviado | fallido | simulado.
"""
from __future__ import annotations
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
RESEND_URL = "https://api.resend.com/emails"
REMITENTE_RESEND_DEMO = "onboarding@resend.dev"


def canal_configurado() -> str:
    """Nombre del canal de envío activo (se muestra en /api/health y en la interfaz)."""
    if settings.resend_api_key.strip():
        return "Resend (API HTTPS)"
    if settings.sendgrid_api_key.strip():
        return "SendGrid (API HTTPS)"
    if settings.smtp_user.strip() and settings.smtp_password.strip():
        return "SMTP"
    return "sin configurar (avisos simulados)"


def destinatario_avisos() -> str:
    """Casilla que recibe los avisos internos (administración / gerencia)."""
    return (settings.email_notificaciones or settings.email_from or settings.smtp_user).strip()


def _enviar_sendgrid(destinatario: str, asunto: str, html: str) -> tuple[str, str]:
    payload = {
        "personalizations": [{"to": [{"email": destinatario}]}],
        "from": {"email": settings.email_from, "name": "RG S.A. — Asistente"},
        "subject": asunto,
        "content": [{"type": "text/html", "value": html}],
    }
    r = httpx.post(
        SENDGRID_URL, json=payload, timeout=15,
        headers={"Authorization": f"Bearer {settings.sendgrid_api_key.strip()}"},
    )
    if r.status_code in (200, 202):
        return "enviado", "SendGrid aceptó el envío"
    return "fallido", f"SendGrid respondió {r.status_code}: {r.text[:200]}"


def _enviar_resend(destinatario: str, asunto: str, html: str) -> tuple[str, str]:
    # Sin dominio verificado en Resend, el remitente tiene que ser el de prueba.
    # Con dominio propio verificado se configura RESEND_FROM (ej. avisos@empresa.com).
    remitente = settings.resend_from.strip() or REMITENTE_RESEND_DEMO
    r = httpx.post(
        RESEND_URL, timeout=15,
        headers={"Authorization": f"Bearer {settings.resend_api_key.strip()}"},
        json={"from": f"RG S.A. Asistente <{remitente}>", "to": [destinatario],
              "subject": asunto, "html": html},
    )
    if r.status_code in (200, 201, 202):
        return "enviado", "Resend aceptó el envío"
    return "fallido", f"Resend respondió {r.status_code}: {r.text[:200]}"


def _enviar_smtp(destinatario: str, asunto: str, html: str) -> tuple[str, str]:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = settings.email_from
    msg["To"] = destinatario
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.email_from, destinatario, msg.as_string())
    return "enviado", "SMTP aceptó el envío"


def enviar_email(destinatario: str, asunto: str, html: str) -> tuple[str, str]:
    """Envía un email por el canal configurado. Nunca lanza excepciones."""
    if not destinatario:
        logger.info(f"Aviso simulado (sin destinatario configurado): {asunto}")
        return "simulado", "No hay casilla de destino configurada (EMAIL_NOTIFICACIONES)"
    try:
        if settings.resend_api_key.strip():
            estado, detalle = _enviar_resend(destinatario, asunto, html)
        elif settings.sendgrid_api_key.strip():
            estado, detalle = _enviar_sendgrid(destinatario, asunto, html)
        elif settings.smtp_user.strip() and settings.smtp_password.strip():
            estado, detalle = _enviar_smtp(destinatario, asunto, html)
        else:
            logger.info(f"Aviso simulado (sin canal de email configurado): {asunto}")
            return "simulado", "Sin canal de email configurado"
    except Exception as e:  # red caída, credenciales inválidas, timeout
        estado, detalle = "fallido", f"{type(e).__name__}: {e}"

    if estado == "enviado":
        logger.info(f"Email enviado a {destinatario}: {asunto}")
    else:
        logger.error(f"No se pudo enviar el email a {destinatario}: {detalle}")
    return estado, detalle

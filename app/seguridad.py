"""
seguridad.py — Controles de seguridad del sistema
RG S.A. — Sistema de Asistencia Inteligente

Implementa las políticas descriptas en la sección Seguridad del TFG,
alineadas con ISO/IEC 27001 (International Organization for Standardization, 2022):

  - Política de complejidad de contraseñas (8+ caracteres, mayúscula,
    minúscula, dígito y carácter especial)
  - Bloqueo temporal de la cuenta tras 5 intentos fallidos consecutivos (15 min)
  - Vencimiento de la contraseña a los 90 días
  - Prohibición de reutilizar las últimas 3 contraseñas
  - Contraseña inicial aleatoria con cambio obligatorio en el primer ingreso
  - Registro de auditoría de los eventos de seguridad
"""
from __future__ import annotations
import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Usuario, HistorialPassword, LogAuditoria

settings = get_settings()

CARACTERES_ESPECIALES = "!@#$%^&*()-_=+[]{};:,.?/"


def ahora() -> datetime:
    """Fecha y hora actual en UTC (sin zona, como se guarda en la base)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── POLÍTICA DE CONTRASEÑAS ───────────────────────────────────────────────────

def validar_politica_password(password: str) -> list[str]:
    """
    Devuelve la lista de requisitos que la contraseña NO cumple.
    Lista vacía = contraseña válida.
    """
    errores = []
    if len(password) < 8:
        errores.append("tener al menos 8 caracteres")
    if not re.search(r"[A-Z]", password):
        errores.append("incluir al menos una letra mayúscula")
    if not re.search(r"[a-z]", password):
        errores.append("incluir al menos una letra minúscula")
    if not re.search(r"\d", password):
        errores.append("incluir al menos un número")
    if not re.search(r"[^A-Za-z0-9]", password):
        errores.append("incluir al menos un carácter especial")
    return errores


def generar_password_inicial(longitud: int = 12) -> str:
    """Genera una contraseña aleatoria criptográficamente segura que cumple la política."""
    # Se excluyen caracteres que se confunden al dictarlos o leerlos (0/O, 1/l/I)
    letras = "".join(c for c in string.ascii_letters if c not in "OIl")
    alfabeto = letras + "23456789" + "!@#$%&*?-_"
    while True:
        pwd = "".join(secrets.choice(alfabeto) for _ in range(longitud))
        if not validar_politica_password(pwd):
            return pwd


# ── BLOQUEO POR INTENTOS FALLIDOS ─────────────────────────────────────────────

def esta_bloqueado(usuario: Usuario) -> Optional[int]:
    """Si la cuenta está bloqueada, devuelve los minutos restantes; si no, None."""
    if usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora():
        restante = usuario.bloqueado_hasta - ahora()
        return max(1, int(restante.total_seconds() // 60) + 1)
    return None


def registrar_intento_fallido(db: Session, usuario: Usuario) -> bool:
    """
    Suma un intento fallido. Al llegar al máximo bloquea la cuenta.
    Devuelve True si la cuenta quedó bloqueada con este intento.
    """
    usuario.intentos_fallidos = (usuario.intentos_fallidos or 0) + 1
    bloqueada = False
    if usuario.intentos_fallidos >= settings.max_intentos_fallidos:
        usuario.bloqueado_hasta = ahora() + timedelta(minutes=settings.minutos_bloqueo)
        usuario.intentos_fallidos = 0
        bloqueada = True
    db.commit()
    return bloqueada


def registrar_acceso_exitoso(db: Session, usuario: Usuario) -> None:
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    usuario.ultimo_acceso = ahora()
    db.commit()


# ── VENCIMIENTO E HISTORIAL ───────────────────────────────────────────────────

def password_vencida(usuario: Usuario) -> bool:
    if not usuario.password_actualizada:
        return False
    return ahora() - usuario.password_actualizada > timedelta(days=settings.dias_vigencia_password)


def requiere_cambio_password(usuario: Usuario) -> bool:
    return bool(usuario.debe_cambiar_password) or password_vencida(usuario)


def password_reutilizada(db: Session, usuario: Usuario, nueva: str, verificar) -> bool:
    """True si `nueva` coincide con la contraseña actual o con alguna de las últimas N."""
    if verificar(nueva, usuario.password_hash):
        return True
    anteriores = (
        db.query(HistorialPassword)
        .filter(HistorialPassword.id_usuario == usuario.id_usuario)
        .order_by(HistorialPassword.fecha.desc(), HistorialPassword.id.desc())
        .limit(settings.passwords_historial)
        .all()
    )
    return any(verificar(nueva, h.password_hash) for h in anteriores)


def guardar_en_historial(db: Session, usuario: Usuario) -> None:
    """Guarda el hash actual en el historial antes de reemplazarlo."""
    db.add(HistorialPassword(id_usuario=usuario.id_usuario, password_hash=usuario.password_hash, fecha=ahora()))


# ── AUDITORÍA ─────────────────────────────────────────────────────────────────

def auditar(db: Session, evento: str, email: Optional[str] = None,
            detalle: Optional[str] = None, ip: Optional[str] = None) -> None:
    """
    Registra un evento de seguridad. Nunca guarda contraseñas ni tokens.
    Eventos: login_ok, login_fallido, cuenta_bloqueada, acceso_denegado,
    cambio_password, alta_usuario, baja_usuario, forzar_cambio, consulta_asistente.
    """
    db.add(LogAuditoria(fecha=ahora(), email=email, evento=evento, detalle=detalle, ip=ip))
    db.commit()

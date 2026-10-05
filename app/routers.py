"""
routers.py — Endpoints de la API REST
RG S.A. — Sistema de Asistencia Inteligente

Expone los endpoints principales del sistema:
  POST /auth/token         — Login y generación de token JWT (con bloqueo por intentos)
  POST /auth/cambiar-password — Cambio de contraseña (política + historial)
  GET  /auth/yo            — Datos del usuario autenticado
  GET/POST /usuarios       — Administración de usuarios (solo Gerencia)
  GET  /seguridad/auditoria — Log de auditoría (solo Gerencia)
  POST /asistente/consulta — Consulta al motor RAG
  GET  /alquileres         — Listado de contratos activos
  GET  /obras              — Listado de obras en curso
  GET  /comercial/oportunidades — Pipeline comercial activo
  GET  /panel              — Resumen ejecutivo
"""
from datetime import timedelta, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
import re
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    Usuario, Contrato, Inquilino, Obra, EtapaObra,
    Oportunidad, ClientePotencial, LogAuditoria, Notificacion
)
from app.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, get_current_user_permitir_cambio,
    require_permiso, require_gerencia, PERMISOS_ROL, ROLES_VALIDOS
)
from app.seguridad import (
    ahora, auditar, esta_bloqueado, registrar_intento_fallido,
    registrar_acceso_exitoso, requiere_cambio_password, password_vencida,
    validar_politica_password, password_reutilizada, guardar_en_historial,
    generar_password_inicial
)
from app.rag_engine import consultar_asistente
from app.config import get_settings

settings = get_settings()


# ── SCHEMAS ───────────────────────────────────────────────────────────────────

class ConsultaRequest(BaseModel):
    pregunta: str


class ConsultaResponse(BaseModel):
    respuesta: str
    modulos_consultados: list[str]
    motor: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    rol: str
    nombre: str
    debe_cambiar_password: bool


class CambioPasswordRequest(BaseModel):
    password_actual: str
    password_nueva: str


class AltaUsuarioRequest(BaseModel):
    nombre: str
    email: str
    rol: str

    @field_validator("email")
    @classmethod
    def email_valido(cls, v):
        v = v.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("Correo electrónico inválido.")
        return v

    @field_validator("rol")
    @classmethod
    def rol_valido(cls, v):
        if v not in ROLES_VALIDOS:
            raise ValueError(f"Rol inválido. Opciones: {', '.join(ROLES_VALIDOS)}")
        return v


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


# ── ROUTER AUTH ───────────────────────────────────────────────────────────────

auth_router = APIRouter(prefix="/auth", tags=["Autenticación"])


@auth_router.post("/token", response_model=TokenResponse)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Autentica al usuario con email y contraseña y retorna un JWT de 8 horas.

    Controles aplicados:
      - Mensaje genérico ante error: no revela si falló el email o la contraseña.
      - Tras 5 intentos fallidos consecutivos la cuenta se bloquea 15 minutos.
      - Si la contraseña es inicial o venció (90 días) el token solo habilita
        el cambio de contraseña (debe_cambiar_password = true).
      - Cada intento queda registrado en el log de auditoría.
    """
    email = form_data.username.strip().lower()
    ip = _ip(request)
    usuario = db.query(Usuario).filter(Usuario.email == email).first()

    if usuario and usuario.activo:
        minutos = esta_bloqueado(usuario)
        if minutos:
            auditar(db, "login_rechazado_bloqueo", email, f"Cuenta bloqueada ({minutos} min restantes)", ip)
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Cuenta bloqueada por intentos fallidos. Intente nuevamente en {minutos} minuto(s).",
            )

    if not usuario or not usuario.activo or not verify_password(form_data.password, usuario.password_hash):
        if usuario and usuario.activo:
            if registrar_intento_fallido(db, usuario):
                auditar(db, "cuenta_bloqueada", email,
                        f"{settings.max_intentos_fallidos} intentos fallidos: bloqueo de {settings.minutos_bloqueo} min", ip)
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail=f"Cuenta bloqueada por {settings.minutos_bloqueo} minutos tras "
                           f"{settings.max_intentos_fallidos} intentos fallidos.",
                )
        auditar(db, "login_fallido", email, None, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    registrar_acceso_exitoso(db, usuario)
    cambio = requiere_cambio_password(usuario)
    motivo = ""
    if cambio:
        motivo = " (debe cambiar contraseña: " + ("vencida" if password_vencida(usuario) else "inicial") + ")"
    auditar(db, "login_ok", email, f"Rol {usuario.rol}{motivo}", ip)

    token = create_access_token(
        data={"sub": usuario.email, "rol": usuario.rol},
        expires_delta=timedelta(hours=settings.access_token_expire_hours)
    )
    return {
        "access_token": token, "token_type": "bearer", "rol": usuario.rol,
        "nombre": usuario.nombre, "debe_cambiar_password": cambio,
    }


@auth_router.post("/cambiar-password")
def cambiar_password(
    datos: CambioPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user_permitir_cambio),
):
    """
    Cambia la contraseña del usuario autenticado.
    Exige la contraseña actual, aplica la política de complejidad e impide
    reutilizar la contraseña actual o cualquiera de las últimas 3.
    """
    if not verify_password(datos.password_actual, usuario.password_hash):
        auditar(db, "cambio_password_rechazado", usuario.email, "Contraseña actual incorrecta", _ip(request))
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta.")

    errores = validar_politica_password(datos.password_nueva)
    if errores:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe " + ", ".join(errores) + ".")

    if password_reutilizada(db, usuario, datos.password_nueva, verify_password):
        raise HTTPException(
            status_code=400,
            detail=f"No puede reutilizar su contraseña actual ni ninguna de las últimas {settings.passwords_historial}.",
        )

    guardar_en_historial(db, usuario)
    usuario.password_hash = hash_password(datos.password_nueva)
    usuario.password_actualizada = ahora()
    usuario.debe_cambiar_password = False
    db.commit()
    auditar(db, "cambio_password", usuario.email, None, _ip(request))
    return {"mensaje": "Contraseña actualizada correctamente."}


@auth_router.get("/yo")
def datos_usuario(usuario: Usuario = Depends(get_current_user_permitir_cambio)):
    """Datos del usuario autenticado (sin información sensible)."""
    dias = None
    if usuario.password_actualizada:
        dias = settings.dias_vigencia_password - (ahora() - usuario.password_actualizada).days
    return {
        "nombre": usuario.nombre, "email": usuario.email, "rol": usuario.rol,
        "modulos": PERMISOS_ROL.get(usuario.rol, []),
        "debe_cambiar_password": requiere_cambio_password(usuario),
        "dias_para_vencimiento_password": dias,
    }


# ── ROUTER USUARIOS (solo Gerencia) ───────────────────────────────────────────

usuarios_router = APIRouter(prefix="/usuarios", tags=["Administración de usuarios"])


def _usuario_dict(u: Usuario) -> dict:
    return {
        "id_usuario": u.id_usuario, "nombre": u.nombre, "email": u.email, "rol": u.rol,
        "activo": u.activo, "bloqueado": esta_bloqueado(u) is not None,
        "debe_cambiar_password": requiere_cambio_password(u),
        "ultimo_acceso": u.ultimo_acceso.isoformat() if u.ultimo_acceso else None,
    }


@usuarios_router.get("/")
def listar_usuarios(db: Session = Depends(get_db), _: Usuario = Depends(require_gerencia)):
    return [_usuario_dict(u) for u in db.query(Usuario).order_by(Usuario.id_usuario).all()]


@usuarios_router.post("/", status_code=201)
def alta_usuario(
    datos: AltaUsuarioRequest,
    request: Request,
    db: Session = Depends(get_db),
    gerente: Usuario = Depends(require_gerencia),
):
    """
    Alta de usuario controlada por la Gerencia (no existe registro libre).
    Se genera una contraseña inicial aleatoria que cumple la política y el
    usuario queda obligado a cambiarla en su primer ingreso. La contraseña
    se envía por correo; si el SMTP no está configurado (modo demo) se
    devuelve una única vez en la respuesta.
    """
    email = datos.email.lower()
    if db.query(Usuario).filter(Usuario.email == email).first():
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese correo electrónico.")

    password_inicial = generar_password_inicial()
    nuevo = Usuario(
        nombre=datos.nombre.strip(), email=email, rol=datos.rol,
        password_hash=hash_password(password_inicial),
        debe_cambiar_password=True, password_actualizada=ahora(), activo=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    # En producción la contraseña inicial viaja por email (EMAIL_ALTAS=true).
    # En la demo los correos de los usuarios son ficticios: se muestra una vez en pantalla.
    enviado = False
    if settings.email_altas:
        from app.notificador import enviar_email
        estado, _ = enviar_email(
            email, "Alta en el Sistema de Asistencia Inteligente — RG S.A.",
            f"<p>Hola {nuevo.nombre}, se creó tu usuario con rol <b>{nuevo.rol}</b>.</p>"
            f"<p>Contraseña inicial: <b>{password_inicial}</b></p>"
            f"<p>Deberás cambiarla en tu primer ingreso.</p>",
        )
        enviado = estado == "enviado"
    auditar(db, "alta_usuario", gerente.email,
            f"Alta de {email} con rol {datos.rol} (contraseña inicial {'enviada por email' if enviado else 'mostrada en pantalla'})",
            _ip(request))

    respuesta = {"usuario": _usuario_dict(nuevo), "correo_enviado": enviado}
    if not enviado:
        respuesta["password_inicial"] = password_inicial
        respuesta["aviso"] = ("Modo demo: comunique esta contraseña al usuario; "
                              "no se volverá a mostrar.")
    return respuesta


@usuarios_router.post("/{id_usuario}/desactivar")
def desactivar_usuario(id_usuario: int, request: Request, db: Session = Depends(get_db),
                       gerente: Usuario = Depends(require_gerencia)):
    """Desactiva la cuenta sin eliminarla, preservando la trazabilidad en la auditoría."""
    u = db.get(Usuario, id_usuario)
    if not u:
        raise HTTPException(status_code=404, detail="Usuario inexistente.")
    if u.id_usuario == gerente.id_usuario:
        raise HTTPException(status_code=400, detail="No puede desactivar su propia cuenta.")
    u.activo = False
    db.commit()
    auditar(db, "baja_usuario", gerente.email, f"Desactivó a {u.email}", _ip(request))
    return _usuario_dict(u)


@usuarios_router.post("/{id_usuario}/activar")
def activar_usuario(id_usuario: int, request: Request, db: Session = Depends(get_db),
                    gerente: Usuario = Depends(require_gerencia)):
    u = db.get(Usuario, id_usuario)
    if not u:
        raise HTTPException(status_code=404, detail="Usuario inexistente.")
    u.activo = True
    u.intentos_fallidos = 0
    u.bloqueado_hasta = None
    db.commit()
    auditar(db, "reactivacion_usuario", gerente.email, f"Reactivó/desbloqueó a {u.email}", _ip(request))
    return _usuario_dict(u)


@usuarios_router.post("/{id_usuario}/forzar-cambio")
def forzar_cambio_password(id_usuario: int, request: Request, db: Session = Depends(get_db),
                           gerente: Usuario = Depends(require_gerencia)):
    """Ante sospecha de compromiso, obliga al usuario a cambiar su contraseña en el próximo uso."""
    u = db.get(Usuario, id_usuario)
    if not u:
        raise HTTPException(status_code=404, detail="Usuario inexistente.")
    u.debe_cambiar_password = True
    db.commit()
    auditar(db, "forzar_cambio", gerente.email, f"Forzó cambio de contraseña de {u.email}", _ip(request))
    return _usuario_dict(u)


# ── ROUTER SEGURIDAD (solo Gerencia) ──────────────────────────────────────────

seguridad_router = APIRouter(prefix="/seguridad", tags=["Seguridad"])


@seguridad_router.get("/auditoria")
def ver_auditoria(limite: int = 100, db: Session = Depends(get_db), _: Usuario = Depends(require_gerencia)):
    """Últimos eventos del log de auditoría."""
    limite = max(1, min(limite, 500))
    eventos = db.query(LogAuditoria).order_by(LogAuditoria.id.desc()).limit(limite).all()
    return [
        {"fecha": e.fecha.isoformat() if e.fecha else None, "email": e.email,
         "evento": e.evento, "detalle": e.detalle, "ip": e.ip}
        for e in eventos
    ]


@seguridad_router.get("/backups")
def ver_backups(_: Usuario = Depends(require_gerencia)):
    """Copias de seguridad disponibles."""
    from app.respaldo import listar_backups
    return listar_backups()


@seguridad_router.post("/backups")
def generar_backup(request: Request, db: Session = Depends(get_db), gerente: Usuario = Depends(require_gerencia)):
    """Genera una copia de seguridad en el momento (además de la copia diaria automática)."""
    from app.respaldo import crear_backup, ErrorRespaldo
    try:
        info = crear_backup()
    except ErrorRespaldo as e:
        auditar(db, "backup_error", gerente.email, str(e)[:400], _ip(request))
        raise HTTPException(status_code=500, detail=str(e))
    auditar(db, "backup_ok", gerente.email, f"Manual: {info['archivo']}", _ip(request))
    return info


@seguridad_router.post("/backups/verificar")
def verificar_backup(request: Request, db: Session = Depends(get_db), gerente: Usuario = Depends(require_gerencia)):
    """Prueba de restauración de la última copia en una base temporal aislada."""
    from app.respaldo import verificar_restauracion, ErrorRespaldo
    try:
        r = verificar_restauracion()
    except ErrorRespaldo as e:
        raise HTTPException(status_code=500, detail=str(e))
    auditar(db, "prueba_restauracion", gerente.email, f"{r['archivo']}: {r['resultado']}", _ip(request))
    return r


@seguridad_router.get("/politicas")
def ver_politicas(_: Usuario = Depends(get_current_user)):
    """Resumen de los controles de seguridad activos (para mostrar en la interfaz)."""
    return {
        "hash_passwords": "bcrypt, 12 rondas",
        "token": f"JWT HS256, validez {settings.access_token_expire_hours} horas",
        "bloqueo": f"{settings.max_intentos_fallidos} intentos fallidos → {settings.minutos_bloqueo} minutos",
        "complejidad": "8+ caracteres, mayúscula, minúscula, número y carácter especial",
        "vigencia_password_dias": settings.dias_vigencia_password,
        "historial_passwords": settings.passwords_historial,
        "alta_usuarios": "Solo Gerencia; contraseña inicial aleatoria con cambio obligatorio",
        "roles": PERMISOS_ROL,
    }


# ── ROUTER ASISTENTE ──────────────────────────────────────────────────────────

asistente_router = APIRouter(prefix="/asistente", tags=["Asistente IA"])


@asistente_router.post("/consulta", response_model=ConsultaResponse)
def consultar(
    request: ConsultaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Endpoint principal del motor RAG.
    Recibe una pregunta en lenguaje natural, recupera el contexto operativo
    permitido para el rol y genera la respuesta con el modelo de lenguaje
    configurado (o con el motor de reglas si no hay modelo disponible).
    """
    modulos = PERMISOS_ROL.get(current_user.rol, [])
    pregunta = request.pregunta.strip()[:500]
    if not pregunta:
        raise HTTPException(status_code=400, detail="La consulta está vacía.")

    respuesta, motor = consultar_asistente(
        query=pregunta,
        db=db,
        rol_usuario=current_user.rol,
        modulos_permitidos=modulos
    )
    auditar(db, "consulta_asistente", current_user.email, f"[{motor}] {pregunta[:120]}")

    return {"respuesta": respuesta, "modulos_consultados": modulos, "motor": motor}


# ── ROUTER ALQUILERES ─────────────────────────────────────────────────────────

alquileres_router = APIRouter(prefix="/alquileres", tags=["Alquileres"])


@alquileres_router.get("/contratos")
def listar_contratos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_permiso("alquileres"))
):
    """Retorna todos los contratos activos con estado de pago."""
    contratos = (
        db.query(Contrato, Inquilino)
        .join(Inquilino)
        .filter(Contrato.estado != "vencido")
        .all()
    )
    return [
        {
            "id_contrato": c.id_contrato,
            "inquilino": f"{inq.apellido}, {inq.nombre}",
            "vencimiento": c.fecha_vencimiento.isoformat(),
            "monto": float(c.monto_mensual),
            "estado": c.estado,
        }
        for c, inq in contratos
    ]


@alquileres_router.get("/mora")
def contratos_en_mora(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_permiso("alquileres"))
):
    """Retorna solo los contratos con estado en_mora."""
    contratos = (
        db.query(Contrato, Inquilino)
        .join(Inquilino)
        .filter(Contrato.estado == "en_mora")
        .all()
    )
    return [
        {
            "inquilino": f"{inq.apellido}, {inq.nombre}",
            "telefono": inq.telefono,
            "email": inq.email,
            "monto_adeudado": float(c.monto_mensual),
            "vencimiento": c.fecha_vencimiento.isoformat(),
        }
        for c, inq in contratos
    ]


# ── ROUTER OBRAS ──────────────────────────────────────────────────────────────

obras_router = APIRouter(prefix="/obras", tags=["Obras"])


@obras_router.get("/")
def listar_obras(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_permiso("obras"))
):
    """Retorna obras activas con avance por etapa."""
    obras = db.query(Obra).filter(Obra.estado.in_(["en_curso", "demorada"])).all()
    resultado = []
    for obra in obras:
        etapas = db.query(EtapaObra).filter(EtapaObra.id_obra == obra.id_obra).all()
        avance = (
            sum(float(e.pct_avance) for e in etapas) / len(etapas) if etapas else 0
        )
        resultado.append({
            "nombre": obra.nombre,
            "estado": obra.estado,
            "avance_general": round(avance, 1),
            "fecha_fin_estimada": obra.fecha_fin_estimada.isoformat() if obra.fecha_fin_estimada else None,
            "etapas": [
                {
                    "nombre": e.nombre_etapa,
                    "avance": float(e.pct_avance),
                    "fecha_fin_plan": e.fecha_fin_plan.isoformat() if e.fecha_fin_plan else None,
                }
                for e in etapas
            ],
        })
    return resultado


# ── ROUTER AUTOMATIZACIÓN (solo Gerencia) ────────────────────────────────────

automatizacion_router = APIRouter(prefix="/automatizacion", tags=["Automatización"])


@automatizacion_router.get("/estado")
def estado_automatizacion(_: Usuario = Depends(require_gerencia)):
    """Canal de email activo, casilla de destino y horario de cada job."""
    from app.notificador import canal_configurado, destinatario_avisos
    return {
        "canal_email": canal_configurado(),
        "destinatario": destinatario_avisos() or None,
        "jobs": [
            {"id": "vencimientos", "nombre": "Vencimientos de contratos", "hora": "08:00"},
            {"id": "mora", "nombre": "Mora en alquileres", "hora": "08:30"},
            {"id": "desvios", "nombre": "Desvíos de cronograma de obra", "hora": "09:00"},
        ],
    }


@automatizacion_router.post("/ejecutar/{job}")
def ejecutar_job(job: str, request: Request, db: Session = Depends(get_db),
                 gerente: Usuario = Depends(require_gerencia)):
    """
    Ejecuta en el momento uno de los jobs diarios (los mismos que corre el
    scheduler), para verificar la automatización sin esperar al horario.
    """
    from jobs.scheduler import JOBS_MANUALES
    funcion = JOBS_MANUALES.get(job)
    if funcion is None:
        raise HTTPException(status_code=404, detail=f"Job inexistente. Opciones: {', '.join(JOBS_MANUALES)}")
    resultado = funcion()
    auditar(db, "job_manual", gerente.email, f"{job}: {resultado}", _ip(request))
    return resultado


@automatizacion_router.post("/prueba-email")
def prueba_email(request: Request, db: Session = Depends(get_db), gerente: Usuario = Depends(require_gerencia)):
    """Envía un email de prueba a la casilla de avisos para verificar la configuración."""
    from app.notificador import enviar_email, destinatario_avisos, canal_configurado
    destino = destinatario_avisos()
    estado, detalle = enviar_email(
        destino, "Prueba de envío — Sistema de Asistencia Inteligente RG S.A.",
        "<h3>Email de prueba</h3><p>Si recibís este mensaje, los avisos automáticos están funcionando.</p>"
        f"<p>Canal: {canal_configurado()}</p>",
    )
    auditar(db, "prueba_email", gerente.email, f"{estado}: {detalle}"[:400], _ip(request))
    return {"estado": estado, "detalle": detalle, "destinatario": destino or None}


@automatizacion_router.get("/notificaciones")
def ver_notificaciones(limite: int = 50, db: Session = Depends(get_db), _: Usuario = Depends(require_gerencia)):
    """Últimos avisos generados por los jobs (tabla NOTIFICACION)."""
    limite = max(1, min(limite, 200))
    filas = db.query(Notificacion).order_by(Notificacion.id_notificacion.desc()).limit(limite).all()
    return [
        {"fecha": n.fecha_envio.isoformat() if n.fecha_envio else None, "tipo": n.tipo,
         "asunto": n.asunto, "destinatario": n.destinatario, "estado": n.estado_envio}
        for n in filas
    ]


# ── ROUTER COMERCIAL ──────────────────────────────────────────────────────────

comercial_router = APIRouter(prefix="/comercial", tags=["Comercial"])


@comercial_router.get("/oportunidades")
def listar_oportunidades(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_permiso("comercial"))
):
    """Pipeline comercial activo con días desde el último contacto."""
    hoy = date.today()
    filas = (
        db.query(Oportunidad, ClientePotencial)
        .join(ClientePotencial)
        .filter(Oportunidad.etapa.notin_(["cerrado_ganado", "cerrado_perdido"]))
        .all()
    )
    return [
        {
            "cliente": f"{cli.apellido}, {cli.nombre}",
            "etapa": op.etapa,
            "tipo_operacion": op.tipo_operacion,
            "origen": cli.origen_consulta,
            "dias_sin_contacto": (hoy - op.fecha_ultimo_contacto).days if op.fecha_ultimo_contacto else None,
        }
        for op, cli in filas
    ]


# ── ROUTER PANEL ──────────────────────────────────────────────────────────────

panel_router = APIRouter(prefix="/panel", tags=["Panel ejecutivo"])


@panel_router.get("/resumen")
def resumen_ejecutivo(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_permiso("panel"))
):
    """Indicadores clave para el panel de gerencia."""
    hoy = date.today()
    contratos_activos = db.query(Contrato).filter(
        Contrato.estado != "vencido"
    ).count()
    contratos_mora = db.query(Contrato).filter(
        Contrato.estado == "en_mora"
    ).count()
    obras_curso = db.query(Obra).filter(
        Obra.estado.in_(["en_curso", "demorada"])
    ).count()
    clientes_activos = db.query(Oportunidad).filter(
        Oportunidad.etapa.notin_(["cerrado_ganado", "cerrado_perdido"])
    ).count()

    return {
        "contratos_activos": contratos_activos,
        "contratos_en_mora": contratos_mora,
        "obras_en_curso": obras_curso,
        "clientes_activos": clientes_activos,
        "fecha_actualizacion": hoy.isoformat(),
    }

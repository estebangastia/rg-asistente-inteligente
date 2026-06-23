"""
routers.py — Endpoints de la API REST
RG S.A. — Sistema de Asistencia Inteligente

Expone los endpoints principales del sistema:
  POST /auth/token         — Login y generación de token JWT
  POST /asistente/consulta — Consulta al motor RAG
  GET  /alquileres         — Listado de contratos activos
  GET  /obras              — Listado de obras en curso
  GET  /comercial          — Pipeline comercial activo
  GET  /panel              — Resumen ejecutivo
"""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Usuario, Contrato, Inquilino, Obra, EtapaObra, Oportunidad
from app.auth import (
    verify_password, create_access_token,
    get_current_user, require_permiso, PERMISOS_ROL
)
from app.rag_engine import consultar_asistente
from app.config import get_settings
from datetime import date

settings = get_settings()


# ── SCHEMAS ───────────────────────────────────────────────────────────────────

class ConsultaRequest(BaseModel):
    pregunta: str


class ConsultaResponse(BaseModel):
    respuesta: str
    modulos_consultados: list[str]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    rol: str


# ── ROUTER AUTH ───────────────────────────────────────────────────────────────

auth_router = APIRouter(prefix="/auth", tags=["Autenticación"])


@auth_router.post("/token", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Autentica al usuario con email y contraseña.
    Retorna un JWT con validez de 8 horas.
    Luego de 5 intentos fallidos la cuenta se bloquea (implementar con Redis en producción).
    """
    usuario = db.query(Usuario).filter(
        Usuario.email == form_data.username,
        Usuario.activo == True
    ).first()

    if not usuario or not verify_password(form_data.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={"sub": usuario.email, "rol": usuario.rol},
        expires_delta=timedelta(hours=settings.access_token_expire_hours)
    )
    return {"access_token": token, "token_type": "bearer", "rol": usuario.rol}


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
    Recibe una pregunta en lenguaje natural y retorna una respuesta
    generada por GPT-4o con contexto transaccional y vectorial de RG S.A.
    """
    modulos = PERMISOS_ROL.get(current_user.rol, [])

    respuesta = consultar_asistente(
        query=request.pregunta,
        db=db,
        rol_usuario=current_user.rol,
        modulos_permitidos=modulos
    )

    return {"respuesta": respuesta, "modulos_consultados": modulos}


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

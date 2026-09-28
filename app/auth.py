"""
auth.py — Autenticación JWT y manejo seguro de contraseñas
RG S.A. — Sistema de Asistencia Inteligente

Implementa:
  - Hasheo de contraseñas con bcrypt, factor de costo 12 (Provos & Mazières, 1999)
  - Generación y validación de tokens JWT con expiración de 8 horas
  - Control de acceso por rol (gerencia | administracion | jefe_obra)
  - Bloqueo de operaciones hasta que el usuario cambie una contraseña
    inicial o vencida (ver app/seguridad.py)
"""
from datetime import timedelta
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db
from app.models import Usuario
from app.seguridad import ahora, requiere_cambio_password, auditar

settings = get_settings()

# bcrypt con factor de costo 12 — resistente a ataques de fuerza bruta
BCRYPT_ROUNDS = 12

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# Permisos por rol
PERMISOS_ROL = {
    "gerencia":      ["alquileres", "obras", "comercial", "asistente", "panel"],
    "administracion": ["alquileres", "comercial", "asistente"],
    "jefe_obra":     ["obras", "asistente"],
}

ROLES_VALIDOS = tuple(PERMISOS_ROL.keys())


def hash_password(password: str) -> str:
    """Genera el hash bcrypt (salt aleatorio + 12 rondas) de la contraseña."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña contra su hash almacenado."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Genera un token JWT firmado con el SECRET_KEY.
    El token contiene el email del usuario, su rol y la expiración.
    Nunca se incluye la contraseña ni otro dato sensible en el payload.
    """
    to_encode = data.copy()
    expire = ahora() + (expires_delta or timedelta(hours=settings.access_token_expire_hours))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def _usuario_desde_token(token: str, db: Session) -> Usuario:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        email: str = payload.get("sub")
        rol: str = payload.get("rol")
        if email is None or rol is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    usuario = db.query(Usuario).filter(Usuario.email == email, Usuario.activo == True).first()  # noqa: E712
    if usuario is None:
        raise credentials_exception
    return usuario


def get_current_user_permitir_cambio(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    """Usuario autenticado, aunque tenga pendiente el cambio de contraseña."""
    return _usuario_desde_token(token, db)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    """
    Dependencia FastAPI: valida el token JWT y retorna el usuario autenticado.
    Lanza HTTP 401 si el token es inválido o expiró, y HTTP 403 si el usuario
    debe cambiar su contraseña (inicial o vencida) antes de operar.
    """
    usuario = _usuario_desde_token(token, db)
    if requiere_cambio_password(usuario):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debe cambiar su contraseña antes de continuar.",
            headers={"X-Requiere-Cambio-Password": "1"},
        )
    return usuario


def require_permiso(modulo: str):
    """
    Dependencia de orden superior: verifica que el usuario tenga
    permiso para acceder al módulo solicitado según su rol.
    Los accesos denegados quedan registrados en la auditoría.

    Uso:
        @router.get("/alquileres", dependencies=[Depends(require_permiso("alquileres"))])
    """
    def check(
        request: Request,
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        if modulo not in PERMISOS_ROL.get(current_user.rol, []):
            auditar(db, "acceso_denegado", current_user.email,
                    f"Rol '{current_user.rol}' intentó acceder a '{modulo}' ({request.url.path})",
                    request.client.host if request.client else None)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"El rol '{current_user.rol}' no tiene acceso al módulo '{modulo}'."
            )
        return current_user
    return check


def require_gerencia(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """Solo la Gerencia administra usuarios y consulta la auditoría."""
    if current_user.rol != "gerencia":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Solo la Gerencia puede realizar esta operación.")
    return current_user

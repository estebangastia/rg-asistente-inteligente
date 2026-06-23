"""
auth.py — Autenticación JWT y manejo seguro de contraseñas
RG S.A. — Sistema de Asistencia Inteligente

Implementa:
  - Hasheo de contraseñas con bcrypt (Provos & Mazières, 1999)
  - Generación y validación de tokens JWT con expiración de 8 horas
  - Control de acceso por rol (gerencia | administracion | jefe_obra)
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db
from app.models import Usuario

settings = get_settings()

# bcrypt con factor de costo 12 — resistente a ataques de fuerza bruta
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# Permisos por rol
PERMISOS_ROL = {
    "gerencia":      ["alquileres", "obras", "comercial", "asistente", "panel"],
    "administracion": ["alquileres", "comercial", "asistente"],
    "jefe_obra":     ["obras", "asistente"],
}


def hash_password(password: str) -> str:
    """Genera el hash bcrypt de la contraseña."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña contra su hash almacenado."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Genera un token JWT firmado con el SECRET_KEY.
    El token contiene el email del usuario, su rol y la expiración.
    Nunca se incluye la contraseña en el payload.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(hours=settings.access_token_expire_hours)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Usuario:
    """
    Dependencia FastAPI: valida el token JWT y retorna el usuario autenticado.
    Lanza HTTP 401 si el token es inválido o expiró.
    """
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

    usuario = db.query(Usuario).filter(Usuario.email == email, Usuario.activo == True).first()
    if usuario is None:
        raise credentials_exception
    return usuario


def require_permiso(modulo: str):
    """
    Dependencia de orden superior: verifica que el usuario tenga
    permiso para acceder al módulo solicitado según su rol.

    Uso:
        @router.get("/alquileres", dependencies=[Depends(require_permiso("alquileres"))])
    """
    def check(current_user: Usuario = Depends(get_current_user)):
        if modulo not in PERMISOS_ROL.get(current_user.rol, []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"El rol '{current_user.rol}' no tiene acceso al módulo '{modulo}'."
            )
        return current_user
    return check

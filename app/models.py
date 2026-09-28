"""
models.py — Modelos ORM del sistema de asistencia inteligente
RG S.A. — 13 entidades del DER + tabla de soporte vectorial

NOTA SOBRE pgvector: la columna `embedding` se define como Text en esta
version para que el sistema funcione sin requerir la extension pgvector
compilada (necesaria solo para la busqueda semantica de
app/rag_engine_openai.py). Para activar pgvector:

  1. Instalar la extension: https://github.com/pgvector/pgvector
  2. Descomentar el import de Vector mas abajo
  3. Reemplazar `embedding = Column(Text, nullable=True)` por
     `embedding = Column(Vector(1536))` en la clase DocumentoVectorial
"""
from sqlalchemy import (
    Column, Integer, String, Numeric, Date, DateTime,
    Boolean, Text, ForeignKey, func
)
from sqlalchemy.orm import relationship, declarative_base

# from pgvector.sqlalchemy import Vector  # Habilitar junto con la extension pgvector

Base = declarative_base()


class Usuario(Base):
    __tablename__ = "usuarios"

    id_usuario = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    rol = Column(String(50), nullable=False)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    # ── Campos de seguridad (sección Seguridad del TFG, ISO/IEC 27001) ──
    intentos_fallidos = Column(Integer, default=0, nullable=False)
    bloqueado_hasta = Column(DateTime, nullable=True)        # bloqueo temporal de 15 min
    debe_cambiar_password = Column(Boolean, default=False, nullable=False)
    password_actualizada = Column(DateTime, server_default=func.now())  # vence a los 90 días
    ultimo_acceso = Column(DateTime, nullable=True)


class Inquilino(Base):
    __tablename__ = "inquilinos"

    id_inquilino = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    apellido = Column(String(100), nullable=False)
    dni = Column(String(20), unique=True)
    telefono = Column(String(30))
    email = Column(String(150))

    contratos = relationship("Contrato", back_populates="inquilino")


class Inmueble(Base):
    __tablename__ = "inmuebles"

    id_inmueble = Column(Integer, primary_key=True, autoincrement=True)
    direccion = Column(String(200), nullable=False)
    tipo = Column(String(50))
    superficie_m2 = Column(Numeric(8, 2))
    disponible = Column(Boolean, default=True)

    contratos = relationship("Contrato", back_populates="inmueble")


class Contrato(Base):
    __tablename__ = "contratos"

    id_contrato = Column(Integer, primary_key=True, autoincrement=True)
    id_inquilino = Column(Integer, ForeignKey("inquilinos.id_inquilino"), nullable=False)
    id_inmueble = Column(Integer, ForeignKey("inmuebles.id_inmueble"), nullable=False)
    fecha_inicio = Column(Date, nullable=False)
    fecha_vencimiento = Column(Date, nullable=False)
    monto_mensual = Column(Numeric(12, 2), nullable=False)
    estado = Column(String(30), default="al_dia")
    indice_actualizacion = Column(String(20), default="IPC")

    inquilino = relationship("Inquilino", back_populates="contratos")
    inmueble = relationship("Inmueble", back_populates="contratos")
    pagos = relationship("Pago", back_populates="contrato")
    notificaciones = relationship("Notificacion", back_populates="contrato")


class Pago(Base):
    __tablename__ = "pagos"

    id_pago = Column(Integer, primary_key=True, autoincrement=True)
    id_contrato = Column(Integer, ForeignKey("contratos.id_contrato"), nullable=False)
    fecha_pago = Column(Date, nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)
    periodo = Column(String(20))
    medio_pago = Column(String(50))

    contrato = relationship("Contrato", back_populates="pagos")


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id_notificacion = Column(Integer, primary_key=True, autoincrement=True)
    id_contrato = Column(Integer, ForeignKey("contratos.id_contrato"), nullable=False)
    tipo = Column(String(50))
    destinatario = Column(String(150))
    fecha_envio = Column(DateTime, server_default=func.now())
    estado_envio = Column(String(20), default="pendiente")

    contrato = relationship("Contrato", back_populates="notificaciones")


class Obra(Base):
    __tablename__ = "obras"

    id_obra = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(150), nullable=False)
    direccion = Column(String(200))
    fecha_inicio = Column(Date)
    fecha_fin_estimada = Column(Date)
    estado = Column(String(30), default="en_curso")
    id_usuario = Column(Integer, ForeignKey("usuarios.id_usuario"))

    etapas = relationship("EtapaObra", back_populates="obra")
    ordenes_trabajo = relationship("OrdenTrabajo", back_populates="obra")


class EtapaObra(Base):
    __tablename__ = "etapas_obra"

    id_etapa = Column(Integer, primary_key=True, autoincrement=True)
    id_obra = Column(Integer, ForeignKey("obras.id_obra"), nullable=False)
    nombre_etapa = Column(String(100), nullable=False)
    fecha_inicio_plan = Column(Date)
    fecha_fin_plan = Column(Date)
    pct_avance = Column(Numeric(5, 2), default=0)

    obra = relationship("Obra", back_populates="etapas")


class ClientePotencial(Base):
    __tablename__ = "clientes_potenciales"

    id_cliente = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    apellido = Column(String(100), nullable=False)
    telefono = Column(String(30))
    email = Column(String(150))
    origen_consulta = Column(String(50))

    oportunidades = relationship("Oportunidad", back_populates="cliente")


class Oportunidad(Base):
    __tablename__ = "oportunidades"

    id_oportunidad = Column(Integer, primary_key=True, autoincrement=True)
    id_cliente = Column(Integer, ForeignKey("clientes_potenciales.id_cliente"), nullable=False)
    etapa = Column(String(50), default="consulta_recibida")
    fecha_consulta = Column(Date)
    fecha_ultimo_contacto = Column(Date)
    tipo_operacion = Column(String(50))
    id_usuario = Column(Integer, ForeignKey("usuarios.id_usuario"))

    cliente = relationship("ClientePotencial", back_populates="oportunidades")
    presupuestos = relationship("Presupuesto", back_populates="oportunidad")


class Presupuesto(Base):
    __tablename__ = "presupuestos"

    id_presupuesto = Column(Integer, primary_key=True, autoincrement=True)
    id_oportunidad = Column(Integer, ForeignKey("oportunidades.id_oportunidad"), nullable=False)
    fecha_emision = Column(Date)
    monto_total = Column(Numeric(14, 2))
    estado = Column(String(30), default="borrador")
    detalle_items = Column(Text)

    oportunidad = relationship("Oportunidad", back_populates="presupuestos")


class Proveedor(Base):
    __tablename__ = "proveedores"

    id_proveedor = Column(Integer, primary_key=True, autoincrement=True)
    razon_social = Column(String(150), nullable=False)
    rubro = Column(String(100))
    telefono = Column(String(30))
    email = Column(String(150))

    ordenes_trabajo = relationship("OrdenTrabajo", back_populates="proveedor")


class OrdenTrabajo(Base):
    __tablename__ = "ordenes_trabajo"

    id_orden = Column(Integer, primary_key=True, autoincrement=True)
    id_obra = Column(Integer, ForeignKey("obras.id_obra"), nullable=False)
    id_proveedor = Column(Integer, ForeignKey("proveedores.id_proveedor"), nullable=False)
    descripcion = Column(String(300))
    fecha_emision = Column(Date)
    monto_acordado = Column(Numeric(12, 2))
    estado = Column(String(30), default="pendiente")

    obra = relationship("Obra", back_populates="ordenes_trabajo")
    proveedor = relationship("Proveedor", back_populates="ordenes_trabajo")


class DocumentoVectorial(Base):
    """
    Tabla de soporte para busqueda semantica con pgvector.

    La columna `embedding` se define como Text para que el sistema
    funcione sin requerir pgvector compilado. Para produccion con
    busqueda semantica real, ver la nota al inicio de este archivo.
    """
    __tablename__ = "documentos_vectoriales"

    id_doc = Column(Integer, primary_key=True, autoincrement=True)
    contenido = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)  # Vector(1536) con pgvector habilitado
    tipo_documento = Column(String(50))
    id_referencia = Column(Integer)
    metadata_json = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


# ── TABLAS DE SOPORTE DE SEGURIDAD ────────────────────────────────────────────
# No forman parte de las 13 entidades de negocio del DER: implementan los
# controles descriptos en la sección Seguridad (historial de contraseñas y
# log de auditoría).

class HistorialPassword(Base):
    """Últimas contraseñas de cada usuario (hash), para impedir su reutilización."""
    __tablename__ = "historial_passwords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    id_usuario = Column(Integer, ForeignKey("usuarios.id_usuario"), nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    fecha = Column(DateTime, server_default=func.now())


class LogAuditoria(Base):
    """Registro de eventos de seguridad: accesos, bloqueos, altas y cambios."""
    __tablename__ = "log_auditoria"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(DateTime, server_default=func.now(), index=True)
    email = Column(String(150))
    evento = Column(String(50), nullable=False)
    detalle = Column(Text)
    ip = Column(String(64))

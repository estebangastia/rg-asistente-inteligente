"""
rag_engine_openai.py — Motor RAG completo (LangChain + GPT-4o + pgvector)
RG S.A. — Sistema de Asistencia Inteligente

IMPLEMENTACIÓN DE REFERENCIA — arquitectura productiva descripta en el TFG.

Este archivo contiene la implementación completa de la técnica RAG
(Retrieval-Augmented Generation) propuesta por Lewis et al. (2020),
sobre la arquitectura Transformer de Vaswani et al. (2017):

  1. Recupera datos transaccionales desde PostgreSQL (datos estructurados)
  2. Recupera fragmentos semánticos desde pgvector (documentos vectorizados:
     contratos en PDF, presupuestos, planos, comunicaciones históricas)
  3. Combina ambas fuentes como contexto para GPT-4o
  4. Genera una respuesta en lenguaje natural precisa y contextualizada

PARA ACTIVAR ESTA VERSIÓN EN LUGAR DE LA DEMO:
  1. Instalar pgvector para PostgreSQL (https://github.com/pgvector/pgvector)
  2. Configurar OPENAI_API_KEY válida en el archivo .env
  3. Descomentar la columna `embedding = Column(Vector(1536))` en app/models.py
  4. Reemplazar app/rag_engine.py por una copia de este archivo
     (o renombrar este archivo a rag_engine.py)

No se ejecuta en la demo de evaluación porque requiere una API key de
OpenAI activa y la extensión pgvector compilada para PostgreSQL, dos
dependencias externas que no deben asumirse disponibles en el entorno
de quien evalúa el prototipo.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage, SystemMessage
from app.config import get_settings
from app.models import (
    Contrato, Inquilino, Obra, EtapaObra,
    Oportunidad, ClientePotencial, DocumentoVectorial
)

settings = get_settings()

# ── Instancias de LangChain ───────────────────────────────────────────────────
llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0.2,          # Respuestas precisas con mínima variación
    openai_api_key=settings.openai_api_key,
)

embeddings_model = OpenAIEmbeddings(
    model="text-embedding-3-small",
    openai_api_key=settings.openai_api_key,
)

SYSTEM_PROMPT = """Sos el asistente operativo de RG S.A., una empresa constructora \
e inmobiliaria de Paraná, Entre Ríos. Tenés acceso a la información operativa actualizada \
de la empresa que se te provee como contexto.

Respondé siempre en español, de forma concisa y directa. Citá los datos específicos \
(nombres, fechas, montos) cuando estén disponibles en el contexto. Si no tenés información \
suficiente para responder con precisión, indicalo claramente. \
Nunca inventes datos que no estén en el contexto proporcionado.

Respetá los permisos del usuario: si el contexto indica que el usuario no tiene \
acceso a un módulo, respondé que esa información no está disponible para su perfil."""


# ── RECUPERACIÓN TRANSACCIONAL ────────────────────────────────────────────────

def _contexto_alquileres(db: Session) -> str:
    hoy = date.today()
    contratos = (
        db.query(Contrato, Inquilino)
        .join(Inquilino)
        .filter(Contrato.estado.in_(["al_dia", "en_mora", "por_vencer"]))
        .all()
    )
    if not contratos:
        return "No hay contratos de alquiler activos en el sistema."
    lineas = ["CONTRATOS DE ALQUILER ACTIVOS:"]
    for c, inq in contratos:
        dias_venc = (c.fecha_vencimiento - hoy).days
        estado_label = {
            "al_dia": "Al día", "en_mora": "En mora", "por_vencer": "Por vencer"
        }.get(c.estado, c.estado)
        lineas.append(
            f"- {inq.apellido}, {inq.nombre} | Estado: {estado_label} | "
            f"Vence: {c.fecha_vencimiento.strftime('%d/%m/%Y')} "
            f"({'en ' + str(dias_venc) + ' días' if dias_venc > 0 else 'VENCIDO'}) | "
            f"Monto: ${c.monto_mensual:,.0f}"
        )
    return "\n".join(lineas)


def _contexto_obras(db: Session) -> str:
    obras = db.query(Obra).filter(Obra.estado.in_(["en_curso", "demorada"])).all()
    if not obras:
        return "No hay obras activas en el sistema."
    lineas = ["OBRAS EN CURSO:"]
    for obra in obras:
        etapas = db.query(EtapaObra).filter(EtapaObra.id_obra == obra.id_obra).all()
        avance_general = (
            sum(float(e.pct_avance) for e in etapas) / len(etapas) if etapas else 0
        )
        lineas.append(f"\n• {obra.nombre} ({obra.direccion})")
        lineas.append(f"  Estado: {obra.estado} | Avance general: {avance_general:.1f}%")
        lineas.append(f"  Fecha fin estimada: {obra.fecha_fin_estimada}")
        for etapa in etapas:
            lineas.append(
                f"  - {etapa.nombre_etapa}: {etapa.pct_avance}% (plan: {etapa.fecha_fin_plan})"
            )
    return "\n".join(lineas)


def _contexto_comercial(db: Session) -> str:
    oportunidades = (
        db.query(Oportunidad, ClientePotencial)
        .join(ClientePotencial)
        .filter(Oportunidad.etapa.notin_(["cerrado_ganado", "cerrado_perdido"]))
        .all()
    )
    if not oportunidades:
        return "No hay oportunidades comerciales activas en el sistema."
    hoy = date.today()
    lineas = ["PIPELINE COMERCIAL ACTIVO:"]
    for op, cli in oportunidades:
        dias_sin_contacto = (
            (hoy - op.fecha_ultimo_contacto).days if op.fecha_ultimo_contacto else "N/D"
        )
        lineas.append(
            f"- {cli.apellido}, {cli.nombre} | Etapa: {op.etapa} | "
            f"Operación: {op.tipo_operacion} | Último contacto: hace {dias_sin_contacto} días"
        )
    return "\n".join(lineas)


# ── RECUPERACIÓN VECTORIAL (pgvector) ─────────────────────────────────────────

def _contexto_vectorial(db: Session, query: str, top_k: int = 4) -> str:
    """
    Genera el embedding de la consulta y recupera los documentos más
    similares semánticamente desde pgvector mediante distancia coseno.
    """
    try:
        query_embedding = embeddings_model.embed_query(query)
        resultados = db.execute(
            text("""
                SELECT contenido, tipo_documento,
                       1 - (embedding <=> :embedding::vector) AS similitud
                FROM documentos_vectoriales
                WHERE 1 - (embedding <=> :embedding::vector) > 0.7
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top_k
            """),
            {"embedding": str(query_embedding), "top_k": top_k}
        ).fetchall()

        if not resultados:
            return ""

        lineas = ["\nDOCUMENTOS RELACIONADOS (búsqueda semántica):"]
        for row in resultados:
            lineas.append(f"[{row.tipo_documento}] {row.contenido}")
        return "\n".join(lineas)

    except Exception:
        return ""


# ── FUNCIÓN PRINCIPAL DEL MOTOR RAG ──────────────────────────────────────────

def consultar_asistente(
    query: str,
    db: Session,
    rol_usuario: str,
    modulos_permitidos: list[str]
) -> str:
    """
    Punto de entrada del motor RAG productivo.
    Combina recuperación transaccional + vectorial y genera la respuesta
    con GPT-4o vía LangChain.
    """
    bloques_contexto = []

    if "alquileres" in modulos_permitidos:
        bloques_contexto.append(_contexto_alquileres(db))
    if "obras" in modulos_permitidos:
        bloques_contexto.append(_contexto_obras(db))
    if "comercial" in modulos_permitidos:
        bloques_contexto.append(_contexto_comercial(db))

    contexto_vectorial = _contexto_vectorial(db, query)
    if contexto_vectorial:
        bloques_contexto.append(contexto_vectorial)

    contexto = "\n\n".join(bloques_contexto) if bloques_contexto else \
        "No tenés acceso a información operativa con tu perfil actual."

    contexto_con_rol = (
        f"PERFIL DEL USUARIO: {rol_usuario.upper()}\n"
        f"MÓDULOS ACCESIBLES: {', '.join(modulos_permitidos)}\n\n"
        f"{contexto}"
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"CONTEXTO OPERATIVO:\n{contexto_con_rol}\n\nPREGUNTA: {query}"),
    ]

    respuesta = llm.invoke(messages)
    return respuesta.content


# ── INDEXACIÓN DE DOCUMENTOS ──────────────────────────────────────────────────

def indexar_documento(
    db: Session,
    contenido: str,
    tipo_documento: str,
    id_referencia: Optional[int] = None,
    metadata: Optional[str] = None
) -> bool:
    """
    Genera el embedding de un documento con OpenAI y lo almacena en pgvector.
    Se invoca al registrar un nuevo contrato, presupuesto u obra.
    """
    try:
        embedding = embeddings_model.embed_documents([contenido])[0]
        doc = DocumentoVectorial(
            contenido=contenido,
            embedding=embedding,
            tipo_documento=tipo_documento,
            id_referencia=id_referencia,
            metadata_json=metadata,
        )
        db.add(doc)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Error al indexar documento: {e}")
        return False

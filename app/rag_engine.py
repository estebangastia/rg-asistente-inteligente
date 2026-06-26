"""
rag_engine.py — Motor RAG (modo DEMO, sin dependencias externas)
RG S.A. — Sistema de Asistencia Inteligente

IMPORTANTE: Este es el motor RAG que se ejecuta por defecto en la demo.
Genera respuestas en lenguaje natural a partir de los datos transaccionales
de PostgreSQL, SIN consumir la API de OpenAI ni requerir pgvector instalado.

Esto permite que cualquier evaluador clone el repositorio y ejecute el
sistema completo sin necesidad de credenciales de OpenAI ni de compilar
la extensión pgvector para PostgreSQL.

La implementación completa con LangChain + GPT-4o + búsqueda vectorial
pgvector está disponible en app/rag_engine_openai.py y reproduce
exactamente la arquitectura RAG descripta en el marco teórico del TFG
(Lewis et al., 2020), activable configurando OPENAI_API_KEY en .env
y reemplazando este archivo por aquel.
"""
from __future__ import annotations
from datetime import date
from sqlalchemy.orm import Session
from app.models import (
    Contrato, Inquilino, Obra, EtapaObra,
    Oportunidad, ClientePotencial
)


# ── RECUPERACIÓN TRANSACCIONAL (equivalente a la etapa "Retrieval" de RAG) ───

def _contexto_alquileres(db: Session) -> str:
    """Recupera el estado actual de contratos desde PostgreSQL."""
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
        dias = (c.fecha_vencimiento - hoy).days
        estado_label = {
            "al_dia": "Al día", "en_mora": "En mora", "por_vencer": "Por vencer"
        }.get(c.estado, c.estado)
        lineas.append(
            f"  - {inq.apellido}, {inq.nombre} | Estado: {estado_label} | "
            f"Vence: {c.fecha_vencimiento.strftime('%d/%m/%Y')} "
            f"({'en ' + str(dias) + ' días' if dias > 0 else 'VENCIDO'}) | "
            f"Monto: ${c.monto_mensual:,.0f}"
        )
    return "\n".join(lineas)


def _contexto_obras(db: Session) -> str:
    """Recupera el avance de obras activas desde PostgreSQL."""
    obras = db.query(Obra).filter(Obra.estado.in_(["en_curso", "demorada"])).all()
    if not obras:
        return "No hay obras activas en el sistema."

    lineas = ["OBRAS EN CURSO:"]
    for obra in obras:
        etapas = db.query(EtapaObra).filter(EtapaObra.id_obra == obra.id_obra).all()
        avance = sum(float(e.pct_avance) for e in etapas) / len(etapas) if etapas else 0
        lineas.append(f"\n  • {obra.nombre} ({obra.direccion})")
        lineas.append(f"    Estado: {obra.estado} | Avance general: {avance:.1f}%")
        for etapa in etapas:
            lineas.append(f"    - {etapa.nombre_etapa}: {etapa.pct_avance}%")
    return "\n".join(lineas)


def _contexto_comercial(db: Session) -> str:
    """Recupera el pipeline comercial activo desde PostgreSQL."""
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
        dias = (hoy - op.fecha_ultimo_contacto).days if op.fecha_ultimo_contacto else "N/D"
        lineas.append(
            f"  - {cli.apellido}, {cli.nombre} | Etapa: {op.etapa} | "
            f"Operación: {op.tipo_operacion} | Último contacto: hace {dias} días"
        )
    return "\n".join(lineas)


# ── GENERACIÓN DE RESPUESTA (equivalente a la etapa "Generation" de RAG) ────
# En la versión productiva (rag_engine_openai.py) este paso lo realiza
# GPT-4o vía LangChain. En modo demo se infiere la intención de la consulta
# mediante coincidencia de palabras clave sobre el contexto recuperado.

def _generar_respuesta(query: str, contexto: str) -> str:
    q = query.lower()

    if any(w in q for w in ["mora", "moroso", "debe", "adeuda", "atrasad"]):
        lineas = [l for l in contexto.split("\n") if "en mora" in l.lower()]
        if lineas:
            return "Los contratos en mora son:\n" + "\n".join(lineas)
        return "No hay contratos en mora actualmente."

    if any(w in q for w in ["venc", "próximo", "vencer", "expira"]):
        lineas = [l for l in contexto.split("\n") if "por vencer" in l.lower() or "días)" in l]
        if lineas:
            return "Contratos próximos a vencer:\n" + "\n".join(lineas)
        return "No hay contratos próximos a vencer en los próximos 30 días."

    if any(w in q for w in ["obra", "avance", "construc", "uruguay", "racedo"]):
        lineas = [l for l in contexto.split("\n") if "•" in l or "%" in l]
        if lineas:
            return "Estado de obras:\n" + "\n".join(lineas)
        return "No hay obras activas en el sistema."

    if any(w in q for w in ["cliente", "comercial", "pipeline", "negocio", "oportunidad"]):
        lineas = [l for l in contexto.split("\n") if "PIPELINE" in l or " - " in l]
        if lineas:
            return "Pipeline comercial activo:\n" + "\n".join(lineas)
        return "No hay oportunidades comerciales activas."

    return f"Información operativa de RG S.A. disponible para tu consulta:\n\n{contexto}"


# ── PUNTO DE ENTRADA DEL MOTOR RAG ───────────────────────────────────────────

def consultar_asistente(
    query: str,
    db: Session,
    rol_usuario: str,
    modulos_permitidos: list[str]
) -> str:
    """
    Motor RAG en modo demo: combina recuperación transaccional (PostgreSQL)
    con generación de respuesta basada en reglas, replicando el flujo
    conceptual Retrieval-Augmented Generation sin dependencias externas.
    """
    bloques = []
    if "alquileres" in modulos_permitidos:
        bloques.append(_contexto_alquileres(db))
    if "obras" in modulos_permitidos:
        bloques.append(_contexto_obras(db))
    if "comercial" in modulos_permitidos:
        bloques.append(_contexto_comercial(db))

    if not bloques:
        return "No tenés acceso a información operativa con tu perfil actual."

    contexto = "\n\n".join(bloques)
    return _generar_respuesta(query, contexto)


def indexar_documento(db, contenido, tipo_documento, id_referencia=None, metadata=None) -> bool:
    """
    En modo demo no se generan embeddings reales.
    Ver rag_engine_openai.py para la implementación con pgvector + OpenAI.
    """
    return True

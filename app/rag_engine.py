"""
rag_engine.py — Motor RAG simplificado para demo sin API key de OpenAI
RG S.A. — Sistema de Asistencia Inteligente
"""
from __future__ import annotations
from datetime import date
from sqlalchemy.orm import Session
from app.models import Contrato, Inquilino, Obra, EtapaObra, Oportunidad, ClientePotencial


def _contexto_alquileres(db: Session) -> str:
    hoy = date.today()
    contratos = (
        db.query(Contrato, Inquilino).join(Inquilino)
        .filter(Contrato.estado.in_(["al_dia", "en_mora", "por_vencer"])).all()
    )
    if not contratos:
        return "No hay contratos activos."
    lineas = ["CONTRATOS ACTIVOS:"]
    for c, inq in contratos:
        dias = (c.fecha_vencimiento - hoy).days
        lineas.append(
            f"  - {inq.apellido}, {inq.nombre} | {c.estado.upper()} | "
            f"Vence: {c.fecha_vencimiento.strftime('%d/%m/%Y')} "
            f"({'en ' + str(dias) + ' dias' if dias > 0 else 'VENCIDO'}) | "
            f"${c.monto_mensual:,.0f}/mes"
        )
    return "\n".join(lineas)


def _contexto_obras(db: Session) -> str:
    obras = db.query(Obra).filter(Obra.estado.in_(["en_curso", "demorada"])).all()
    if not obras:
        return "No hay obras activas."
    lineas = ["OBRAS EN CURSO:"]
    for obra in obras:
        etapas = db.query(EtapaObra).filter(EtapaObra.id_obra == obra.id_obra).all()
        avance = sum(float(e.pct_avance) for e in etapas) / len(etapas) if etapas else 0
        lineas.append(f"\n  * {obra.nombre} | {obra.estado} | Avance: {avance:.1f}%")
        for e in etapas:
            lineas.append(f"    - {e.nombre_etapa}: {e.pct_avance}%")
    return "\n".join(lineas)


def _contexto_comercial(db: Session) -> str:
    ops = (
        db.query(Oportunidad, ClientePotencial).join(ClientePotencial)
        .filter(Oportunidad.etapa.notin_(["cerrado_ganado", "cerrado_perdido"])).all()
    )
    if not ops:
        return "No hay oportunidades activas."
    hoy = date.today()
    lineas = ["PIPELINE COMERCIAL:"]
    for op, cli in ops:
        dias = (hoy - op.fecha_ultimo_contacto).days if op.fecha_ultimo_contacto else "N/D"
        lineas.append(f"  - {cli.apellido}, {cli.nombre} | {op.etapa} | hace {dias} dias")
    return "\n".join(lineas)


def _respuesta_inteligente(query: str, contexto: str) -> str:
    q = query.lower()
    if any(w in q for w in ["mora", "moroso", "debe"]):
        lineas = [l for l in contexto.split("\n") if "mora" in l.lower()]
        return "Contratos en mora:\n" + "\n".join(lineas) if lineas else "No hay contratos en mora."
    if any(w in q for w in ["venc", "vencer", "expira"]):
        lineas = [l for l in contexto.split("\n") if "por_vencer" in l.lower() or "dias" in l.lower()]
        return "Contratos por vencer:\n" + "\n".join(lineas) if lineas else "No hay contratos proximos a vencer."
    if any(w in q for w in ["obra", "avance", "construc", "uruguay", "racedo"]):
        lineas = [l for l in contexto.split("\n") if "*" in l or "%" in l]
        return "Estado de obras:\n" + "\n".join(lineas) if lineas else "No hay obras activas."
    if any(w in q for w in ["cliente", "comercial", "pipeline"]):
        lineas = [l for l in contexto.split("\n") if "PIPELINE" in l or " - " in l]
        return "Pipeline comercial:\n" + "\n".join(lineas) if lineas else "No hay oportunidades activas."
    return f"Resumen operativo de RG S.A.:\n\n{contexto}"


def consultar_asistente(query, db, rol_usuario, modulos_permitidos):
    bloques = []
    if "alquileres" in modulos_permitidos:
        bloques.append(_contexto_alquileres(db))
    if "obras" in modulos_permitidos:
        bloques.append(_contexto_obras(db))
    if "comercial" in modulos_permitidos:
        bloques.append(_contexto_comercial(db))
    if not bloques:
        return "No tenes acceso a informacion operativa con tu perfil actual."
    contexto = "\n\n".join(bloques)
    return _respuesta_inteligente(query, contexto)


def indexar_documento(db, contenido, tipo_documento, id_referencia=None, metadata=None):
    return True
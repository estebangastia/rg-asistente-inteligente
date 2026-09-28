"""
seed_demo.py — Datos de prueba para la demo del TFG
RG S.A. — Sistema de Asistencia Inteligente

Crea datos realistas para demostrar el funcionamiento del sistema:
  - 3 usuarios (gerencia, administración, jefe de obra)
  - 5 inquilinos con contratos en distintos estados
  - 2 obras activas con etapas
  - 3 clientes en pipeline comercial

Uso:
    python seed_demo.py              → carga los datos solo si la base está vacía
    python seed_demo.py --reiniciar  → borra todo y vuelve a cargar los datos de demo
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from app.database import SessionLocal, init_db, engine
from app.models import (
    Usuario, Inquilino, Inmueble, Contrato,
    Obra, EtapaObra, ClientePotencial, Oportunidad
)
from app.models import Base
from app.auth import hash_password
from app.seguridad import ahora


def _base_con_datos() -> bool:
    from sqlalchemy import inspect, text
    if not inspect(engine).has_table("usuarios"):
        return False
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM usuarios")).scalar() > 0


def seed(reiniciar: bool = False):
    # Si la base ya tiene datos no se toca (así los scripts de arranque se
    # pueden ejecutar siempre). Con --reiniciar se borra todo y se recrea.
    if _base_con_datos() and not reiniciar:
        init_db()  # aplica migraciones pendientes (columnas de seguridad)
        print("La base ya tiene datos: se conservan. Para volver a los datos de demo: python seed_demo.py --reiniciar")
        return
    Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()

    print("Insertando datos de demo...")

    # ── USUARIOS ──────────────────────────────────────────────────
    usuarios = [
        Usuario(
            nombre="Ricardo Gómez",
            email="gerencia@rg-sa.com.ar",
            password_hash=hash_password("Rg2026!gerencia"),
            rol="gerencia",
            password_actualizada=ahora(),
        ),
        Usuario(
            nombre="Ana Martínez",
            email="admin@rg-sa.com.ar",
            password_hash=hash_password("Rg2026!admin"),
            rol="administracion",
            password_actualizada=ahora(),
        ),
        Usuario(
            nombre="Luis Rodríguez",
            email="obras@rg-sa.com.ar",
            password_hash=hash_password("Rg2026!obras"),
            rol="jefe_obra",
            password_actualizada=ahora(),
        ),
    ]
    for u in usuarios:
        db.add(u)
    db.commit()
    print("  ✅ Usuarios creados")

    # ── INQUILINOS E INMUEBLES ────────────────────────────────────
    hoy = date.today()

    inmuebles = [
        Inmueble(direccion="San Martín 450 — 2B, Paraná", tipo="departamento", superficie_m2=58),
        Inmueble(direccion="Urquiza 1200 — PB, Paraná", tipo="local", superficie_m2=80),
        Inmueble(direccion="Bv. Racedo 780 — 3A, Paraná", tipo="departamento", superficie_m2=65),
        Inmueble(direccion="Corrientes 90 — 1C, Paraná", tipo="departamento", superficie_m2=48),
        Inmueble(direccion="Laprida 340 — 4B, Paraná", tipo="departamento", superficie_m2=72),
    ]
    for inm in inmuebles:
        db.add(inm)
    db.commit()

    inquilinos = [
        Inquilino(nombre="Martín", apellido="García", dni="28.456.789", telefono="343-4451122", email="mgarcia@gmail.com"),
        Inquilino(nombre="Ana", apellido="Rodríguez", dni="31.234.567", telefono="343-5566778", email="ana.rod@gmail.com"),
        Inquilino(nombre="Carlos", apellido="López", dni="25.678.901", telefono="343-6677889", email="calopez@gmail.com"),
        Inquilino(nombre="María", apellido="Fernández", dni="33.456.123", telefono="343-7788990", email="mfernandez@gmail.com"),
        Inquilino(nombre="Roberto", apellido="Pérez", dni="29.876.543", telefono="343-8899001", email="rperez@gmail.com"),
    ]
    for inq in inquilinos:
        db.add(inq)
    db.commit()

    contratos = [
        Contrato(
            id_inquilino=inquilinos[0].id_inquilino,
            id_inmueble=inmuebles[0].id_inmueble,
            fecha_inicio=hoy - timedelta(days=180),
            fecha_vencimiento=hoy - timedelta(days=15),  # Vencido → mora
            monto_mensual=185000,
            estado="en_mora",
        ),
        Contrato(
            id_inquilino=inquilinos[1].id_inquilino,
            id_inmueble=inmuebles[1].id_inmueble,
            fecha_inicio=hoy - timedelta(days=90),
            fecha_vencimiento=hoy + timedelta(days=90),
            monto_mensual=210000,
            estado="al_dia",
        ),
        Contrato(
            id_inquilino=inquilinos[2].id_inquilino,
            id_inmueble=inmuebles[2].id_inmueble,
            fecha_inicio=hoy - timedelta(days=150),
            fecha_vencimiento=hoy + timedelta(days=5),  # Por vencer en 5 días
            monto_mensual=175000,
            estado="por_vencer",
        ),
        Contrato(
            id_inquilino=inquilinos[3].id_inquilino,
            id_inmueble=inmuebles[3].id_inmueble,
            fecha_inicio=hoy - timedelta(days=60),
            fecha_vencimiento=hoy + timedelta(days=120),
            monto_mensual=195000,
            estado="al_dia",
        ),
        Contrato(
            id_inquilino=inquilinos[4].id_inquilino,
            id_inmueble=inmuebles[4].id_inmueble,
            fecha_inicio=hoy - timedelta(days=30),
            fecha_vencimiento=hoy + timedelta(days=150),
            monto_mensual=220000,
            estado="al_dia",
        ),
    ]
    for c in contratos:
        db.add(c)
    db.commit()
    print("  ✅ Inquilinos, inmuebles y contratos creados")

    # ── OBRAS ─────────────────────────────────────────────────────
    obras = [
        Obra(
            nombre="Edificio Av. Uruguay 450",
            direccion="Av. Uruguay 450, Paraná",
            fecha_inicio=hoy - timedelta(days=90),
            fecha_fin_estimada=hoy + timedelta(days=90),
            estado="en_curso",
            id_usuario=usuarios[2].id_usuario,
        ),
        Obra(
            nombre="Refacción Bv. Racedo 1200",
            direccion="Bv. Racedo 1200, Paraná",
            fecha_inicio=hoy - timedelta(days=30),
            fecha_fin_estimada=hoy + timedelta(days=60),
            estado="demorada",
            id_usuario=usuarios[2].id_usuario,
        ),
    ]
    for o in obras:
        db.add(o)
    db.commit()

    # Etapas obra 1
    etapas_obra1 = [
        EtapaObra(id_obra=obras[0].id_obra, nombre_etapa="Fundaciones", fecha_inicio_plan=hoy - timedelta(days=90), fecha_fin_plan=hoy - timedelta(days=60), pct_avance=100),
        EtapaObra(id_obra=obras[0].id_obra, nombre_etapa="Estructura", fecha_inicio_plan=hoy - timedelta(days=60), fecha_fin_plan=hoy - timedelta(days=30), pct_avance=100),
        EtapaObra(id_obra=obras[0].id_obra, nombre_etapa="Mampostería", fecha_inicio_plan=hoy - timedelta(days=30), fecha_fin_plan=hoy - timedelta(days=10), pct_avance=80),
        EtapaObra(id_obra=obras[0].id_obra, nombre_etapa="Instalaciones", fecha_inicio_plan=hoy - timedelta(days=10), fecha_fin_plan=hoy + timedelta(days=30), pct_avance=35),
        EtapaObra(id_obra=obras[0].id_obra, nombre_etapa="Terminaciones", fecha_inicio_plan=hoy + timedelta(days=30), fecha_fin_plan=hoy + timedelta(days=90), pct_avance=0),
    ]
    # Etapas obra 2
    etapas_obra2 = [
        EtapaObra(id_obra=obras[1].id_obra, nombre_etapa="Demolición", fecha_inicio_plan=hoy - timedelta(days=30), fecha_fin_plan=hoy - timedelta(days=20), pct_avance=100),
        EtapaObra(id_obra=obras[1].id_obra, nombre_etapa="Obras civiles", fecha_inicio_plan=hoy - timedelta(days=20), fecha_fin_plan=hoy - timedelta(days=5), pct_avance=60),
        EtapaObra(id_obra=obras[1].id_obra, nombre_etapa="Terminaciones", fecha_inicio_plan=hoy - timedelta(days=5), fecha_fin_plan=hoy + timedelta(days=60), pct_avance=10),
    ]
    for e in etapas_obra1 + etapas_obra2:
        db.add(e)
    db.commit()
    print("  ✅ Obras y etapas creadas")

    # ── CLIENTES POTENCIALES ──────────────────────────────────────
    clientes = [
        ClientePotencial(nombre="Jorge", apellido="Suárez", telefono="343-1122334", email="jsuarez@gmail.com", origen_consulta="Instagram"),
        ClientePotencial(nombre="Patricia", apellido="Vega", telefono="343-2233445", email="pvega@hotmail.com", origen_consulta="Referido"),
        ClientePotencial(nombre="Diego", apellido="Morales", telefono="343-3344556", email="dmorales@gmail.com", origen_consulta="WhatsApp"),
    ]
    for cli in clientes:
        db.add(cli)
    db.commit()

    oportunidades = [
        Oportunidad(id_cliente=clientes[0].id_cliente, etapa="propuesta_enviada", fecha_consulta=hoy - timedelta(days=15), fecha_ultimo_contacto=hoy - timedelta(days=3), tipo_operacion="Compra", id_usuario=usuarios[0].id_usuario),
        Oportunidad(id_cliente=clientes[1].id_cliente, etapa="contrato_en_proceso", fecha_consulta=hoy - timedelta(days=30), fecha_ultimo_contacto=hoy - timedelta(days=1), tipo_operacion="Alquiler", id_usuario=usuarios[0].id_usuario),
        Oportunidad(id_cliente=clientes[2].id_cliente, etapa="consulta_recibida", fecha_consulta=hoy - timedelta(days=2), fecha_ultimo_contacto=hoy - timedelta(days=2), tipo_operacion="Lote", id_usuario=usuarios[0].id_usuario),
    ]
    for op in oportunidades:
        db.add(op)
    db.commit()
    print("  ✅ Clientes potenciales y oportunidades creadas")

    db.close()
    print("\n✅ Datos de demo insertados correctamente.")
    print("\nCredenciales de acceso:")
    print("  gerencia@rg-sa.com.ar  / Rg2026!gerencia")
    print("  admin@rg-sa.com.ar     / Rg2026!admin")
    print("  obras@rg-sa.com.ar     / Rg2026!obras")


if __name__ == "__main__":
    seed(reiniciar="--reiniciar" in sys.argv)

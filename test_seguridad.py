"""
test_seguridad.py — Tests de los controles de seguridad, el asistente y el respaldo
RG S.A. — Trabajo Final de Graduación

Verifica que el prototipo implementa lo descripto en la sección Seguridad:
  - Política de complejidad de contraseñas
  - Bloqueo tras 5 intentos fallidos
  - Alta de usuarios solo por Gerencia con cambio obligatorio de contraseña
  - Vencimiento a los 90 días e historial de las últimas 3 contraseñas
  - Log de auditoría y cabeceras HTTP de seguridad
  - Asistente: filtrado por rol y respaldo automático al motor de reglas
  - Copia de seguridad y prueba de restauración

Ejecución (con la base inicializada por seed_demo.py):
    pytest -v
"""
import shutil
import uuid
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from main import app
from app.database import SessionLocal
from app.models import Usuario, HistorialPassword
from app.seguridad import validar_politica_password, generar_password_inicial, ahora
from app import rag_engine

client = TestClient(app)

GERENCIA = ("gerencia@rg-sa.com.ar", "Rg2026!gerencia")
ADMIN = ("admin@rg-sa.com.ar", "Rg2026!admin")
OBRAS = ("obras@rg-sa.com.ar", "Rg2026!obras")


def login(email, password):
    return client.post("/auth/token", data={"username": email, "password": password})


def auth(creds):
    r = login(*creds)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def usuario_nuevo():
    """Crea un usuario de prueba vía Gerencia y lo elimina al terminar."""
    email = f"test_{uuid.uuid4().hex[:8]}@rg-sa.com.ar"
    r = client.post("/usuarios/", headers=auth(GERENCIA),
                    json={"nombre": "Usuario de Prueba", "email": email, "rol": "administracion"})
    assert r.status_code == 201, r.text
    data = r.json()
    yield {"email": email, "password": data["password_inicial"], "id": data["usuario"]["id_usuario"]}
    db = SessionLocal()
    db.query(HistorialPassword).filter(HistorialPassword.id_usuario == data["usuario"]["id_usuario"]).delete()
    db.query(Usuario).filter(Usuario.email == email).delete()
    db.commit()
    db.close()


def cambiar(headers, actual, nueva):
    return client.post("/auth/cambiar-password", headers=headers,
                       json={"password_actual": actual, "password_nueva": nueva})


# ── POLÍTICA DE CONTRASEÑAS ───────────────────────────────────────────────────

class TestPoliticaPasswords:

    @pytest.mark.parametrize("pwd", ["corta1!", "sinmayuscula1!", "SINMINUSCULA1!", "SinNumero!!", "SinEspecial123"])
    def test_rechaza_passwords_debiles(self, pwd):
        assert validar_politica_password(pwd) != []

    def test_acepta_password_fuerte(self):
        assert validar_politica_password("Obra2026!segura") == []

    def test_password_inicial_cumple_politica(self):
        for _ in range(20):
            assert validar_politica_password(generar_password_inicial()) == []


# ── BLOQUEO POR INTENTOS FALLIDOS ─────────────────────────────────────────────

class TestBloqueo:

    def test_bloqueo_tras_5_intentos(self, usuario_nuevo):
        email, pwd = usuario_nuevo["email"], usuario_nuevo["password"]
        for _ in range(4):
            assert login(email, "Incorrecta1!").status_code == 401
        assert login(email, "Incorrecta1!").status_code == 423      # 5.º intento: bloquea
        # Aun con la contraseña correcta, la cuenta sigue bloqueada
        r = login(email, pwd)
        assert r.status_code == 423
        assert "bloqueada" in r.json()["detail"].lower()

    def test_gerencia_puede_desbloquear(self, usuario_nuevo):
        email, pwd = usuario_nuevo["email"], usuario_nuevo["password"]
        for _ in range(5):
            login(email, "Incorrecta1!")
        assert login(email, pwd).status_code == 423
        r = client.post(f"/usuarios/{usuario_nuevo['id']}/activar", headers=auth(GERENCIA))
        assert r.status_code == 200
        assert login(email, pwd).status_code == 200

    def test_mensaje_generico_no_revela_dato(self):
        """El error es el mismo para un email inexistente y para una contraseña incorrecta."""
        a = login("noexiste@rg-sa.com.ar", "Cualquiera1!")
        b = login(ADMIN[0], "Incorrecta1!")
        assert a.status_code == b.status_code == 401
        assert a.json()["detail"] == b.json()["detail"]
        # dejar el contador del usuario de demo en cero
        assert login(*ADMIN).status_code == 200


# ── ALTA POR GERENCIA Y CAMBIO OBLIGATORIO ────────────────────────────────────

class TestAltaYCambioPassword:

    def test_solo_gerencia_da_de_alta(self):
        r = client.post("/usuarios/", headers=auth(ADMIN),
                        json={"nombre": "X", "email": "x@rg-sa.com.ar", "rol": "jefe_obra"})
        assert r.status_code == 403

    def test_rol_invalido(self):
        r = client.post("/usuarios/", headers=auth(GERENCIA),
                        json={"nombre": "X", "email": "x2@rg-sa.com.ar", "rol": "superadmin"})
        assert r.status_code == 422

    def test_primer_ingreso_obliga_a_cambiar(self, usuario_nuevo):
        r = login(usuario_nuevo["email"], usuario_nuevo["password"])
        assert r.status_code == 200
        assert r.json()["debe_cambiar_password"] is True
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        # No puede operar hasta cambiar la contraseña
        assert client.get("/alquileres/contratos", headers=headers).status_code == 403
        assert client.post("/asistente/consulta", headers=headers, json={"pregunta": "mora"}).status_code == 403
        # Contraseña débil: rechazada
        assert cambiar(headers, usuario_nuevo["password"], "debil").status_code == 400
        # Contraseña válida: aceptada y ya puede operar
        assert cambiar(headers, usuario_nuevo["password"], "Alquiler2026!ok").status_code == 200
        assert client.get("/alquileres/contratos", headers=headers).status_code == 200

    def test_no_reutiliza_ultimas_3(self, usuario_nuevo):
        r = login(usuario_nuevo["email"], usuario_nuevo["password"])
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        claves = [usuario_nuevo["password"], "Primera2026!a", "Segunda2026!b", "Tercera2026!c"]
        for anterior, nueva in zip(claves, claves[1:]):
            assert cambiar(headers, anterior, nueva).status_code == 200
        # Volver a cualquiera de las últimas 3 anteriores o a la actual: rechazado
        for repetida in ["Tercera2026!c", "Segunda2026!b", "Primera2026!a"]:
            assert cambiar(headers, "Tercera2026!c", repetida).status_code == 400

    def test_password_vencida_a_los_90_dias(self, usuario_nuevo):
        db = SessionLocal()
        u = db.query(Usuario).filter(Usuario.email == usuario_nuevo["email"]).first()
        u.debe_cambiar_password = False
        u.password_actualizada = ahora() - timedelta(days=91)
        db.commit()
        db.close()
        r = login(usuario_nuevo["email"], usuario_nuevo["password"])
        assert r.status_code == 200
        assert r.json()["debe_cambiar_password"] is True

    def test_usuario_desactivado_no_ingresa(self, usuario_nuevo):
        assert client.post(f"/usuarios/{usuario_nuevo['id']}/desactivar", headers=auth(GERENCIA)).status_code == 200
        assert login(usuario_nuevo["email"], usuario_nuevo["password"]).status_code == 401


# ── AUDITORÍA Y CABECERAS ─────────────────────────────────────────────────────

class TestAuditoria:

    def test_eventos_registrados(self, usuario_nuevo):
        for _ in range(5):
            login(usuario_nuevo["email"], "Incorrecta1!")
        eventos = client.get("/seguridad/auditoria", headers=auth(GERENCIA)).json()
        propios = [e["evento"] for e in eventos if e["email"] == usuario_nuevo["email"]]
        assert "login_fallido" in propios
        assert "cuenta_bloqueada" in propios

    def test_auditoria_solo_gerencia(self):
        assert client.get("/seguridad/auditoria", headers=auth(OBRAS)).status_code == 403

    def test_acceso_denegado_queda_auditado(self):
        client.get("/obras/", headers=auth(ADMIN))
        eventos = client.get("/seguridad/auditoria?limite=20", headers=auth(GERENCIA)).json()
        assert any(e["evento"] == "acceso_denegado" and e["email"] == ADMIN[0] for e in eventos)

    def test_auditoria_no_guarda_passwords(self):
        login(ADMIN[0], "ClaveSecreta99!")
        login(*ADMIN)
        eventos = client.get("/seguridad/auditoria?limite=50", headers=auth(GERENCIA)).json()
        assert not any("ClaveSecreta99!" in (e["detalle"] or "") for e in eventos)

    def test_cabeceras_de_seguridad(self):
        r = client.get("/api/health")
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"


# ── ASISTENTE: FILTRADO POR ROL Y RESPALDO ────────────────────────────────────

class TestAsistente:

    def test_contexto_filtrado_por_rol(self):
        db = SessionLocal()
        ctx_obras = rag_engine.recuperar_contexto(db, ["obras", "asistente"])
        ctx_admin = rag_engine.recuperar_contexto(db, ["alquileres", "comercial", "asistente"])
        db.close()
        assert "CONTRATOS" not in ctx_obras and "PIPELINE" not in ctx_obras
        assert "OBRAS" not in ctx_admin

    def test_jefe_obra_no_obtiene_datos_de_alquileres(self):
        r = client.post("/asistente/consulta", headers=auth(OBRAS), json={"pregunta": "¿Cuántos contratos están en mora?"})
        assert r.status_code == 200
        assert "García" not in r.json()["respuesta"]
        assert "no tiene acceso" in r.json()["respuesta"].lower()

    def test_respuesta_informa_motor(self):
        r = client.post("/asistente/consulta", headers=auth(GERENCIA), json={"pregunta": "¿Quién está en mora?"})
        assert r.status_code == 200
        assert r.json()["motor"]

    def test_usa_modelo_de_lenguaje_si_esta_configurado(self, monkeypatch):
        monkeypatch.setattr(rag_engine, "configuracion_llm", lambda: ("http://x", "modelo-prueba", "groq"))
        monkeypatch.setattr(rag_engine, "_generar_con_llm", lambda *a, **k: "Respuesta del modelo")
        r = client.post("/asistente/consulta", headers=auth(GERENCIA), json={"pregunta": "¿Quién me debe plata?"})
        assert r.json()["respuesta"] == "Respuesta del modelo"
        assert "groq" in r.json()["motor"]

    def test_si_el_modelo_falla_responde_con_reglas(self, monkeypatch):
        def falla(*a, **k):
            raise ConnectionError("sin internet")
        monkeypatch.setattr(rag_engine, "configuracion_llm", lambda: ("http://x", "modelo-prueba", "groq"))
        monkeypatch.setattr(rag_engine, "_generar_con_llm", falla)
        r = client.post("/asistente/consulta", headers=auth(GERENCIA), json={"pregunta": "¿Cuántos contratos están en mora?"})
        assert r.status_code == 200
        assert "reglas" in r.json()["motor"]
        assert "García" in r.json()["respuesta"]

    def test_comercial_por_rol(self):
        assert client.get("/comercial/oportunidades", headers=auth(ADMIN)).status_code == 200
        assert client.get("/comercial/oportunidades", headers=auth(OBRAS)).status_code == 403


# ── RESPALDO Y RESTAURACIÓN ───────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("pg_dump") is None and shutil.which("pg_dump.exe") is None,
                    reason="pg_dump no está en el PATH")
class TestRespaldo:

    def test_backup_y_prueba_de_restauracion(self):
        h = auth(GERENCIA)
        r = client.post("/seguridad/backups", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["archivo"].endswith(".dump")
        v = client.post("/seguridad/backups/verificar", headers=h)
        assert v.status_code == 200, v.text
        assert v.json()["resultado"] in ("OK", "DIFERENCIAS")
        assert v.json()["tablas"]["contratos"]["backup"] >= 5

    def test_backup_solo_gerencia(self):
        assert client.post("/seguridad/backups", headers=auth(ADMIN)).status_code == 403

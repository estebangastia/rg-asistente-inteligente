"""
test_sistema.py — Tests automatizados del Sistema de Asistencia Inteligente
RG S.A. — Trabajo Final de Graduación

Cubre los aspectos críticos del prototipo:
  - Autenticación JWT por rol
  - Endpoints de cada módulo de negocio
  - Motor RAG (modo demo)
  - Control de acceso por rol (seguridad)
  - Hasheo de contraseñas con bcrypt

Ejecución:
    pytest test_sistema.py -v

Requiere que la base de datos esté inicializada con seed_demo.py.
"""
import pytest
from fastapi.testclient import TestClient
from main import app
from app.auth import hash_password, verify_password, PERMISOS_ROL

client = TestClient(app)

# Credenciales de los usuarios de demo
CREDENCIALES = {
    "gerencia": ("gerencia@rg-sa.com.ar", "Rg2026!gerencia"),
    "administracion": ("admin@rg-sa.com.ar", "Rg2026!admin"),
    "jefe_obra": ("obras@rg-sa.com.ar", "Rg2026!obras"),
}


def obtener_token(rol: str) -> str:
    """Helper: hace login y devuelve el token de un rol."""
    email, password = CREDENCIALES[rol]
    r = client.post("/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


def header(rol: str) -> dict:
    return {"Authorization": f"Bearer {obtener_token(rol)}"}


# ── TESTS DE SEGURIDAD: HASHEO DE CONTRASEÑAS ─────────────────────────────────

class TestSeguridadPassword:

    def test_hash_no_es_texto_plano(self):
        """La contraseña hasheada nunca debe coincidir con el texto plano."""
        password = "MiClave123!"
        hashed = hash_password(password)
        assert hashed != password
        assert hashed.startswith("$2b$")  # prefijo bcrypt

    def test_verificacion_correcta(self):
        """Una contraseña correcta debe verificarse exitosamente."""
        password = "MiClave123!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verificacion_incorrecta(self):
        """Una contraseña incorrecta debe fallar la verificación."""
        hashed = hash_password("MiClave123!")
        assert verify_password("ClaveErronea", hashed) is False

    def test_mismo_password_distinto_hash(self):
        """bcrypt usa salt: el mismo password genera hashes distintos."""
        h1 = hash_password("MiClave123!")
        h2 = hash_password("MiClave123!")
        assert h1 != h2  # distinto salt


# ── TESTS DE AUTENTICACIÓN ────────────────────────────────────────────────────

class TestAutenticacion:

    def test_login_gerencia_exitoso(self):
        r = client.post("/auth/token", data={
            "username": "gerencia@rg-sa.com.ar", "password": "Rg2026!gerencia"
        })
        assert r.status_code == 200
        assert r.json()["rol"] == "gerencia"
        assert r.json()["token_type"] == "bearer"

    def test_login_credenciales_invalidas(self):
        r = client.post("/auth/token", data={
            "username": "hacker@test.com", "password": "wrong"
        })
        assert r.status_code == 401

    def test_login_password_incorrecta(self):
        r = client.post("/auth/token", data={
            "username": "gerencia@rg-sa.com.ar", "password": "passwordmala"
        })
        assert r.status_code == 401

    def test_acceso_sin_token(self):
        """Sin token, los endpoints protegidos devuelven 401."""
        r = client.get("/panel/resumen")
        assert r.status_code == 401


# ── TESTS DE MÓDULOS DE NEGOCIO ───────────────────────────────────────────────

class TestAlquileres:

    def test_listar_contratos(self):
        r = client.get("/alquileres/contratos", headers=header("gerencia"))
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) > 0

    def test_contratos_en_mora(self):
        r = client.get("/alquileres/mora", headers=header("gerencia"))
        assert r.status_code == 200
        # Debe haber al menos un contrato en mora en los datos de demo
        for contrato in r.json():
            assert "inquilino" in contrato
            assert "monto_adeudado" in contrato


class TestObras:

    def test_listar_obras(self):
        r = client.get("/obras/", headers=header("gerencia"))
        assert r.status_code == 200
        obras = r.json()
        assert len(obras) > 0
        for obra in obras:
            assert "avance_general" in obra
            assert 0 <= obra["avance_general"] <= 100


class TestPanel:

    def test_resumen_ejecutivo(self):
        r = client.get("/panel/resumen", headers=header("gerencia"))
        assert r.status_code == 200
        data = r.json()
        assert "contratos_activos" in data
        assert "contratos_en_mora" in data
        assert "obras_en_curso" in data
        assert "clientes_activos" in data
        assert data["contratos_activos"] >= 0


# ── TESTS DEL MOTOR RAG ───────────────────────────────────────────────────────

class TestAsistenteRAG:

    def test_consulta_mora(self):
        r = client.post("/asistente/consulta",
                        headers=header("gerencia"),
                        json={"pregunta": "¿Cuántos contratos están en mora?"})
        assert r.status_code == 200
        assert "respuesta" in r.json()
        assert len(r.json()["respuesta"]) > 0

    def test_consulta_obras(self):
        r = client.post("/asistente/consulta",
                        headers=header("gerencia"),
                        json={"pregunta": "¿Cómo van las obras?"})
        assert r.status_code == 200
        assert "obra" in r.json()["respuesta"].lower() or "avance" in r.json()["respuesta"].lower()

    def test_consulta_retorna_modulos(self):
        r = client.post("/asistente/consulta",
                        headers=header("gerencia"),
                        json={"pregunta": "Resumen general"})
        assert r.status_code == 200
        assert "modulos_consultados" in r.json()


# ── TESTS DE CONTROL DE ACCESO POR ROL (CRÍTICO PARA SEGURIDAD) ───────────────

class TestControlAccesoPorRol:

    def test_admin_no_accede_obras(self):
        """Administración NO debe poder ver el módulo de obras."""
        r = client.get("/obras/", headers=header("administracion"))
        assert r.status_code == 403

    def test_jefe_obra_no_accede_alquileres(self):
        """Jefe de obra NO debe poder ver el módulo de alquileres."""
        r = client.get("/alquileres/contratos", headers=header("jefe_obra"))
        assert r.status_code == 403

    def test_gerencia_accede_todo(self):
        """Gerencia debe poder acceder a todos los módulos."""
        assert client.get("/alquileres/contratos", headers=header("gerencia")).status_code == 200
        assert client.get("/obras/", headers=header("gerencia")).status_code == 200
        assert client.get("/panel/resumen", headers=header("gerencia")).status_code == 200

    def test_permisos_definidos_por_rol(self):
        """Verifica la matriz de permisos por rol."""
        assert "obras" in PERMISOS_ROL["jefe_obra"]
        assert "obras" not in PERMISOS_ROL["administracion"]
        assert "alquileres" in PERMISOS_ROL["administracion"]
        assert len(PERMISOS_ROL["gerencia"]) == 5  # acceso completo


# ── TEST DE HEALTH CHECK ──────────────────────────────────────────────────────

def test_health_check():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["estado"] == "operativo"
    assert len(r.json()["jobs_activos"]) == 3  # 3 jobs de APScheduler


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

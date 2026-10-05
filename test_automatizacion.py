"""
test_automatizacion.py — Tests de los avisos automáticos
RG S.A. — Trabajo Final de Graduación

Verifica los jobs de APScheduler (ejecutados a mano), el registro en la
tabla NOTIFICACION y el envío por SendGrid (simulado con un mock, sin
mandar mails reales).
"""
from datetime import date
import httpx
import pytest
from fastapi.testclient import TestClient
from main import app
from app import notificador
from app.database import SessionLocal
from app.models import Contrato, Inquilino

client = TestClient(app)


def auth(email, password):
    r = client.post("/auth/token", data={"username": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


GER = ("gerencia@rg-sa.com.ar", "Rg2026!gerencia")
ADM = ("admin@rg-sa.com.ar", "Rg2026!admin")


class TestNotificador:

    def test_sin_canal_es_simulado(self, monkeypatch):
        monkeypatch.setattr(notificador.settings, "resend_api_key", "")
        monkeypatch.setattr(notificador.settings, "sendgrid_api_key", "")
        monkeypatch.setattr(notificador.settings, "smtp_user", "")
        estado, _ = notificador.enviar_email("a@b.com", "Asunto", "<p>x</p>")
        assert estado == "simulado"

    def test_sendgrid_ok(self, monkeypatch):
        llamadas = []

        def falso_post(url, json, timeout, headers):
            llamadas.append((url, json, headers))
            return httpx.Response(202)

        monkeypatch.setattr(notificador.settings, "resend_api_key", "")
        monkeypatch.setattr(notificador.settings, "sendgrid_api_key", "SG.prueba")
        monkeypatch.setattr(notificador.settings, "email_from", "avisos@ejemplo.com")
        monkeypatch.setattr(notificador.httpx, "post", falso_post)
        estado, _ = notificador.enviar_email("destino@ejemplo.com", "Asunto", "<p>x</p>")
        assert estado == "enviado"
        url, payload, headers = llamadas[0]
        assert url == notificador.SENDGRID_URL
        assert payload["personalizations"][0]["to"][0]["email"] == "destino@ejemplo.com"
        assert headers["Authorization"] == "Bearer SG.prueba"

    def test_resend_ok(self, monkeypatch):
        llamadas = []

        def falso_post(url, timeout, headers, json):
            llamadas.append((url, json, headers))
            return httpx.Response(200, json={"id": "abc"})

        monkeypatch.setattr(notificador.settings, "resend_api_key", "re_prueba")
        monkeypatch.setattr(notificador.settings, "resend_from", "")
        monkeypatch.setattr(notificador.httpx, "post", falso_post)
        estado, _ = notificador.enviar_email("yo@gmail.com", "Asunto", "<p>x</p>")
        assert estado == "enviado"
        url, payload, headers = llamadas[0]
        assert url == notificador.RESEND_URL
        assert "onboarding@resend.dev" in payload["from"]   # sin dominio propio
        assert payload["to"] == ["yo@gmail.com"]
        assert headers["Authorization"] == "Bearer re_prueba"

    def test_sendgrid_error_no_rompe(self, monkeypatch):
        monkeypatch.setattr(notificador.settings, "resend_api_key", "")
        def falla(*a, **k):
            raise httpx.ConnectError("sin red")
        monkeypatch.setattr(notificador.settings, "sendgrid_api_key", "SG.prueba")
        monkeypatch.setattr(notificador.httpx, "post", falla)
        estado, detalle = notificador.enviar_email("d@e.com", "A", "<p>x</p>")
        assert estado == "fallido" and "ConnectError" in detalle


class TestJobsManuales:

    def test_solo_gerencia(self):
        assert client.post("/automatizacion/ejecutar/mora", headers=auth(*ADM)).status_code == 403

    def test_job_inexistente(self):
        assert client.post("/automatizacion/ejecutar/otro", headers=auth(*GER)).status_code == 404

    def test_vencimientos_registra_notificacion(self):
        h = auth(*GER)
        r = client.post("/automatizacion/ejecutar/vencimientos", headers=h)
        assert r.status_code == 200
        assert r.json()["detectados"] >= 1          # López vence en 5 días
        avisos = client.get("/automatizacion/notificaciones", headers=h).json()
        assert any("López" in (a["asunto"] or "") for a in avisos)

    def test_vencimientos_no_pisa_la_mora(self):
        db = SessionLocal()
        c = db.query(Contrato).join(Inquilino).filter(Inquilino.apellido == "López").first()
        c.estado = "en_mora"
        db.commit()
        client.post("/automatizacion/ejecutar/vencimientos", headers=auth(*GER))
        db.refresh(c)
        assert c.estado == "en_mora"
        c.estado = "por_vencer"
        db.commit()
        db.close()

    def test_desvios_registra_aviso_de_obra(self):
        h = auth(*GER)
        r = client.post("/automatizacion/ejecutar/desvios", headers=h).json()
        assert r["detectados"] >= 1                  # Mampostería y Obras civiles demoradas
        avisos = client.get("/automatizacion/notificaciones", headers=h).json()
        assert any(a["tipo"] == "desvio_obra" for a in avisos)

    @pytest.mark.skipif(date.today().day < 6, reason="la mora del día 1 se detecta a partir del día 6")
    def test_mora_detecta_solo_a_perez(self):
        r = client.post("/automatizacion/ejecutar/mora", headers=auth(*GER)).json()
        db = SessionLocal()
        estados = {i.apellido: c.estado for c, i in db.query(Contrato, Inquilino).join(Inquilino).all()}
        db.close()
        assert estados["Pérez"] == "en_mora"
        assert estados["Rodríguez"] == "al_dia" and estados["Fernández"] == "al_dia"
        assert r["detectados"] >= 0

    def test_estado_muestra_canal(self):
        r = client.get("/automatizacion/estado", headers=auth(*GER)).json()
        assert "canal_email" in r and len(r["jobs"]) == 3

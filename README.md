# Sistema de Asistencia Inteligente — RG S.A.
**Trabajo Final de Graduación — Licenciatura en Informática**
**Universidad Siglo 21 — Gastiazoro, Juan Esteban — VINF011565**

---

## Descripción

Sistema de asistencia inteligente para la gestión operativa de RG S.A., basado en la técnica
RAG (Retrieval-Augmented Generation) que cruza datos transaccionales de PostgreSQL con
documentos vectorizados en pgvector para responder consultas en lenguaje natural mediante GPT-4o.

**Stack tecnológico:**
- Backend: Python 3.11 + FastAPI
- Base de datos: PostgreSQL 16 + pgvector
- IA: LangChain + OpenAI GPT-4o
- Automatización: APScheduler
- Autenticación: JWT + bcrypt

---

## Requisitos previos

- Python 3.11+
- PostgreSQL 16 con extensión pgvector instalada
- Cuenta de OpenAI con API key activa

---

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/[usuario]/rg-asistente-inteligente.git
cd rg-asistente-inteligente
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
```

Editar `.env` con los valores reales:
- `DATABASE_URL`: URL de conexión a PostgreSQL
- `OPENAI_API_KEY`: API key de OpenAI
- `SECRET_KEY`: clave secreta para JWT (mínimo 32 caracteres)
- Datos SMTP para el envío de notificaciones

### 4. Inicializar la base de datos y cargar datos de demo

```bash
python seed_demo.py
```

Esto crea todas las tablas, habilita pgvector y carga datos de prueba realistas
de RG S.A. (contratos, obras, clientes y usuarios).

### 5. Iniciar la aplicación

```bash
uvicorn main:app --reload --port 8000
```

La API estará disponible en: `http://localhost:8000`
Documentación interactiva (Swagger): `http://localhost:8000/docs`

---

## Uso de la API

### Autenticación

```bash
curl -X POST http://localhost:8000/auth/token \
  -d "username=gerencia@rg-sa.com.ar&password=Rg2026!gerencia"
```

Respuesta:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "rol": "gerencia"
}
```

### Consulta al asistente conversacional

```bash
curl -X POST http://localhost:8000/asistente/consulta \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
  -d '{"pregunta": "¿Cuántos contratos están en mora?"}'
```

### Ejemplos de consultas al asistente

| Consulta | Módulo |
|---|---|
| ¿Cuántos contratos están en mora? | Alquileres |
| ¿Cómo va la obra de Av. Uruguay? | Obras |
| ¿Qué clientes están esperando propuesta? | Comercial |
| ¿Qué contratos vencen este mes? | Alquileres |
| Resumí el estado de todas las obras | Obras |

---

## Credenciales de demo

| Email | Contraseña | Rol |
|---|---|---|
| gerencia@rg-sa.com.ar | Rg2026!gerencia | Gerencia (acceso completo) |
| admin@rg-sa.com.ar | Rg2026!admin | Administración |
| obras@rg-sa.com.ar | Rg2026!obras | Jefe de obra |

---

## Estructura del proyecto

```
rg_asistente/
├── main.py              # Punto de entrada FastAPI
├── requirements.txt     # Dependencias Python
├── seed_demo.py         # Datos de prueba para la demo
├── .env.example         # Variables de entorno (plantilla)
├── app/
│   ├── config.py        # Configuración centralizada
│   ├── database.py      # Conexión PostgreSQL + init
│   ├── models.py        # Modelos ORM (13 entidades)
│   ├── auth.py          # JWT + bcrypt + control de acceso
│   ├── rag_engine.py    # Motor RAG (núcleo del asistente)
│   └── routers.py       # Endpoints FastAPI
└── jobs/
    └── scheduler.py     # Jobs APScheduler (automatización)
```

---

## Jobs automáticos

El sistema ejecuta tres jobs diarios sin intervención manual:

| Job | Hora | Función |
|---|---|---|
| verificar_vencimientos | 08:00 | Detecta contratos por vencer (30 y 7 días) |
| verificar_mora | 08:30 | Detecta mora a partir de 5 días de retraso |
| verificar_desvios_obra | 09:00 | Detecta etapas de obra demoradas |

---

## Referencias técnicas

- Lewis, P. et al. (2020). Retrieval-Augmented Generation for knowledge-intensive NLP tasks.
- Vaswani, A. et al. (2017). Attention is all you need.
- Provos, N. & Mazières, D. (1999). A future-adaptable password scheme (bcrypt).
- Tanenbaum, A. S. & Woodhull, A. S. (2006). Sistemas operativos (APScheduler).

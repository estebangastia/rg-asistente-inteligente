# Sistema de Asistencia Inteligente — RG S.A.

**Trabajo Final de Graduación — Licenciatura en Informática**
**Universidad Siglo 21 — Gastiazoro, Juan Esteban — VINF011565**
**Director: Prof. Pablo Virgolini**

---

## Descripción

Sistema de asistencia inteligente para la gestión operativa de RG S.A., una empresa
constructora e inmobiliaria PyME de Paraná, Entre Ríos. El sistema centraliza la
información de alquileres, obras y clientes en una única base de datos relacional y
permite consultarla en lenguaje natural mediante un asistente conversacional basado en
la tecnica RAG (Retrieval-Augmented Generation; Lewis et al., 2020). Ademas, automatiza
las comunicaciones recurrentes (vencimientos, mora, desvios de obra) mediante tareas
programadas.

**Stack tecnologico:**
- Backend: Python 3.12 + FastAPI
- Base de datos: PostgreSQL 16 (con pgvector opcional)
- IA: LangChain + OpenAI GPT-4o (modo productivo) / motor basado en reglas (modo demo)
- Automatizacion: APScheduler
- Autenticacion: JWT + bcrypt
- Interfaz: HTML/CSS/JavaScript (SPA servida por FastAPI)

---

## Formas de ejecutar el sistema

Hay tres maneras de levantar el prototipo, ordenadas de mas simple a mas manual.

### Opcion A — Docker (recomendada, un solo comando)

Es la forma mas simple: no requiere instalar Python ni PostgreSQL, solo Docker.

```bash
docker compose up
```

Esto levanta la base de datos PostgreSQL (con pgvector), inicializa las tablas, carga
los datos de demo y arranca el servidor automaticamente. Una vez iniciado:

- Interfaz web:  http://localhost:8000
- API (Swagger): http://localhost:8000/docs

Para detener: Ctrl+C y luego `docker compose down`.

### Opcion B — Script de arranque automatico

Si se tiene Python y PostgreSQL instalados localmente:

- Windows: doble clic en `iniciar_windows.bat`
- Linux/macOS: `bash iniciar_linux_mac.sh`

El script crea el entorno virtual, instala dependencias, genera el `.env`, inicializa la
base de datos y levanta el servidor.

### Opcion C — Instalacion manual paso a paso

```bash
# 1. Entorno virtual
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate             # Windows

# 2. Dependencias
pip install -r requirements.txt

# 3. Configuracion
cp .env.example .env              # ajustar DATABASE_URL con los datos de PostgreSQL

# 4. Base de datos (crear previamente en PostgreSQL):
#    CREATE USER rg_user WITH PASSWORD 'rg2026';
#    CREATE DATABASE rg_asistente OWNER rg_user;

# 5. Inicializar tablas + datos de demo
python seed_demo.py

# 6. Levantar
uvicorn main:app --reload --port 8000
```

---

## Credenciales de demo

| Email | Contrasena | Rol | Acceso |
|---|---|---|---|
| gerencia@rg-sa.com.ar | Rg2026!gerencia | Gerencia | Todos los modulos |
| admin@rg-sa.com.ar | Rg2026!admin | Administracion | Alquileres y comercial |
| obras@rg-sa.com.ar | Rg2026!obras | Jefe de obra | Solo obras |

En la pantalla de login se puede hacer clic en cada usuario de demo para autocompletar
las credenciales.

---

## Tests automatizados

El proyecto incluye una suite de 20 tests que cubren autenticacion, endpoints de cada
modulo, el motor RAG y el control de acceso por rol:

```bash
pytest test_sistema.py -v
```

Los tests requieren que la base de datos este inicializada (`python seed_demo.py`).

---

## Dos versiones del motor RAG

El sistema incluye dos implementaciones del motor conversacional, ambas descriptas en
el marco teorico del TFG:

| Archivo | Cuando se usa | Requiere |
|---|---|---|
| `app/rag_engine.py` | Por defecto. Se ejecuta sin configuracion adicional. | Solo PostgreSQL |
| `app/rag_engine_openai.py` | Implementacion productiva completa | API key de OpenAI + pgvector |

El motor por defecto (`rag_engine.py`) recupera el contexto operativo real desde
PostgreSQL y genera la respuesta en lenguaje natural mediante reglas de coincidencia
sobre la intencion de la consulta, replicando el flujo conceptual Retrieval -> Generation
sin depender de servicios externos. Esto permite que cualquier evaluador clone el
repositorio y ejecute el sistema completo sin necesidad de credenciales de OpenAI.

Para activar la version completa con GPT-4o y busqueda semantica:
1. Instalar pgvector: https://github.com/pgvector/pgvector
2. Configurar `OPENAI_API_KEY` en `.env`
3. Descomentar `embedding = Column(Vector(1536))` en `app/models.py`
4. Reemplazar el contenido de `app/rag_engine.py` por el de `app/rag_engine_openai.py`

Ambos archivos comparten la misma firma de funcion, por lo que el resto del sistema no
requiere cambios al alternar entre ellos.

---

## Estructura del proyecto

```
rg_asistente/
|-- docker-compose.yml          # Orquestacion Docker (opcion A)
|-- Dockerfile                  # Imagen de la aplicacion
|-- iniciar_windows.bat         # Script de arranque Windows (opcion B)
|-- iniciar_linux_mac.sh        # Script de arranque Linux/Mac (opcion B)
|-- main.py                     # Punto de entrada FastAPI
|-- requirements.txt            # Dependencias Python
|-- seed_demo.py                # Datos de prueba
|-- test_sistema.py             # Suite de 20 tests automatizados
|-- .env.example                # Plantilla de variables de entorno
|-- README.md
|-- static/
|   `-- index.html              # Interfaz web (SPA)
|-- app/
|   |-- config.py
|   |-- database.py
|   |-- models.py               # 13 entidades ORM + DocumentoVectorial
|   |-- auth.py                 # JWT + bcrypt + control de acceso
|   |-- rag_engine.py           # Motor RAG - MODO DEMO (activo)
|   |-- rag_engine_openai.py    # Motor RAG - MODO PRODUCTIVO (referencia)
|   `-- routers.py              # Endpoints de la API
`-- jobs/
    `-- scheduler.py            # Jobs APScheduler (automatizacion)
```

---

## Endpoints principales

| Metodo | Ruta | Descripcion | Roles |
|---|---|---|---|
| POST | `/auth/token` | Login y generacion de JWT | Todos |
| POST | `/asistente/consulta` | Consulta al motor RAG | Segun permisos |
| GET | `/alquileres/contratos` | Contratos activos | Gerencia, Administracion |
| GET | `/alquileres/mora` | Contratos en mora | Gerencia, Administracion |
| GET | `/obras/` | Obras con avance por etapa | Gerencia, Jefe de obra |
| GET | `/panel/resumen` | Indicadores ejecutivos | Gerencia |
| GET | `/api/health` | Estado del sistema | Publico |

---

## Jobs automaticos (APScheduler)

| Job | Hora | Funcion |
|---|---|---|
| Verificacion de vencimientos | 08:00 | Detecta contratos por vencer (30 y 7 dias) |
| Verificacion de mora | 08:30 | Detecta mora a partir de 5 dias de retraso |
| Verificacion de desvios de obra | 09:00 | Detecta etapas de obra demoradas |

---

## Referencias tecnicas

- Lewis, P. et al. (2020). Retrieval-Augmented Generation for knowledge-intensive NLP tasks.
- Vaswani, A. et al. (2017). Attention is all you need.
- Provos, N. & Mazieres, D. (1999). A future-adaptable password scheme (bcrypt).

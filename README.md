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
- IA: LangChain + modelo de lenguaje configurable (OpenAI GPT-4o en produccion; Groq,
  Gemini u OpenRouter gratuitos para la demo) con respaldo automatico a un motor de reglas
- Automatizacion: APScheduler (notificaciones y copia de seguridad diaria)
- Seguridad: JWT + bcrypt, bloqueo por intentos, politica y vencimiento de contrasenas,
  alta de usuarios por Gerencia, log de auditoria, respaldo con prueba de restauracion
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

# 5. Inicializar tablas + datos de demo (solo si la base esta vacia)
python seed_demo.py
#    Para volver a los datos de demo originales: python seed_demo.py --reiniciar
#    (en un despliegue en la nube: botón "Reiniciar datos de demo" en Automatización, solo Gerencia)

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

## Activar el modelo de lenguaje (opcional, gratis)

Sin configuracion, el asistente responde con el motor de reglas local. Para que
responda un modelo de lenguaje real:

1. Crear una API key gratuita en https://console.groq.com/keys (no pide tarjeta).
2. En el archivo `.env` completar:
   ```
   LLM_PROVIDER=groq
   LLM_API_KEY=gsk_...
   ```
3. Reiniciar el servidor. En `http://localhost:8000/api/health` el campo `motor_ia`
   muestra el modelo activo, y cada respuesta del asistente indica que motor la genero.

Tambien funciona con `LLM_PROVIDER=openai` (GPT-4o, pago), `gemini` u `openrouter`.
Si el proveedor no responde (sin internet o limite de uso alcanzado), el asistente
vuelve automaticamente al motor de reglas: la demo nunca queda sin respuesta.

---

## Avisos por email

Los jobs mandan los avisos por **Resend** o **SendGrid** (API HTTPS) y los registran en la tabla
`notificaciones`. Configurar en `.env` (o en las variables de Railway):

```
RESEND_API_KEY=re_...      # o SENDGRID_API_KEY=SG....
EMAIL_FROM=remitente_verificado@...
EMAIL_NOTIFICACIONES=casilla_de_avisos@...
```

Sin ninguna key (ni SMTP) los avisos se registran como **simulados**: la demo
funciona igual. Desde la interfaz, Gerencia → **Automatizacion** permite ejecutar
cada job en el momento, enviar un email de prueba y ver los avisos generados.

---

## Seguridad implementada

| Control | Implementacion |
|---|---|
| Almacenamiento de contrasenas | bcrypt con 12 rondas y salt aleatorio |
| Sesion | JWT HS256 de 8 horas; solo contiene email y rol |
| Control de acceso | Permisos por rol en cada endpoint y en el contexto del asistente |
| Bloqueo de cuenta | 5 intentos fallidos consecutivos → 15 minutos |
| Complejidad | 8+ caracteres, mayuscula, minuscula, numero y caracter especial |
| Vencimiento | Cambio obligatorio a los 90 dias; no se repiten las ultimas 3 |
| Alta de usuarios | Solo Gerencia; contrasena inicial aleatoria con cambio en el primer ingreso |
| Baja | Desactivacion sin borrado, conserva la trazabilidad |
| Auditoria | Login ok/fallido, bloqueos, accesos denegados, altas, cambios, backups, consultas |
| Cabeceras HTTP | X-Frame-Options, X-Content-Type-Options, Referrer-Policy |
| Respaldo | Copia diaria 00:00 con pg_dump, retencion 7 dias, prueba de restauracion |

Todo se puede ver desde la interfaz con el usuario de Gerencia, en las secciones
**Usuarios** y **Seguridad**.

### Copias de seguridad por consola

```bash
python backup.py              # genera una copia ahora (carpeta backups/)
python backup.py --verificar  # restaura la ultima copia en una base temporal y compara
python backup.py --listar     # lista las copias disponibles
```

Requiere `pg_dump` y `pg_restore` (vienen con PostgreSQL). En Windows se detectan
solos en `C:\Program Files\PostgreSQL\<version>\bin`; si no, configurar `PG_BIN_DIR`.

---

## Tests automatizados

El proyecto incluye 59 tests: autenticacion, endpoints de cada modulo, motor RAG,
control de acceso por rol, controles de seguridad y respaldo.

```bash
pytest -v
```

Los tests requieren que la base de datos este inicializada (`python seed_demo.py`).

---

## Motor RAG

`app/rag_engine.py` (activo):
1. **Recuperacion:** consulta PostgreSQL y arma el contexto (alquileres, obras, pipeline)
   solo con los modulos permitidos para el rol del usuario.
2. **Generacion:** envia contexto y pregunta al modelo de lenguaje via LangChain. Si no
   hay modelo configurado o no responde, genera la respuesta con reglas locales.

`app/rag_engine_openai.py` (referencia): agrega busqueda semantica sobre documentos
(contratos en PDF, presupuestos) con embeddings de OpenAI y pgvector.

Para activar la variante con busqueda semantica:
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
|-- seed_demo.py                # Datos de prueba (--reiniciar para volver al estado inicial)
|-- backup.py                   # Copia de seguridad y prueba de restauracion
|-- test_sistema.py             # Tests de modulos, asistente y roles
|-- test_seguridad.py           # Tests de seguridad, asistente y respaldo
|-- test_automatizacion.py      # Tests de jobs, notificaciones y envio de email
|-- GUIA_DEMO.md                # Guion para la demostracion en vivo
|-- .env.example                # Plantilla de variables de entorno
|-- README.md
|-- static/
|   `-- index.html              # Interfaz web (SPA)
|-- app/
|   |-- config.py
|   |-- database.py
|   |-- models.py               # 13 entidades ORM + tablas de soporte (seguridad, vectorial)
|   |-- auth.py                 # JWT + bcrypt + control de acceso por rol
|   |-- seguridad.py            # Bloqueo, politica de contrasenas, historial, auditoria
|   |-- respaldo.py             # pg_dump, retencion y prueba de restauracion
|   |-- notificador.py          # Envio de email: SendGrid (API), SMTP o simulado
|   |-- rag_engine.py           # Motor RAG activo (LangChain + LLM, con respaldo por reglas)
|   |-- rag_engine_openai.py    # Variante con busqueda semantica pgvector (referencia)
|   `-- routers.py              # Endpoints de la API
`-- jobs/
    `-- scheduler.py            # Jobs APScheduler (automatizacion)
```

---

## Endpoints principales

| Metodo | Ruta | Descripcion | Roles |
|---|---|---|---|
| POST | `/auth/token` | Login y generacion de JWT (con bloqueo) | Todos |
| POST | `/auth/cambiar-password` | Cambio de contrasena | Todos |
| GET/POST | `/usuarios/` | Listado y alta de usuarios | Gerencia |
| POST | `/usuarios/{id}/desactivar` · `/activar` · `/forzar-cambio` | Gestion de cuentas | Gerencia |
| GET | `/seguridad/auditoria` | Log de auditoria | Gerencia |
| GET/POST | `/seguridad/backups` · `/backups/verificar` | Copias y prueba de restauracion | Gerencia |
| GET | `/comercial/oportunidades` | Pipeline comercial | Gerencia, Administracion |
| POST | `/automatizacion/ejecutar/{job}` | Ejecuta vencimientos, mora o desvios en el momento | Gerencia |
| GET | `/automatizacion/notificaciones` | Avisos generados por los jobs | Gerencia |
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
| Copia de seguridad | 00:00 | pg_dump de la base, retencion de 7 dias |

---

## Referencias tecnicas

- Lewis, P. et al. (2020). Retrieval-Augmented Generation for knowledge-intensive NLP tasks.
- Vaswani, A. et al. (2017). Attention is all you need.
- Provos, N. & Mazieres, D. (1999). A future-adaptable password scheme (bcrypt).

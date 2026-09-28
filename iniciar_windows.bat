@echo off
REM ============================================================
REM  Sistema de Asistencia Inteligente - RG S.A.
REM  Script de arranque automatico para Windows
REM ============================================================
REM
REM  Este script automatiza la puesta en marcha del prototipo:
REM    1. Crea el entorno virtual de Python
REM    2. Instala las dependencias
REM    3. Crea el archivo .env si no existe
REM    4. Inicializa la base de datos con datos de demo
REM    5. Levanta el servidor
REM
REM  REQUISITO PREVIO: tener PostgreSQL instalado y una base de
REM  datos llamada "rg_asistente". Ajustar DATABASE_URL en .env
REM  con el usuario, contrasena y puerto correctos.
REM ============================================================

echo.
echo ====================================================
echo   Sistema de Asistencia Inteligente - RG S.A.
echo ====================================================
echo.

REM 1. Crear entorno virtual si no existe
REM Se prefiere el lanzador "py" de Windows: el comando "python" puede ser
REM el acceso directo de la Microsoft Store, que no ejecuta nada.
if not exist "venv\Scripts\python.exe" (
    echo [1/5] Creando entorno virtual...
    py -3.12 -m venv venv 2>nul || py -3 -m venv venv 2>nul || python -m venv venv
)
if not exist "venv\Scripts\python.exe" (
    echo.
    echo ERROR: no se pudo crear el entorno virtual. Verifique que Python 3.11 o superior
    echo este instalado ^(https://www.python.org/downloads/^) y desactive los alias de la
    echo Microsoft Store en Configuracion ^> Aplicaciones ^> Alias de ejecucion de aplicaciones.
    pause
    exit /b 1
)
echo [1/5] Entorno virtual listo.

REM 2. Activar e instalar dependencias
echo [2/5] Instalando dependencias...
venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo ERROR al instalar dependencias.
    pause
    exit /b 1
)

REM 3. Crear .env si no existe
if not exist ".env" (
    echo [3/5] Creando archivo .env desde la plantilla...
    copy .env.example .env
    echo.
    echo   IMPORTANTE: revisa el archivo .env y ajusta DATABASE_URL
    echo   con tu usuario, contrasena y puerto de PostgreSQL.
    echo.
    pause
) else (
    echo [3/5] Archivo .env ya existe.
)

REM 4. Inicializar base de datos
echo [4/5] Inicializando base de datos (carga datos de demo solo si esta vacia)...
venv\Scripts\python.exe seed_demo.py
if errorlevel 1 (
    echo.
    echo ERROR al inicializar la base de datos. Revise DATABASE_URL en el archivo .env
    echo ^(usuario, contrasena y puerto de PostgreSQL^).
    pause
    exit /b 1
)

REM 5. Levantar servidor
echo [5/5] Levantando servidor...
echo.
echo ====================================================
echo   Sistema listo. Abri en el navegador:
echo     - Interfaz web:  http://localhost:8000
echo     - API (Swagger): http://localhost:8000/docs
echo ====================================================
echo.
venv\Scripts\python.exe -m uvicorn main:app --port 8000
pause

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
if not exist "venv\" (
    echo [1/5] Creando entorno virtual...
    python -m venv venv
) else (
    echo [1/5] Entorno virtual ya existe.
)

REM 2. Activar e instalar dependencias
echo [2/5] Instalando dependencias...
call venv\Scripts\activate.bat
pip install -q -r requirements.txt

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
echo [4/5] Inicializando base de datos con datos de demo...
python seed_demo.py

REM 5. Levantar servidor
echo [5/5] Levantando servidor...
echo.
echo ====================================================
echo   Sistema listo. Abri en el navegador:
echo     - Interfaz web:  http://localhost:8000
echo     - API (Swagger): http://localhost:8000/docs
echo ====================================================
echo.
uvicorn main:app --reload --port 8000

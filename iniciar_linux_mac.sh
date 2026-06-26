#!/bin/bash
# ============================================================
#  Sistema de Asistencia Inteligente - RG S.A.
#  Script de arranque automático para Linux / macOS
# ============================================================
set -e

echo ""
echo "===================================================="
echo "  Sistema de Asistencia Inteligente - RG S.A."
echo "===================================================="
echo ""

# 1. Entorno virtual
if [ ! -d "venv" ]; then
    echo "[1/5] Creando entorno virtual..."
    python3 -m venv venv
else
    echo "[1/5] Entorno virtual ya existe."
fi

# 2. Dependencias
echo "[2/5] Instalando dependencias..."
source venv/bin/activate
pip install -q -r requirements.txt

# 3. Archivo .env
if [ ! -f ".env" ]; then
    echo "[3/5] Creando archivo .env desde la plantilla..."
    cp .env.example .env
    echo ""
    echo "  IMPORTANTE: revisá el archivo .env y ajustá DATABASE_URL"
    echo "  con tu usuario, contraseña y puerto de PostgreSQL."
    echo ""
    read -p "  Presioná Enter para continuar..."
else
    echo "[3/5] Archivo .env ya existe."
fi

# 4. Inicializar base de datos
echo "[4/5] Inicializando base de datos con datos de demo..."
python seed_demo.py

# 5. Levantar servidor
echo "[5/5] Levantando servidor..."
echo ""
echo "===================================================="
echo "  Sistema listo. Abrí en el navegador:"
echo "    - Interfaz web:  http://localhost:8000"
echo "    - API (Swagger): http://localhost:8000/docs"
echo "===================================================="
echo ""
uvicorn main:app --reload --port 8000

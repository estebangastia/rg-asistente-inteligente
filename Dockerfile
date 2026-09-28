FROM python:3.12-slim-trixie

# Directorio de trabajo
WORKDIR /app

# Dependencias del sistema: libpq para psycopg2 y el cliente de PostgreSQL
# (pg_dump / pg_restore) para las copias de seguridad
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias de Python primero (mejor cacheo de capas)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Exponer el puerto de la API
EXPOSE 8000

# Cargar datos de demo (solo si la base está vacía) y levantar el servidor
CMD ["sh", "-c", "python seed_demo.py && uvicorn main:app --host 0.0.0.0 --port 8000"]

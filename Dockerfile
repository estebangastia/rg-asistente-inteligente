FROM python:3.12-slim-trixie

# Directorio de trabajo
WORKDIR /app

# Dependencias del sistema: libpq para psycopg2 y el cliente de PostgreSQL 18
# (pg_dump / pg_restore) desde el repositorio oficial de PostgreSQL. La versión
# del cliente debe ser igual o mayor a la del servidor (Railway usa PostgreSQL 18);
# el cliente 18 también respalda servidores 16 y 17.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev curl ca-certificates \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
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

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# git: commits de la bóveda | libmagic1: detección real de MIME, la extensión del archivo no es confiable
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El UID debe coincidir con el del host: la bóveda es un bind-mount que también se
# edita desde Obsidian, y un desajuste deja los .md sin permiso de escritura.
ARG UID=1000
ARG GID=1000
RUN groupadd --gid ${GID} agent 2>/dev/null || true \
 && useradd --create-home --uid ${UID} --gid ${GID} agent 2>/dev/null || true

COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
 && mkdir -p /app/vault /app/data /app/quarantine /app/logs \
 && chown -R ${UID}:${GID} /app

USER ${UID}:${GID}

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

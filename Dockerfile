FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RPM_HOST=0.0.0.0
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY backend/migrations backend/migrations
COPY backend/alembic.ini backend/alembic.ini
COPY scripts/ scripts/
COPY run_server.py ./
COPY --from=web /web/dist frontend/dist
RUN useradd --create-home --uid 10001 rpm && mkdir -p backend/data simulator_keys && chown -R rpm /app
USER rpm
EXPOSE 8443
# Readiness = database reachable, keys loaded, model hash verified. TLS is verified against the mounted certificate.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import ssl,urllib.request; urllib.request.urlopen('https://localhost:8443/api/health/ready', context=ssl.create_default_context(cafile='/app/certs/dev-cert.pem'), timeout=4)" || exit 1
CMD ["python", "run_server.py"]

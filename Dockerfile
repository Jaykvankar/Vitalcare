FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY scripts/ scripts/
COPY run_server.py ./
COPY --from=web /web/dist frontend/dist
RUN useradd --create-home rpm && mkdir -p backend/data simulator_keys && chown -R rpm /app
USER rpm
ENV RPM_HOST=0.0.0.0
EXPOSE 8443
CMD ["python", "run_server.py"]

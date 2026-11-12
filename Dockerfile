FROM cloudflare/cloudflared:latest AS cloudflared

# Stage 1: the React app (frontend/) -> portal/static/portal/app/ (vite.config.ts writes the build there)
FROM node:22.17.0-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: one image for both services (docker-compose.yml):
#   mi-mcp: the MCP server (Streamable HTTP at :8000/mcp), with cloudflared for the public link (the CMD below)
#   mi-web: the website (Django + the React build) with gunicorn on :8000
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SQLITE_PATH=/app/data/db.sqlite3
WORKDIR /app
COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY manage.py /app/
COPY nopsite /app/nopsite
COPY portal /app/portal
COPY docs /app/docs
COPY pdfs /app/pdfs
COPY --from=frontend /src/portal/static/portal/app /app/portal/static/portal/app
# every static file (the React build, the admin's) into /app/staticfiles for WhiteNoise; the key is only
# for this build step (the real one comes from .env when the container runs)
RUN DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput
COPY --chmod=755 docker-entrypoint.sh /app/docker-entrypoint.sh
RUN useradd --uid 10001 --create-home mcp \
    && mkdir -p /app/data /app/.fastembed_cache \
    && chown -R mcp:mcp /app/data /app/.fastembed_cache
USER mcp
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "manage.py", "run_mcp", "--host", "0.0.0.0", "--port", "8000"]

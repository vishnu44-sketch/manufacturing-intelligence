FROM cloudflare/cloudflared:latest AS cloudflared

# Ask NOP as an MCP server (Streamable HTTP at :8000/mcp), with cloudflared for the public link
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
COPY --chmod=755 docker-entrypoint.sh /app/docker-entrypoint.sh
RUN useradd --uid 10001 --create-home mcp \
    && mkdir -p /app/data /app/.fastembed_cache \
    && chown -R mcp:mcp /app/data /app/.fastembed_cache
USER mcp
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "manage.py", "run_mcp", "--host", "0.0.0.0", "--port", "8000"]

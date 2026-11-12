#!/bin/sh
# Container start (the same image runs the MCP server and the website - see docker-compose.yml):
# 1. the History database (MySQL schema APP_DB_NAME, or SQLite in the app_data volume) gets its tables
# 2. the search indexes (Qdrant) are built once, when they are empty (takes a few minutes):
#    the SQL notes (QDRANT_COLLECTION, default mi_docs) and the company PDFs (QDRANT_PDF_COLLECTION, default mi_pdfs)
#    Steps 1-2 hold a lock in the app_data volume, so mi-mcp and mi-web never do them at the same time.
#    MI_MIGRATE=off / MI_INGEST=off skip them.
# 3. the public link: CLOUDFLARE_TUNNEL_TOKEN = the company's fixed Cloudflare tunnel (production);
#    else PUBLIC_LINK=quick = a free test link https://<random>.trycloudflare.com (new on every start)
# 4. the server (CMD: the MCP server; mi-web runs gunicorn instead)
set -e

# exit 0 when the Qdrant collection named by env var $1 (default $2) exists and holds something
index_ready() {
    python - "$1" "$2" <<'EOF'
import os
import sys
from qdrant_client import QdrantClient
client = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.getenv("QDRANT_API_KEY") or None)
name = os.getenv(sys.argv[1], "").strip() or sys.argv[2]
ready = client.collection_exists(name) and client.count(name).count > 0
raise SystemExit(0 if ready else 1)
EOF
}

setup() {
    if [ "$MI_MIGRATE" != "off" ]; then
        python manage.py migrate --noinput
    fi
    if [ "$MI_INGEST" != "off" ]; then
        if ! index_ready QDRANT_COLLECTION mi_docs; then
            echo "Search index is empty - building it (a few minutes) ..."
            python manage.py ingest_docs
        fi
        if ! index_ready QDRANT_PDF_COLLECTION mi_pdfs; then
            echo "PDF index is empty - building it from pdfs/ ..."
            # the data questions still work without it, so a failure here does not stop the server
            python manage.py ingest_pdfs || echo "WARNING: ingest_pdfs failed - document questions go to the data"
        fi
    fi
}

if command -v flock >/dev/null 2>&1; then
    exec 9>/app/data/.setup.lock
    flock 9
    setup
    flock -u 9
    exec 9>&-
else
    setup
fi

if [ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]; then
    echo "Public link: the company's Cloudflare tunnel (its hostname, path /mcp)"
    cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN" >/tmp/cloudflared.log 2>&1 &
elif [ "$PUBLIC_LINK" = "quick" ]; then
    cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000 2>&1 | tee /tmp/cloudflared.log \
        | grep --line-buffered -o 'https://[a-z0-9-]*\.trycloudflare\.com' \
        | sed -u 's#\(.*\)#==> PUBLIC MCP LINK: \1/mcp#' &
fi

exec "$@"

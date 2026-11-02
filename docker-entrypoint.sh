#!/bin/sh
# Ask NOP MCP container start:
# 1. the History database (SQLite in the app_data volume) gets its tables
# 2. the search index (Qdrant) is built once, when it is empty (takes a few minutes)
# 3. the public link: CLOUDFLARE_TUNNEL_TOKEN = the company's fixed Cloudflare tunnel (production);
#    else PUBLIC_LINK=quick = a free test link https://<random>.trycloudflare.com (new on every start)
# 4. the MCP server (CMD)
set -e

python manage.py migrate --noinput

if ! python - <<'EOF'
import os
from qdrant_client import QdrantClient
client = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.getenv("QDRANT_API_KEY") or None)
name = os.getenv("QDRANT_COLLECTION", "").strip() or "mi_docs"
ready = client.collection_exists(name) and client.count(name).count > 0
raise SystemExit(0 if ready else 1)
EOF
then
    echo "Search index is empty - building it (a few minutes) ..."
    python manage.py ingest_docs
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

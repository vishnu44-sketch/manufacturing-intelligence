# Deploying Manufacturing Intelligence

One Docker image runs two services (docker-compose.yml), next to their own Qdrant:

- `mi-web` - the website: Django + the built React app, served by gunicorn. Static files (the React
  build and the admin's) are served by WhiteNoise, so DEBUG can be off. http://127.0.0.1:8094
- `mi-mcp` - the MCP server for other chatbots (http://127.0.0.1:8096/mcp), with the optional
  Cloudflare link (see the top of docker-entrypoint.sh).

The image builds the React app itself (a Node stage), runs `collectstatic`, and copies `docs/` and
`pdfs/`. Secrets are never in the image: both services read `.env` when they start.

## 1. The .env keys

Already used on the laptop (see .env): `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_FALLBACK_MODEL`,
`EMBED_MODEL`, `MYSQL_*`, `AI_GOLD_DATABASE`, `AI_DB_USER`, `AI_DB_PASSWORD`, `APP_DB_NAME`,
`APP_DB_USER`, `APP_DB_PASSWORD`, `QDRANT_API_KEY` (needed: it protects the compose Qdrant),
`QDRANT_COLLECTION` (default mi_docs), `QDRANT_PDF_COLLECTION` (default mi_pdfs), `MCP_ACCESS_KEY`, `MCP_AUTH`.

For the website in production:

- `DJANGO_SECRET_KEY` - a long random value; the site does not start without it when DEBUG is off.
- `DJANGO_DEBUG` - the laptop keeps `True`. The `mi-web` container ignores it and runs with DEBUG off
  (`DOCKER_DJANGO_DEBUG`, default False). Never turn DEBUG on for a site other people use.
- `ALLOWED_HOSTS` - the names the site is opened with, comma separated, e.g.
  `mi.example.com,localhost,127.0.0.1`. Missing = `localhost,127.0.0.1` (as before).
- `CSRF_TRUSTED_ORIGINS` - the https address(es) people use, e.g. `https://mi.example.com`.
  Needed for signing in and asking through a public name; missing = none (fine on 127.0.0.1).
- `DJANGO_BEHIND_HTTPS_PROXY=on` - when a proxy or tunnel ends https in front of the site.
- `DJANGO_SECURE_COOKIES` - with DEBUG off the sign-in cookies go only over https (browsers still allow
  them on http://localhost and 127.0.0.1). `off` only for a test over plain http from another machine.

Docker only (in .env or the shell): `DOCKER_MYSQL_HOST` (default host.docker.internal = this PC),
`MI_WEB_PORT` (8094), `MI_MCP_PORT` (8096), `MI_WEB_WORKERS` (1) and `MI_WEB_THREADS` (8),
`PUBLIC_LINK` / `CLOUDFLARE_TUNNEL_TOKEN` (the MCP link only), `MI_MIGRATE=off` / `MI_INGEST=off`
(skip the start-up steps below).

## 2. Build and start

    docker compose build
    docker compose up -d
    docker compose logs -f mi-web mi-mcp

At the first start the container that gets there first runs `migrate`, then builds the search
indexes when they are empty: `ingest_docs` (the SQL notes) and `ingest_pdfs` (the PDFs). That takes a
few minutes and downloads the search model once (~210 MB, kept in the model_cache volume). The other
container waits for it (a lock in the app_data volume). After a change to `docs/` or `pdfs/`, run
`docker compose exec mi-mcp python manage.py ingest_docs` (or `ingest_pdfs`).

Check: http://127.0.0.1:8094/ shows the sign-in page, http://127.0.0.1:8094/admin/ the admin sign-in.
Make the first staff user with `docker compose exec mi-web python manage.py createsuperuser` (only when
the History database has none yet).

Others reach the site only through an https proxy or a tunnel pointed at port 8094 (the compose file
publishes it on 127.0.0.1 only). Then set `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and
`DJANGO_BEHIND_HTTPS_PROXY=on`.

## 3. MySQL from a container

The containers reach MySQL at `DOCKER_MYSQL_HOST`. Two logins are used: the History user
(`APP_DB_USER`, e.g. 'mi_app'@'localhost') and the read-only AI user (`AI_DB_USER`).

- On this PC (Docker Desktop, tested 03-Nov-2026) both logins worked from a container as they are.
- On another server (e.g. Linux with Docker), MySQL sees the container's own address (often
  172.17.x.x / 172.18.x.x), not localhost, so a user made for 'localhost' is refused
  ("Access denied for user ..."). Then a MySQL admin must:
  1. let MySQL listen on an address the containers can reach (`bind-address` in my.cnf), and
  2. make the same users for the Docker addresses, with the same passwords and the same rights only -
     e.g. 'mi_app'@'172.%' with all rights on the History schema only, and the AI user with SELECT on
     the AI database only (never more).
  Or point `DOCKER_MYSQL_HOST` at a MySQL server whose users already allow the Docker host.
- Without a reachable MySQL the History is SQLite in the app_data volume (leave `APP_DB_NAME`
  empty), but the data questions still need the AI user.

## 4. Static files and DEBUG - good to know

- `npm run build` (frontend/) writes the React app into `portal/static/portal/app/`;
  `python manage.py collectstatic` copies every static file into `staticfiles/` (both not in git).
  The image does both itself.
- With DEBUG off, WhiteNoise serves `/static/...` from `staticfiles/` (gzip, and Vite's hashed files
  are cached for a year). With DEBUG on (the laptop's runserver) it reads them from the app folders.
  So after a new React build on the laptop with DEBUG off, run collectstatic again.
- Every address that is not `/api/`, `/admin/` or `/static/` gets the React page (also with DEBUG off);
  the view reads `portal/static/portal/app/index.html`, which the image holds.
- The image name is `manufacturing-intelligence:latest` (was `manufacturing-intelligence-mcp`).

## 5. The streamed answer (Ask page) and proxies

The Ask page asks through `POST /api/ask/stream`: the reply is one JSON object per line
(`application/x-ndjson`) sent while the question runs - each step as it starts, then the answer piece by
piece, then the finished card. `/api/ask` (one JSON reply) is still there: the page falls back to it when
the stream cannot be used, and the MCP server and the eval use the plain path anyway.

- gunicorn (`mi-web`: 1 worker, 8 threads, the gthread worker) sends each line as it is written; nothing
  to set. One streamed question keeps one of the 8 threads busy until it ends - the same as `/api/ask`.
  `--timeout 300` is gunicorn's check that the worker is alive, not a limit per request.
- WhiteNoise only serves `/static/...`; it does not touch the API. Django has no GZip middleware here (with
  one, Django still compresses a stream line by line).
- The stream says `X-Accel-Buffering: no` and `Cache-Control: no-cache`, so nginx passes each line on at once.
  Another proxy in front of port 8094 must not buffer the reply either, e.g. nginx without that header:
  `location /api/ask/stream { proxy_pass http://127.0.0.1:8094; proxy_buffering off; proxy_read_timeout 300s; }`
  (Apache: `SetEnv proxy-sendchunked 1` and no `mod_deflate` on that address). A proxy that buffers does no
  harm: the steps and the answer then arrive together at the end, as with `/api/ask`.
- When the browser closes or reloads the page during a stream, the question still runs to the end and is
  saved in History (as with `/api/ask`); only nothing more is sent.

# Deploying Manufacturing Intelligence

One Docker image runs two services (docker-compose.yml), next to their own Qdrant and MySQL:

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

Docker only (in .env or the shell): `DOCKER_MYSQL_ROOT_PASSWORD` (needed: the admin password of the MySQL
container - a long random value), `DOCKER_MYSQL_HOST` (default `mysql` = the MySQL container; another
server's name to use that one instead), `MI_MYSQL_PORT` (3307: MySQL on 127.0.0.1 of this PC, for a MySQL tool),
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

## 3. MySQL in Docker (branch docker-mysql)

The compose file runs MySQL 8.4 itself (service `mysql`), so the PC needs only Docker - no MySQL install.

- The data files are in the Docker volume `mysql_data`. They stay when the containers stop, when the PC
  restarts, after `docker compose down` and after an update of the app. They are deleted only by
  `docker compose down -v` or by removing the volume by hand.
- On the FIRST start (empty volume) `docker/mysql-init/01-databases-and-users.sh` makes the data schema
  (`AI_GOLD_DATABASE`), the app's schema (`APP_DB_NAME`) with its user (`APP_DB_USER`, all rights there only)
  and the read-only AI user (`AI_DB_USER`, SELECT on the data schema only). Names and passwords come from
  `.env`. A password changed in `.env` later is NOT changed in MySQL by itself (the script runs once).
- `mi-web` and `mi-mcp` wait until MySQL answers, then start. MySQL is reachable from the containers as
  `mysql:3306` and from this PC as `127.0.0.1:3307` (`MI_MYSQL_PORT`) - never from other machines.

### First start on a new PC (e.g. the office computer)

1. Install Docker Desktop and Git. `git clone` the repo, `git checkout docker-mysql`.
2. Copy by hand (they are not in git): `.env` and the folder `inputdata/`. In `.env` add
   `DOCKER_MYSQL_ROOT_PASSWORD=<a long random value>`; `QDRANT_API_KEY` and `DJANGO_SECRET_KEY` must be set.
3. `docker compose up -d --build` - builds the image, starts MySQL, Qdrant, the website and the MCP server.
   The first start takes a few minutes (the search indexes are built once).
4. Load the data once: `docker compose --profile load run --rm loader` (fills `ai_gold` from `inputdata/`).
5. Make the first sign-in: `docker compose exec mi-web python manage.py createsuperuser`.
6. Open http://127.0.0.1:8094.

Later: `docker compose up -d` starts everything again; after a `git pull`, `docker compose up -d --build`.

### Backup and restore (the chats, history and users)

`ai_gold` can always be made again with the loader; the app's schema cannot. Back it up before updates:

    docker compose exec mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --databases "$APP_DB_NAME" > /backups/app_$(date +%Y%m%d_%H%M).sql'

The file is written into `backups/` next to the compose file (not in git). Restore one:

    docker compose exec mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot < /backups/<file>.sql'

### Another MySQL server instead

Set `DOCKER_MYSQL_HOST` (and `DOCKER_MYSQL_PORT`) to that server. Its admin must make the same two users for
the address the containers come from - the app user with all rights on the app schema only, the AI user with
SELECT on the data schema only (never more). A MySQL installed on this PC: `DOCKER_MYSQL_HOST=host.docker.internal`.
The `mysql` container still starts; it is simply not used.

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

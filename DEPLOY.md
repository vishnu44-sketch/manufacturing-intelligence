# Deploying the SS Manufacturing Intelligence Platform

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
The data database and its read-only user are always `AI_GOLD_DATABASE=ss_gold` and `AI_DB_USER=ss_ai_reader`
(see section 6).

The AI model chain (18-Nov): every AI call (rewrite, route, SQL, answer, documents, general answer, AI chart)
tries these models in turn until one answers - 1) Groq main `GROQ_MODEL`, 2) Gemini Flash `GEMINI_MODEL`
(default gemini-flash-latest), 3) Gemini Flash-Lite `GEMINI_LITE_MODEL` (default gemini-flash-lite-latest),
4) the Groq backup `GROQ_FALLBACK_MODEL`. Groq main and Gemini Flash get the full request, Flash-Lite and the
backup a smaller one.

- `GEMINI_API_KEY` - needed on the office PC too (copy it into its .env); without it the Gemini models are
  simply left out and the chain is Groq main + the backup, as before.
- `AI_MODEL_CHAIN` (optional) - the order as ids, e.g. `groq-main,gemini-flash,gemini-flash-lite,groq-backup`
  (an id left out is not used).
- A model moves on after: its daily limit (it then rests 10 minutes), busy / unreachable / a 45 s Gemini
  timeout (rests 2 minutes), a request too large even when made smaller, or any other error (a wrong key or
  model name is logged as a warning, never the key). Only Groq main still waits after a per-minute limit.
- The answer card names the model that answered and why it was not the first (e.g. "Groq's daily limit was
  reached"). Admins can choose one model on the Ask page (`GET /api/models`, "model" on `/api/ask`): only that
  model is asked (no fallback) - when it is busy or used up the card says so ("Gemini Flash is busy right now ...
  choose Auto"). Auto keeps the whole chain. Gemini Flash-Lite only does the small steps (rewrite, route), never
  the SQL or the answers. Other users always get Auto.
- Privacy: on Google's free tier, Google may use the prompts (the question, the notes, the rows sent for the
  answer) to improve its products. Fine for the demo data - not for a client's real data: use a paid Gemini
  key, or leave `GEMINI_API_KEY` out, before real client data goes in.

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
- On every start the small service `mysql-setup` runs `docker/mysql-setup/databases-and-users.sh`: it makes
  the data schema (`AI_GOLD_DATABASE`), the app's schema (`APP_DB_NAME`) with its user (`APP_DB_USER`, all
  rights there only) and the read-only AI user (`AI_DB_USER`, SELECT on the data schema only), when they are
  missing. Names and passwords come from `.env`; it drops nothing, and a password changed in `.env` reaches
  MySQL at the next `docker compose up -d`. (`DOCKER_MYSQL_ROOT_PASSWORD` itself is fixed at the first start.)
- `mi-web` and `mi-mcp` start only after MySQL answers and that setup ended well. MySQL is reachable from the containers as
  `mysql:3306` and from this PC as `127.0.0.1:3307` (`MI_MYSQL_PORT`) - never from other machines.

### First start on a new PC (e.g. the office computer)

1. Install Docker Desktop and Git. `git clone` the repo, `git checkout docker-mysql`.
2. Copy by hand (they are not in git): `.env` and the folders `inputdata/` and `inputdata_batches/batch_001/`.
   In `.env` add `DOCKER_MYSQL_ROOT_PASSWORD=<a long random value>`; `QDRANT_API_KEY` and `DJANGO_SECRET_KEY`
   must be set, and the data database and its read-only user must be `AI_GOLD_DATABASE=ss_gold` and
   `AI_DB_USER=ss_ai_reader` (with `AI_DB_PASSWORD`).
3. `docker compose up -d --build` - builds the image, starts MySQL, Qdrant, the website and the MCP server.
   The first start takes a few minutes (the search indexes are built once).
4. Load the data once: `docker compose --profile load run --rm loader` (fills `ss_gold` from `inputdata/`),
   then the batch: `docker compose --profile load run --rm loader --batch inputdata_batches/batch_001`.
   Then build the search indexes again: `docker compose exec mi-web python manage.py ingest_docs` and
   `docker compose exec mi-web python manage.py ingest_pdfs`.
5. Make the first sign-in: `docker compose exec mi-web python manage.py createsuperuser`.
6. Open http://127.0.0.1:8094.

Later: `docker compose up -d` starts everything again; after a `git pull`, `docker compose up -d --build`.

### Backup and restore (the chats, history and users)

`ss_gold` can always be made again with the loader; the app's schema cannot. Back it up before updates:

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

## 6. The company data: the database ss_gold and the loader

The data questions read SS Manufacturing's (synthetic) sales, stock and master data from the MySQL database
`ss_gold`, through the read-only user `ss_ai_reader` (SELECT on ss_gold only). `loader/load_gold.py` builds
ss_gold from the input files and writes into no other database, so another project's database on the same
MySQL server is never touched. A sales month runs from the 21st of the previous month to the 20th
(`dim_calendar.sales_month`, e.g. 21-Sep-2026 .. 20-Oct-2026 = 'Oct 2026').

1. The input files are not in git. Copy them next to `manage.py`: the folder `inputdata/` (the base files)
   and the folder `inputdata_batches/batch_001/` (one incremental batch).
2. In `.env` (the loader stops when the names are different):

       AI_GOLD_DATABASE=ss_gold
       AI_DB_USER=ss_ai_reader
       AI_DB_PASSWORD=<a password for the read-only user>

3. Load, on the laptop (the MySQL admin login is `MYSQL_USER` / `MYSQL_PASSWORD` in `.env`):

       venv\Scripts\python.exe loader\load_gold.py
       venv\Scripts\python.exe loader\load_gold.py --batch inputdata_batches\batch_001

   The first command drops and rebuilds every ss_gold table from `inputdata/` and makes / updates
   'ss_ai_reader'@'localhost'; the second merges the batch (nothing dropped; running it twice changes nothing).
   `load_log` shows each run. Then build the search indexes again: `python manage.py ingest_docs` and
   `python manage.py ingest_pdfs`.

## 7. ML: forecast, customers at risk, groups, unusual invoices, pairs, stock run-out

`ml/run_ml.py` reads ss_gold, trains six small models (scikit-learn, statsmodels) and writes their results back
into ss_gold as `ml_*` tables (only ml_* tables, only inside ss_gold - it refuses anything else). The Insights
page (`/api/insights`) and the AI read them as the read-only user. It also writes each model's training data
as CSV into `ml_inputdata/` (the ML's input files, next to `inputdata/`; not in git; `ml_inputdata/README.md` says what each file is). The models work "as of" the
newest invoice date (ml_run_log.data_to), not today. One run takes about 15-30 seconds. Run it again after
every data load (full or batch).

On the laptop (the MySQL admin login of `.env`, like the loader):

    venv\Scripts\python.exe ml\run_ml.py          (or: venv\Scripts\python.exe manage.py run_ml)
    venv\Scripts\python.exe ml\run_ml.py --dry-run   (train + CSV files only, nothing written to MySQL)

In the office Docker (branch docker-mysql), after the data load, with the loader service's admin settings:

    docker compose build
    docker compose --profile load run --rm --entrypoint python loader ml/run_ml.py
    docker compose restart mi-web mi-mcp

- `docker compose build` once after pulling this change: the image must hold `ml/` and the two new libraries.
- `--entrypoint python` because the loader service's own entrypoint is `loader/load_gold.py`.
- The CSV files land in `ml_inputdata/` on this PC (the loader service mounts it), next to `inputdata/`.
- The restart only after the FIRST run (when the ml_* tables are new): the AI's list of allowed tables is
  read once per process. The Insights page reads the tables fresh and needs no restart.

## 8. Before a demo: test each model

The golden questions (`portal/evals/questions.py`) are asked with ONE model of the chain - as an admin's model
choice, so no other model answers - graded against our own SQL and scored in `eval_results/scores.csv`.
Nothing goes into History. On the laptop (Qdrant running; add `--memory-store` when it is not):

    venv\Scripts\python.exe manage.py run_eval quick --model groq-main      (15 questions, the Assistant)
    venv\Scripts\python.exe manage.py run_eval ml --model gemini-flash      (10 ML Insights questions)
    venv\Scripts\python.exe manage.py run_eval ml --model groq-backup --ids N32 N33   (only these + their chat)

- `--model`: `groq-main` (= `main`, the default), `gemini-flash`, `groq-backup` (= `backup`). Gemini Flash-Lite
  only does the small steps (rewrite, route), so it cannot be tested alone. A model not set up in .env (or not
  in `AI_MODEL_CHAIN`) is refused before anything is asked.
- Token cost (estimate): about 7,000 tokens a question, 11,000 a follow-up - `quick` about 105,000, `ml` about
  85,000. A run stops before 70 % of a model's daily 200,000 Groq tokens (minus what the app used in the last
  24 hours), so a Groq model gets ONE set a day - run it the day before the demo, not on the day. For Gemini
  the same cap is only a safety stop: its free tier counts requests a day (about 4 calls a question).
- Read the result lines: FAIL / PARTIAL with the reason (e.g. `missing 53.7`, `says 'you can ask me'`); the
  answers are in `eval_results/<set>_<model>_<date>.json`. A model with FAILs in `ml` should not be the one
  chosen for an ML Insights demo.

"""Deploy checks (03-Nov): the settings that come from .env (DEBUG, hosts, https cookies), WhiteNoise for the
static files, the React page with DEBUG off, and the Docker files (one image: the website and the MCP server).
Nothing is started: settings.py is read again with test values, the Docker files are only read."""
import runpy
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from nopsite import settings as site_settings
from portal import views

REPO = Path(__file__).resolve().parents[2]
SETTINGS_FILE = REPO / "nopsite" / "settings.py"
REACT_HTML = "<!doctype html><title>Manufacturing Intelligence</title><div id=root></div>"


def settings_with(monkeypatch, **env):
    """settings.py read again with these .env values (None = the key is not given: an empty value, which
    settings.py treats like a missing key - and load_dotenv never overrides a key that is already set)."""
    for key, value in env.items():
        monkeypatch.setenv(key, "" if value is None else value)
    monkeypatch.setenv("APP_DB_NAME", "")    # SQLite: no MySQL driver set up for this read
    return runpy.run_path(str(SETTINGS_FILE))


def test_whitenoise_serves_the_static_files():
    assert settings.MIDDLEWARE[:2] == ["django.middleware.security.SecurityMiddleware",
                                       "whitenoise.middleware.WhiteNoiseMiddleware"]
    assert settings.STATIC_ROOT and settings.STATIC_URL == "/static/"
    assert settings.STORAGES["staticfiles"]["BACKEND"] == "whitenoise.storage.CompressedStaticFilesStorage"


def test_vites_hashed_files_may_be_kept_by_the_browser():
    assert site_settings._vite_hashed_file("", "/static/portal/app/assets/index-DO1YksTB.js")
    assert not site_settings._vite_hashed_file("", "/static/admin/css/base.css")


def test_production_values_come_from_env(monkeypatch):
    found = settings_with(monkeypatch, DJANGO_DEBUG="False", DJANGO_SECRET_KEY="k" * 50,
                          ALLOWED_HOSTS="mi.example.com, localhost", CSRF_TRUSTED_ORIGINS="https://mi.example.com",
                          DJANGO_SECURE_COOKIES=None)
    assert found["DEBUG"] is False
    assert found["ALLOWED_HOSTS"] == ["mi.example.com", "localhost"]
    assert found["CSRF_TRUSTED_ORIGINS"] == ["https://mi.example.com"]
    assert found["SESSION_COOKIE_SECURE"] and found["CSRF_COOKIE_SECURE"]   # https only without DEBUG
    assert "SECURE_PROXY_SSL_HEADER" not in found


def test_the_laptop_defaults_stay(monkeypatch):
    """No ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS in .env: as before (localhost only); DEBUG on: plain http cookies."""
    found = settings_with(monkeypatch, DJANGO_DEBUG="True", ALLOWED_HOSTS=None, CSRF_TRUSTED_ORIGINS=None,
                          DJANGO_SECURE_COOKIES=None)
    assert found["DEBUG"] is True
    assert found["ALLOWED_HOSTS"] == ["localhost", "127.0.0.1"] and found["CSRF_TRUSTED_ORIGINS"] == []
    assert not found["SESSION_COOKIE_SECURE"] and not found["CSRF_COOKIE_SECURE"]


def test_secure_cookies_and_the_https_proxy_can_be_set(monkeypatch):
    found = settings_with(monkeypatch, DJANGO_DEBUG="False", DJANGO_SECRET_KEY="k" * 50,
                          DJANGO_SECURE_COOKIES="off", DJANGO_BEHIND_HTTPS_PROXY="on")
    assert not found["SESSION_COOKIE_SECURE"]
    assert found["SECURE_PROXY_SSL_HEADER"] == ("HTTP_X_FORWARDED_PROTO", "https")


@pytest.mark.django_db
@override_settings(DEBUG=False)
@pytest.mark.parametrize("url", ["/", "/c/5", "/history"])
def test_the_react_page_works_with_debug_off(client, tmp_path, monkeypatch, url):
    index = tmp_path / "index.html"
    index.write_text(REACT_HTML, encoding="utf-8")
    monkeypatch.setattr(views, "REACT_INDEX", index)
    response = client.get(url)
    assert response.status_code == 200 and response.content.decode() == REACT_HTML
    assert client.get("/api/me").status_code == 401                    # the API is still the API


def test_the_image_builds_the_react_app_and_collects_the_static_files():
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "AS frontend" in dockerfile and "npm run build" in dockerfile
    assert "COPY --from=frontend /src/portal/static/portal/app /app/portal/static/portal/app" in dockerfile
    assert "collectstatic --noinput" in dockerfile and "COPY pdfs /app/pdfs" in dockerfile


def test_the_start_script_builds_both_indexes_once():
    script = (REPO / "docker-entrypoint.sh").read_bytes()
    assert b"\r\n" not in script                                        # runs in Linux: LF only
    text = script.decode()
    assert "index_ready QDRANT_COLLECTION mi_docs" in text and "ingest_docs" in text
    assert "index_ready QDRANT_PDF_COLLECTION mi_pdfs" in text and "ingest_pdfs" in text
    assert "flock" in text and "migrate --noinput" in text


def test_compose_runs_the_website_next_to_the_mcp_server():
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "mi-mcp:" in compose and "mi-web:" in compose and "qdrant:" in compose
    assert '"127.0.0.1:${MI_WEB_PORT:-8094}:8000"' in compose
    assert '"gunicorn", "nopsite.wsgi:application"' in compose
    assert "DJANGO_DEBUG: ${DOCKER_DJANGO_DEBUG:-False}" in compose


def test_compose_runs_mysql_with_a_volume_and_the_app_waits_for_it():
    """Branch docker-mysql: MySQL is a compose service; its data is kept in a named volume."""
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "  mysql:\n    image: mysql:8.4" in compose
    assert "- mysql_data:/var/lib/mysql" in compose and "\nvolumes:\n  mysql_data:" in compose
    assert "MYSQL_ROOT_PASSWORD: ${DOCKER_MYSQL_ROOT_PASSWORD:?" in compose          # from .env, never in the file
    assert compose.count("MYSQL_HOST: ${DOCKER_MYSQL_HOST:-mysql}") == 2            # the website and the MCP server
    assert compose.count("      mysql:\n        condition: service_healthy") == 3   # both, and the loader
    assert '"127.0.0.1:${MI_MYSQL_PORT:-3307}:3306"' in compose                     # this PC only
    assert 'profiles: ["load"]' in compose and '"loader/load_gold.py"' in compose   # the one-off data load


def test_the_mysql_first_start_script_gives_only_the_needed_rights():
    script = (REPO / "docker" / "mysql-init" / "01-databases-and-users.sh").read_bytes()
    assert b"\r\n" not in script                                                    # runs in Linux: LF only
    text = script.decode()
    assert "GRANT SELECT ON \\`$GOLD\\`.* TO '$AI_DB_USER'@'%'" in text              # the AI user: read-only
    assert "GRANT ALL PRIVILEGES ON \\`$APP_DB_NAME\\`.* TO '$APP_DB_USER'@'%'" in text  # the app user: its schema only
    assert text.count("GRANT ") == 2 and "*.*" not in text                          # nothing server-wide
    assert '-p"$MYSQL_ROOT_PASSWORD' not in text                                    # no password on a command line
    assert "*.sh text eol=lf" in (REPO / ".gitattributes").read_text(encoding="utf-8")

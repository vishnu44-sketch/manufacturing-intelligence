"""Settings for NOP Intelligence ("Ask NOP").

Secrets come from the .env file next to manage.py (never from this file).
Django's own tables (users, sessions, saved questions) live in the MySQL
schema APP_DB_NAME (its own user), or in SQLite (db.sqlite3) when
APP_DB_NAME is empty. The NOP data in MySQL (ai_gold) is NOT a Django database:
it is read later by separate code with a read-only user.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# the repo folder (the one that holds manage.py)
BASE_DIR = Path(__file__).resolve().parent.parent

# read .env into os.environ
load_dotenv(BASE_DIR / ".env")

# DEBUG is on only when .env says True (shows error details - laptop only)
DEBUG = os.getenv("DJANGO_DEBUG", "False").strip().lower() in ("1", "true", "yes")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is missing in .env")
    SECRET_KEY = "dev-only-key-not-secret"  # local laptop only


def _env_list(key, default=""):
    """A comma separated .env value as a list (empty parts dropped); default when the key is missing or empty."""
    return [part.strip() for part in (os.getenv(key, "").strip() or default).split(",") if part.strip()]


def _env_on(key, default):
    """True / False from .env (1, true, yes, on = True); default when the key is missing or empty."""
    value = os.getenv(key, "").strip().lower()
    return default if not value else value in ("1", "true", "yes", "on")


# the host names the site may be opened with (comma separated in .env)
ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
# the https addresses a POST may come from when the site is opened by a public name
# (e.g. https://mi.example.com); comma separated in .env, none by default
CSRF_TRUSTED_ORIGINS = _env_list("CSRF_TRUSTED_ORIGINS")

# production (DEBUG off): the sign-in cookies go only over https (browsers also allow them on http://localhost).
# DJANGO_SECURE_COOKIES=off in .env for a test over plain http from another machine
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = _env_on("DJANGO_SECURE_COOKIES", not DEBUG)
SESSION_COOKIE_HTTPONLY = True   # the session cookie is never readable by JavaScript
# CSRF_COOKIE_HTTPONLY stays False: the React app reads that cookie for its POSTs
# behind a proxy that ends https (Cloudflare tunnel, nginx): it says the request came over https
if _env_on("DJANGO_BEHIND_HTTPS_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# own cookie names: a browser shares cookies between ports of the same host, so another Django site
# on 127.0.0.1 (the main NOP project on :8080) overwrote 'csrftoken' / 'sessionid' -> 403 "CSRF token incorrect"
SESSION_COOKIE_NAME = "asknop_sessionid"
CSRF_COOKIE_NAME = "asknop_csrftoken"


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # the static files (the React build, the admin's) without DEBUG
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "nopsite.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,  # only the admin's own templates (the website is the React app)
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "nopsite.wsgi.application"


# Django's own tables only (users, sessions, Question) - a local SQLite file
APP_DB_NAME = os.getenv("APP_DB_NAME", "").strip()
if APP_DB_NAME:
    # Django's own tables in MySQL, in their own schema (never ai_gold): many saves at once are
    # fine and nothing is lost when the container is made again. Driver: PyMySQL standing in for
    # mysqlclient (no C compiler needed in Docker); Django checks the mysqlclient version number.
    import sys

    import pymysql
    import pymysql.constants.CLIENT
    import pymysql.constants.FIELD_TYPE
    import pymysql.converters

    pymysql.version_info = (2, 2, 1, "final", 0)
    pymysql.install_as_MySQLdb()
    # Django imports MySQLdb.constants, MySQLdb.converters ...: give it PyMySQL's own modules. Else Python
    # loads second copies, pymysql.err becomes the copy and 'except pymysql.err.MySQLError' in
    # warehouse.py misses MySQL's errors (28-Oct: a GROUP BY error was not sent back to the AI to fix).
    for _name, _module in list(sys.modules.items()):
        if _name.startswith("pymysql."):
            sys.modules["MySQLdb" + _name[len("pymysql"):]] = _module
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": APP_DB_NAME,
            "HOST": os.getenv("MYSQL_HOST", "").strip() or "127.0.0.1",  # Docker: DOCKER_MYSQL_HOST
            "PORT": os.getenv("MYSQL_PORT", "").strip() or "3306",
            "USER": os.getenv("APP_DB_USER", "").strip(),
            "PASSWORD": os.getenv("APP_DB_PASSWORD", ""),
            "OPTIONS": {"charset": "utf8mb4"},
            "TEST": {"NAME": f"test_{APP_DB_NAME}"},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.getenv("SQLITE_PATH", "").strip() or BASE_DIR / "db.sqlite3",  # Docker: a file in a volume
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# the sign-in page is the React app's own (/login); the admin keeps its own sign-in at /admin/login/
LOGIN_URL = "/login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"  # India time on every page
USE_I18N = True
USE_TZ = True

# the React app's build (frontend/: npm run build) is found in portal/static/portal/app/
STATIC_URL = "static/"
# `python manage.py collectstatic` copies every static file here; WhiteNoise serves them from here when
# DEBUG is off (with DEBUG on it reads them from the apps' static folders, like runserver)
STATIC_ROOT = os.getenv("STATIC_ROOT", "").strip() or BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # also a gzip copy of each file; no renaming - Vite already puts a hash in the names of its files
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}


def _vite_hashed_file(path, url):
    """True for Vite's own files (assets/index-B4xY9k2Z.js): their name changes with every build, so a
    browser may keep them for a year. index.html is read by the view, not served from here."""
    return "/portal/app/assets/" in url


WHITENOISE_IMMUTABLE_FILE_TEST = _vite_hashed_file

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# the app's own messages (e.g. "Groq tokens: ..." per AI call) go to the runserver console
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"portal": {"handlers": ["console"], "level": "INFO"}},
}

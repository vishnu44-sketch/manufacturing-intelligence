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

# the host names the site may be opened with (comma separated in .env)
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

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
        "APP_DIRS": True,  # templates are found in portal/templates/
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

# login / logout pages and where they send the user
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "ask"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"  # India time on every page
USE_I18N = True
USE_TZ = True

# css, js and pictures are found in portal/static/
STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# the app's own messages (e.g. "Groq tokens: ..." per AI call) go to the runserver console
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"portal": {"handlers": ["console"], "level": "INFO"}},
}

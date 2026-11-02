"""Entry point for a normal (WSGI) web server."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nopsite.settings")

application = get_wsgi_application()

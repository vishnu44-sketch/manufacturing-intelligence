"""Entry point for an async (ASGI) web server."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nopsite.settings")

application = get_asgi_application()

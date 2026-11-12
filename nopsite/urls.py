"""Top-level web addresses: the admin (with its own sign-in), then the website (portal/urls.py:
the JSON API and the React app, which has its own sign-in page)."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("portal.urls")),
]

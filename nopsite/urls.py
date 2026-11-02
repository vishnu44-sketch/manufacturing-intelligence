"""Top-level web addresses: admin, login, logout, then the portal pages."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # sign-in page (the copied NOP login look); a signed-in user goes straight on
    path("login/", auth_views.LoginView.as_view(
        template_name="portal/login.html",
        redirect_authenticated_user=True), name="login"),
    # sign-out works by POST only (the button in the sidebar)
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("portal.urls")),
]

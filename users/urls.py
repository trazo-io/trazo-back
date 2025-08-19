from django.urls import include, path

from rest_framework.routers import SimpleRouter

from .social_auth import OAuthConfigView, SocialAuthView
from .views import APILogoutView, CustomTokenRefreshView, LoginViewSet, RegistrationViewSet, UserViewSet

routes = SimpleRouter()

# AUTHENTICATION
routes.register(r"auth/login", LoginViewSet, basename="auth-login")
routes.register(r"auth/register", RegistrationViewSet, basename="auth-register")

# USER
routes.register(r"users", UserViewSet, basename="user")


urlpatterns = [
    *routes.urls,
    path("auth/refresh/", CustomTokenRefreshView.as_view(), name="token_refresh"),
    path("auth/logout/", APILogoutView.as_view(), name="logout"),
    path("auth/social/", SocialAuthView.as_view(), name="social_auth"),
    path("auth/oauth-config/", OAuthConfigView.as_view(), name="oauth_config"),
    # Company invitation system
    path("", include("users.urls_invitation")),
]

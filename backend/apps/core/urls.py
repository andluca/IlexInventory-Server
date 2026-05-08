"""URL patterns for apps.core.

Routes added here are mounted under /api/v1/ in the root urls.py.
"""

from __future__ import annotations

from django.urls import path

from apps.core.apis import HealthView, LoginView, LogoutView, MeView, SignupView

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("auth/signup", SignupView.as_view(), name="auth-signup"),
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/me", MeView.as_view(), name="auth-me"),
]

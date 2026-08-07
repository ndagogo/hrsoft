from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.HRMSLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("change-password/", views.change_password_view, name="change_password"),
    path("mfa/verify/", views.mfa_verify_view, name="mfa_verify"),
    path("mfa/setup/", views.mfa_setup_view, name="mfa_setup"),
    path("mfa/disable/", views.mfa_disable_view, name="mfa_disable"),
    path("login-history/", views.login_history_view, name="login_history"),
    path("password-reset/", views.HRMSPasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", views.HRMSPasswordResetDoneView.as_view(), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", views.HRMSPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("reset/done/", views.HRMSPasswordResetCompleteView.as_view(), name="password_reset_complete"),
]

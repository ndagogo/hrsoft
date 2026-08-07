from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.views import (
    LoginView, PasswordResetView, PasswordResetDoneView,
    PasswordResetConfirmView, PasswordResetCompleteView,
)
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy

from .forms import (
    StyledAuthenticationForm,
    ProfileForm,
    ChangePasswordForm,
    HRMSPasswordResetForm,
    HRMSSetPasswordForm,
)
from .models import LoginHistory
from . import mfa as mfa_helpers


def _parse_user_agent(ua):
    if not ua:
        return "Unknown"
    ua_lower = ua.lower()
    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        return "Mobile"
    if "tablet" in ua_lower or "ipad" in ua_lower:
        return "Tablet"
    return "Desktop"


class HRMSLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = StyledAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if user.mfa_enabled:
            self.request.session["mfa_user_id"] = user.pk
            return redirect("accounts:mfa_verify")
        return self._complete_login(form)

    def _complete_login(self, form):
        response = super().form_valid(form)
        ip = self.request.META.get("REMOTE_ADDR")
        ua = self.request.META.get("HTTP_USER_AGENT", "")
        self.request.user.last_login_ip = ip
        self.request.user.save(update_fields=["last_login_ip"])
        LoginHistory.objects.create(
            user=self.request.user,
            ip_address=ip,
            user_agent=ua[:255],
            device=_parse_user_agent(ua),
            success=True,
        )
        messages.success(self.request, f"Welcome back, {self.request.user.first_name or self.request.user.username}.")
        return response

    def get_success_url(self):
        return super().get_success_url()

    def form_invalid(self, form):
        username = form.cleaned_data.get("username") if form.cleaned_data else form.data.get("username")
        if username:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.filter(username=username).first()
            if user:
                LoginHistory.objects.create(
                    user=user,
                    ip_address=self.request.META.get("REMOTE_ADDR"),
                    user_agent=self.request.META.get("HTTP_USER_AGENT", "")[:255],
                    device=_parse_user_agent(self.request.META.get("HTTP_USER_AGENT", "")),
                    success=False,
                )
        return super().form_invalid(form)


class HRMSPasswordResetView(PasswordResetView):
    template_name = "registration/password_reset.html"
    email_template_name = "registration/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"
    form_class = HRMSPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")
    from_email = settings.DEFAULT_FROM_EMAIL
    html_email_template_name = None

    def form_valid(self, form):
        messages.success(
            self.request,
            f"Reset instructions have been sent to {form.cleaned_data['email']}.",
        )
        return super().form_valid(form)

    def form_invalid(self, form):
        # Surface the "email doesn't exist" message clearly
        if form.errors.get("email"):
            messages.error(self.request, form.errors["email"][0])
        return super().form_invalid(form)


class HRMSPasswordResetDoneView(PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["debug"] = settings.DEBUG
        if settings.DEBUG:
            from apps.core.mail import get_dev_reset_link

            context["dev_reset_link"] = get_dev_reset_link()
        return context


class HRMSPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    form_class = HRMSSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        messages.success(self.request, "Your password has been updated. You can sign in now.")
        return super().form_valid(form)


class HRMSPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "registration/password_reset_complete.html"


@login_required
def login_history_view(request):
    history = request.user.login_history.all()[:30]
    return render(request, "registration/login_history.html", {"history": history})


@login_required
def logout_view(request):
    auth_logout(request)
    if request.GET.get("reason") == "idle":
        messages.warning(request, "You were signed out due to inactivity.")
    else:
        messages.info(request, "You've been signed out.")
    return redirect("accounts:login")


@login_required
def profile_view(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile has been updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "registration/profile.html", {"form": form})


@login_required
def change_password_view(request):
    if request.method == "POST":
        form = ChangePasswordForm(request.POST, user=request.user)
        if form.is_valid():
            request.user.set_password(form.cleaned_data["new_password1"])
            request.user.must_change_password = False
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, "Password changed successfully.")
            return redirect("dashboard:router")
    else:
        form = ChangePasswordForm(user=request.user)
    return render(request, "registration/change_password.html", {"form": form})


def mfa_verify_view(request):
    user_id = request.session.get("mfa_user_id")
    if not user_id:
        return redirect("accounts:login")
    from django.contrib.auth import get_user_model, login
    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)
    if request.method == "POST":
        token = request.POST.get("token", "")
        if mfa_helpers.verify_token(user.mfa_device.secret, token):
            request.session.pop("mfa_user_id", None)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "Signed in with two-factor authentication.")
            return redirect("dashboard:router")
        messages.error(request, "Invalid authentication code. Try again.")
    return render(request, "registration/mfa_verify.html", {"user": user})


@login_required
def mfa_setup_view(request):
    device = mfa_helpers.get_or_create_device(request.user)
    qr_b64 = mfa_helpers.qr_code_base64(request.user, device.secret)
    if request.method == "POST":
        token = request.POST.get("token", "")
        if mfa_helpers.verify_token(device.secret, token):
            mfa_helpers.activate_device(device)
            messages.success(request, "Two-factor authentication is now enabled.")
            return redirect("accounts:profile")
        messages.error(request, "Invalid code. Scan the QR code and enter the 6-digit token.")
    return render(request, "registration/mfa_setup.html", {
        "qr_base64": qr_b64,
        "secret": device.secret,
        "is_active": device.is_active,
    })


@login_required
def mfa_disable_view(request):
    if request.method == "POST":
        mfa_helpers.deactivate_device(request.user)
        messages.success(request, "Two-factor authentication disabled.")
    return redirect("accounts:profile")

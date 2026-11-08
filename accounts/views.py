from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView as BaseLoginView
from django.contrib.auth.views import LogoutView as BaseLogoutView
from django.utils import timezone

from accounts.models import LoginEvent


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class LoginView(BaseLoginView):
    template_name = "login.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        LoginEvent.objects.create(
            user=self.request.user, via="site", ip=_client_ip(self.request),
            user_agent=self.request.META.get("HTTP_USER_AGENT", "")[:500],
        )
        return response


class LogoutView(BaseLogoutView):
    next_page = "/login/"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            # Web-выход закрывает только site-события: app закрывает API-выход.
            LoginEvent.objects.filter(
                user=request.user, via="site", logout_at__isnull=True
            ).update(logout_at=timezone.now())
        return super().dispatch(request, *args, **kwargs)

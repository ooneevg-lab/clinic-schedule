from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("api/", include("api.urls")),
    path("schedule/", include("schedule.urls")),
    path("", RedirectView.as_view(pattern_name="schedule", permanent=False)),
]

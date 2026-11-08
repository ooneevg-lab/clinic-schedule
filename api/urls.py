from django.urls import path

from . import views

urlpatterns = [
    path("auth/login/", views.login_view, name="api-login"),
    path("auth/logout/", views.logout_view, name="api-logout"),
    path("schedule/my/", views.my_schedule, name="api-my"),
    path("schedule/full/", views.full_schedule, name="api-full"),
    path("columns/", views.columns_list, name="api-columns"),
    path("admin/upload/", views.admin_upload, name="api-upload"),
    path("integration/schedule/", views.integration_schedule, name="api-1c"),
    path("admin/versions/", views.admin_versions, name="api-versions"),
    path("admin/analytics/", views.admin_analytics, name="api-analytics"),
    path("push/register/", views.push_register, name="api-push-register"),
    path("push/unregister/", views.push_unregister, name="api-push-unregister"),
]

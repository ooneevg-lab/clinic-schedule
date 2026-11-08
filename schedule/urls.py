from django.urls import path

from . import views

urlpatterns = [
    path("", views.schedule_page, name="schedule"),
    path("upload/", views.upload_page, name="upload"),
]
